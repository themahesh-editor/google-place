from __future__ import annotations

import email
import imaplib
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.utils import parseaddr, parsedate_to_datetime

from app.models import InboundEventType

HARD_RE = re.compile(r"(?:5\.1\.1|5\.1\.0|5\.2\.1|user unknown|mailbox .*not found|recipient .*does not exist|no such user|address rejected|unknown user|\b550\b|\b551\b|\b553\b)", re.I)
SOFT_RE = re.compile(r"(?:4\.2\.0|4\.3\.0|4\.4\.1|mailbox full|temporar|try again|deferred|\b421\b|\b450\b|\b451\b|\b452\b)", re.I)
OPT_OUT_RE = re.compile(r"\b(?:unsubscribe|remove me|stop emailing me|do not contact me|don['’]?t contact me|take me off|opt[ -]?out)\b", re.I)
DSN_RE = re.compile(r"(?:delivery status notification|delivery failure|mail delivery|undeliverable|returned mail|failure notice|message not delivered|mailer-daemon|postmaster)", re.I)


@dataclass(frozen=True)
class ParsedInbound:
    message_id: str
    in_reply_to: str
    references: list[str]
    subject: str
    from_email: str
    received_at_utc: str
    text_excerpt: str


class IMAPProvider:
    def __init__(self, sender, credential: str):
        self.sender = sender
        self.credential = credential
        self.client = None
        self.uidvalidity = None

    def connect(self) -> None:
        if self.sender.imap_ssl:
            self.client = imaplib.IMAP4_SSL(self.sender.imap_host, self.sender.imap_port)
        else:
            self.client = imaplib.IMAP4(self.sender.imap_host, self.sender.imap_port)
            self.client.starttls()
        self.client.login(self.sender.email, self.credential)
        status, _ = self.client.select("INBOX", readonly=True)
        if status != "OK":
            raise RuntimeError("IMAP INBOX select failed")
        try:
            _, data = self.client.response("UIDVALIDITY")
            self.uidvalidity = data[0].decode() if data and isinstance(data[0], bytes) else str(data[0]) if data else None
        except Exception:
            self.uidvalidity = None

    def fetch_since(self, last_uid: int, lookback_minutes: int, max_messages: int) -> list[tuple[int, bytes]]:
        since = (datetime.now(timezone.utc) - timedelta(minutes=lookback_minutes)).strftime("%d-%b-%Y")
        status, data = self.client.uid("SEARCH", None, f'(SINCE "{since}" UID {max(1,last_uid + 1)}:*)')
        if status != "OK" or not data or not data[0]:
            return []
        uids = [int(x) for x in data[0].split()]
        uids = uids[:max_messages]
        out = []
        for uid in uids:
            status, parts = self.client.uid("FETCH", str(uid), "(RFC822)")
            if status == "OK":
                for part in parts:
                    if isinstance(part, tuple):
                        out.append((uid, part[1]))
        return out

    def close(self) -> None:
        if self.client:
            try: self.client.close()
            except Exception: pass
            try: self.client.logout()
            except Exception: pass
            self.client = None


def header(msg, name: str) -> str:
    try: return str(make_header(decode_header(msg.get(name, ""))))
    except Exception: return msg.get(name, "") or ""


def parse_message(raw: bytes) -> ParsedInbound:
    msg = email.message_from_bytes(raw)
    raw_date = header(msg, "Date")
    try:
        received = parsedate_to_datetime(raw_date).astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z") if raw_date else now_utc()
    except (TypeError, ValueError, OverflowError):
        received = now_utc()
    body = []
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in str(part.get("Content-Disposition", "")).lower():
                try: body.append(part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace"))
                except Exception: pass
    elif msg.get_content_type() == "text/plain":
        try: body.append(msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8", "replace"))
        except Exception: pass
    text = re.sub(r"\s+", " ", " ".join(body)).strip()[:5000]
    return ParsedInbound(header(msg,"Message-ID").strip(), header(msg,"In-Reply-To").strip(), re.findall(r"<[^>]+>", header(msg,"References")), header(msg,"Subject").strip(), parseaddr(header(msg,"From"))[1].lower(), received, text)


def classify(msg: ParsedInbound) -> tuple[InboundEventType, float]:
    combined = f"{msg.subject}\n{msg.text_excerpt}"
    if OPT_OUT_RE.search(combined): return InboundEventType.UNSUBSCRIBED, 0.99
    dsn = DSN_RE.search(combined) or msg.from_email.split("@",1)[0] in {"mailer-daemon", "postmaster"}
    if dsn and HARD_RE.search(combined): return InboundEventType.HARD_BOUNCE, 0.97
    if dsn and SOFT_RE.search(combined): return InboundEventType.SOFT_BOUNCE, 0.93
    return InboundEventType.REPLY, 0.80


class MailboxMonitor:
    def __init__(self, store, settings, run_id: str, provider_factory=IMAPProvider):
        self.store = store; self.settings = settings; self.run_id = run_id; self.provider_factory = provider_factory

    def _correlate(self, sender_id: str, parsed: ParsedInbound):
        for ref in [parsed.in_reply_to, *parsed.references]:
            if ref:
                row = self.store.fetchone("SELECT * FROM outreach WHERE message_id=?", [ref])
                if row:
                    return row["lead_id"], row["outreach_id"]
        lead = self.store.get_lead_by_email(parsed.from_email)
        if lead:
            row = self.store.fetchone("SELECT * FROM outreach WHERE lead_id=? AND sender_id=? AND status='SENT' ORDER BY sent_at_utc DESC LIMIT 1", [lead["lead_id"], sender_id])
            return lead["lead_id"], row["outreach_id"] if row else None
        return None, None

    def run_sender(self, sender) -> dict[str, int]:
        credential = os.getenv(sender.credential_env, "").strip()
        provider = self.provider_factory(sender, credential)
        provider.connect()
        state = self.store.mailbox_state(sender.sender_id)
        last_uid = int(state["last_processed_uid"]) if state else 0
        prior_validity = str(state["uidvalidity"]) if state and state["uidvalidity"] else None
        if prior_validity and provider.uidvalidity and prior_validity != provider.uidvalidity:
            last_uid = 0
            self.store.add_event("mailbox_uidvalidity_changed", run_id=self.run_id, sender_id=sender.sender_id, status="REBASE", reason="uidvalidity_changed")
        items = provider.fetch_since(last_uid, self.settings.mailbox_check_lookback_minutes, self.settings.mailbox_max_messages_per_run)
        processed = replies = bounces = unsubscribes = 0
        max_seen = last_uid
        lookback = datetime.now(timezone.utc) - timedelta(minutes=self.settings.mailbox_check_lookback_minutes)
        for uid, raw in items:
            max_seen = max(max_seen, uid)
            parsed = parse_message(raw)
            message_id = parsed.message_id or f"<imap-{sender.sender_id.lower()}-{uid}@local>"
            if self.store.inbound_exists(sender.sender_id, message_id):
                continue
            received_at = datetime.fromisoformat(parsed.received_at_utc.replace("Z", "+00:00"))
            if received_at < lookback:
                continue
            event, confidence = classify(parsed)
            lead_id, outreach_id = self._correlate(sender.sender_id, parsed)
            if event == InboundEventType.REPLY and not lead_id:
                event, confidence = InboundEventType.UNCLASSIFIED, 0.45
            if event == InboundEventType.HARD_BOUNCE and not lead_id:
                event, confidence = InboundEventType.REVIEW_NEEDED, 0.45
            try:
                inserted = self.store.save_inbound(sender_id=sender.sender_id, message_id=message_id, in_reply_to=parsed.in_reply_to, references=" ".join(parsed.references), received_at_utc=parsed.received_at_utc, lead_id=lead_id, outreach_id=outreach_id, event_type=event.value, confidence=confidence, subject=parsed.subject, from_email=parsed.from_email)
                if not inserted:
                    continue
                processed += 1
                if event == InboundEventType.REPLY and lead_id:
                    self.store.update_lead_status(lead_id, "REPLIED"); self.store.cancel_future_followups(lead_id); replies += 1
                    self.store.add_event("reply_detected", run_id=self.run_id, lead_id=lead_id, outreach_id=outreach_id, sender_id=sender.sender_id, status="REPLIED")
                elif event == InboundEventType.HARD_BOUNCE and lead_id:
                    lead = self.store.get_lead(lead_id); self.store.suppress(lead["email"], lead_id, "hard_bounce"); self.store.update_lead_status(lead_id, "BOUNCED"); self.store.cancel_future_followups(lead_id); bounces += 1
                    self.store.add_event("bounce_detected", run_id=self.run_id, lead_id=lead_id, outreach_id=outreach_id, sender_id=sender.sender_id, status="HARD_BOUNCE")
                elif event == InboundEventType.UNSUBSCRIBED and lead_id:
                    lead = self.store.get_lead(lead_id); self.store.suppress(lead["email"], lead_id, "unsubscribe"); self.store.update_lead_status(lead_id, "UNSUBSCRIBED"); self.store.cancel_future_followups(lead_id); unsubscribes += 1
                    self.store.add_event("unsubscribe_detected", run_id=self.run_id, lead_id=lead_id, outreach_id=outreach_id, sender_id=sender.sender_id, status="UNSUBSCRIBED")
                elif event == InboundEventType.SOFT_BOUNCE:
                    bounces += 1
                self.store.add_event("inbound_processed", run_id=self.run_id, lead_id=lead_id, outreach_id=outreach_id, sender_id=sender.sender_id, status=event.value)
            except Exception as exc:
                self.store.add_event("inbound_processing_error", run_id=self.run_id, sender_id=sender.sender_id, status="FAILED", reason=exc.__class__.__name__)
        current_state = self.store.sender_day(sender.sender_id, datetime.now(self.settings.timezone()).date().isoformat())
        current_health = "STOPPED" if current_state["health_state"] == "STOPPED" else "HEALTHY"
        if current_health == "HEALTHY" and current_state["health_state"] == "DEGRADED":
            self.store.set_sender_health(sender.sender_id, datetime.now(self.settings.timezone()).date().isoformat(), "HEALTHY", None)
        self.store.save_mailbox_state(sender_id=sender.sender_id, uidvalidity=provider.uidvalidity or prior_validity, last_processed_uid=max_seen, health_state=current_health)
        provider.close()
        self.store.add_event("mailbox_check", run_id=self.run_id, sender_id=sender.sender_id, status="SUCCESS", metadata={"messages_seen": len(items), "last_processed_uid": max_seen})
        return {"mailbox_checks": 1, "inbound_processed": processed, "replies": replies, "bounces": bounces, "unsubscribes": unsubscribes}

    def run_all(self) -> dict[str, int]:
        total = {"mailbox_checks": 0, "inbound_processed": 0, "replies": 0, "bounces": 0, "unsubscribes": 0}
        for sender in self.settings.sender_configs():
            try:
                result = self.run_sender(sender)
                for key, value in result.items(): total[key] += value
            except Exception as exc:
                self.store.add_event("mailbox_error", run_id=self.run_id, sender_id=sender.sender_id, status="FAILED", reason=exc.__class__.__name__)
                self.store.set_sender_health(sender.sender_id, datetime.now(self.settings.timezone()).date().isoformat(), "DEGRADED")
        return total
