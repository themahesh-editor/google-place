from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_email(value: str) -> str:
    return (value or "").strip().lower()


def normalize_domain(value: str) -> str:
    text = (value or "").strip().lower()
    if "@" in text:
        text = text.rsplit("@", 1)[1]
    if "://" not in text:
        text = "https://" + text
    host = (urlparse(text).hostname or "").strip(".")
    return host[4:] if host.startswith("www.") else host


def deterministic_lead_id(email: str, website: str) -> str:
    return hashlib.sha256(f"{normalize_email(email)}|{normalize_domain(website)}".encode()).hexdigest()


def deterministic_research_id(lead_id: str, timestamp_utc: str) -> str:
    return hashlib.sha256(f"{lead_id}|{timestamp_utc}".encode()).hexdigest()


def deterministic_outreach_id(lead_id: str, sequence_type: str, sequence_number: int) -> str:
    return hashlib.sha256(f"{lead_id}:{sequence_type}:{sequence_number}".encode()).hexdigest()


def utc_from_value(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class Store:
    """Single production persistence layer. Production accepts only Supabase/Postgres URLs."""

    def __init__(self, database_url: str):
        self.database_url = database_url
        self.is_sqlite = database_url.startswith("sqlite://")
        self.conn = None
        if self.is_sqlite:
            import sqlite3
            path = database_url.removeprefix("sqlite://") or ":memory:"
            if path != ":memory:":
                Path(path).parent.mkdir(parents=True, exist_ok=True)
            self.conn = sqlite3.connect(path, timeout=30, isolation_level=None, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA foreign_keys = ON")
        else:
            try:
                import psycopg
                from psycopg.rows import dict_row
            except ImportError as exc:
                raise RuntimeError("psycopg[binary] is required for Supabase/Postgres") from exc
            if "sslmode=" not in database_url:
                database_url += "&sslmode=require" if "?" in database_url else "?sslmode=require"
            self.conn = psycopg.connect(database_url, row_factory=dict_row, autocommit=True, prepare_threshold=None)

    def close(self) -> None:
        if self.conn:
            self.conn.close()
            self.conn = None

    def _sql(self, query: str) -> str:
        return query.replace("?", "%s") if not self.is_sqlite else query

    def execute(self, query: str, params: Iterable[Any] = ()):
        cur = self.conn.cursor()
        cur.execute(self._sql(query), tuple(params))
        return cur

    def fetchone(self, query: str, params: Iterable[Any] = ()):
        cur = self.execute(query, params)
        row = cur.fetchone()
        cur.close()
        return row

    def fetchall(self, query: str, params: Iterable[Any] = ()):
        cur = self.execute(query, params)
        rows = cur.fetchall()
        cur.close()
        return rows

    def scalar(self, query: str, params: Iterable[Any] = (), default: Any = 0) -> Any:
        row = self.fetchone(query, params)
        if row is None:
            return default
        try:
            return row[0]
        except (KeyError, IndexError, TypeError):
            return next(iter(row.values()))

    @contextmanager
    def transaction(self):
        if self.is_sqlite:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                yield self.conn
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise
        else:
            with self.conn.transaction():
                yield self.conn

    def migrate(self, migrations_dir: str | Path = "migrations") -> None:
        root = Path(migrations_dir)
        files = sorted(root.glob("*.sql"), key=lambda p: p.name)
        if not files:
            raise RuntimeError("No SQL migrations found")
        self.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at_utc TEXT NOT NULL)")
        applied = {str(r["version"] if isinstance(r, dict) else r[0]) for r in self.fetchall("SELECT version FROM schema_migrations")}
        for path in files:
            if path.name in applied:
                continue
            sql = path.read_text(encoding="utf-8")
            statements = [s.strip() for s in re.split(r";\s*(?:\n|$)", sql) if s.strip() and not s.strip().startswith("--")]
            with self.transaction():
                for statement in statements:
                    self.execute(statement)
                self.execute("INSERT INTO schema_migrations(version, applied_at_utc) VALUES(?,?)", [path.name, now_utc()])

    def reset_runtime_state(self) -> None:
        tables = [
            "inbound_message", "suppression", "event_log", "workflow_run", "outreach_batches",
            "outreach", "sender_daily_state", "lead_research", "lead_qualification", "discovery_candidate", "leads",
        ]
        with self.transaction():
            if self.is_sqlite:
                for table in tables:
                    self.execute(f"DELETE FROM {table}")
            else:
                self.execute("TRUNCATE TABLE " + ", ".join(tables) + " RESTART IDENTITY CASCADE")

    def recover_interrupted_workflow_state(self, current_run_id: str) -> None:
        """Recover durable state left by a previously interrupted runner before resuming."""
        stale_runs = self.fetchall(
            "SELECT workflow_run_id FROM workflow_run WHERE status='RUNNING' AND workflow_run_id<>?",
            [current_run_id],
        )
        stale_run_ids = [str(row["workflow_run_id"]) for row in stale_runs]
        if stale_run_ids:
            now = now_utc()
            for run_id in stale_run_ids:
                self.execute("UPDATE workflow_run SET ended_at_utc=?,status='FAILED',metrics_json=? WHERE workflow_run_id=?", [now, json.dumps({'status':'FAILED','error':'runner_interrupted'}), run_id])
            placeholders = ",".join("?" for _ in stale_run_ids)
            # Rows that were only scheduled belong back in the durable queue. A SENDING row is
            # intentionally made REVIEW_NEEDED because SMTP delivery may already have happened.
            self.execute(
                f"UPDATE outreach SET batch_id=NULL,status='QUEUED',updated_at_utc=? WHERE workflow_run_id IN ({placeholders}) AND status='SCHEDULED'",
                [now, *stale_run_ids],
            )
            self.execute(
                f"UPDATE outreach SET status='REVIEW_NEEDED',last_error='runner_interrupted_while_sending',updated_at_utc=? WHERE workflow_run_id IN ({placeholders}) AND status='SENDING'",
                [now, *stale_run_ids],
            )
        # No GitHub runner should still be executing when the next manual run starts. Recover
        # every leftover research claim to the furthest durable state we actually have.
        self.execute(
            """UPDATE leads AS l
               SET status=CASE WHEN EXISTS (SELECT 1 FROM lead_research r WHERE r.lead_id=l.lead_id AND r.research_status='RESEARCHED')
                               THEN 'RESEARCHED' ELSE 'ELIGIBLE' END,
                   updated_at_utc=?
               WHERE l.status='RESEARCHING'""",
            [now_utc()],
        )

    # ---- Workflow runs / events -------------------------------------------------
    def start_workflow(self, mode: str, reset_state: bool) -> str:
        run_id = str(uuid.uuid4())
        ts = now_utc()
        self.execute(
            "INSERT INTO workflow_run(workflow_run_id,started_at_utc,mode,status,reset_state) VALUES(?,?,?,?,?)",
            [run_id, ts, mode, "RUNNING", reset_state],
        )
        return run_id

    def finish_workflow(self, run_id: str, status: str, metrics: dict[str, Any]) -> None:
        self.execute(
            "UPDATE workflow_run SET ended_at_utc=?,status=?,metrics_json=? WHERE workflow_run_id=?",
            [now_utc(), status, json.dumps(metrics, ensure_ascii=False), run_id],
        )

    def add_event(self, event_type: str, *, run_id: str | None = None, lead_id: str | None = None,
                  outreach_id: str | None = None, sender_id: str | None = None, batch_id: str | None = None,
                  sequence_type: str | None = None, status: str | None = None, reason: str | None = None,
                  metadata: dict[str, Any] | None = None) -> None:
        event_id = str(uuid.uuid4())
        self.execute(
            """INSERT INTO event_log(event_id,event_timestamp_utc,event_type,workflow_run_id,lead_id,outreach_id,
               sender_id,batch_id,sequence_type,status,reason,metadata_json)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            [event_id, now_utc(), event_type, run_id, lead_id, outreach_id, sender_id, batch_id,
             sequence_type, status, reason, json.dumps(metadata or {}, ensure_ascii=False)],
        )

    # ---- Leads / discovery ------------------------------------------------------
    def upsert_lead(self, lead: dict[str, Any]) -> str:
        lead_id = lead["lead_id"]
        existing = self.fetchone("SELECT status FROM leads WHERE lead_id=?", [lead_id])
        if existing:
            self.execute(
                """UPDATE leads SET email=?,company=?,website=?,website_domain=?,city=?,region=?,country_code=?,timezone=?,
                   lead_source=?,place_id=?,scale_class=?,qualification_confidence=?,qualification_reason=?,discovery_facts=?,updated_at_utc=?
                   WHERE lead_id=?""",
                [lead["email"], lead["company"], lead["website"], lead["website_domain"], lead["city"], lead["region"],
                 lead["country_code"], lead["timezone"], lead["lead_source"], lead["place_id"], lead["scale_class"],
                 lead["qualification_confidence"], lead["qualification_reason"], lead.get("discovery_facts", ""), now_utc(), lead_id],
            )
            return lead_id
        try:
            self.execute(
                """INSERT INTO leads(lead_id,email,company,website,website_domain,city,region,country_code,timezone,lead_source,
                   place_id,scale_class,qualification_confidence,qualification_reason,discovery_facts,status,created_at_utc,updated_at_utc)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [lead_id, lead["email"], lead["company"], lead["website"], lead["website_domain"], lead["city"], lead["region"],
                 lead["country_code"], lead["timezone"], lead["lead_source"], lead["place_id"], lead["scale_class"],
                 lead["qualification_confidence"], lead["qualification_reason"], lead.get("discovery_facts", ""), lead.get("status", "ELIGIBLE"),
                 now_utc(), now_utc()],
            )
            return lead_id
        except Exception as exc:
            if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
                existing = self.fetchone("SELECT lead_id FROM leads WHERE website_domain=? OR place_id=? OR lower(email)=lower(?)", [lead["website_domain"], lead["place_id"], normalize_email(lead["email"])])
                return str(existing["lead_id"] if isinstance(existing, dict) else existing[0]) if existing else lead_id
            raise

    def insert_qualification(self, lead_id: str, *, action: str, confidence: float, reason: str, run_id: str, evidence_urls: list[str]) -> None:
        self.execute(
            """INSERT INTO lead_qualification(qualification_id,lead_id,workflow_run_id,action,confidence,reason,evidence_urls_json,created_at_utc)
               VALUES(?,?,?,?,?,?,?,?)""",
            [str(uuid.uuid4()), lead_id, run_id, action, confidence, reason[:1000], json.dumps(evidence_urls), now_utc()],
        )

    def get_lead(self, lead_id: str):
        return self.fetchone("SELECT * FROM leads WHERE lead_id=?", [lead_id])

    def get_lead_by_email(self, email: str):
        return self.fetchone("SELECT * FROM leads WHERE lower(email)=lower(?) LIMIT 1", [normalize_email(email)])

    def update_lead_status(self, lead_id: str, status: str) -> None:
        self.execute("UPDATE leads SET status=?,updated_at_utc=? WHERE lead_id=?", [status, now_utc(), lead_id])

    def claim_untouched_leads(self, limit: int, stale_after_minutes: int = 120, exclude_ids: tuple[str, ...] = ()) -> list[Any]:
        cutoff = datetime.now(timezone.utc).timestamp() - stale_after_minutes * 60
        cutoff_iso = datetime.fromtimestamp(cutoff, tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        self.execute("UPDATE leads SET status='ELIGIBLE',updated_at_utc=? WHERE status='RESEARCHING' AND updated_at_utc<?", [now_utc(), cutoff_iso])
        exclude_ids = tuple(dict.fromkeys(x for x in exclude_ids if x))
        excluded = " AND l.lead_id NOT IN (" + ",".join("?" for _ in exclude_ids) + ")" if exclude_ids else ""
        params = list(exclude_ids) + [limit]
        with self.transaction():
            postgres_sql = (
                """SELECT l.* FROM leads l
                   WHERE l.status IN ('ELIGIBLE','RESEARCHED')
                     AND l.status NOT IN ('REPLIED','BOUNCED','UNSUBSCRIBED','COMPLETED','MANUAL_STOP')
                     AND NOT EXISTS (SELECT 1 FROM outreach o WHERE o.lead_id=l.lead_id AND o.sequence_type='INITIAL' AND o.sequence_number=1)
                """ + excluded + " ORDER BY l.created_at_utc,l.lead_id LIMIT ? FOR UPDATE SKIP LOCKED"
            )
            sqlite_sql = (
                """SELECT l.* FROM leads l
                   WHERE l.status IN ('ELIGIBLE','RESEARCHED')
                     AND NOT EXISTS (SELECT 1 FROM outreach o WHERE o.lead_id=l.lead_id AND o.sequence_type='INITIAL' AND o.sequence_number=1)
                """ + excluded + " ORDER BY l.created_at_utc,l.lead_id LIMIT ?"
            )
            rows = self.fetchall(postgres_sql, params) if not self.is_sqlite else self.fetchall(sqlite_sql, params)
            for row in rows:
                self.execute("UPDATE leads SET status='RESEARCHING',updated_at_utc=? WHERE lead_id=?", [now_utc(), row["lead_id"]])
        return rows

    def count_eligible_untouched(self) -> int:
        return int(self.scalar(
            """SELECT count(*) FROM leads l WHERE l.status IN ('ELIGIBLE','RESEARCHED')
               AND NOT EXISTS (SELECT 1 FROM outreach o WHERE o.lead_id=l.lead_id AND o.sequence_type='INITIAL' AND o.sequence_number=1)"""
        ))

    # ---- Research ---------------------------------------------------------------
    def save_research(self, record: dict[str, Any]) -> None:
        self.execute(
            """INSERT INTO lead_research(research_id,lead_id,website_domain,canonical_url,company_identity,business_summary,
               services_json,business_facts_json,locations_json,specialties_json,website_signals_json,customer_journey_signals_json,
               ai_opportunity_signals_json,important_public_text,evidence_json,research_timestamp_utc,research_status,research_version,
               error,retry_count,next_retry_at_utc,created_at_utc)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [record["research_id"], record["lead_id"], record["website_domain"], record["canonical_url"], record["company_identity"],
             record["business_summary"], json.dumps(record["services"]), json.dumps(record["business_facts"]), json.dumps(record["locations"]),
             json.dumps(record["specialties"]), json.dumps(record["website_signals"]), json.dumps(record["customer_journey_signals"]),
             json.dumps(record["ai_opportunity_signals"]), record["important_public_text"], json.dumps(record["evidence"]), record["research_timestamp_utc"],
             record["research_status"], record["research_version"], record.get("error"), record.get("retry_count", 0), record.get("next_retry_at_utc"), now_utc()],
        )

    def latest_research(self, lead_id: str):
        return self.fetchone("SELECT * FROM lead_research WHERE lead_id=? ORDER BY research_timestamp_utc DESC LIMIT 1", [lead_id])

    # ---- Suppression ------------------------------------------------------------
    def is_suppressed(self, email: str) -> bool:
        return bool(self.fetchone("SELECT 1 FROM suppression WHERE email=?", [normalize_email(email)]))

    def suppress(self, email: str, lead_id: str | None, reason: str) -> None:
        self.execute(
            "INSERT INTO suppression(email,lead_id,reason,created_at_utc) VALUES(?,?,?,?) ON CONFLICT(email) DO NOTHING",
            [normalize_email(email), lead_id, reason[:200], now_utc()],
        )

    # ---- Sender state -----------------------------------------------------------
    def sender_day(self, sender_id: str, date_key: str):
        row = self.fetchone("SELECT * FROM sender_daily_state WHERE sender_id=? AND date_key=?", [sender_id, date_key])
        if row:
            return row
        self.execute("INSERT INTO sender_daily_state(sender_id,date_key) VALUES(?,?)", [sender_id, date_key])
        return self.fetchone("SELECT * FROM sender_daily_state WHERE sender_id=? AND date_key=?", [sender_id, date_key])

    def set_sender_health(self, sender_id: str, date_key: str, state: str, cooldown_until_utc: str | None = None) -> None:
        self.sender_day(sender_id, date_key)
        self.execute("UPDATE sender_daily_state SET health_state=?,cooldown_until_utc=? WHERE sender_id=? AND date_key=?", [state, cooldown_until_utc, sender_id, date_key])

    def record_send(self, sender_id: str, date_key: str, is_followup: bool, sent_at_utc: str) -> None:
        self.sender_day(sender_id, date_key)
        column = "followups" if is_followup else "initials"
        self.execute(f"UPDATE sender_daily_state SET {column}={column}+1,total=total+1,last_successful_send_utc=?,health_state='HEALTHY',cooldown_until_utc=NULL WHERE sender_id=? AND date_key=?", [sent_at_utc, sender_id, date_key])

    def record_failure(self, sender_id: str, date_key: str, kind: str) -> None:
        self.sender_day(sender_id, date_key)
        column = "authentication_failures" if kind == "AUTH" else "temporary_provider_failures" if kind == "TEMPORARY" else "failures"
        self.execute(f"UPDATE sender_daily_state SET {column}={column}+1,failures=failures+1 WHERE sender_id=? AND date_key=?", [sender_id, date_key])

    # ---- Outreach batches/items -------------------------------------------------
    def count_successful_initials(self) -> int:
        return int(self.scalar("SELECT count(*) FROM outreach WHERE sequence_type='INITIAL' AND status='SENT'"))

    def count_initial_progress(self) -> int:
        return int(self.scalar("SELECT count(*) FROM outreach WHERE sequence_type='INITIAL' AND status IN ('SENT','SENDING','SCHEDULED','QUEUED','FAILED_RETRYABLE')"))

    def count_unfinished_initials(self) -> int:
        return int(self.scalar("SELECT count(*) FROM outreach WHERE sequence_type='INITIAL' AND status IN ('SENDING','SCHEDULED','QUEUED','FAILED_RETRYABLE')"))

    def next_batch_number(self, run_id: str, batch_type: str) -> int:
        return int(self.scalar(
            "SELECT COALESCE(MAX(batch_number),0)+1 FROM outreach_batches WHERE workflow_run_id=? AND batch_type=?",
            [run_id, batch_type], default=1,
        ))

    def body_hash_exists(self, body_hash: str) -> bool:
        return bool(self.fetchone("SELECT 1 FROM outreach WHERE body_hash=? AND status NOT IN ('CANCELLED','FAILED_TERMINAL') LIMIT 1", [body_hash]))

    def get_outreach(self, outreach_id: str):
        return self.fetchone("SELECT * FROM outreach WHERE outreach_id=?", [outreach_id])

    def get_sequence(self, lead_id: str, sequence_type: str, sequence_number: int):
        return self.fetchone("SELECT * FROM outreach WHERE lead_id=? AND sequence_type=? AND sequence_number=?", [lead_id, sequence_type, sequence_number])

    def insert_outreach(self, record: dict[str, Any]) -> bool:
        try:
            self.execute(
                """INSERT INTO outreach(outreach_id,workflow_run_id,batch_id,lead_id,sequence_type,sequence_number,sender_id,sender_email,
                   email,subject,body,status,scheduled_at_utc,attempted_at_utc,sent_at_utc,message_id,retry_count,next_retry_at_utc,
                   evidence_urls_json,personalization_confidence,body_hash,in_reply_to,references_text,created_at_utc,updated_at_utc)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [record["outreach_id"], record["workflow_run_id"], record.get("batch_id"), record["lead_id"], record["sequence_type"],
                 record["sequence_number"], record["sender_id"], record["sender_email"], record["email"], record["subject"], record["body"],
                 record.get("status", "QUEUED"), record.get("scheduled_at_utc"), record.get("attempted_at_utc"), record.get("sent_at_utc"),
                 record.get("message_id"), record.get("retry_count", 0), record.get("next_retry_at_utc"), json.dumps(record.get("evidence_urls", [])),
                 record.get("personalization_confidence", 0.0), record["body_hash"], record.get("in_reply_to"), record.get("references_text"), now_utc(), now_utc()],
            )
            return True
        except Exception as exc:
            if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
                return False
            raise

    def queue_initial(self, *, run_id: str, lead_id: str, sender_id: str, sender_email: str, subject: str, body: str,
                      evidence_urls: list[str], confidence: float) -> str | None:
        body_hash = hashlib.sha256(re.sub(r"\s+", " ", body.strip().lower()).encode()).hexdigest()
        if self.body_hash_exists(body_hash):
            return None
        outreach_id = deterministic_outreach_id(lead_id, "INITIAL", 1)
        if self.get_outreach(outreach_id):
            return None
        ok = self.insert_outreach({
            "outreach_id": outreach_id, "workflow_run_id": run_id, "lead_id": lead_id,
            "sequence_type": "INITIAL", "sequence_number": 1, "sender_id": sender_id, "sender_email": sender_email,
            "email": self.get_lead(lead_id)["email"], "subject": subject, "body": body, "status": "QUEUED",
            "evidence_urls": evidence_urls, "personalization_confidence": confidence, "body_hash": body_hash,
        })
        return outreach_id if ok else None

    def list_queued_initials(self, limit: int = 10) -> list[Any]:
        return self.fetchall("SELECT o.*,l.timezone,l.status AS lead_status FROM outreach o JOIN leads l ON l.lead_id=o.lead_id WHERE o.sequence_type='INITIAL' AND o.status='QUEUED' AND o.batch_id IS NULL ORDER BY o.created_at_utc LIMIT ?", [limit])

    def create_batch(self, run_id: str, batch_number: int, batch_type: str, scheduled_at_utc: str, target_count: int) -> str:
        batch_id = f"{run_id}:{batch_type}:{batch_number}"
        self.execute(
            "INSERT INTO outreach_batches(batch_id,workflow_run_id,batch_number,batch_type,scheduled_at_utc,status,target_count,attempted_count,successful_count,failed_count,created_at_utc,updated_at_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            [batch_id, run_id, batch_number, batch_type, scheduled_at_utc, "SCHEDULED", target_count, 0, 0, 0, now_utc(), now_utc()],
        )
        return batch_id

    def assign_batch(self, batch_id: str, assignments: list[tuple[str, str, str, str]], scheduled_at_utc: str) -> None:
        """assignments = [(outreach_id, lead_id, sender_id, sender_email)]"""
        with self.transaction():
            for outreach_id, lead_id, sender_id, sender_email in assignments:
                self.execute(
                    "UPDATE outreach SET batch_id=?,sender_id=?,sender_email=?,scheduled_at_utc=?,status='SCHEDULED',updated_at_utc=? WHERE outreach_id=? AND status IN ('QUEUED','FAILED_RETRYABLE') AND batch_id IS NULL",
                    [batch_id, sender_id, sender_email, scheduled_at_utc, now_utc(), outreach_id],
                )
                self.execute("UPDATE leads SET sender_id=?,status='QUEUED',updated_at_utc=? WHERE lead_id=?", [sender_id, now_utc(), lead_id])

    def list_ready_initials(self, limit: int = 10) -> list[Any]:
        return self.fetchall("""SELECT o.*,l.timezone,l.status AS lead_status FROM outreach o JOIN leads l ON l.lead_id=o.lead_id
            WHERE o.sequence_type='INITIAL' AND o.batch_id IS NULL AND (o.status='QUEUED' OR (o.status='FAILED_RETRYABLE' AND (o.next_retry_at_utc IS NULL OR o.next_retry_at_utc<=?)))
            ORDER BY o.created_at_utc LIMIT ?""", [now_utc(), limit])

    def requeue_batch_pending(self, batch_id: str) -> None:
        self.execute("""UPDATE outreach SET batch_id=NULL,status=CASE WHEN status='SCHEDULED' THEN 'QUEUED' ELSE status END,updated_at_utc=?
            WHERE batch_id=? AND status IN ('SCHEDULED','FAILED_RETRYABLE')""", [now_utc(), batch_id])

    def reconcile_stale_batches(self, cutoff_utc: str) -> None:
        batches = self.fetchall(
            "SELECT batch_id FROM outreach_batches WHERE status IN ('SCHEDULED','RUNNING') AND updated_at_utc<?",
            [cutoff_utc],
        )
        for row in batches:
            batch_id = row["batch_id"]
            self.requeue_batch_pending(batch_id)
            pending = int(self.scalar("SELECT count(*) FROM outreach WHERE batch_id=? AND status IN ('SCHEDULED','QUEUED','FAILED_RETRYABLE')", [batch_id]))
            sent = int(self.scalar("SELECT count(*) FROM outreach WHERE batch_id=? AND status='SENT'", [batch_id]))
            attempted = int(self.scalar("SELECT count(*) FROM outreach WHERE batch_id=? AND status NOT IN ('QUEUED','SCHEDULED')", [batch_id]))
            status = "COMPLETED" if pending == 0 else "PARTIAL"
            self.execute(
                "UPDATE outreach_batches SET status=?,attempted_count=?,successful_count=?,failed_count=?,completed_at_utc=?,updated_at_utc=? WHERE batch_id=?",
                [status, attempted, sent, max(0, attempted - sent), now_utc(), now_utc(), batch_id],
            )

    def claim_outreach(self, outreach_id: str) -> bool:
        row = self.execute(
            "UPDATE outreach SET status='SENDING',attempted_at_utc=?,retry_count=retry_count+1,updated_at_utc=? WHERE outreach_id=? AND status IN ('SCHEDULED','QUEUED','FAILED_RETRYABLE')",
            [now_utc(), now_utc(), outreach_id],
        )
        count = row.rowcount
        row.close()
        return count == 1

    def mark_sent(self, outreach_id: str, sent_at_utc: str, message_id: str) -> None:
        self.execute("UPDATE outreach SET status='SENT',sent_at_utc=?,message_id=?,next_retry_at_utc=NULL,updated_at_utc=? WHERE outreach_id=? AND status='SENDING'", [sent_at_utc, message_id, now_utc(), outreach_id])

    def mark_failed(self, outreach_id: str, status: str, error: str, next_retry_at_utc: str | None) -> None:
        self.execute("UPDATE outreach SET status=?,last_error=?,next_retry_at_utc=?,updated_at_utc=? WHERE outreach_id=? AND status='SENDING'", [status, error[:1000], next_retry_at_utc, now_utc(), outreach_id])

    def mark_review_needed(self, outreach_id: str, reason: str) -> None:
        self.execute("UPDATE outreach SET status='REVIEW_NEEDED',last_error=?,next_retry_at_utc=NULL,updated_at_utc=? WHERE outreach_id=? AND status='SENDING'", [reason[:1000], now_utc(), outreach_id])

    def update_batch_counts(self, batch_id: str, *, status: str, attempted: int, successful: int, failed: int) -> None:
        self.execute("UPDATE outreach_batches SET status=?,attempted_count=?,successful_count=?,failed_count=?,completed_at_utc=?,updated_at_utc=? WHERE batch_id=?", [status, attempted, successful, failed, now_utc(), now_utc(), batch_id])

    def cancel_future_followups(self, lead_id: str) -> None:
        self.execute("UPDATE outreach SET status='CANCELLED',updated_at_utc=? WHERE lead_id=? AND sequence_type LIKE 'FOLLOWUP_%' AND status IN ('QUEUED','SCHEDULED','FAILED_RETRYABLE')", [now_utc(), lead_id])

    def list_followup_candidates(self, sequence_type: str, limit: int = 100) -> list[Any]:
        number = int(sequence_type.split("_")[-1])
        previous_type = "INITIAL" if number == 1 else f"FOLLOWUP_{number-1}"
        previous_number = 1 if previous_type == "INITIAL" else number - 1
        return self.fetchall(
            """SELECT p.*,l.timezone,l.status AS lead_status,l.email AS lead_email FROM outreach p JOIN leads l ON l.lead_id=p.lead_id
               WHERE p.sequence_type=? AND p.sequence_number=? AND p.status='SENT'
                 AND NOT EXISTS (SELECT 1 FROM outreach x WHERE x.lead_id=p.lead_id AND x.sequence_type=? AND x.sequence_number=?)
               ORDER BY p.sent_at_utc LIMIT ?""",
            [previous_type, previous_number, sequence_type, number, limit],
        )

    def list_due_followups(self, limit: int = 100) -> list[Any]:
        return self.fetchall(
            """SELECT o.*,l.timezone,l.status AS lead_status FROM outreach o JOIN leads l ON l.lead_id=o.lead_id
               WHERE o.sequence_type LIKE 'FOLLOWUP_%' AND o.status IN ('QUEUED','SCHEDULED','FAILED_RETRYABLE')
                 AND (o.scheduled_at_utc IS NULL OR o.scheduled_at_utc<=?)
               ORDER BY o.scheduled_at_utc,o.created_at_utc LIMIT ?""",
            [now_utc(), limit],
        )

    def previous_sent_history(self, lead_id: str) -> list[Any]:
        return self.fetchall("SELECT * FROM outreach WHERE lead_id=? AND status='SENT' ORDER BY sequence_number", [lead_id])

    def insert_followup(self, *, run_id: str, lead_id: str, sequence_type: str, sequence_number: int, sender_id: str, sender_email: str,
                        subject: str, body: str, evidence_urls: list[str], confidence: float, in_reply_to: str, references_text: str,
                        scheduled_at_utc: str) -> str | None:
        lead = self.get_lead(lead_id)
        if not lead or self.is_suppressed(lead["email"]):
            return None
        outreach_id = deterministic_outreach_id(lead_id, sequence_type, sequence_number)
        if self.get_outreach(outreach_id):
            return None
        body_hash = hashlib.sha256(re.sub(r"\s+", " ", body.strip().lower()).encode()).hexdigest()
        if self.body_hash_exists(body_hash):
            return None
        previous_type = "INITIAL" if sequence_number == 1 else f"FOLLOWUP_{sequence_number-1}"
        previous_number = 1 if previous_type == "INITIAL" else sequence_number - 1
        previous = self.get_sequence(lead_id, previous_type, previous_number)
        if not previous or previous["status"] != "SENT" or not previous["sent_at_utc"]:
            return None
        self.execute(
            """INSERT INTO outreach(outreach_id,workflow_run_id,batch_id,lead_id,sequence_type,sequence_number,sender_id,sender_email,email,subject,body,status,scheduled_at_utc,retry_count,evidence_urls_json,personalization_confidence,body_hash,in_reply_to,references_text,created_at_utc,updated_at_utc)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [outreach_id, run_id, None, lead_id, sequence_type, sequence_number, sender_id, sender_email, lead["email"], subject, body, "QUEUED", scheduled_at_utc, 0, json.dumps(evidence_urls), confidence, body_hash, in_reply_to, references_text, now_utc(), now_utc()],
        )
        return outreach_id

    def count_event(self, run_id: str, event_type: str) -> int:
        return int(self.scalar("SELECT count(*) FROM event_log WHERE workflow_run_id=? AND event_type=?", [run_id, event_type]))

    # ---- Mailbox ---------------------------------------------------------------
    def mailbox_state(self, sender_id: str):
        return self.fetchone("SELECT * FROM mailbox_state WHERE sender_id=?", [sender_id])

    def save_mailbox_state(self, *, sender_id: str, uidvalidity: str | None, last_processed_uid: int, health_state: str) -> None:
        self.execute(
            """INSERT INTO mailbox_state(sender_id,mailbox_identifier,provider_type,uidvalidity,last_processed_uid,last_checked_at_utc,health_state)
               VALUES(?,?,?,?,?,?,?) ON CONFLICT(sender_id) DO UPDATE SET uidvalidity=excluded.uidvalidity,last_processed_uid=excluded.last_processed_uid,
               last_checked_at_utc=excluded.last_checked_at_utc,health_state=excluded.health_state""",
            [sender_id, "INBOX", "imap", uidvalidity, last_processed_uid, now_utc(), health_state],
        )

    def inbound_exists(self, sender_id: str, message_id: str) -> bool:
        return bool(self.fetchone("SELECT 1 FROM inbound_message WHERE sender_id=? AND message_id=?", [sender_id, message_id]))

    def save_inbound(self, *, sender_id: str, message_id: str, in_reply_to: str, references: str, received_at_utc: str,
                     lead_id: str | None, outreach_id: str | None, event_type: str, confidence: float, subject: str, from_email: str) -> bool:
        try:
            self.execute(
                """INSERT INTO inbound_message(inbound_message_id,sender_id,message_id,in_reply_to,references_text,received_at_utc,
                   lead_id,outreach_id,event_type,classification_confidence,processing_status,processed_at_utc,subject,from_email)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [str(uuid.uuid4()), sender_id, message_id, in_reply_to, references[:4000], received_at_utc, lead_id, outreach_id, event_type,
                 confidence, "PROCESSED", now_utc(), subject[:500], normalize_email(from_email)],
            )
            return True
        except Exception as exc:
            if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
                return False
            raise
