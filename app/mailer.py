from __future__ import annotations

import smtplib
import ssl
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import Any

from .db import deterministic_message_id, now_utc, normalize_email
from .debug import debug
from .models import SendResult


try:
    SMTP_AUTH_ERRORS = (smtplib.SMTPAuthenticationError,)
    SMTP_RECIPIENT_ERRORS = (smtplib.SMTPRecipientsRefused, smtplib.SMTPDataError)
except AttributeError:
    SMTP_AUTH_ERRORS = (Exception,)
    SMTP_RECIPIENT_ERRORS = (Exception,)


def classify_send_error(exc: Exception) -> str:
    if isinstance(exc, SMTP_AUTH_ERRORS):
        return "authentication"
    if isinstance(exc, SMTP_RECIPIENT_ERRORS):
        return "terminal recipient/address"
    if isinstance(exc, (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError, TimeoutError, ConnectionError, OSError)):
        return "temporary/provider/network"
    if isinstance(exc, smtplib.SMTPException):
        code = getattr(exc, "smtp_code", None)
        if isinstance(code, int) and 400 <= code < 500:
            return "temporary/provider/network"
        if isinstance(code, int) and 500 <= code < 600:
            return "terminal unknown"
    return "terminal unknown"


def build_message(row: Any) -> EmailMessage:
    message = EmailMessage()
    message["From"] = row["sender_email"]
    message["To"] = normalize_email(row["email"])
    message["Subject"] = row["subject"]
    message["Date"] = formatdate(usegmt=True)
    message["Message-ID"] = row["smtp_message_id"] or deterministic_message_id(row["outreach_id"], row["sender_email"])
    if row["in_reply_to"]:
        message["In-Reply-To"] = row["in_reply_to"]
    if row["references_text"]:
        message["References"] = row["references_text"]
    message.set_content(row["body"])
    return message


class SMTPMailer:
    def __init__(self, sender: Any, credential: str, timeout_seconds: int = 30):
        self.sender = sender
        self.credential = credential
        self.timeout_seconds = timeout_seconds

    def send(self, row: Any) -> SendResult:
        message = build_message(row)
        try:
            if self.sender.smtp_ssl:
                context = ssl.create_default_context()
                with smtplib.SMTP_SSL(self.sender.smtp_host, self.sender.smtp_port, timeout=self.timeout_seconds, context=context) as client:
                    client.login(self.sender.email, self.credential)
                    refused = client.send_message(message)
            else:
                context = ssl.create_default_context()
                with smtplib.SMTP(self.sender.smtp_host, self.sender.smtp_port, timeout=self.timeout_seconds) as client:
                    client.ehlo()
                    client.starttls(context=context)
                    client.ehlo()
                    client.login(self.sender.email, self.credential)
                    refused = client.send_message(message)
            if refused:
                return SendResult(str(row["outreach_id"]), "FAILED", "terminal recipient/address", str(refused))
            return SendResult(str(row["outreach_id"]), "SENT", provider_message_id=str(message["Message-ID"]))
        except Exception as exc:
            return SendResult(str(row["outreach_id"]), "FAILED", classify_send_error(exc), str(exc)[:1000])


class BatchSendController:
    def __init__(self, store, settings):
        self.store = store
        self.settings = settings

    def _send_one(self, row: Any, sender_by_id: dict[str, Any], credentials: dict[str, str]) -> SendResult:
        sender_id = str(row["sender_id"])
        if sender_id not in sender_by_id:
            return SendResult(str(row["outreach_id"]), "FAILED", "sender stopped/degraded/cooldown", "sender assignment unavailable")
        mailer = SMTPMailer(sender_by_id[sender_id], credentials[sender_by_id[sender_id].credential_env])
        return mailer.send(row)

    def send_batch(self, batch_id: str, rows: list[Any], sender_by_id: dict[str, Any], credentials: dict[str, str], *, dry_run: bool) -> list[SendResult]:
        if dry_run:
            return [SendResult(str(row["outreach_id"]), "DRY_RUN") for row in rows]
        claimed: list[Any] = []
        for row in rows:
            if self.store.claim_for_send(str(row["outreach_id"])):
                claimed.append(self.store.get_outreach(str(row["outreach_id"])))
        results: list[SendResult] = []
        workers = min(10, max(1, self.settings.max_concurrency), len(claimed) or 1)
        debug("BATCH_START", batch_id=batch_id, planned=len(rows), claimed=len(claimed), concurrency=workers)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(self._send_one, row, sender_by_id, credentials): row for row in claimed}
            for future in as_completed(futures):
                results.append(future.result())
        return results
