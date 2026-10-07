from __future__ import annotations

import email
import email.utils
import imaplib
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from .db import normalize_email, now_utc
from .debug import debug
from .models import InboundEventType


@dataclass(frozen=True)
class ParsedInbound:
    message_id: str
    in_reply_to: str
    references_text: str
    from_email: str
    subject: str
    received_at: datetime
    auto_submitted: str
    precedence: str
    list_unsubscribe: str
    list_id: str
    body_for_classification: str


class IMAPProvider:
    def __init__(self, sender, credential: str, timeout_seconds: int = 30):
        self.sender = sender
        self.credential = credential
        self.timeout_seconds = timeout_seconds
        self.client = None
        self.uidvalidity: str | None = None

    def connect(self) -> None:
        if self.sender.imap_ssl:
            self.client = imaplib.IMAP4_SSL(self.sender.imap_host, self.sender.imap_port)
        else:
            self.client = imaplib.IMAP4(self.sender.imap_host, self.sender.imap_port)
            self.client.starttls()
        self.client.login(self.sender.email, self.credential)
        status, data = self.client.select("INBOX", readonly=True)
        if status != "OK":
            raise RuntimeError("IMAP INBOX selection failed")
        self.uidvalidity = self._uidvalidity()

    def _uidvalidity(self) -> str:
        try:
            typ, data = self.client.response("UIDVALIDITY")
            return str((data or [b""])[0].decode(errors="ignore"))
        except Exception:
            return ""

    def fetch_since(self, last_uid: int, max_messages: int) -> list[tuple[int, bytes]]:
        if not self.client:
            raise RuntimeError("not connected")
        start = max(1, last_uid + 1)
        typ, data = self.client.uid("SEARCH", None, f"UID {start}:*")
        if typ != "OK":
            return []
        ids = [int(x) for x in (data[0].split() if data and data[0] else [])]
        ids = ids[-max_messages:]
        result: list[tuple[int, bytes]] = []
        for uid in ids:
            typ, data = self.client.uid("FETCH", str(uid), "(RFC822)")
            if typ != "OK":
                continue
            for item in data or []:
                if isinstance(item, tuple) and len(item) == 2 and isinstance(item[1], (bytes, bytearray)):
                    result.append((uid, bytes(item[1])))
                    break
        return result

    def close(self) -> None:
        try:
            if self.client:
                self.client.close()
                self.client.logout()
        except Exception:
            pass
        finally:
            self.client = None


def _header(msg: email.message.Message, name: str) -> str:
    return str(msg.get(name, "") or "").strip()


def _body_text(msg: email.message.Message) -> str:
    if msg.is_multipart():
        chunks: list[str] = []
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and part.get_content_disposition() != "attachment":
                try:
                    chunks.append(part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", errors="replace"))
                except Exception:
                    continue
        return "\n".join(chunks)[:8000]
    try:
        payload = msg.get_payload(decode=True)
        return (payload or b"").decode(msg.get_content_charset() or "utf-8", errors="replace")[:8000]
    except Exception:
        return ""


def parse_message(raw: bytes) -> ParsedInbound:
    msg = email.message_from_bytes(raw)
    message_id = _header(msg, "Message-ID")
    received_header = _header(msg, "Date")
    try:
        received = email.utils.parsedate_to_datetime(received_header).astimezone(timezone.utc).replace(microsecond=0) if received_header else now_utc()
    except Exception:
        received = now_utc()
    from_value = _header(msg, "From")
    parsed_from = normalize_email(email.utils.parseaddr(from_value)[1] or from_value)
    return ParsedInbound(
        message_id=message_id or f"<unknown-{uuid.uuid4()}>",
        in_reply_to=_header(msg, "In-Reply-To"),
        references_text=_header(msg, "References"),
        from_email=parsed_from,
        subject=_header(msg, "Subject"),
        received_at=received,
        auto_submitted=_header(msg, "Auto-Submitted").lower(),
        precedence=_header(msg, "Precedence").lower(),
        list_unsubscribe=_header(msg, "List-Unsubscribe"),
        list_id=_header(msg, "List-Id"),
        body_for_classification=_body_text(msg),
    )


def classify(parsed: ParsedInbound) -> tuple[InboundEventType, float]:
    sender = parsed.from_email.lower()
    subject = parsed.subject.lower()
    body = parsed.body_for_classification.lower()
    if parsed.list_unsubscribe:
        return InboundEventType.UNSUBSCRIBED, 0.98
    if any(token in subject for token in ("unsubscribe", "remove me", "opt out", "opt-out")) or any(token in body[:2000] for token in ("unsubscribe", "remove me", "opt out", "opt-out")):
        return InboundEventType.UNSUBSCRIBED, 0.96
    if "mailer-daemon" in sender or "postmaster" in sender or any(token in subject for token in ("delivery status notification", "undeliverable", "delivery failure", "mail delivery failed", "returned mail")):
        if any(token in subject + " " + body for token in ("permanent", "5.1.1", "user unknown", "does not exist", "mailbox unavailable")):
            return InboundEventType.HARD_BOUNCE, 0.97
        return InboundEventType.SOFT_BOUNCE, 0.90
    if parsed.auto_submitted in {"auto-replied", "auto-generated"} or parsed.precedence in {"bulk", "junk", "list"}:
        return InboundEventType.UNCLASSIFIED, 0.65
    return InboundEventType.REPLY, 0.88


class MailboxMonitor:
    def __init__(self, store, settings, provider_factory=IMAPProvider):
        self.store = store
        self.settings = settings
        self.provider_factory = provider_factory

    def _correlate(self, parsed: ParsedInbound) -> tuple[Any | None, Any | None]:
        msg = self.store.fetchone("SELECT * FROM outreach WHERE smtp_message_id=? OR smtp_message_id=? LIMIT 1", [parsed.in_reply_to, parsed.message_id])
        if msg:
            lead = self.store.get_lead(msg["lead_id"])
            return lead, msg
        refs = [x for x in re.split(r"\s+", parsed.references_text or "") if x]
        for ref in reversed(refs):
            msg = self.store.fetchone("SELECT * FROM outreach WHERE smtp_message_id=? LIMIT 1", [ref])
            if msg:
                return self.store.get_lead(msg["lead_id"]), msg
        lead = self.store.get_lead_by_email(parsed.from_email)
        return lead, self.store.previous_successful(lead["lead_id"]) if lead else None

    def run_sender(self, sender) -> dict[str, int]:
        credential = __import__("os").getenv(sender.credential_env, "")
        provider = self.provider_factory(sender, credential)
        counts = {"replies": 0, "bounces": 0, "unsubscribes": 0, "unclassified": 0, "duplicates": 0, "failed": 0}
        try:
            provider.connect()
            last_uid, reset_cursor = self.store.reconcile_inbound_cursor(sender.sender_id, provider.uidvalidity)
            if reset_cursor:
                last_uid = 0
            messages = provider.fetch_since(last_uid, self.settings.mailbox_max_messages_per_run)
            highest_uid = last_uid
            for uid, raw in messages:
                highest_uid = max(highest_uid, uid)
                parsed = parse_message(raw)
                if self.store.inbound_exists(sender.sender_id, parsed.message_id):
                    counts["duplicates"] += 1
                    continue
                event_type, confidence = classify(parsed)
                lead, outreach = self._correlate(parsed)
                inserted = self.store.save_inbound(
                    inbound_id=str(uuid.uuid4()), sender_id=sender.sender_id, message_id=parsed.message_id,
                    in_reply_to=parsed.in_reply_to, references_text=parsed.references_text,
                    received_at=parsed.received_at, from_email=parsed.from_email, subject=parsed.subject,
                    event_type=event_type.value, confidence=confidence,
                    lead_id=lead["lead_id"] if lead else None,
                    outreach_id=outreach["outreach_id"] if outreach else None,
                )
                if not inserted:
                    counts["duplicates"] += 1
                    continue
                if event_type == InboundEventType.REPLY:
                    counts["replies"] += 1
                    if lead:
                        self.store.suppress(lead["email"], lead["lead_id"], "reply")
                elif event_type == InboundEventType.HARD_BOUNCE:
                    counts["bounces"] += 1
                    if lead:
                        self.store.suppress(lead["email"], lead["lead_id"], "hard_bounce")
                elif event_type == InboundEventType.UNSUBSCRIBED:
                    counts["unsubscribes"] += 1
                    if lead:
                        self.store.suppress(lead["email"], lead["lead_id"], "unsubscribe")
                else:
                    counts["unclassified"] += 1
            self.store.save_mailbox_state(sender.sender_id, provider.uidvalidity, highest_uid, "HEALTHY")
            day = now_utc().date().isoformat()
            self.store.set_sender_health(sender.sender_id, day, "HEALTHY")
            return counts
        except Exception as exc:
            counts["failed"] += 1
            day = now_utc().date().isoformat()
            self.store.set_sender_health(sender.sender_id, day, "DEGRADED")
            self.store.save_mailbox_state(sender.sender_id, getattr(provider, "uidvalidity", None), 0, "DEGRADED")
            debug("MAILBOX_FAILED", sender_id=sender.sender_id, error=str(exc)[:500])
            return counts
        finally:
            provider.close()

    def run_all(self, senders: list[Any]) -> dict[str, int]:
        totals = {"replies": 0, "bounces": 0, "unsubscribes": 0, "unclassified": 0, "duplicates": 0, "failed": 0}
        for sender in senders:
            result = self.run_sender(sender)
            for key, value in result.items():
                totals[key] += value
        return totals
