from __future__ import annotations

import hashlib
import os
import smtplib
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from email.message import EmailMessage
from email.policy import SMTP

from app.models import SendResult


def message_id_for(outreach_id: str, sender_email: str) -> str:
    token = hashlib.sha256(f"{outreach_id}|{sender_email}".encode()).hexdigest()[:24]
    domain = sender_email.split("@", 1)[1]
    return f"<attachai-{token}@{domain}>"


def classify_send_error(exc: Exception) -> str:
    text = str(exc).lower()
    if isinstance(exc, smtplib.SMTPRecipientsRefused) or any(x in text for x in ("550", "551", "553", "5.1.1", "user unknown", "mailbox not found", "recipient does not exist")):
        return "TERMINAL_RECIPIENT"
    if isinstance(exc, smtplib.SMTPAuthenticationError) or "authentication" in text or "535" in text:
        return "AUTH"
    if isinstance(exc, (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError, TimeoutError, ConnectionError)) or any(x in text for x in ("timeout", "temporar", "try again", "421", "450", "451", "452", "rate limit", "too many")):
        return "TEMPORARY"
    return "TERMINAL"


class SMTPMailer:
    def __init__(self, sender):
        self.sender = sender
        self.credential = os.getenv(sender.credential_env, "").strip()

    def validate(self) -> None:
        self._open().quit()

    def _open(self):
        if not self.credential:
            raise ValueError(f"Missing credential for {self.sender.sender_id}")
        if self.sender.smtp_ssl:
            client = smtplib.SMTP_SSL(self.sender.smtp_host, self.sender.smtp_port, timeout=30)
        else:
            client = smtplib.SMTP(self.sender.smtp_host, self.sender.smtp_port, timeout=30)
            client.ehlo(); client.starttls(); client.ehlo()
        client.login(self.sender.email, self.credential)
        return client

    def send(self, row) -> str:
        message_id = row["message_id"]
        client = self._open()
        try:
            message = EmailMessage(policy=SMTP)
            message["From"] = row["sender_email"]
            message["To"] = row["email"]
            message["Subject"] = row["subject"]
            message["Message-ID"] = message_id
            if row.get("in_reply_to"):
                message["In-Reply-To"] = row["in_reply_to"]
                message["References"] = row.get("references_text") or row["in_reply_to"]
            message.set_content(row["body"])
            client.send_message(message, from_addr=row["sender_email"], to_addrs=[row["email"]])
            return message_id
        finally:
            try:
                client.quit()
            except Exception:
                pass


class BatchSendController:
    """Claims rows before sending; SMTP calls run concurrently; DB state is reconciled by the coordinator thread."""

    def __init__(self, store, settings, smtp_factory=SMTPMailer):
        self.store = store
        self.settings = settings
        self.smtp_factory = smtp_factory

    def send_batch(self, batch_id: str, rows: list, sender_by_id: dict, allow_real_send: bool) -> list[SendResult]:
        run_id = batch_id.split(":", 1)[0]
        if not allow_real_send:
            return [SendResult(row["outreach_id"], row["sender_id"], "DRY_RUN", message_id_for(row["outreach_id"], row["sender_email"] or sender_by_id[row["sender_id"]].email)) for row in rows]

        claimed = []
        for row in rows:
            if not self.store.claim_outreach(row["outreach_id"]):
                continue
            message_id = message_id_for(row["outreach_id"], row["sender_email"])
            row_data = dict(row)
            row_data["message_id"] = message_id
            claimed.append(row_data)
            self.store.add_event("send_attempted", run_id=run_id, lead_id=row_data["lead_id"], outreach_id=row_data["outreach_id"], sender_id=row_data["sender_id"], batch_id=batch_id, sequence_type=row_data["sequence_type"], status="SENDING")
        if not claimed:
            return []
        results: list[SendResult] = []
        max_workers = min(self.settings.max_concurrent_sends, len(claimed))
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="attachai-sender") as executor:
            futures: dict[Future, dict] = {}
            for row in claimed:
                futures[executor.submit(self.smtp_factory(sender_by_id[row["sender_id"]]).send, row)] = row
            for future in as_completed(futures):
                row = futures[future]
                try:
                    mid = future.result()
                except Exception as exc:
                    kind = classify_send_error(exc)
                    current = self.store.get_outreach(row["outreach_id"])
                    retry_count = int(current["retry_count"] or 0) if current else 0
                    if kind == "TEMPORARY" and retry_count < self.settings.retry_limit:
                        next_retry = (datetime.now(timezone.utc) + timedelta(seconds=self.settings.retry_base_seconds * (2 ** min(retry_count, 6)))).replace(microsecond=0).isoformat().replace("+00:00", "Z")
                        self.store.mark_failed(row["outreach_id"], "FAILED_RETRYABLE", str(exc), next_retry)
                        cooldown_date_key = datetime.now(timezone.utc).astimezone(self.settings.timezone()).date().isoformat()
                        self.store.set_sender_health(row["sender_id"], cooldown_date_key, "COOLDOWN", next_retry)
                        self.store.add_event("send_failed", run_id=run_id, lead_id=row["lead_id"], outreach_id=row["outreach_id"], sender_id=row["sender_id"], batch_id=batch_id, sequence_type=row["sequence_type"], status="FAILED_RETRYABLE", reason=kind)
                        results.append(SendResult(row["outreach_id"], row["sender_id"], "FAILED_RETRYABLE", row["message_id"], kind, str(exc)))
                    else:
                        self.store.mark_failed(row["outreach_id"], "FAILED_TERMINAL", str(exc), None)
                        failure_date_key = datetime.now(timezone.utc).astimezone(self.settings.timezone()).date().isoformat()
                        self.store.record_failure(row["sender_id"], failure_date_key, kind)
                        if kind == "AUTH":
                            self.store.set_sender_health(row["sender_id"], failure_date_key, "STOPPED", None)
                        if kind == "TERMINAL_RECIPIENT":
                            self.store.suppress(row["email"], row["lead_id"], "hard_bounce")
                            self.store.update_lead_status(row["lead_id"], "BOUNCED")
                            self.store.cancel_future_followups(row["lead_id"])
                        self.store.add_event("send_failed", run_id=run_id, lead_id=row["lead_id"], outreach_id=row["outreach_id"], sender_id=row["sender_id"], batch_id=batch_id, sequence_type=row["sequence_type"], status="FAILED_TERMINAL", reason=kind)
                        results.append(SendResult(row["outreach_id"], row["sender_id"], "FAILED_TERMINAL", row["message_id"], kind, str(exc)))
                    continue

                sent_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
                try:
                    self.store.mark_sent(row["outreach_id"], sent_at, mid)
                    sent_date_key = datetime.fromisoformat(sent_at.replace("Z", "+00:00")).astimezone(self.settings.timezone()).date().isoformat()
                    self.store.record_send(row["sender_id"], sent_date_key, row["sequence_type"] != "INITIAL", sent_at)
                    next_status = "COMPLETED" if row["sequence_type"] == "FOLLOWUP_3" else "ACTIVE"
                    self.store.update_lead_status(row["lead_id"], next_status)
                    self.store.add_event("message_sent", run_id=run_id, lead_id=row["lead_id"], outreach_id=row["outreach_id"], sender_id=row["sender_id"], batch_id=batch_id, sequence_type=row["sequence_type"], status="SENT", metadata={"sent_at_utc": sent_at, "message_id": mid})
                    results.append(SendResult(row["outreach_id"], row["sender_id"], "SENT", mid))
                except Exception as exc:
                    # SMTP has already accepted the message. Never retry automatically if durable state cannot be confirmed.
                    try:
                        self.store.mark_review_needed(row["outreach_id"], "smtp_accepted_but_state_persistence_failed")
                    except Exception:
                        pass
                    self.store.add_event("send_persistence_ambiguous", run_id=run_id, lead_id=row["lead_id"], outreach_id=row["outreach_id"], sender_id=row["sender_id"], batch_id=batch_id, sequence_type=row["sequence_type"], status="REVIEW_NEEDED", reason=exc.__class__.__name__)
                    results.append(SendResult(row["outreach_id"], row["sender_id"], "REVIEW_NEEDED", mid, "PERSISTENCE_AMBIGUOUS", str(exc)))
                    continue

        return results

