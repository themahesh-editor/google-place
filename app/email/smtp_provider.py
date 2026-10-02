from __future__ import annotations
import os
import smtplib
from email.message import EmailMessage
from email.policy import SMTP
from app.email.provider import EmailSender

def classify_send_error(exc:Exception)->str:
    text=str(exc).lower()
    if isinstance(exc,smtplib.SMTPAuthenticationError) or any(x in text for x in ("authentication","auth","535")): return "AUTH"
    if isinstance(exc,(smtplib.SMTPServerDisconnected,smtplib.SMTPConnectError,TimeoutError,ConnectionError)) or any(x in text for x in ("timeout","temporar","try again","421","450","451","452","rate limit","too many")): return "TEMPORARY"
    return "TERMINAL"

class SMTPEmailSender(EmailSender):
    def __init__(self, config): self.config=config; self.credential=os.getenv(config.credential_env,"").strip(); self.client=None
    def _open(self):
        if not self.config.email or not self.credential: raise ValueError(f"{self.config.sender_id} sender identity/credential missing")
        if self.config.smtp_ssl:
            self.client=smtplib.SMTP_SSL(self.config.smtp_host,self.config.smtp_port,timeout=30)
        else:
            self.client=smtplib.SMTP(self.config.smtp_host,self.config.smtp_port,timeout=30); self.client.ehlo(); self.client.starttls(); self.client.ehlo()
        self.client.login(self.config.email,self.credential)
    def validate_connection(self)->None:
        self._open(); self.close()
    def send(self,*,to_email,subject,body,from_email,message_id,in_reply_to=None)->str:
        self._open();
        try:
            msg=EmailMessage(policy=SMTP); msg["From"]=from_email; msg["To"]=to_email; msg["Subject"]=subject; msg["Message-ID"]=message_id
            if in_reply_to: msg["In-Reply-To"]=in_reply_to; msg["References"]=in_reply_to
            msg.set_content(body)
            self.client.send_message(msg,from_addr=from_email,to_addrs=[to_email]); return message_id
        finally:self.close()
    def classify_error(self,exc:Exception)->str:return classify_send_error(exc)
    def close(self):
        if self.client:
            try:self.client.quit()
            except Exception:pass
            self.client=None
