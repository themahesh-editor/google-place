from __future__ import annotations

import email
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parseaddr, parsedate_to_datetime

@dataclass(frozen=True)
class ParsedInbound:
    message_id: str
    in_reply_to: str
    references: list[str]
    subject: str
    from_email: str
    received_at_utc: str
    text_excerpt: str


def _header(msg: Message, name: str) -> str:
    try: return str(make_header(decode_header(msg.get(name, ""))))
    except Exception: return msg.get(name, "") or ""


def _utc_date(value: str) -> str:
    try: return parsedate_to_datetime(value).astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z")
    except Exception: return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z")


def _text(msg: Message) -> str:
    parts=[]
    if msg.is_multipart():
        for part in msg.walk():
            ctype=part.get_content_type()
            disp=str(part.get("Content-Disposition", ""))
            if ctype=="text/plain" and "attachment" not in disp.lower():
                try: parts.append(part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8","replace"))
                except Exception: pass
    elif msg.get_content_type()=="text/plain":
        try: parts.append(msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8","replace"))
        except Exception: pass
    return re.sub(r"\s+"," "," ".join(parts)).strip()[:5000]


def parse_message(raw: bytes) -> ParsedInbound:
    msg=email.message_from_bytes(raw)
    mid=_header(msg,"Message-ID").strip()
    refs=re.findall(r"<[^>]+>",_header(msg,"References"))
    irt=_header(msg,"In-Reply-To").strip()
    return ParsedInbound(mid,irt,refs,_header(msg,"Subject").strip(),parseaddr(_header(msg,"From"))[1].lower(),_utc_date(_header(msg,"Date")),_text(msg))
