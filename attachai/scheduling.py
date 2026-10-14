"""Pure scheduling helpers; durable slot claims belong to CLI/database."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from croniter import croniter

POLL_TOLERANCE = timedelta(minutes=20)


def due_slots(data: dict, now: datetime) -> dict[str, str]:
    """Latest due UTC slot per enabled feature within the polling tolerance.

    Repeated calls may return the same slot. The coordinator must claim each
    (feature, slot) uniquely in PostgreSQL, under the process advisory lock.
    Missed slots older than 20 minutes are deliberately not backfilled.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if not data["automation"]["enabled"] or data["safety"]["emergency_stop"]:
        return {}
    now_utc = now.astimezone(timezone.utc)
    local_zone = ZoneInfo(data["automation"]["timezone"])
    result = {}
    for feature in ("outreach", "followups"):
        if not data[feature]["enabled"]:
            continue
        # Scan actual UTC minutes, not local-wall-clock arithmetic. This avoids
        # inventing a nonexistent spring-forward tick and preserves distinct
        # UTC slots for repeated fall-back minutes. Only the latest match wins.
        candidate = now_utc.replace(second=0, microsecond=0)
        for minutes in range(21):
            due = candidate - timedelta(minutes=minutes)
            if now_utc - due > POLL_TOLERANCE:
                break
            # croniter matching itself must see wall fields only; aware-datetime
            # internal arithmetic can incorrectly discard fold=1 minutes.
            wall = due.astimezone(local_zone).replace(tzinfo=None)
            if croniter.match(data["automation"][f"{feature}_cron"], wall):
                result[feature] = due.isoformat(timespec="seconds")
                break
    return result
