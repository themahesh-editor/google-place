from __future__ import annotations
import re
from app.email.message_parser import ParsedInbound
from app.models import InboundEventType

HARD_RE=re.compile(r"(?:5\.1\.1|5\.1\.0|5\.2\.1|user unknown|mailbox .*not found|recipient .*does not exist|no such user|address rejected|unknown user|\b550\b|\b551\b|\b553\b)",re.I)
SOFT_RE=re.compile(r"(?:4\.2\.0|4\.3\.0|4\.4\.1|mailbox full|temporar|try again|deferred|\b421\b|\b450\b|\b451\b|\b452\b)",re.I)
OPT_OUT_RE=re.compile(r"\b(?:unsubscribe|remove me|stop emailing me|do not contact me|don['’]?t contact me|take me off|opt[ -]?out)\b",re.I)
DSN_RE=re.compile(r"(?:delivery status notification|delivery failure|mail delivery|undeliverable|returned mail|failure notice|message not delivered|mailer-daemon|postmaster)",re.I)

def classify_inbound(msg:ParsedInbound)->tuple[InboundEventType,float]:
    combined=f"{msg.subject}\n{msg.text_excerpt}"
    if OPT_OUT_RE.search(combined): return InboundEventType.UNSUBSCRIBED,0.99
    dsn=DSN_RE.search(combined) or msg.from_email.lower().split('@',1)[0] in {'mailer-daemon','postmaster'}
    if dsn and HARD_RE.search(combined): return InboundEventType.HARD_BOUNCE,0.97
    if dsn and SOFT_RE.search(combined): return InboundEventType.SOFT_BOUNCE,0.93
    return InboundEventType.REPLY,0.8
