from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone


def _enabled() -> bool:
    return os.getenv("ATTACHAI_DEBUG", "true").strip().lower() in {"1", "true", "yes", "on"}


def log(event: str, **fields) -> None:
    payload = {
        "ts_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "event": event,
        **fields,
    }
    print(json.dumps(payload, ensure_ascii=False, default=str), flush=True)


def debug(event: str, **fields) -> None:
    if _enabled():
        log(event, **fields)


def elapsed(start: float) -> float:
    return round(time.monotonic() - start, 3)
