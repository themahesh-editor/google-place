import copy
from datetime import datetime

import pytest

from attachai.config import DEFAULTS
from attachai.scheduling import due_slots


def controls():
    data = copy.deepcopy(DEFAULTS)
    data["automation"]["enabled"] = True
    return data


def now(text):
    return datetime.fromisoformat(text)


def test_defaults_disabled_and_emergency_stop():
    assert due_slots(DEFAULTS, now("2026-10-12T09:00:00+00:00")) == {}
    data = controls()
    data["safety"]["emergency_stop"] = True
    assert due_slots(data, now("2026-10-12T09:00:00+00:00")) == {}


def test_exact_tick_included_and_repeated_poll_stable():
    data = controls()
    slot = {"outreach": "2026-10-12T09:00:00+00:00"}
    assert due_slots(data, now("2026-10-12T09:00:00+00:00")) == slot
    assert due_slots(data, now("2026-10-12T09:15:00+00:00")) == slot


def test_boundary_tolerance_and_no_backfill():
    data = controls()
    assert "outreach" in due_slots(data, now("2026-10-12T09:20:00+00:00"))
    assert due_slots(data, now("2026-10-12T09:20:00.000001+00:00")) == {}
    assert due_slots(data, now("2026-10-12T08:59:59+00:00")) == {}


def test_both_features_can_be_due_but_disabled_wins():
    data = controls()
    data["automation"]["outreach_cron"] = "0 */4 * * *"
    slots = due_slots(data, now("2026-10-12T12:15:00+00:00"))
    assert slots == {"outreach": "2026-10-12T12:00:00+00:00", "followups": "2026-10-12T12:00:00+00:00"}
    data["outreach"]["enabled"] = False
    assert due_slots(data, now("2026-10-12T12:15:00+00:00")) == {"followups": "2026-10-12T12:00:00+00:00"}


def test_latest_only_for_frequent_cron():
    data = controls()
    data["automation"]["outreach_cron"] = "*/5 * * * *"
    assert due_slots(data, now("2026-10-12T09:19:00+00:00")) == {"outreach": "2026-10-12T09:15:00+00:00"}


def test_weekends_are_not_backfilled():
    assert due_slots(controls(), now("2026-10-11T09:00:00+00:00")) == {}


@pytest.mark.parametrize("date,slot", [("2026-07-13T13:15:00+00:00", "2026-07-13T13:00:00+00:00"), ("2026-12-14T14:15:00+00:00", "2026-12-14T14:00:00+00:00")])
def test_iana_timezone_summer_winter(date, slot):
    data = controls()
    data["automation"]["timezone"] = "America/New_York"
    assert due_slots(data, now(date)) == {"outreach": slot}


def test_non_utc_now_returns_canonical_utc():
    data = controls()
    data["automation"]["timezone"] = "Asia/Kolkata"
    assert due_slots(data, now("2026-10-12T09:15:00+05:30")) == {"outreach": "2026-10-12T03:30:00+00:00"}


def test_naive_datetime_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        due_slots(controls(), datetime(2026, 10, 12, 9))


def test_nonexistent_dst_spring_minute_is_not_invented():
    data = controls()
    data["automation"].update(timezone="America/New_York", outreach_cron="30 2 * * *")
    assert due_slots(data, now("2026-03-08T07:35:00+00:00")) == {}


def test_dst_fall_back_has_two_distinct_utc_slots():
    data = controls()
    data["automation"].update(timezone="America/New_York", outreach_cron="30 1 * * *")
    assert due_slots(data, now("2026-11-01T05:45:00+00:00")) == {"outreach": "2026-11-01T05:30:00+00:00"}
    assert due_slots(data, now("2026-11-01T06:45:00+00:00")) == {"outreach": "2026-11-01T06:30:00+00:00"}
