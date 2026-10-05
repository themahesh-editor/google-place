from __future__ import annotations

import os
from datetime import datetime, timezone


def _enabled() -> bool:
    value = os.getenv("ATTACHAI_DEBUG", "true").strip().lower()
    return value in {"1", "true", "yes", "on"}


def debug(event: str, **fields) -> None:
    """
    Safe operational tracing.

    Do NOT pass:
    - API keys
    - passwords
    - email body
    - full prompts
    - full LLM responses
    """
    if not _enabled():
        return

    parts = [f"TRACE event={event}"]

    for key, value in fields.items():
        if value is None:
            continue

        text = str(value).replace("\n", " ").replace("\r", " ")
        text = text[:500]

        parts.append(f"{key}={text}")

    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    print(
        f"TRACE timestamp={timestamp} " + " ".join(parts[1:]),
        flush=True,
    )
