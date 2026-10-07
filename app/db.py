from __future__ import annotations

import hashlib
import json
import re
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso_utc(value: datetime | None = None) -> str:
    value = value or now_utc()
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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


def normalize_url(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    if "://" not in text:
        text = "https://" + text
    parsed = urlparse(text)
    if not parsed.hostname:
        return ""
    scheme = parsed.scheme.lower()
    host = parsed.hostname.lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    port = parsed.port
    if port and not ((scheme == "https" and port == 443) or (scheme == "http" and port == 80)):
        host = f"{host}:{port}"
    path = re.sub(r"/{2,}", "/", parsed.path or "/").rstrip("/") or "/"
    query = parsed.query
    return f"{scheme}://{host}{path}" + (f"?{query}" if query else "")


def deterministic_lead_id(email: str, place_id: str) -> str:
    return hashlib.sha256(f"lead|{normalize_email(email)}|{place_id.strip()}".encode()).hexdigest()


def deterministic_research_id(lead_id: str, version: str) -> str:
    return hashlib.sha256(f"research|{lead_id}|{version}".encode()).hexdigest()


def deterministic_outreach_id(lead_id: str, sequence_type: str, sequence_number: int) -> str:
    return hashlib.sha256(f"outreach|{lead_id}|{sequence_type}|{sequence_number}".encode()).hexdigest()


def deterministic_message_id(outreach_id: str, sender_email: str) -> str:
    domain = normalize_domain(sender_email) or "attachai.invalid"
    token = hashlib.sha256(f"message|{outreach_id}|{normalize_email(sender_email)}".encode()).hexdigest()[:32]
    return f"<attachai-{token}@{domain}>"


def _scalar_row(row: Any, default: Any = None) -> Any:
    if row is None:
        return default
    if isinstance(row, dict):
        return next(iter(row.values()))
    return row[0]


class Store:
    """The only durable state layer. Production is PostgreSQL/Supabase; sqlite is test-only."""

    def __init__(self, database_url: str):
        self.database_url = database_url
        self.is_sqlite = database_url.startswith("sqlite://")
        self.conn = None
        self._thread_lock = threading.RLock()
        self._lock_held = False
        if self.is_sqlite:
            import sqlite3
            path = database_url.removeprefix("sqlite://") or ":memory:"
            if path != ":memory:":
                Path(path).parent.mkdir(parents=True, exist_ok=True)
            self.conn = sqlite3.connect(path, timeout=30, isolation_level=None, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA foreign_keys=ON")
        else:
            try:
                import psycopg
                from psycopg.rows import dict_row
            except ImportError as exc:
                raise RuntimeError("psycopg[binary] is required for PostgreSQL") from exc
            url = database_url
            if "sslmode=" not in url:
                url += "&sslmode=require" if "?" in url else "?sslmode=require"
            self.conn = psycopg.connect(url, row_factory=dict_row, autocommit=True, prepare_threshold=None)

    def close(self) -> None:
        self.release_run_lock()
        if self.conn:
            self.conn.close()
            self.conn = None

    def _sql(self, query: str) -> str:
        return query if self.is_sqlite else query.replace("?", "%s")

    def execute(self, query: str, params: Iterable[Any] = ()):
        with self._thread_lock:
            cur = self.conn.cursor()
            cur.execute(self._sql(query), tuple(params))
            return cur

    def executemany(self, query: str, params_seq: Iterable[Iterable[Any]]):
        with self._thread_lock:
            cur = self.conn.cursor()
            cur.executemany(self._sql(query), [tuple(x) for x in params_seq])
            return cur

    def fetchone(self, query: str, params: Iterable[Any] = ()):
        cur = self.execute(query, params)
        try:
            return cur.fetchone()
        finally:
            cur.close()

    def fetchall(self, query: str, params: Iterable[Any] = ()):
        cur = self.execute(query, params)
        try:
            return cur.fetchall()
        finally:
            cur.close()

    def scalar(self, query: str, params: Iterable[Any] = (), default: Any = 0) -> Any:
        return _scalar_row(self.fetchone(query, params), default)

    @contextmanager
    def transaction(self):
        with self._thread_lock:
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
            raise RuntimeError("No migration files found")
        self.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at_utc TIMESTAMPTZ NOT NULL)")
        applied = {str(_scalar_row(r)) for r in self.fetchall("SELECT version FROM schema_migrations")}
        for path in files:
            if path.name in applied:
                continue
            sql = path.read_text(encoding="utf-8")
            statements = [s.strip() for s in re.split(r";\s*(?:\n|$)", sql) if s.strip() and not s.lstrip().startswith("--")]
            with self.transaction():
                for statement in statements:
                    self.execute(statement)
                self.execute("INSERT INTO schema_migrations(version,applied_at_utc) VALUES(?,?)", [path.name, now_utc()])

    def try_acquire_run_lock(self) -> bool:
        with self._thread_lock:
            if self.is_sqlite:
                acquired = self._lock_held is False
                self._lock_held = acquired
                return acquired
            row = self.fetchone("SELECT pg_try_advisory_lock(?) AS acquired", [89237111])
            self._lock_held = bool(row["acquired"] if isinstance(row, dict) else row[0])
            return self._lock_held

    def release_run_lock(self) -> None:
        with self._thread_lock:
            if not self._lock_held:
                return
            if not self.is_sqlite:
                self.execute("SELECT pg_advisory_unlock(?)", [89237111]).close()
            self._lock_held = False

    def reset_runtime_state(self) -> None:
        tables = [
            "inbound_message", "suppression", "retry_attempt", "event_log", "personalization_draft", "lead_research",
            "research_cache", "outreach", "outreach_batch", "sender_day", "lead_qualification", "discovery_candidate",
            "campaign_run", "workflow_run", "automation_cursor", "lead",
        ]
        with self.transaction():
            if self.is_sqlite:
                for table in tables:
                    self.execute(f"DELETE FROM {table}")
            else:
                self.execute("TRUNCATE TABLE " + ", ".join(tables) + " CASCADE")

    def reconcile_startup(self, *, sending_stale_minutes: int, research_stale_minutes: int, personalization_stale_minutes: int) -> dict[str, int]:
        now = now_utc()
        results: dict[str, int] = {}
        send_cutoff = now - timedelta(minutes=sending_stale_minutes)
        research_cutoff = now - timedelta(minutes=research_stale_minutes)
        personalization_cutoff = now - timedelta(minutes=personalization_stale_minutes)
        # SQL UPDATE rowcounts are collected directly from cursor.rowcount.
        cur = self.execute("UPDATE lead_research SET status='FAILED_RETRYABLE', error='stale_research_lease', updated_at_utc=? WHERE status='RESEARCHING' AND updated_at_utc < ?", [now, research_cutoff])
        try:
            results["research_requeued"] = cur.rowcount if cur.rowcount is not None else 0
        finally:
            cur.close()
        cur = self.execute("UPDATE personalization_draft SET status='RETRYABLE', validation_error='stale_personalization_lease', updated_at_utc=? WHERE status='IN_PROGRESS' AND updated_at_utc < ?", [now, personalization_cutoff])
        try:
            results["personalization_requeued"] = cur.rowcount or 0
        finally:
            cur.close()
        cur = self.execute("UPDATE outreach SET status='REVIEW_NEEDED', last_error='ambiguous_smtp_acceptance_after_runner_interruption', updated_at_utc=? WHERE status='SENDING' AND updated_at_utc < ?", [now, send_cutoff])
        try:
            results["ambiguous_sends"] = cur.rowcount or 0
        finally:
            cur.close()
        cur = self.execute("UPDATE outreach SET status='QUEUED', batch_id=NULL, updated_at_utc=? WHERE status='SCHEDULED' AND updated_at_utc < ?", [now, send_cutoff])
        try:
            results["scheduled_requeued"] = cur.rowcount or 0
        finally:
            cur.close()
        return results

    # ---- Workflow/campaign ------------------------------------------------------
    def get_active_campaign(self) -> Any | None:
        return self.fetchone(
            """SELECT c.*,
                      (SELECT count(*) FROM outreach o WHERE o.campaign_run_id=c.campaign_run_id AND o.sequence_type='INITIAL' AND o.status='SENT') AS successful_initials
               FROM campaign_run c
               WHERE c.status IN ('ACTIVE','BLOCKED')
                 AND c.successful_initials < c.target_new_initials
               ORDER BY c.created_at_utc ASC LIMIT 1"""
        )

    def create_campaign(self, target: int, workflow_run_id: str) -> str:
        campaign_id = str(uuid.uuid4())
        ts = now_utc()
        self.execute(
            "INSERT INTO campaign_run(campaign_run_id,workflow_run_id,target_new_initials,successful_initials,status,created_at_utc,updated_at_utc,last_block_reason) VALUES(?,?,?,?,?,?,?,NULL)",
            [campaign_id, workflow_run_id, target, 0, "ACTIVE", ts, ts],
        )
        return campaign_id

    def start_workflow(self, mode: str, reset_state: bool, target: int) -> tuple[str, str, bool]:
        workflow_id = str(uuid.uuid4())
        ts = now_utc()
        self.execute(
            "INSERT INTO workflow_run(workflow_run_id,started_at_utc,mode,status,reset_state,target_new_initials) VALUES(?,?,?,?,?,?)",
            [workflow_id, ts, mode, "RUNNING", reset_state, target],
        )
        campaign = self.get_active_campaign()
        resumed = campaign is not None
        campaign_id = str(campaign["campaign_run_id"] if campaign else self.create_campaign(target, workflow_id))
        self.execute("UPDATE workflow_run SET campaign_run_id=? WHERE workflow_run_id=?", [campaign_id, workflow_id])
        self.execute("UPDATE campaign_run SET workflow_run_id=?,updated_at_utc=? WHERE campaign_run_id=?", [workflow_id, ts, campaign_id])
        return workflow_id, campaign_id, resumed

    def finish_workflow(self, workflow_id: str, status: str, metrics: dict[str, Any]) -> None:
        self.execute("UPDATE workflow_run SET ended_at_utc=?,status=?,metrics_json=? WHERE workflow_run_id=?", [now_utc(), status, json.dumps(metrics, ensure_ascii=False), workflow_id])

    def finish_campaign(self, campaign_id: str, *, blocked: bool = False, reason: str | None = None) -> None:
        success = self.successful_initial_count(campaign_id)
        target = int(self.scalar("SELECT target_new_initials FROM campaign_run WHERE campaign_run_id=?", [campaign_id], 0))
        status = "SUCCESS" if success >= target else ("BLOCKED" if blocked else "ACTIVE")
        self.execute("UPDATE campaign_run SET successful_initials=?,status=?,last_block_reason=?,updated_at_utc=? WHERE campaign_run_id=?", [success, status, reason, now_utc(), campaign_id])

    def add_event(self, event_type: str, *, run_id: str | None = None, campaign_id: str | None = None, lead_id: str | None = None,
                  outreach_id: str | None = None, sender_id: str | None = None, batch_id: str | None = None,
                  sequence_type: str | None = None, status: str | None = None, reason: str | None = None,
                  metadata: dict[str, Any] | None = None) -> None:
        self.execute(
            """INSERT INTO event_log(event_id,event_timestamp_utc,event_type,workflow_run_id,campaign_run_id,lead_id,outreach_id,sender_id,batch_id,sequence_type,status,reason,metadata_json)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [str(uuid.uuid4()), now_utc(), event_type, run_id, campaign_id, lead_id, outreach_id, sender_id, batch_id, sequence_type, status, reason, json.dumps(metadata or {}, ensure_ascii=False)],
        )

    # ---- Leads / candidates -----------------------------------------------------
    def upsert_lead(self, lead: dict[str, Any]) -> str:
        lead_id = lead["lead_id"]
        existing = self.get_lead(lead_id)
        if existing:
            self.execute(
                """UPDATE lead SET email=?,company=?,website=?,website_domain=?,place_id=?,city=?,region=?,country_code=?,timezone=?,lead_source=?,scale_class=?,qualification_confidence=?,qualification_reason=?,discovery_facts=?,updated_at_utc=? WHERE lead_id=?""",
                [lead["email"], lead["company"], lead["website"], lead["website_domain"], lead["place_id"], lead.get("city", ""), lead.get("region", ""), lead["country_code"], lead["timezone"], lead["lead_source"], lead["scale_class"], lead["qualification_confidence"], lead.get("qualification_reason", ""), lead.get("discovery_facts", ""), now_utc(), lead_id],
            )
            return lead_id
        self.execute(
            """INSERT INTO lead(lead_id,email,company,website,website_domain,place_id,city,region,country_code,timezone,lead_source,scale_class,qualification_confidence,qualification_reason,discovery_facts,status,suppression_reason,research_attempts,next_research_at_utc,created_at_utc,updated_at_utc)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [lead_id, normalize_email(lead["email"]), lead["company"], lead["website"], normalize_domain(lead["website"]), lead["place_id"], lead.get("city", ""), lead.get("region", ""), lead["country_code"], lead["timezone"], lead["lead_source"], lead["scale_class"], lead["qualification_confidence"], lead.get("qualification_reason", ""), lead.get("discovery_facts", ""), lead.get("status", "ELIGIBLE"), None, 0, None, now_utc(), now_utc()],
        )
        return lead_id

    def get_lead(self, lead_id: str) -> Any | None:
        return self.fetchone("SELECT * FROM lead WHERE lead_id=?", [lead_id])

    def get_lead_by_email(self, email: str) -> Any | None:
        return self.fetchone("SELECT * FROM lead WHERE email=?", [normalize_email(email)])

    def get_lead_by_place_id(self, place_id: str) -> Any | None:
        return self.fetchone("SELECT * FROM lead WHERE place_id=?", [place_id])

    def set_lead_status(self, lead_id: str, status: str, suppression_reason: str | None = None) -> None:
        self.execute("UPDATE lead SET status=?,suppression_reason=COALESCE(?,suppression_reason),updated_at_utc=? WHERE lead_id=?", [status, suppression_reason, now_utc(), lead_id])

    def record_retry(self, entity_type: str, entity_id: str, attempt_number: int, error_class: str, error_message: str) -> None:
        self.execute(
            "INSERT INTO retry_attempt(retry_id,entity_type,entity_id,attempt_number,error_class,error_message,created_at_utc) VALUES(?,?,?,?,?,?,?)",
            [str(uuid.uuid4()), entity_type, entity_id, int(attempt_number), error_class[:120], error_message[:1000], now_utc()],
        )

    def mark_research_retry(self, lead_id: str, *, delay_seconds: int, terminal_after: int = 3, reason: str = "research_failed") -> bool:
        row = self.get_lead(lead_id)
        attempts = int(row["research_attempts"] or 0) + 1 if row else 1
        self.record_retry("lead_research", lead_id, attempts, reason, reason)
        if attempts >= terminal_after:
            self.execute("UPDATE lead SET status='REVIEW_NEEDED',research_attempts=?,next_research_at_utc=NULL,updated_at_utc=? WHERE lead_id=?", [attempts, now_utc(), lead_id])
            return False
        self.execute("UPDATE lead SET status='ELIGIBLE',research_attempts=?,next_research_at_utc=?,updated_at_utc=? WHERE lead_id=?", [attempts, now_utc() + timedelta(seconds=delay_seconds), now_utc(), lead_id])
        return True

    def insert_qualification(self, lead_id: str, action: str, confidence: float, reason: str, run_id: str, evidence_urls: list[str]) -> None:
        self.execute(
            "INSERT INTO lead_qualification(qualification_id,lead_id,workflow_run_id,action,confidence,reason,evidence_urls_json,created_at_utc) VALUES(?,?,?,?,?,?,?,?)",
            [str(uuid.uuid4()), lead_id, run_id, action, confidence, reason, json.dumps(evidence_urls), now_utc()],
        )

    def upsert_candidate(self, *, place_id: str, company: str, website: str, address: str, country_code: str, types: list[str], query: str) -> tuple[str, bool]:
        existing = self.fetchone("SELECT candidate_id FROM discovery_candidate WHERE place_id=?", [place_id])
        if existing:
            self.execute("UPDATE discovery_candidate SET company=?,website=?,address=?,country_code=?,types_json=?,query=?,last_seen_at_utc=? WHERE place_id=?", [company, website, address, country_code, json.dumps(types), query, now_utc(), place_id])
            return str(existing["candidate_id"] if isinstance(existing, dict) else existing[0]), False
        candidate_id = str(uuid.uuid4())
        self.execute(
            "INSERT INTO discovery_candidate(candidate_id,place_id,company,website,address,country_code,types_json,query,status,attempts,next_retry_at_utc,last_reason,last_seen_at_utc,created_at_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [candidate_id, place_id, company, website, address, country_code, json.dumps(types), query, "DISCOVERED", 0, None, None, now_utc(), now_utc()],
        )
        return candidate_id, True

    def list_pending_candidates(self, limit: int) -> list[Any]:
        return self.fetchall(
            """SELECT dc.* FROM discovery_candidate dc
               LEFT JOIN lead l ON l.place_id=dc.place_id
               WHERE l.lead_id IS NULL AND dc.status IN ('DISCOVERED','RETRYABLE')
                 AND (dc.next_retry_at_utc IS NULL OR dc.next_retry_at_utc <= ?)
               ORDER BY dc.created_at_utc ASC LIMIT ?""",
            [now_utc(), limit],
        )

    def set_candidate_result(self, candidate_id: str, status: str, *, reason: str | None = None, next_retry_at: datetime | None = None, increment_attempt: bool = False) -> None:
        if increment_attempt:
            self.execute("UPDATE discovery_candidate SET attempts=attempts+1,status=?,last_reason=?,next_retry_at_utc=?,last_seen_at_utc=? WHERE candidate_id=?", [status, reason, next_retry_at, now_utc(), candidate_id])
            row = self.fetchone("SELECT attempts FROM discovery_candidate WHERE candidate_id=?", [candidate_id])
            self.record_retry("candidate", candidate_id, int(row["attempts"] if row else 1), status, reason or status)
        else:
            self.execute("UPDATE discovery_candidate SET status=?,last_reason=?,next_retry_at_utc=?,last_seen_at_utc=? WHERE candidate_id=?", [status, reason, next_retry_at, now_utc(), candidate_id])

    # ---- Research / personalization --------------------------------------------
    def get_research_cache(self, canonical_url: str, version: str) -> Any | None:
        return self.fetchone("SELECT * FROM research_cache WHERE canonical_url=? AND research_version=?", [canonical_url, version])

    def save_research_cache(self, canonical_url: str, version: str, pages: list[Any], research: dict, status: str, error: str | None) -> str:
        cache_id = hashlib.sha256(f"cache|{canonical_url}|{version}".encode()).hexdigest()
        pages_json = json.dumps([p.__dict__ | {"links": list(p.links), "emails": list(getattr(p, "emails", ())) } if hasattr(p, "__dict__") else p for p in pages], ensure_ascii=False)
        research_json = json.dumps(research, ensure_ascii=False)
        self.execute(
            """INSERT INTO research_cache(cache_id,canonical_url,research_version,pages_json,research_json,status,error,created_at_utc,updated_at_utc)
               VALUES(?,?,?,?,?,?,?,?,?)
               ON CONFLICT(canonical_url,research_version) DO UPDATE SET pages_json=excluded.pages_json,research_json=excluded.research_json,status=excluded.status,error=excluded.error,updated_at_utc=excluded.updated_at_utc""",
            [cache_id, canonical_url, version, pages_json, research_json, status, error, now_utc(), now_utc()],
        )
        return cache_id

    def save_lead_research(self, lead_id: str, cache_id: str, status: str, error: str | None = None) -> str:
        row = self.fetchone("SELECT research_id FROM lead_research WHERE lead_id=? AND research_version=(SELECT research_version FROM research_cache WHERE cache_id=?)", [lead_id, cache_id])
        version = str(self.scalar("SELECT research_version FROM research_cache WHERE cache_id=?", [cache_id], ""))
        research_id = str(row["research_id"] if row else deterministic_research_id(lead_id, version))
        self.execute(
            """INSERT INTO lead_research(research_id,lead_id,cache_id,research_version,status,error,retry_count,created_at_utc,updated_at_utc)
               VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(lead_id,research_version) DO UPDATE SET cache_id=excluded.cache_id,status=excluded.status,error=excluded.error,updated_at_utc=excluded.updated_at_utc""",
            [research_id, lead_id, cache_id, version, status, error, 0, now_utc(), now_utc()],
        )
        return research_id

    def latest_research(self, lead_id: str) -> Any | None:
        return self.fetchone(
            "SELECT lr.*,rc.canonical_url,rc.pages_json,rc.research_json,rc.status AS cache_status FROM lead_research lr JOIN research_cache rc ON rc.cache_id=lr.cache_id WHERE lr.lead_id=? ORDER BY lr.updated_at_utc DESC LIMIT 1",
            [lead_id],
        )

    def save_personalization(self, *, lead_id: str, campaign_id: str, outreach_id: str, sequence_type: str, payload: dict, validation_valid: bool, validation_error: str | None, attempts: int) -> str:
        draft_id = hashlib.sha256(f"draft|{outreach_id}".encode()).hexdigest()
        self.execute(
            """INSERT INTO personalization_draft(draft_id,lead_id,campaign_run_id,outreach_id,sequence_type,payload_json,status,validation_error,repair_attempts,created_at_utc,updated_at_utc)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(outreach_id) DO UPDATE SET payload_json=excluded.payload_json,status=excluded.status,validation_error=excluded.validation_error,repair_attempts=excluded.repair_attempts,updated_at_utc=excluded.updated_at_utc""",
            [draft_id, lead_id, campaign_id, outreach_id, sequence_type, json.dumps(payload, ensure_ascii=False), "VALIDATED" if validation_valid else "REVIEW_NEEDED", validation_error, attempts, now_utc(), now_utc()],
        )
        return draft_id

    # ---- Suppression ------------------------------------------------------------
    def is_suppressed(self, email: str) -> bool:
        return self.fetchone("SELECT email FROM suppression WHERE email=?", [normalize_email(email)]) is not None

    def suppress(self, email: str, lead_id: str | None, reason: str) -> None:
        normalized = normalize_email(email)
        self.execute(
            "INSERT INTO suppression(email,lead_id,reason,created_at_utc) VALUES(?,?,?,?) ON CONFLICT(email) DO UPDATE SET lead_id=excluded.lead_id,reason=excluded.reason",
            [normalized, lead_id, reason, now_utc()],
        )
        if lead_id:
            self.set_lead_status(lead_id, {"reply": "REPLIED", "hard_bounce": "BOUNCED", "unsubscribe": "UNSUBSCRIBED"}.get(reason, "MANUAL_STOP"), reason)
            self.execute("UPDATE outreach SET status='CANCELLED',updated_at_utc=?,last_error=? WHERE lead_id=? AND sequence_type<>'INITIAL' AND status IN ('WAITING_DUE','DRAFT','VALIDATED','QUEUED','SCHEDULED','FAILED_RETRYABLE')", [now_utc(), reason, lead_id])

    # ---- Sender health ----------------------------------------------------------
    def sender_day(self, sender_id: str, date_key: str) -> Any:
        row = self.fetchone("SELECT * FROM sender_day WHERE sender_id=? AND date_key=?", [sender_id, date_key])
        if row:
            return row
        self.execute("INSERT INTO sender_day(sender_id,date_key,initials,followups,total,failures,authentication_failures,temporary_provider_failures,cooldown_until_utc,health_state,last_successful_send_utc,updated_at_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", [sender_id, date_key, 0, 0, 0, 0, 0, 0, None, "HEALTHY", None, now_utc()])
        return self.fetchone("SELECT * FROM sender_day WHERE sender_id=? AND date_key=?", [sender_id, date_key])

    def set_sender_health(self, sender_id: str, date_key: str, state: str, cooldown_until: datetime | None = None) -> None:
        self.sender_day(sender_id, date_key)
        self.execute("UPDATE sender_day SET health_state=?,cooldown_until_utc=?,updated_at_utc=? WHERE sender_id=? AND date_key=?", [state, cooldown_until, now_utc(), sender_id, date_key])

    def record_send_success(self, sender_id: str, date_key: str, is_followup: bool, sent_at: datetime) -> None:
        self.sender_day(sender_id, date_key)
        if is_followup:
            self.execute("UPDATE sender_day SET followups=followups+1,total=total+1,last_successful_send_utc=?,health_state='HEALTHY',cooldown_until_utc=NULL,updated_at_utc=? WHERE sender_id=? AND date_key=?", [sent_at, now_utc(), sender_id, date_key])
        else:
            self.execute("UPDATE sender_day SET initials=initials+1,total=total+1,last_successful_send_utc=?,health_state='HEALTHY',cooldown_until_utc=NULL,updated_at_utc=? WHERE sender_id=? AND date_key=?", [sent_at, now_utc(), sender_id, date_key])

    def record_send_failure(self, sender_id: str, date_key: str, kind: str, cooldown_until: datetime | None = None) -> None:
        self.sender_day(sender_id, date_key)
        if kind == "authentication":
            self.execute("UPDATE sender_day SET failures=failures+1,authentication_failures=authentication_failures+1,health_state='STOPPED',cooldown_until_utc=NULL,updated_at_utc=? WHERE sender_id=? AND date_key=?", [now_utc(), sender_id, date_key])
        elif kind == "temporary/provider/network":
            self.execute("UPDATE sender_day SET failures=failures+1,temporary_provider_failures=temporary_provider_failures+1,health_state='COOLDOWN',cooldown_until_utc=?,updated_at_utc=? WHERE sender_id=? AND date_key=?", [cooldown_until, now_utc(), sender_id, date_key])
        else:
            self.execute("UPDATE sender_day SET failures=failures+1,updated_at_utc=? WHERE sender_id=? AND date_key=?", [now_utc(), sender_id, date_key])

    def available_senders(self, sender_configs: list[Any], *, is_followup: bool, enforce_limits: bool, at: datetime) -> list[Any]:
        date_key = at.date().isoformat()
        available: list[Any] = []
        for sender in sender_configs:
            day = self.sender_day(sender.sender_id, date_key)
            state = str(day["health_state"])
            cooldown = day["cooldown_until_utc"]
            if state == "STOPPED":
                continue
            if state == "COOLDOWN" and cooldown and cooldown > at:
                continue
            if enforce_limits:
                if int(day["total"]) >= int(sender.daily_total_limit if hasattr(sender, "daily_total_limit") else 10**9):
                    continue
            available.append(sender)
        return available

    # ---- Outreach ---------------------------------------------------------------
    def successful_initial_count(self, campaign_id: str) -> int:
        return int(self.scalar("SELECT count(*) FROM outreach WHERE campaign_run_id=? AND sequence_type='INITIAL' AND status='SENT'", [campaign_id], 0))

    def pending_initial_count(self, campaign_id: str) -> int:
        return int(self.scalar("SELECT count(*) FROM outreach WHERE campaign_run_id=? AND sequence_type='INITIAL' AND status IN ('QUEUED','SCHEDULED','SENDING','FAILED_RETRYABLE')", [campaign_id], 0))

    def insert_outreach(self, record: dict[str, Any]) -> bool:
        outreach_id = record["outreach_id"]
        try:
            self.execute(
                """INSERT INTO outreach(outreach_id,workflow_run_id,campaign_run_id,batch_id,lead_id,sequence_type,sequence_number,sender_id,sender_email,email,subject,body,status,scheduled_at_utc,attempted_at_utc,sent_at_utc,smtp_message_id,retry_count,next_retry_at_utc,last_error,evidence_urls_json,personalization_confidence,in_reply_to,references_text,created_at_utc,updated_at_utc)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [outreach_id, record["workflow_run_id"], record["campaign_id"], None, record["lead_id"], record["sequence_type"], record["sequence_number"], record.get("sender_id", ""), record.get("sender_email", ""), record["email"], record["subject"], record["body"], record.get("status", "QUEUED"), record.get("scheduled_at_utc"), None, None, record.get("smtp_message_id"), 0, None, None, json.dumps(record.get("evidence_urls", [])), record.get("confidence", 0), record.get("in_reply_to"), record.get("references_text"), now_utc(), now_utc()],
            )
            return True
        except Exception as exc:
            if "unique" in str(exc).lower() or "duplicate" in str(exc).lower() or "constraint" in str(exc).lower():
                return False
            raise

    def get_outreach(self, outreach_id: str) -> Any | None:
        return self.fetchone("SELECT * FROM outreach WHERE outreach_id=?", [outreach_id])

    def get_sequence(self, lead_id: str, sequence_type: str) -> Any | None:
        return self.fetchone("SELECT * FROM outreach WHERE lead_id=? AND sequence_type=?", [lead_id, sequence_type])

    def list_ready_initials(self, campaign_id: str, limit: int = 10) -> list[Any]:
        return self.fetchall(
            """SELECT o.*,l.status AS lead_status FROM outreach o JOIN lead l ON l.lead_id=o.lead_id
               WHERE o.campaign_run_id=? AND o.sequence_type='INITIAL' AND o.status IN ('QUEUED','FAILED_RETRYABLE')
                 AND (o.next_retry_at_utc IS NULL OR o.next_retry_at_utc <= ?)
                 AND l.status NOT IN ('REPLIED','BOUNCED','UNSUBSCRIBED','MANUAL_STOP')
                 AND NOT EXISTS (SELECT 1 FROM suppression s WHERE s.email=o.email)
               ORDER BY o.created_at_utc ASC LIMIT ?""",
            [campaign_id, now_utc(), limit],
        )

    def list_queued_followups(self, limit: int = 100) -> list[Any]:
        return self.fetchall(
            """SELECT o.*,l.status AS lead_status FROM outreach o JOIN lead l ON l.lead_id=o.lead_id
               WHERE o.sequence_type<>'INITIAL' AND o.status IN ('WAITING_DUE','QUEUED','FAILED_RETRYABLE') AND (o.scheduled_at_utc IS NULL OR o.scheduled_at_utc <= ?) AND (o.next_retry_at_utc IS NULL OR o.next_retry_at_utc <= ?)
                 AND l.status NOT IN ('REPLIED','BOUNCED','UNSUBSCRIBED','MANUAL_STOP')
                 AND NOT EXISTS (SELECT 1 FROM suppression s WHERE s.email=o.email)
               ORDER BY COALESCE(o.scheduled_at_utc,o.created_at_utc) ASC LIMIT ?""",
            [now_utc(), now_utc(), limit],
        )

    def queue_followup_draft(self, outreach_id: str, subject: str, body: str, evidence_urls: list[str], confidence: float, in_reply_to: str, references_text: str) -> None:
        self.execute("UPDATE outreach SET subject=?,body=?,evidence_urls_json=?,personalization_confidence=?,in_reply_to=?,references_text=?,status='QUEUED',updated_at_utc=? WHERE outreach_id=? AND status IN ('WAITING_DUE','REVIEW_NEEDED','DRAFT')", [subject, body, json.dumps(evidence_urls), confidence, in_reply_to, references_text, now_utc(), outreach_id])

    def create_followup_row(self, *, workflow_id: str, campaign_id: str, lead: Any, previous: Any, sequence_type: str, sequence_number: int, scheduled_at: datetime) -> str | None:
        required_previous = {"FOLLOWUP_1": "INITIAL", "FOLLOWUP_2": "FOLLOWUP_1", "FOLLOWUP_3": "FOLLOWUP_2"}.get(sequence_type)
        if required_previous is None or not previous or str(previous["sequence_type"]) != required_previous or str(previous["status"]) != "SENT":
            return None
        outreach_id = deterministic_outreach_id(str(lead["lead_id"]), sequence_type, sequence_number)
        if self.get_outreach(outreach_id):
            return None
        if not str(previous["sender_id"] or "").strip() or not str(previous["sender_email"] or "").strip() or not str(previous["smtp_message_id"] or "").strip():
            return None
        self.insert_outreach({
            "outreach_id": outreach_id,
            "workflow_run_id": workflow_id,
            "campaign_id": campaign_id,
            "lead_id": lead["lead_id"],
            "sequence_type": sequence_type,
            "sequence_number": sequence_number,
            "sender_id": previous["sender_id"],
            "sender_email": previous["sender_email"],
            "smtp_message_id": deterministic_message_id(outreach_id, previous["sender_email"]),
            "email": lead["email"],
            "subject": "",
            "body": "",
            "status": "WAITING_DUE",
            "scheduled_at_utc": scheduled_at,
            "in_reply_to": previous["smtp_message_id"],
            "references_text": previous["references_text"] or previous["smtp_message_id"],
            "confidence": 0,
            "evidence_urls": [],
        })
        return outreach_id

    def create_batch(self, workflow_id: str, campaign_id: str, batch_type: str, batch_number: int, row_ids: list[str]) -> str:
        batch_id = str(uuid.uuid4())
        self.execute("INSERT INTO outreach_batch(batch_id,workflow_run_id,campaign_run_id,batch_number,batch_type,status,target_count,attempted_count,successful_count,failed_count,created_at_utc,updated_at_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", [batch_id, workflow_id, campaign_id, batch_number, batch_type, "SCHEDULED", len(row_ids), 0, 0, 0, now_utc(), now_utc()])
        placeholders = ",".join("?" for _ in row_ids)
        if row_ids:
            self.execute(f"UPDATE outreach SET batch_id=?,status='SCHEDULED',updated_at_utc=? WHERE outreach_id IN ({placeholders}) AND status IN ('QUEUED','FAILED_RETRYABLE')", [batch_id, now_utc(), *row_ids])
        return batch_id

    def assign_batch(self, batch_id: str, assignments: list[tuple[str, str, str, str]]) -> None:
        with self.transaction():
            seen: set[str] = set()
            for outreach_id, lead_id, sender_id, sender_email in assignments:
                if sender_id in seen:
                    raise ValueError("batch cannot assign more than one outreach to a sender")
                seen.add(sender_id)
                mid = deterministic_message_id(outreach_id, sender_email)
                self.execute("UPDATE outreach SET sender_id=?,sender_email=?,smtp_message_id=?,status='SCHEDULED',updated_at_utc=? WHERE outreach_id=? AND batch_id=?", [sender_id, sender_email, mid, now_utc(), outreach_id, batch_id])

    def claim_for_send(self, outreach_id: str) -> bool:
        cur = self.execute("UPDATE outreach SET status='SENDING',attempted_at_utc=?,updated_at_utc=? WHERE outreach_id=? AND (status='SCHEDULED' OR (status='QUEUED' AND sender_id<>'' AND sender_email<>'' AND smtp_message_id IS NOT NULL))", [now_utc(), now_utc(), outreach_id])
        try:
            return (cur.rowcount or 0) == 1
        finally:
            cur.close()

    def mark_sent(self, outreach_id: str, sent_at: datetime) -> None:
        self.execute("UPDATE outreach SET status='SENT',sent_at_utc=?,next_retry_at_utc=NULL,last_error=NULL,updated_at_utc=? WHERE outreach_id=? AND status='SENDING'", [sent_at, now_utc(), outreach_id])

    def mark_failed(self, outreach_id: str, *, error_class: str, error: str, retryable: bool, next_retry_at: datetime | None, sender_id: str) -> None:
        status = "FAILED_RETRYABLE" if retryable else "FAILED_TERMINAL"
        self.execute("UPDATE outreach SET status=?,retry_count=retry_count+1,next_retry_at_utc=?,last_error=?,updated_at_utc=? WHERE outreach_id=? AND status='SENDING'", [status, next_retry_at, error[:1000], now_utc(), outreach_id])
        row = self.get_outreach(outreach_id)
        self.record_retry("outreach", outreach_id, int(row["retry_count"] if row else 1), error_class, error)

    def mark_review_needed(self, outreach_id: str, reason: str) -> None:
        self.execute("UPDATE outreach SET status='REVIEW_NEEDED',last_error=?,updated_at_utc=? WHERE outreach_id=?", [reason, now_utc(), outreach_id])

    def complete_batch(self, batch_id: str, attempted: int, successful: int, failed: int) -> None:
        status = "COMPLETED" if failed == 0 else ("PARTIAL" if successful else "FAILED")
        self.execute("UPDATE outreach_batch SET status=?,attempted_count=?,successful_count=?,failed_count=?,completed_at_utc=?,updated_at_utc=? WHERE batch_id=?", [status, attempted, successful, failed, now_utc(), now_utc(), batch_id])

    def next_batch_number(self, workflow_id: str, batch_type: str) -> int:
        value = self.scalar("SELECT COALESCE(MAX(batch_number),0)+1 FROM outreach_batch WHERE workflow_run_id=? AND batch_type=?", [workflow_id, batch_type], 1)
        return int(value)

    def count_message_status(self, campaign_id: str, sequence_type: str, status: str) -> int:
        return int(self.scalar("SELECT count(*) FROM outreach WHERE campaign_run_id=? AND sequence_type=? AND status=?", [campaign_id, sequence_type, status], 0))

    def previous_successful(self, lead_id: str) -> Any | None:
        return self.fetchone("SELECT * FROM outreach WHERE lead_id=? AND status='SENT' ORDER BY sent_at_utc DESC LIMIT 1", [lead_id])

    # ---- Mailbox ----------------------------------------------------------------
    def mailbox_state(self, sender_id: str) -> Any | None:
        return self.fetchone("SELECT * FROM mailbox_state WHERE sender_id=?", [sender_id])

    def save_mailbox_state(self, sender_id: str, uidvalidity: str | None, last_uid: int, health_state: str) -> None:
        self.execute("INSERT INTO mailbox_state(sender_id,uidvalidity,last_processed_uid,last_checked_at_utc,health_state) VALUES(?,?,?,?,?) ON CONFLICT(sender_id) DO UPDATE SET uidvalidity=excluded.uidvalidity,last_processed_uid=excluded.last_processed_uid,last_checked_at_utc=excluded.last_checked_at_utc,health_state=excluded.health_state", [sender_id, uidvalidity, last_uid, now_utc(), health_state])

    def inbound_exists(self, sender_id: str, message_id: str) -> bool:
        return self.fetchone("SELECT 1 FROM inbound_message WHERE sender_id=? AND message_id=?", [sender_id, message_id]) is not None

    def save_inbound(self, *, inbound_id: str, sender_id: str, message_id: str, in_reply_to: str, references_text: str, received_at: datetime, from_email: str, subject: str, event_type: str, confidence: float, lead_id: str | None, outreach_id: str | None) -> bool:
        try:
            self.execute("INSERT INTO inbound_message(inbound_message_id,sender_id,message_id,in_reply_to,references_text,received_at_utc,from_email,subject,event_type,classification_confidence,processing_status,processed_at_utc,lead_id,outreach_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [inbound_id, sender_id, message_id, in_reply_to, references_text, received_at, normalize_email(from_email), subject[:500], event_type, confidence, "PROCESSED", now_utc(), lead_id, outreach_id])
            return True
        except Exception as exc:
            if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
                return False
            raise

    def reconcile_inbound_cursor(self, sender_id: str, uidvalidity: str | None) -> tuple[int, bool]:
        row = self.mailbox_state(sender_id)
        if not row:
            return 0, True
        if uidvalidity and row["uidvalidity"] and str(row["uidvalidity"]) != str(uidvalidity):
            return 0, True
        return int(row["last_processed_uid"]), False

    # ---- Metrics / automation ---------------------------------------------------
    def count_events(self, workflow_id: str) -> dict[str, int]:
        rows = self.fetchall("SELECT event_type,count(*) AS n FROM event_log WHERE workflow_run_id=? GROUP BY event_type", [workflow_id])
        return {str(r["event_type"]): int(r["n"]) for r in rows}

    def automation_last_trigger(self, key: str) -> datetime | None:
        row = self.fetchone("SELECT last_triggered_at_utc FROM automation_cursor WHERE cursor_key=?", [key])
        if not row or not row["last_triggered_at_utc"]:
            return None
        value = row["last_triggered_at_utc"]
        return value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))

    def set_automation_last_trigger(self, key: str, when: datetime) -> None:
        self.execute("INSERT INTO automation_cursor(cursor_key,last_triggered_at_utc) VALUES(?,?) ON CONFLICT(cursor_key) DO UPDATE SET last_triggered_at_utc=excluded.last_triggered_at_utc", [key, when])

    # Backward-compatible test/API alias; the durable table and semantics are unchanged.
    def save_automation_last_trigger(self, key: str, when: datetime) -> None:
        self.set_automation_last_trigger(key, when)
