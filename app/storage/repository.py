from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Protocol
from urllib.parse import urlparse

from app.models import Evidence, Lead, MessageStatus, SequenceType, WebsiteResearch


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_email(value: str) -> str:
    return (value or "").strip().lower()


def normalize_website(value: str) -> str:
    value = (value or "").strip().lower()
    if "://" not in value:
        value = "https://" + value
    host = (urlparse(value).hostname or "").strip(".")
    return host[4:] if host.startswith("www.") else host


def deterministic_lead_id(email: str, website: str) -> str:
    return hashlib.sha256(f"{normalize_email(email)}|{normalize_website(website)}".encode()).hexdigest()


def deterministic_research_id(lead_id: str, timestamp_utc: str) -> str:
    return hashlib.sha256(f"{lead_id}|{timestamp_utc}".encode()).hexdigest()


def deterministic_outreach_id(lead_id: str, sequence_type: SequenceType | str, sequence_number: int) -> tuple[str, str]:
    seq = sequence_type.value if isinstance(sequence_type, SequenceType) else str(sequence_type)
    key = f"{lead_id}:{seq}:{sequence_number}"
    return hashlib.sha256(key.encode()).hexdigest(), key

SCHEMA_SQLITE = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS leads (
 lead_id TEXT PRIMARY KEY, email TEXT NOT NULL, company TEXT NOT NULL, website TEXT NOT NULL,
 city TEXT, state TEXT, timezone TEXT, lead_source TEXT, verified TEXT, place_id TEXT,
 email_source_url TEXT, website_facts TEXT, scale_class TEXT, qualification_confidence REAL,
 status TEXT NOT NULL, sender_id TEXT, created_at_utc TEXT NOT NULL, updated_at_utc TEXT NOT NULL, notes TEXT
);
CREATE TABLE IF NOT EXISTS research (
 research_id TEXT PRIMARY KEY, lead_id TEXT NOT NULL, research_timestamp_utc TEXT NOT NULL,
 business_summary TEXT, services_json TEXT NOT NULL, target_customers_json TEXT NOT NULL, locations_json TEXT NOT NULL,
 specialties_json TEXT NOT NULL, website_signals_json TEXT NOT NULL, customer_journey_signals_json TEXT NOT NULL,
 ai_opportunity_signals_json TEXT NOT NULL, evidence_json TEXT NOT NULL, research_status TEXT NOT NULL, research_version TEXT NOT NULL,
 FOREIGN KEY(lead_id) REFERENCES leads(lead_id)
);
CREATE INDEX IF NOT EXISTS idx_research_lead ON research(lead_id);
CREATE TABLE IF NOT EXISTS outreach (
 outreach_id TEXT PRIMARY KEY, lead_id TEXT NOT NULL, sequence_key TEXT NOT NULL UNIQUE,
 email TEXT NOT NULL, company TEXT NOT NULL, website TEXT NOT NULL, sender_id TEXT NOT NULL, sender_email TEXT NOT NULL,
 sequence_type TEXT NOT NULL, sequence_number INTEGER NOT NULL, subject TEXT NOT NULL DEFAULT '', body TEXT NOT NULL DEFAULT '',
 generated_at_utc TEXT, scheduled_at_utc TEXT, sent_at_utc TEXT, status TEXT NOT NULL, attempt_count INTEGER NOT NULL DEFAULT 0,
 last_error TEXT, next_retry_at_utc TEXT, evidence_urls_json TEXT NOT NULL DEFAULT '[]', personalization_confidence REAL NOT NULL DEFAULT 0,
 suppression_status TEXT NOT NULL DEFAULT 'CLEAR', message_id TEXT, body_hash TEXT, in_reply_to TEXT,
 created_at_utc TEXT NOT NULL, updated_at_utc TEXT NOT NULL, FOREIGN KEY(lead_id) REFERENCES leads(lead_id)
);
CREATE INDEX IF NOT EXISTS idx_outreach_due ON outreach(status, scheduled_at_utc);
CREATE INDEX IF NOT EXISTS idx_outreach_lead ON outreach(lead_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_outreach_body_hash ON outreach(body_hash);
CREATE TABLE IF NOT EXISTS sender_daily_state (
 sender_id TEXT NOT NULL, date_key TEXT NOT NULL, new_outreach INTEGER NOT NULL DEFAULT 0, followups INTEGER NOT NULL DEFAULT 0,
 total INTEGER NOT NULL DEFAULT 0, bounces INTEGER NOT NULL DEFAULT 0, failures INTEGER NOT NULL DEFAULT 0,
 authentication_failures INTEGER NOT NULL DEFAULT 0, temporary_provider_failures INTEGER NOT NULL DEFAULT 0,
 cooldown_until_utc TEXT, health_state TEXT NOT NULL DEFAULT 'HEALTHY', last_successful_send_utc TEXT,
 PRIMARY KEY(sender_id,date_key)
);
CREATE TABLE IF NOT EXISTS suppression (
 email TEXT PRIMARY KEY, lead_id TEXT, reason TEXT NOT NULL, created_at_utc TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS event_log (
 event_id INTEGER PRIMARY KEY AUTOINCREMENT, event_timestamp_utc TEXT NOT NULL, event_type TEXT NOT NULL,
 lead_id TEXT, outreach_id TEXT, sender_id TEXT, sequence_type TEXT, status TEXT, reason TEXT, metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_event_lead ON event_log(lead_id);
CREATE INDEX IF NOT EXISTS idx_event_time ON event_log(event_timestamp_utc);
CREATE TABLE IF NOT EXISTS workflow_run (
 workflow_run_id TEXT PRIMARY KEY, started_at_utc TEXT NOT NULL, ended_at_utc TEXT, mode TEXT NOT NULL,
 status TEXT NOT NULL, metrics_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS mailbox_state (
 sender_id TEXT PRIMARY KEY, mailbox_identifier TEXT NOT NULL, provider_type TEXT NOT NULL, uidvalidity TEXT,
 last_processed_uid INTEGER NOT NULL DEFAULT 0, last_checked_at_utc TEXT, health_state TEXT NOT NULL DEFAULT 'HEALTHY'
);
CREATE TABLE IF NOT EXISTS inbound_message (
 inbound_message_id TEXT PRIMARY KEY, sender_id TEXT NOT NULL, message_id TEXT NOT NULL, in_reply_to TEXT,
 references_text TEXT NOT NULL DEFAULT '', received_at_utc TEXT NOT NULL, lead_id TEXT, outreach_id TEXT,
 event_type TEXT NOT NULL, classification_confidence REAL NOT NULL, processing_status TEXT NOT NULL,
 processed_at_utc TEXT, subject TEXT NOT NULL DEFAULT '', from_email TEXT NOT NULL DEFAULT '',
 UNIQUE(sender_id,message_id)
);
CREATE INDEX IF NOT EXISTS idx_inbound_sender_uid ON inbound_message(sender_id, received_at_utc);
"""

SCHEMA_POSTGRES = SCHEMA_SQLITE.replace(
    "event_id INTEGER PRIMARY KEY AUTOINCREMENT", "event_id BIGSERIAL PRIMARY KEY"
).replace("PRAGMA foreign_keys = ON;", "")


class LeadRepository(Protocol):
    def upsert_lead(self, lead: Lead) -> None: ...
    def get_lead(self, lead_id: str) -> Lead | None: ...
    def list_eligible_leads(self, limit: int = 100) -> list[Lead]: ...
    def assign_sender(self, lead_id: str, sender_id: str) -> bool: ...


class ResearchRepository(Protocol):
    def save_research(self, research: WebsiteResearch) -> None: ...
    def latest_research(self, lead_id: str) -> WebsiteResearch | None: ...


class OutreachRepository(Protocol):
    def insert_outreach(self, record: dict[str, Any]) -> bool: ...
    def claim_outreach(self, outreach_id: str) -> bool: ...
    def mark_sent(self, outreach_id: str, sent_at_utc: str, message_id: str) -> None: ...


class EventRepository(Protocol):
    def add_event(self, event_type: str, **kwargs: Any) -> None: ...


class SuppressionRepository(Protocol):
    def is_suppressed(self, email: str) -> bool: ...
    def suppress(self, email: str, lead_id: str | None, reason: str) -> None: ...


class MailboxRepository(Protocol):
    def mailbox_state(self, sender_id: str): ...
    def save_mailbox_state(self, **kwargs: Any) -> None: ...


class Database:
    def __init__(self, sqlite_path: str = "runtime/outreach.db", database_url: str = ""):
        self.is_postgres = database_url.startswith(("postgres://", "postgresql://"))
        self.path = sqlite_path
        self.conn = None
        if self.is_postgres:
            try:
                import psycopg
                from psycopg.rows import dict_row
            except ImportError as exc:
                raise RuntimeError("Postgres storage requires psycopg[binary]") from exc
            self.conn = psycopg.connect(database_url, row_factory=dict_row, autocommit=True)
            with self.conn.cursor() as cur:
                for statement in [x.strip() for x in SCHEMA_POSTGRES.split(";") if x.strip()]:
                    cur.execute(statement)
        else:
            Path(sqlite_path).parent.mkdir(parents=True, exist_ok=True)
            self.conn = sqlite3.connect(sqlite_path, timeout=30, isolation_level=None, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            self.conn.executescript(SCHEMA_SQLITE)

    def _sql(self, sql: str) -> str:
        return sql.replace("?", "%s") if self.is_postgres else sql

    @contextmanager
    def transaction(self):
        if self.is_postgres:
            with self.conn.transaction():
                yield self.conn
        else:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                yield self.conn
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise

    def execute(self, sql: str, params: Iterable[Any] = ()):
        if self.is_postgres:
            cur = self.conn.cursor()
            cur.execute(self._sql(sql), tuple(params))
            return cur
        return self.conn.execute(sql, tuple(params))

    def fetchone(self, sql: str, params: Iterable[Any] = ()):
        cur = self.execute(sql, params)
        row = cur.fetchone()
        if self.is_postgres: cur.close()
        return row

    def fetchall(self, sql: str, params: Iterable[Any] = ()):
        cur = self.execute(sql, params)
        rows = cur.fetchall()
        if self.is_postgres: cur.close()
        return rows

    def close(self) -> None:
        self.conn.close()


class OperationalStore(LeadRepository, ResearchRepository, OutreachRepository, EventRepository, SuppressionRepository, MailboxRepository):
    """Transactional operational store; SQLite for local/dev, Postgres for CI/prod."""
    def __init__(self, sqlite_path: str = "runtime/outreach.db", database_url: str = ""):
        self.db = Database(sqlite_path, database_url)

    def close(self): self.db.close()

    def upsert_lead(self, lead: Lead) -> None:
        now = _now()
        self.db.execute("""
        INSERT INTO leads(lead_id,email,company,website,city,state,timezone,lead_source,verified,place_id,email_source_url,
          website_facts,scale_class,qualification_confidence,status,created_at_utc,updated_at_utc,notes)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(lead_id) DO UPDATE SET
          email=excluded.email,company=excluded.company,website=excluded.website,city=excluded.city,state=excluded.state,
          timezone=excluded.timezone,lead_source=excluded.lead_source,verified=excluded.verified,place_id=excluded.place_id,
          email_source_url=excluded.email_source_url,website_facts=excluded.website_facts,scale_class=excluded.scale_class,
          qualification_confidence=excluded.qualification_confidence, updated_at_utc=excluded.updated_at_utc, notes=excluded.notes
        """, [lead.lead_id,lead.email,lead.company,lead.website,lead.city,lead.state,lead.timezone,lead.lead_source,lead.verified,
        lead.place_id,lead.email_source_url,lead.website_facts,lead.scale_class,lead.qualification_confidence,lead.status,
        lead.first_seen_date or now,now,lead.notes])

    @staticmethod
    def _row_lead(r) -> Lead:
        def v(k, d=""):
            try: x=r[k]
            except Exception: x=d
            return x if x is not None else d
        return Lead(lead_id=v("lead_id"),email=v("email"),company=v("company"),website=v("website"),city=v("city"),state=v("state"),
          timezone=v("timezone","Asia/Kolkata") or "Asia/Kolkata",lead_source=v("lead_source"),verified=v("verified"),place_id=v("place_id"),
          email_source_url=v("email_source_url"),website_facts=v("website_facts"),scale_class=v("scale_class"),qualification_confidence=float(v("qualification_confidence",0) or 0),
          status=v("status"),first_seen_date=v("created_at_utc"),notes=v("notes"))

    def get_lead(self, lead_id: str) -> Lead | None:
        r=self.db.fetchone("SELECT * FROM leads WHERE lead_id=?",[lead_id]); return self._row_lead(r) if r else None

    def list_eligible_leads(self, limit: int=100) -> list[Lead]:
        rows=self.db.fetchall("SELECT * FROM leads WHERE upper(verified)='PASS' AND lower(status) IN ('verified','eligible','researched','outreach_prepared','scheduled','active') ORDER BY created_at_utc LIMIT ?",[limit])
        return [self._row_lead(r) for r in rows]

    def assign_sender(self,lead_id:str,sender_id:str)->bool:
        r=self.db.execute("UPDATE leads SET sender_id=?,updated_at_utc=? WHERE lead_id=? AND coalesce(sender_id,'')=''",[sender_id,_now(),lead_id])
        return r.rowcount==1

    def sender_for(self,lead_id:str)->str|None:
        r=self.db.fetchone("SELECT sender_id FROM leads WHERE lead_id=?",[lead_id]); return r["sender_id"] if r and r["sender_id"] else None

    def set_lead_status(self,lead_id:str,status:str)->None:
        self.db.execute("UPDATE leads SET status=?,updated_at_utc=? WHERE lead_id=?",[status,_now(),lead_id])

    def save_research(self,r:WebsiteResearch)->None:
        self.db.execute("""INSERT INTO research(research_id,lead_id,research_timestamp_utc,business_summary,services_json,target_customers_json,
        locations_json,specialties_json,website_signals_json,customer_journey_signals_json,ai_opportunity_signals_json,evidence_json,research_status,research_version)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",[r.research_id,r.lead_id,r.research_timestamp,r.business_summary,json.dumps(r.services),json.dumps(r.target_customers),json.dumps(r.locations),json.dumps(r.specialties),json.dumps(r.website_signals),json.dumps(r.customer_journey_signals),json.dumps(r.ai_opportunity_signals),json.dumps([e.__dict__ for e in r.evidence]),r.research_status,r.research_version])

    def latest_research(self,lead_id:str)->WebsiteResearch|None:
        r=self.db.fetchone("SELECT * FROM research WHERE lead_id=? ORDER BY research_timestamp_utc DESC LIMIT 1",[lead_id])
        if not r:return None
        return WebsiteResearch(r["research_id"],r["lead_id"],r["research_timestamp_utc"],(r["business_summary"] or ""),json.loads(r["services_json"]),json.loads(r["target_customers_json"]),json.loads(r["locations_json"]),json.loads(r["specialties_json"]),json.loads(r["website_signals_json"]),json.loads(r["customer_journey_signals_json"]),json.loads(r["ai_opportunity_signals_json"]),[Evidence(**e) for e in json.loads(r["evidence_json"] or "[]")],r["research_status"],r["research_version"])

    def is_suppressed(self,email:str)->bool:
        return bool(self.db.fetchone("SELECT 1 FROM suppression WHERE email=?",[normalize_email(email)]))

    def suppress(self,email:str,lead_id:str|None,reason:str)->None:
        self.db.execute("INSERT INTO suppression(email,lead_id,reason,created_at_utc) VALUES(?,?,?,?) ON CONFLICT(email) DO NOTHING",[normalize_email(email),lead_id,reason,_now()])

    def add_event(self,event_type:str,**kwargs:Any)->None:
        self.db.execute("INSERT INTO event_log(event_timestamp_utc,event_type,lead_id,outreach_id,sender_id,sequence_type,status,reason,metadata_json) VALUES(?,?,?,?,?,?,?,?,?)",[_now(),event_type,kwargs.get("lead_id"),kwargs.get("outreach_id"),kwargs.get("sender_id"),kwargs.get("sequence_type"),kwargs.get("status"),kwargs.get("reason"),json.dumps(kwargs.get("metadata") or {},ensure_ascii=False)])

    def insert_outreach(self,record:dict[str,Any])->bool:
        try:
            self.db.execute("""INSERT INTO outreach(outreach_id,lead_id,sequence_key,email,company,website,sender_id,sender_email,sequence_type,sequence_number,subject,body,
            generated_at_utc,scheduled_at_utc,sent_at_utc,status,attempt_count,last_error,next_retry_at_utc,evidence_urls_json,personalization_confidence,suppression_status,message_id,body_hash,in_reply_to,created_at_utc,updated_at_utc)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",[record["outreach_id"],record["lead_id"],record["sequence_key"],record["email"],record["company"],record["website"],record["sender_id"],record["sender_email"],record["sequence_type"],record["sequence_number"],record.get("subject",""),record.get("body",""),record.get("generated_at_utc"),record.get("scheduled_at_utc"),record.get("sent_at_utc"),record.get("status",MessageStatus.DRAFT.value),record.get("attempt_count",0),record.get("last_error"),record.get("next_retry_at_utc"),json.dumps(record.get("evidence_urls",[])),float(record.get("personalization_confidence",0)),record.get("suppression_status","CLEAR"),record.get("message_id"),record.get("body_hash"),record.get("in_reply_to"),record.get("created_at_utc",_now()),record.get("updated_at_utc",_now())])
            return True
        except Exception as exc:
            if "unique" in str(exc).lower() or "duplicate key" in str(exc).lower(): return False
            raise

    def body_hash_exists(self, body_hash: str) -> bool:
        return bool(self.db.fetchone("SELECT 1 FROM outreach WHERE body_hash=? LIMIT 1", [body_hash]))

    def last_planned_send_at(self, sender_id: str):
        r=self.db.fetchone("SELECT max(coalesce(scheduled_at_utc,sent_at_utc)) AS ts FROM outreach WHERE sender_id=? AND status NOT IN ('CANCELLED','FAILED_TERMINAL')",[sender_id])
        return r["ts"] if r and r["ts"] else None

    def get_outreach(self,outreach_id:str): return self.db.fetchone("SELECT * FROM outreach WHERE outreach_id=?",[outreach_id])
    def get_sequence(self,lead_id:str,sequence_type:str,sequence_number:int): return self.db.fetchone("SELECT * FROM outreach WHERE lead_id=? AND sequence_type=? AND sequence_number=?",[lead_id,sequence_type,sequence_number])
    def get_by_message_id(self,message_id:str): return self.db.fetchone("SELECT * FROM outreach WHERE message_id=?",[message_id])
    def get_outreach_for_lead(self,lead_id:str,include_unsent:bool=True):
        clause="" if include_unsent else " AND status='SENT'"; return self.db.fetchall("SELECT * FROM outreach WHERE lead_id=?"+clause+" ORDER BY sequence_number",[lead_id])

    def claim_outreach(self,outreach_id:str)->bool:
        r=self.db.execute("UPDATE outreach SET status='SENDING',attempt_count=attempt_count+1,updated_at_utc=? WHERE outreach_id=? AND status IN ('QUEUED','SCHEDULED','FAILED_RETRYABLE')",[_now(),outreach_id])
        return r.rowcount==1

    def mark_sent(self,outreach_id:str,sent_at_utc:str,message_id:str)->None:
        r=self.db.execute("UPDATE outreach SET status='SENT',sent_at_utc=?,message_id=?,last_error=NULL,next_retry_at_utc=NULL,updated_at_utc=? WHERE outreach_id=? AND status='SENDING'",[sent_at_utc,message_id,_now(),outreach_id])
        if r.rowcount!=1: raise RuntimeError("Cannot mark send successful: state is no longer SENDING")

    def mark_failure(self,outreach_id:str,retryable:bool,error:str,next_retry_at_utc:str|None=None)->None:
        status=MessageStatus.FAILED_RETRYABLE.value if retryable else MessageStatus.FAILED_TERMINAL.value
        self.db.execute("UPDATE outreach SET status=?,last_error=?,next_retry_at_utc=?,updated_at_utc=? WHERE outreach_id=? AND status='SENDING'",[status,error[:500],next_retry_at_utc,_now(),outreach_id])

    def cancel_future_followups(self,lead_id:str)->int:
        r=self.db.execute("UPDATE outreach SET status='CANCELLED',updated_at_utc=? WHERE lead_id=? AND sequence_type LIKE 'FOLLOWUP_%' AND status IN ('DRAFT','VALIDATED','QUEUED','SCHEDULED','FAILED_RETRYABLE')",[_now(),lead_id]); return r.rowcount

    def set_outreach_suppressed(self,lead_id:str,email:str):
        self.db.execute("UPDATE outreach SET suppression_status='SUPPRESSED',status='CANCELLED',updated_at_utc=? WHERE lead_id=? AND lower(email)=lower(?) AND status NOT IN ('SENT','CANCELLED')",[_now(),lead_id,email])

    def due_followup_candidates(self,now_utc:str,limit:int=100):
        return self.db.fetchall("SELECT * FROM outreach WHERE sequence_type LIKE 'FOLLOWUP_%' AND status='SCHEDULED' AND scheduled_at_utc<=? ORDER BY scheduled_at_utc LIMIT ?",[now_utc,limit])

    def last_sent_at(self,sender_id:str):
        r=self.db.fetchone("SELECT last_successful_send_utc FROM sender_daily_state WHERE sender_id=? ORDER BY date_key DESC LIMIT 1",[sender_id]); return r["last_successful_send_utc"] if r else None

    def sender_daily_state(self,sender_id:str,date_key:str):
        r=self.db.fetchone("SELECT * FROM sender_daily_state WHERE sender_id=? AND date_key=?",[sender_id,date_key]);
        if r:return r
        self.db.execute("INSERT INTO sender_daily_state(sender_id,date_key) VALUES(?,?) ON CONFLICT(sender_id,date_key) DO NOTHING",[sender_id,date_key]); return self.db.fetchone("SELECT * FROM sender_daily_state WHERE sender_id=? AND date_key=?",[sender_id,date_key])

    def record_send(self,sender_id:str,date_key:str,is_followup:bool,sent_at_utc:str):
        self.sender_daily_state(sender_id,date_key)
        col="followups" if is_followup else "new_outreach"
        self.db.execute(f"UPDATE sender_daily_state SET {col}={col}+1,total=total+1,last_successful_send_utc=? WHERE sender_id=? AND date_key=?",[sent_at_utc,sender_id,date_key])

    def record_failure(self,sender_id:str,date_key:str,kind:str):
        self.sender_daily_state(sender_id,date_key)
        col="authentication_failures" if kind=="AUTH" else "temporary_provider_failures" if kind=="TEMPORARY" else "failures"
        self.db.execute(f"UPDATE sender_daily_state SET {col}={col}+1,failures=failures+1 WHERE sender_id=? AND date_key=?",[sender_id,date_key])

    def set_sender_health(self,sender_id:str,date_key:str,state:str,cooldown_until_utc:str|None=None):
        self.sender_daily_state(sender_id,date_key); self.db.execute("UPDATE sender_daily_state SET health_state=?,cooldown_until_utc=? WHERE sender_id=? AND date_key=?",[state,cooldown_until_utc,sender_id,date_key])

    def mailbox_state(self,sender_id:str): return self.db.fetchone("SELECT * FROM mailbox_state WHERE sender_id=?",[sender_id])
    def save_mailbox_state(self,**kwargs:Any)->None:
        self.db.execute("""INSERT INTO mailbox_state(sender_id,mailbox_identifier,provider_type,uidvalidity,last_processed_uid,last_checked_at_utc,health_state)
        VALUES(?,?,?,?,?,?,?) ON CONFLICT(sender_id) DO UPDATE SET mailbox_identifier=excluded.mailbox_identifier,provider_type=excluded.provider_type,uidvalidity=excluded.uidvalidity,last_processed_uid=excluded.last_processed_uid,last_checked_at_utc=excluded.last_checked_at_utc,health_state=excluded.health_state""",[kwargs["sender_id"],kwargs.get("mailbox_identifier","INBOX"),kwargs.get("provider_type","imap"),kwargs.get("uidvalidity"),int(kwargs.get("last_processed_uid",0)),kwargs.get("last_checked_at_utc",_now()),kwargs.get("health_state","HEALTHY")])

    def inbound_exists(self,sender_id:str,message_id:str)->bool: return bool(self.db.fetchone("SELECT 1 FROM inbound_message WHERE sender_id=? AND message_id=?",[sender_id,message_id]))
    def save_inbound(self,**kwargs:Any)->bool:
        try:
            self.db.execute("""INSERT INTO inbound_message(inbound_message_id,sender_id,message_id,in_reply_to,references_text,received_at_utc,lead_id,outreach_id,event_type,classification_confidence,processing_status,processed_at_utc,subject,from_email)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",[kwargs["inbound_message_id"],kwargs["sender_id"],kwargs["message_id"],kwargs.get("in_reply_to"),kwargs.get("references_text","")[:2000],kwargs["received_at_utc"],kwargs.get("lead_id"),kwargs.get("outreach_id"),kwargs["event_type"],float(kwargs.get("classification_confidence",0)),kwargs.get("processing_status","PROCESSED"),kwargs.get("processed_at_utc",_now()),kwargs.get("subject","")[:500],kwargs.get("from_email","")[:320]])
            return True
        except Exception as exc:
            if "unique" in str(exc).lower() or "duplicate key" in str(exc).lower(): return False
            raise

    def get_lead_by_email(self,email:str): return self.db.fetchone("SELECT * FROM leads WHERE lower(email)=lower(?) LIMIT 1",[email])
    def get_unfinished_sends(self): return self.db.fetchall("SELECT * FROM outreach WHERE status='SENDING'")
    def set_lead_status_by_id(self, lead_id:str, state:str): self.set_lead_status(lead_id,state)


def open_store(sqlite_path: str = "runtime/outreach.db", database_url: str = "") -> OperationalStore:
    return OperationalStore(sqlite_path, database_url)
