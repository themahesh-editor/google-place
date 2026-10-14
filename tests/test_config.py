import json
from pathlib import Path

import pytest
import yaml

from attachai.config import DEFAULTS, load_config, load_secrets, parse_bool


@pytest.fixture
def monitor(tmp_path):
    path = tmp_path / "monitor.yaml"
    path.write_text(yaml.safe_dump(DEFAULTS), encoding="utf-8")
    return path


def edit(path, section, key, value):
    data = yaml.safe_load(path.read_text())
    data[section][key] = value
    path.write_text(yaml.safe_dump(data), encoding="utf-8")


@pytest.fixture(autouse=True)
def isolated_secrets(monkeypatch):
    for name in ("DATABASE_URL", "GOOGLE_PLACES_API_KEY", "LLM_API_KEY", "SENDER_ACCOUNTS_JSON"):
        monkeypatch.delenv(name, raising=False)


def credentials(monkeypatch, count=10):
    accounts = [dict(id=f"sender{i}", email=f"sender{i}@example.com", password="private-test-password", smtp_host="smtp.example.com", smtp_port=465, imap_host="imap.example.com", imap_port=993, tls_mode="ssl") for i in range(count)]
    monkeypatch.setenv("DATABASE_URL", "postgresql://tester:secret@localhost:5432/test")
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "private-places-key")
    monkeypatch.setenv("LLM_API_KEY", "private-llm-key")
    monkeypatch.setenv("SENDER_ACCOUNTS_JSON", json.dumps(accounts))
    return accounts


def test_repository_defaults_are_safe():
    config = load_config(Path(__file__).resolve().parents[1] / "monitor.yaml")

    assert not config.data["automation"]["enabled"]
    assert config.data["safety"]["send_enabled"] is False
    assert config.data["safety"]["dry_run"] is True

    assert not config.send_enabled
    assert config.dry_run
    assert config.process_followups
    assert config.process_new_outreach
    assert config.target == 100

    # Operator-configured discovery queries are allowed.
    assert config.data["discovery"]["queries"]
    assert all(
        isinstance(query, str) and query.strip()
        for query in config.data["discovery"]["queries"]
    )

    limits = config.data["limits"]
    assert not any(
        limits[key]
        for key in (
            "send_window_enabled",
            "daily_sender_enabled",
            "daily_total_enabled",
        )
    )
    assert limits["batch_gap_seconds"] == 0

    # No postal address should be committed into the public config.
    assert config.data["llm"]["postal_address"] == ""

@pytest.mark.parametrize("value,expected", [(True, True), (False, False), ("true", True), ("false", False), (" FALSE ", False)])
def test_booleans(value, expected):
    assert parse_bool(value) is expected


@pytest.mark.parametrize("value", [None, 0, 1, [], {}, "yes", "off", "", "flase", "false; echo attack"])
def test_invalid_booleans_fail(value):
    with pytest.raises(ValueError, match="true or false"):
        parse_bool(value)


def test_dispatch_and_emergency_precedence(monitor):
    edit(monitor, "llm", "postal_address", "123 Genuine Street, Austin, TX 78701")
    overrides = {"send_enabled": "true", "dry_run": "false", "target_new_initials": "27"}
    config = load_config(monitor, overrides)
    assert config.send_enabled and not config.dry_run and config.target == 27
    assert overrides["send_enabled"] == "true"  # caller data is not mutated
    edit(monitor, "safety", "emergency_stop", True)
    stopped = load_config(monitor, overrides)
    assert not stopped.send_enabled and stopped.dry_run
    assert not stopped.process_new_outreach and not stopped.process_followups


def test_monitor_feature_disables_win(monitor):
    edit(monitor, "outreach", "enabled", False)
    edit(monitor, "followups", "enabled", False)
    config = load_config(monitor, {"process_followups": True, "process_new_outreach": True})
    assert not config.process_followups and not config.process_new_outreach


def test_real_send_requires_postal_address(monitor):
    with pytest.raises(ValueError, match="postal_address"):
        load_config(monitor, {"send_enabled": True, "dry_run": False})
    assert load_config(monitor, {"send_enabled": True, "dry_run": True}).dry_run


@pytest.mark.parametrize("section,key,value", [
    ("outreach", "batch_size", 11), ("outreach", "max_concurrency", 0),
    ("outreach", "target_new_initials", True), ("outreach", "target_new_initials", 1.2),
    ("limits", "max_runtime_seconds", 18001), ("limits", "window_start", "24:00"),
    ("limits", "timezone", "not/a/timezone"), ("limits", "daily_total", 0),
    ("automation", "outreach_cron", "* * * * * *"), ("automation", "followups_cron", "61 * * * *"),
    ("retry", "max_attempts", 0), ("retry", "base_seconds", -1),
    ("retry", "base_seconds", 61), ("discovery", "buffer_ratio", float("nan")),
    ("discovery", "min_rating", 6), ("discovery", "queries", []),
    ("discovery", "queries", [1]), ("research", "max_bytes", 0),
    ("research", "robots_enabled", "definitely"), ("followups", "delays_seconds", [1, 2]),
    ("followups", "delays_seconds", [1, -1, 2]), ("llm", "base_url", "http://example.com"),
    ("llm", "base_url", "https://secret@example.com"), ("llm", "base_url", "https://example.com?key=secret"),
])
def test_invalid_controls_fail(monitor, section, key, value):
    edit(monitor, section, key, value)
    with pytest.raises(ValueError):
        load_config(monitor)


@pytest.mark.parametrize("override", [{"target_new_initials": "1; touch /tmp/injection"}, {"target_new_initials": 0}, {"target_new_initials": True}, {"target_new_initials": "1e2"}, {"emergency_stop": False}, {"reset_state": "YES"}, {"send_enabled": "not-a-bool"}])
def test_invalid_overrides(monitor, override):
    with pytest.raises(ValueError):
        load_config(monitor, override)


@pytest.mark.parametrize("text", ["[]", "safety: 1", "unknown: {}", "safety: {secret: hidden}", "safety: {dry_run: true, dry_run: false}", "safety: [oops]", "[unclosed", "!!python/object:os.system {}"])
def test_bad_yaml_is_safe(monitor, text):
    monitor.write_text(text)
    with pytest.raises(ValueError):
        load_config(monitor)


def test_partial_control_file_and_testing_delays(monitor):
    monitor.write_text("followups:\n  delays_seconds: [0, 0, 0]\n")
    config = load_config(monitor)
    assert config.target == 100
    assert config.data["followups"]["delays_seconds"] == [0, 0, 0]
    assert DEFAULTS["followups"]["delays_seconds"] == [86400, 604800, 1209600]


def test_no_secrets_needed_for_loading_or_disabled_schedule(monitor):
    load_config(monitor)
    from attachai.scheduling import due_slots
    from datetime import datetime, timezone
    assert due_slots(load_config(monitor).data, datetime.now(timezone.utc)) == {}


def test_minimal_db_secrets_for_non_provider_command(monitor, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://tester:password@localhost/test")
    config = load_config(monitor, {"process_followups": False, "process_new_outreach": False})
    secrets = load_secrets(config)
    assert secrets.places_key == secrets.llm_key == ""
    assert secrets.senders == []
    assert "password" not in repr(secrets)


@pytest.mark.parametrize("url", ["sqlite:///test", "postgresql://localhost", "postgresql://localhost:bad/db", "not-a-url"])
def test_bad_database_urls_do_not_leak(monitor, monkeypatch, url):
    monkeypatch.setenv("DATABASE_URL", url)
    with pytest.raises(ValueError, match="PostgreSQL connection URL") as error:
        load_secrets(load_config(monitor))
    assert url not in str(error.value)


def test_remote_database_requires_tls_without_echoing_url(monitor, monkeypatch):
    url = "postgresql://db-user:very-private-password@db.example.com:5432/postgres"
    monkeypatch.setenv("DATABASE_URL", url)
    with pytest.raises(ValueError, match="sslmode=require") as error:
        load_secrets(load_config(monitor))
    assert "very-private-password" not in str(error.value)
    monkeypatch.setenv("DATABASE_URL", url + "?sslmode=require")
    credentials(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", url + "?sslmode=require")
    assert load_secrets(load_config(monitor)).database_url.endswith("sslmode=require")


def test_provider_credentials_required_for_drafts(monitor, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
    with pytest.raises(ValueError, match="GOOGLE_PLACES_API_KEY"):
        load_secrets(load_config(monitor))
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "secret")
    with pytest.raises(ValueError, match="LLM_API_KEY"):
        load_secrets(load_config(monitor))


def test_ten_accounts_and_optional_imap_password(monitor, monkeypatch):
    accounts = credentials(monkeypatch)
    accounts[0]["imap_password"] = "private-imap-password"
    monkeypatch.setenv("SENDER_ACCOUNTS_JSON", json.dumps(accounts))
    edit(monitor, "llm", "postal_address", "123 Genuine Street")
    secrets = load_secrets(load_config(monitor, {"send_enabled": True, "dry_run": False}))
    assert len(secrets.senders) == 10
    assert secrets.senders[0].imap_password == "private-imap-password"
    assert "private-" not in repr(secrets)
    assert "private-" not in repr(secrets.senders[0])


def test_real_send_rejects_nine_accounts(monitor, monkeypatch):
    credentials(monkeypatch, 9)
    edit(monitor, "llm", "postal_address", "123 Genuine Street")
    with pytest.raises(ValueError, match="ten accounts"):
        load_secrets(load_config(monitor, {"send_enabled": True, "dry_run": False}))


@pytest.mark.parametrize("key,value", [("email", "invalid"), ("smtp_port", True), ("smtp_port", 0), ("imap_port", "993"), ("tls_mode", "none"), ("password", ""), ("id", "x\nheader"), ("smtp_host", "https://host"), ("imap_password", ""), ("unexpected", "private-secret-value")])
def test_invalid_accounts_are_redacted(monitor, monkeypatch, key, value):
    accounts = credentials(monkeypatch)
    accounts[0][key] = value
    monkeypatch.setenv("SENDER_ACCOUNTS_JSON", json.dumps(accounts))
    with pytest.raises(ValueError, match="invalid or duplicate") as error:
        load_secrets(load_config(monitor))
    assert "private" not in str(error.value)


def test_duplicate_accounts_rejected(monitor, monkeypatch):
    accounts = credentials(monkeypatch)
    accounts[1]["email"] = accounts[0]["email"].upper()
    monkeypatch.setenv("SENDER_ACCOUNTS_JSON", json.dumps(accounts))
    with pytest.raises(ValueError, match="duplicate"):
        load_secrets(load_config(monitor))


def test_malformed_secret_json_is_redacted(monitor, monkeypatch):
    credentials(monkeypatch)
    monkeypatch.setenv("SENDER_ACCOUNTS_JSON", "private-secret-not-json")
    with pytest.raises(ValueError, match="valid JSON") as error:
        load_secrets(load_config(monitor))
    assert "private-secret" not in str(error.value)


def test_duplicate_json_keys_and_oversized_sender_secret_rejected(monitor, monkeypatch):
    credentials(monkeypatch)
    monkeypatch.setenv("SENDER_ACCOUNTS_JSON", '[{"id":"first","id":"second"}]')
    with pytest.raises(ValueError, match="duplicate object keys"):
        load_secrets(load_config(monitor))
    monkeypatch.setenv("SENDER_ACCOUNTS_JSON", "x" * 131073)
    with pytest.raises(ValueError, match="128 KiB"):
        load_secrets(load_config(monitor))
