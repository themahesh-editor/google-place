from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol

@dataclass(frozen=True)
class MailboxItem:
    uid: int
    raw: bytes

class MailboxProvider(Protocol):
    def connect(self) -> None: ...
    def check_new_messages(self, last_processed_uid: int, lookback_minutes: int, max_messages: int) -> list[MailboxItem]: ...
    def mark_processed(self, uid: int) -> None: ...
    def close(self) -> None: ...
