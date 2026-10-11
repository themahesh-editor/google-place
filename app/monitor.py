from __future__ import annotations

from datetime import datetime, timedelta, timezone


def _field_matches(value: int, field: str, minimum: int, maximum: int) -> bool:
    field = field.strip()
    if field == "*":
        return True
    for part in field.split(","):
        part = part.strip()
        if not part:
            continue
        if "/" in part:
            base, step_raw = part.split("/", 1)
            step = int(step_raw)
            if step <= 0:
                return False
            if base == "*":
                start, end = minimum, maximum
            elif "-" in base:
                start, end = map(int, base.split("-", 1))
            else:
                start, end = int(base), maximum
            if start <= value <= end and (value - start) % step == 0:
                return True
            continue
        if "-" in part:
            start, end = map(int, part.split("-", 1))
            if start <= value <= end:
                return True
            continue
        if int(part) == value:
            return True
    return False


def cron_matches(expression: str, value: datetime) -> bool:
    parts = expression.split()
    if len(parts) != 5:
        raise ValueError(f"Cron expression must have 5 fields: {expression}")
    minute, hour, day, month, weekday = parts
    # Cron weekdays: 0/7 Sunday, 1 Monday ... 6 Saturday.
    cron_weekday = (value.weekday() + 1) % 7
    day_match = _field_matches(value.day, day, 1, 31)
    weekday_match = _field_matches(cron_weekday, weekday, 0, 7) or (cron_weekday == 0 and _field_matches(7, weekday, 0, 7))
    # Standard cron semantics: when both DOM and DOW are restricted, either may match.
    dom_restricted = day != "*"
    dow_restricted = weekday != "*"
    calendar_match = (day_match or weekday_match) if (dom_restricted and dow_restricted) else (day_match and weekday_match)
    return _field_matches(value.minute, minute, 0, 59) and _field_matches(value.hour, hour, 0, 23) and _field_matches(value.month, month, 1, 12) and calendar_match


def scheduled_ticks_since(expression: str, start: datetime | None, now: datetime) -> list[datetime]:
    now = now.astimezone(timezone.utc).replace(second=0, microsecond=0)
    cursor = (start or (now - timedelta(minutes=1))).astimezone(timezone.utc).replace(second=0, microsecond=0)
    ticks: list[datetime] = []
    # 366 days/5-minute worst-case is enough for this polling use, and avoids hidden third-party scheduling semantics.
    for _ in range(105408):
        cursor += timedelta(minutes=1)
        if cursor > now:
            break
        if cron_matches(expression, cursor):
            ticks.append(cursor)
    if len(ticks) > 10:
        return ticks[-10:]
    return ticks


def pipeline_schedule_is_due(expression: str, last_trigger: datetime | None, now: datetime) -> bool:
    if last_trigger is None:
        previous = now.astimezone(timezone.utc).replace(second=0, microsecond=0) - timedelta(minutes=1)
        for _ in range(31):
            if cron_matches(expression, previous):
                return True
            previous -= timedelta(minutes=1)
        return False
    return bool(scheduled_ticks_since(expression, last_trigger, now))


def automatic_run_flags(settings, store, now: datetime | None = None) -> tuple[bool, bool, bool]:
    now = now or datetime.now(timezone.utc)
    if not settings.automation_enabled or settings.emergency_stop:
        return False, False, False
    outreach_due = settings.outreach_enabled and pipeline_schedule_is_due(settings.outreach_schedule, store.automation_last_trigger("outreach"), now)
    followup_due = settings.followups_enabled and pipeline_schedule_is_due(settings.followups_schedule, store.automation_last_trigger("followups"), now)
    return outreach_due or followup_due, followup_due, outreach_due
