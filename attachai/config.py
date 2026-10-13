"""Validated non-secret controls and separately loaded environment credentials."""
from __future__ import annotations

import copy
import ipaddress
import json
import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from croniter import croniter

if TYPE_CHECKING:
    from .providers import Sender


DEFAULTS = {
    "automation": {"enabled": False, "outreach_cron": "0 9 * * 1-5", "followups_cron": "0 */4 * * *", "timezone": "UTC"},
    "safety": {"emergency_stop": False, "send_enabled": False, "dry_run": True},
    "outreach": {"enabled": True, "target_new_initials": 100, "batch_size": 10, "max_concurrency": 10},
    "followups": {"enabled": True, "delays_seconds": [86400, 604800, 1209600], "max_per_run": 1000},
    "limits": {"send_window_enabled": False, "window_start": "09:00", "window_end": "17:00", "timezone": "UTC", "daily_sender_enabled": False, "daily_sender": 100, "daily_total_enabled": False, "daily_total": 1000, "batch_gap_seconds": 0, "max_runtime_seconds": 18000},
    "retry": {"max_attempts": 3, "base_seconds": 2, "max_seconds": 60, "sender_cooldown_seconds": 30},
    "discovery": {"queries": ["dentist in Austin Texas"], "max_requests_per_run": 100, "max_candidates_per_run": 2000, "buffer_ratio": 1.5, "min_rating": 4, "min_reviews": 5},
    "research": {"version": "v1", "max_pages": 5, "max_bytes": 1000000, "timeout_seconds": 15, "robots_enabled": True, "max_evidence": 12},
    "llm": {"base_url": "https://integrate.api.nvidia.com/v1", "model": "openai/gpt-oss-20b", "timeout_seconds": 60, "offer": "AttachAI helps businesses respond to customer inquiries with an AI assistant.", "signature": "AttachAI team", "postal_address": ""},
    "mailbox": {"enabled": True, "lookback_days": 30, "max_messages_per_sender": 1000, "timeout_seconds": 20},
}


def parse_bool(value, name="boolean") -> bool:
    """Accept actual booleans or the exact dispatch strings; never truthy strings."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in {"true", "false"}:
        return value.strip().lower() == "true"
    raise ValueError(f"{name} must be true or false")


def _integer(value, name, low, high, *, dispatch=False):
    if dispatch and isinstance(value, str) and re.fullmatch(r"[0-9]+", value.strip()):
        try:
            value = int(value.strip())
        except ValueError:
            raise ValueError(f"{name} must be an integer within bounds") from None
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be an integer between {low} and {high}")
    return value


def _number(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name} must be a finite number between {low} and {high}")


class _UniqueLoader(yaml.SafeLoader):
    pass


def _mapping(loader, node):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        if not isinstance(key, str) or key in result:
            raise ValueError("monitor.yaml contains duplicate or non-string keys")
        result[key] = loader.construct_object(value_node, deep=True)
    return result


_UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


@dataclass(frozen=True)
class Config:
    data: dict
    send_enabled: bool
    dry_run: bool
    process_followups: bool
    process_new_outreach: bool
    target: int


@dataclass(frozen=True)
class Secrets:
    database_url: str = field(repr=False)
    places_key: str = field(default="", repr=False)
    llm_key: str = field(default="", repr=False)
    senders: list[Sender] = field(default_factory=list, repr=False)


def _validate(data):
    for section, values in data.items():
        for key, default in DEFAULTS[section].items():
            if isinstance(default, bool):
                values[key] = parse_bool(values[key], f"{section}.{key}")
    bounds = {
        "outreach": {"target_new_initials": (1, 100000), "batch_size": (1, 10), "max_concurrency": (1, 10)},
        "followups": {"max_per_run": (0, 100000)},
        "limits": {"daily_sender": (1, 100000), "daily_total": (1, 1000000), "batch_gap_seconds": (0, 3600), "max_runtime_seconds": (1, 18000)},
        "retry": {"max_attempts": (1, 20), "sender_cooldown_seconds": (0, 86400)},
        "discovery": {"max_requests_per_run": (1, 10000), "max_candidates_per_run": (1, 100000), "min_reviews": (0, 10000000)},
        "research": {"max_pages": (1, 50), "max_bytes": (1024, 10000000), "max_evidence": (1, 100)},
        "mailbox": {"lookback_days": (1, 3650), "max_messages_per_sender": (1, 100000)},
    }
    for section, values in bounds.items():
        for key, (low, high) in values.items():
            _integer(data[section][key], f"{section}.{key}", low, high)
    for section, key, low, high in [
        ("retry", "base_seconds", 0, 3600), ("retry", "max_seconds", 0, 86400),
        ("discovery", "buffer_ratio", 1, 10), ("discovery", "min_rating", 0, 5),
        ("research", "timeout_seconds", 1, 120), ("llm", "timeout_seconds", 1, 300),
        ("mailbox", "timeout_seconds", 1, 120),
    ]:
        _number(data[section][key], f"{section}.{key}", low, high)
    if data["retry"]["base_seconds"] > data["retry"]["max_seconds"]:
        raise ValueError("retry.base_seconds must not exceed retry.max_seconds")
    delays = data["followups"]["delays_seconds"]
    if not isinstance(delays, list) or len(delays) != 3:
        raise ValueError("followups.delays_seconds must contain exactly three delays")
    for delay in delays:
        _integer(delay, "followups.delays_seconds", 0, 31536000)
    for section in ("automation", "limits"):
        timezone = data[section]["timezone"]
        if not isinstance(timezone, str) or len(timezone) > 100:
            raise ValueError(f"{section}.timezone must be an IANA timezone")
        try:
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"{section}.timezone must be an IANA timezone") from None
    for key in ("outreach_cron", "followups_cron"):
        expression = data["automation"][key]
        if not isinstance(expression, str) or len(expression) > 200 or len(expression.split()) != 5 or not croniter.is_valid(expression):
            raise ValueError(f"automation.{key} must be a five-field cron expression")
    for key in ("window_start", "window_end"):
        if not isinstance(data["limits"][key], str) or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", data["limits"][key]):
            raise ValueError(f"limits.{key} must use HH:MM (24-hour)")
    queries = data["discovery"]["queries"]
    if not isinstance(queries, list) or not 1 <= len(queries) <= 100 or any(not isinstance(q, str) or not q.strip() or len(q) > 500 for q in queries):
        raise ValueError("discovery.queries must contain 1–100 nonempty queries")
    for section, key, max_len, empty in [
        ("research", "version", 100, False), ("llm", "base_url", 2048, False),
        ("llm", "model", 200, False), ("llm", "offer", 2000, False),
        ("llm", "signature", 500, False), ("llm", "postal_address", 1000, True),
    ]:
        value = data[section][key]
        if not isinstance(value, str) or len(value) > max_len or (not empty and not value.strip()) or any(ord(c) < 32 and c not in "\n\t" for c in value):
            raise ValueError(f"{section}.{key} is invalid")
    try:
        parsed = urlsplit(data["llm"]["base_url"])
        valid = parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment
        parsed.port
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("llm.base_url must be HTTPS without credentials, query or fragment")


def load_config(path="monitor.yaml", overrides: dict | None = None) -> Config:
    try:
        with Path(path).open(encoding="utf-8") as handle:
            raw = yaml.load(handle, Loader=_UniqueLoader)
    except yaml.YAMLError:
        raise ValueError("monitor.yaml is not valid YAML") from None
    if not isinstance(raw, dict):
        raise ValueError("monitor.yaml must contain a mapping")
    data = copy.deepcopy(DEFAULTS)
    for section, values in raw.items():
        if section not in data or not isinstance(values, dict):
            raise ValueError("monitor.yaml has an unknown section or non-mapping section")
        if values.keys() - data[section].keys():
            raise ValueError(f"monitor.yaml has unknown controls in {section}")
        data[section].update(values)
    _validate(data)
    overrides = {} if overrides is None else overrides
    allowed = {"reset_state", "target_new_initials", "send_enabled", "dry_run", "process_followups", "process_new_outreach"}
    if not isinstance(overrides, dict) or overrides.keys() - allowed:
        raise ValueError("Unknown workflow override")
    overrides = {k: v for k, v in overrides.items() if v is not None}
    for key in allowed - {"target_new_initials"}:
        if key in overrides:
            overrides[key] = parse_bool(overrides[key], key)
    target = _integer(overrides.get("target_new_initials", data["outreach"]["target_new_initials"]), "target_new_initials", 1, 100000, dispatch=True)
    stop = data["safety"]["emergency_stop"]
    send = overrides.get("send_enabled", data["safety"]["send_enabled"]) and not stop
    dry = overrides.get("dry_run", data["safety"]["dry_run"]) or stop
    followups = overrides.get("process_followups", True) and data["followups"]["enabled"] and not stop
    outreach = overrides.get("process_new_outreach", True) and data["outreach"]["enabled"] and not stop
    data["safety"].update(send_enabled=send, dry_run=dry)
    data["outreach"]["target_new_initials"] = target
    if send and not dry and (outreach or followups) and not data["llm"]["postal_address"].strip():
        raise ValueError("llm.postal_address is required for real sends")
    return Config(data, send, dry, followups, outreach, target)


def _secret(name, *, required=False):
    value = os.environ.get(name, "").strip()
    if required and not value:
        raise ValueError(f"Missing required environment secret: {name}")
    return value


def _json_object_no_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            # The caller replaces this low-level detail with a fixed safe error.
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _validate_database_url(database: str) -> None:
    """Validate PostgreSQL URL structure and require TLS for remote hosts.

    Local loopback URLs remain usable for disposable test databases. A remote
    Supabase URL must explicitly carry sslmode=require (or stronger).
    """
    try:
        if any(ord(char) < 32 or ord(char) == 127 for char in database):
            raise ValueError
        parsed = urlsplit(database)
        if (parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname
                or parsed.path in {"", "/"} or parsed.fragment):
            raise ValueError
        parsed.port  # force validation of malformed/out-of-range ports
        host = parsed.hostname.rstrip(".").lower()
        local = host in {"localhost", "localhost.localdomain"}
        try:
            local = local or ipaddress.ip_address(host).is_loopback
        except ValueError:
            pass
        modes = parse_qs(parsed.query, keep_blank_values=True).get("sslmode", [])
        if not local and (not modes or modes[-1].lower() not in {"require", "verify-ca", "verify-full"}):
            raise ValueError("tls")
    except ValueError as exc:
        if str(exc) == "tls":
            raise ValueError("DATABASE_URL must require TLS for remote databases (add sslmode=require)") from None
        raise ValueError("DATABASE_URL must be a valid PostgreSQL connection URL with a database name") from None


def _validate_api_key(name: str, value: str) -> None:
    if value and (len(value) > 4096 or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value)):
        raise ValueError(f"{name} has an invalid format")


def load_secrets(config: Config, *, validate_all: bool = False) -> Secrets:
    """Disabled scheduled runs must exit before calling this function."""
    database = _secret("DATABASE_URL", required=True)
    _validate_database_url(database)
    active = config.process_new_outreach or config.process_followups
    places = _secret("GOOGLE_PLACES_API_KEY", required=config.process_new_outreach or validate_all)
    llm = _secret("LLM_API_KEY", required=active or validate_all)
    _validate_api_key("GOOGLE_PLACES_API_KEY", places)
    _validate_api_key("LLM_API_KEY", llm)
    real = config.send_enabled and not config.dry_run and active
    raw = _secret("SENDER_ACCOUNTS_JSON", required=real or validate_all)
    senders = []
    if raw:
        if len(raw.encode("utf-8")) > 131072:
            raise ValueError("SENDER_ACCOUNTS_JSON exceeds the 128 KiB size limit")
        from .providers import Sender, normalize_email
        try:
            accounts = json.loads(raw, object_pairs_hook=_json_object_no_duplicate_keys)
        except (ValueError, TypeError):
            raise ValueError("SENDER_ACCOUNTS_JSON must be valid JSON without duplicate object keys") from None
        if not isinstance(accounts, list) or len(accounts) > 10 or ((real or validate_all) and len(accounts) != 10):
            raise ValueError("SENDER_ACCOUNTS_JSON must contain ten accounts for real sends (at most ten otherwise)")
        ids, emails = set(), set()
        for account in accounts:
            try:
                fields = {"id", "email", "password", "smtp_host", "smtp_port", "imap_host", "imap_port", "tls_mode"}
                if not isinstance(account, dict) or not fields <= account.keys() or account.keys() - (fields | {"imap_password"}):
                    raise ValueError()
                for key in ("id", "email", "password", "smtp_host", "imap_host", "tls_mode"):
                    if not isinstance(account[key], str) or not account[key].strip() or any(ord(c) < 32 for c in account[key]):
                        raise ValueError()
                if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", account["id"]):
                    raise ValueError()
                for key in ("smtp_host", "imap_host"):
                    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?", account[key]):
                        raise ValueError()
                if account["tls_mode"] not in {"ssl", "starttls"}:
                    raise ValueError()
                for key in ("smtp_port", "imap_port"):
                    _integer(account[key], "sender port", 1, 65535)
                if "imap_password" in account and (not isinstance(account["imap_password"], str) or not account["imap_password"] or any(ord(c) < 32 for c in account["imap_password"])):
                    raise ValueError()
                email = normalize_email(account["email"])
                if email in emails or account["id"] in ids:
                    raise ValueError()
                ids.add(account["id"])
                emails.add(email)
                senders.append(Sender(**{**account, "email": email}))
            except Exception:
                # Never echo the account, original exception, URL or credentials.
                raise ValueError("SENDER_ACCOUNTS_JSON contains an invalid or duplicate account") from None
    return Secrets(database, places, llm, senders)
