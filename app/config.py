from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _int(value: Any, default: int) -> int:
    return int(default if value is None else value)


def _float(value: Any, default: float) -> float:
    return float(default if value is None else value)


def _clock(value: Any, default: str) -> time:
    raw = str(default if value is None else value).strip()
    hour, minute = map(int, raw.split(":", 1))
    return time(hour, minute)


def _section(root: dict[str, Any], *keys: str) -> dict[str, Any]:
    cur: Any = root
    for key in keys:
        if not isinstance(cur, dict):
            return {}
        cur = cur.get(key, {})
    return cur if isinstance(cur, dict) else {}


@dataclass(frozen=True)
class SenderConfig:
    sender_id: str
    email: str
    credential_env: str
    imap_host: str
    imap_port: int
    imap_ssl: bool
    smtp_host: str
    smtp_port: int
    smtp_ssl: bool


@dataclass(frozen=True)
class Settings:
    monitor_path: str
    app_timezone: str
    automation_enabled: bool
    outreach_enabled: bool
    followups_enabled: bool
    outreach_schedule: str
    followups_schedule: str
    emergency_stop: bool
    target_new_initials: int
    batch_size: int
    max_concurrency: int
    send_enabled: bool
    dry_run: bool
    send_window_enforce: bool
    send_window_mode: str
    send_window_start: time
    send_window_end: time
    daily_limits_enforce: bool
    daily_initial_limit: int
    daily_followup_limit: int
    daily_total_limit: int
    batch_gap_seconds: int
    retry_limit: int
    retry_base_seconds: int
    smtp_sending_lease_minutes: int
    research_lease_minutes: int
    personalization_retry_limit: int
    min_personalization_confidence: float
    followup_1_delay_hours: int
    followup_2_delay_days: int
    followup_3_delay_days: int
    discovery_queries: tuple[str, ...]
    allowed_country_codes: tuple[str, ...]
    discovery_overage_buffer: int
    discovery_max_places_requests: int
    discovery_max_pages_per_query: int
    places_page_size: int
    max_candidates_per_run: int
    candidate_retry_limit: int
    candidate_retry_hours: int
    candidate_no_email_retry_days: int
    crawler_timeout_seconds: int
    crawler_max_bytes: int
    crawler_max_pages: int
    crawler_request_delay_seconds: float
    honor_robots: bool
    llm_base_url: str
    llm_model: str
    llm_timeout_seconds: int
    llm_max_tokens: int
    max_run_minutes: int
    mailbox_lookback_minutes: int
    mailbox_max_messages_per_run: int
    mailbox_stale_after_hours: int

    @classmethod
    def from_monitor(cls, path: str | Path = "monitor.yaml", overrides: dict[str, Any] | None = None) -> "Settings":
        monitor_path = Path(path)
        if not monitor_path.exists():
            raise FileNotFoundError(f"Missing operational control file: {monitor_path}")
        with monitor_path.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        overrides = overrides or {}

        app = _section(raw, "application")
        automation = _section(raw, "automation")
        outreach = _section(automation, "outreach")
        followups = _section(automation, "followups")
        execution = _section(raw, "execution")
        window = _section(execution, "send_window")
        limits = _section(execution, "daily_limits")
        retry = _section(execution, "retry")
        discovery = _section(raw, "discovery")
        crawler = _section(raw, "crawler")
        research = _section(raw, "research")
        personalization = _section(raw, "personalization")
        sender = _section(raw, "sender")
        safety = _section(raw, "safety")
        mailbox = _section(raw, "mailbox")

        def ov(name: str, fallback: Any) -> Any:
            return overrides[name] if name in overrides and overrides[name] is not None else fallback

        tz = str(ov("app_timezone", app.get("timezone", "Asia/Kolkata")))
        try:
            ZoneInfo(tz)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"Unknown application.timezone: {tz}") from exc

        settings = cls(
            monitor_path=str(monitor_path),
            app_timezone=tz,
            automation_enabled=_bool(automation.get("enabled"), False),
            outreach_enabled=_bool(outreach.get("enabled"), True),
            followups_enabled=_bool(followups.get("enabled"), True),
            outreach_schedule=str(outreach.get("schedule", "0 9 * * 1-5")),
            followups_schedule=str(followups.get("schedule", "0 10 * * 1-5")),
            emergency_stop=_bool(ov("emergency_stop", safety.get("emergency_stop")), False),
            target_new_initials=_int(ov("target_new_initials", execution.get("target_new_initials")), 100),
            batch_size=_int(execution.get("batch_size"), 10),
            max_concurrency=_int(execution.get("max_concurrency"), 10),
            send_enabled=_bool(ov("send_enabled", execution.get("send_enabled")), False),
            dry_run=_bool(ov("dry_run", execution.get("dry_run")), True),
            send_window_enforce=_bool(window.get("enforce"), False),
            send_window_mode=str(window.get("mode", "recipient")).lower(),
            send_window_start=_clock(window.get("start"), "09:00"),
            send_window_end=_clock(window.get("end"), "17:00"),
            daily_limits_enforce=_bool(limits.get("enforce"), False),
            daily_initial_limit=_int(limits.get("initial"), 1000),
            daily_followup_limit=_int(limits.get("followups"), 1000),
            daily_total_limit=_int(limits.get("total"), 2000),
            batch_gap_seconds=_int(execution.get("batch_gap_seconds"), 0),
            retry_limit=_int(retry.get("attempts"), 3),
            retry_base_seconds=_int(retry.get("base_seconds"), 5),
            smtp_sending_lease_minutes=_int(retry.get("smtp_sending_lease_minutes"), 30),
            research_lease_minutes=_int(research.get("lease_minutes"), 30),
            personalization_retry_limit=_int(personalization.get("repair_attempts"), 1),
            min_personalization_confidence=_float(personalization.get("min_confidence"), 0.75),
            followup_1_delay_hours=_int(followups.get("f1_delay_hours"), 24),
            followup_2_delay_days=_int(followups.get("f2_delay_days"), 7),
            followup_3_delay_days=_int(followups.get("f3_delay_days"), 14),
            discovery_queries=tuple(str(x).strip() for x in discovery.get("queries", []) if str(x).strip()),
            allowed_country_codes=tuple(str(x).strip().upper() for x in discovery.get("allowed_country_codes", []) if str(x).strip()),
            discovery_overage_buffer=_int(discovery.get("overage_buffer"), 50),
            discovery_max_places_requests=_int(discovery.get("max_places_requests_per_run"), 60),
            discovery_max_pages_per_query=_int(discovery.get("max_pages_per_query"), 3),
            places_page_size=min(20, max(1, _int(discovery.get("page_size"), 20))),
            max_candidates_per_run=_int(discovery.get("max_candidates_per_run"), 2000),
            candidate_retry_limit=_int(discovery.get("retry_limit"), 3),
            candidate_retry_hours=_int(discovery.get("temporary_retry_hours"), 24),
            candidate_no_email_retry_days=_int(discovery.get("no_email_retry_days"), 7),
            crawler_timeout_seconds=_int(crawler.get("timeout_seconds"), 15),
            crawler_max_bytes=_int(crawler.get("max_bytes"), 2_000_000),
            crawler_max_pages=_int(crawler.get("max_pages"), 10),
            crawler_request_delay_seconds=_float(crawler.get("request_delay_seconds"), 0.25),
            honor_robots=_bool(crawler.get("honor_robots"), True),
            llm_base_url=str(_env("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")).rstrip("/"),
            llm_model=str(_env("NVIDIA_MODEL", "nvidia/nemotron-3-ultra-550b-a55b")),
            llm_timeout_seconds=_int(_env("NVIDIA_TIMEOUT_SECONDS", str(_int(research.get("llm_timeout_seconds"), 90))), 90),
            llm_max_tokens=_int(_env("NVIDIA_MAX_TOKENS", str(_int(research.get("llm_max_tokens"), 1400))), 1400),
            max_run_minutes=_int(_section(raw, "runtime").get("max_run_minutes"), 300),
            mailbox_lookback_minutes=_int(mailbox.get("lookback_minutes"), 180),
            mailbox_max_messages_per_run=_int(mailbox.get("max_messages_per_run"), 100),
            mailbox_stale_after_hours=_int(mailbox.get("stale_after_hours"), 6),
        )
        settings.validate()
        return settings

    def timezone(self) -> ZoneInfo:
        return ZoneInfo(self.app_timezone)

    def validate_runtime_environment(self, *, process_new_outreach: bool, process_followups: bool, send_enabled: bool) -> None:
        required_base = {
            "SUPABASE_DB_URL": _env("SUPABASE_DB_URL"),
        }
        if process_new_outreach:
            required_base["GOOGLE_PLACES_API_KEY"] = _env("GOOGLE_PLACES_API_KEY")
            required_base["NVIDIA_API_KEY"] = _env("NVIDIA_API_KEY")
        if process_followups or send_enabled:
            for sender in self.sender_configs():
                required_base[f"{sender.sender_id}_EMAIL"] = sender.email
                required_base[f"{sender.credential_env}"] = _env(sender.credential_env)
        missing = [name for name, value in required_base.items() if not value]
        if missing:
            raise ValueError("Missing required runtime configuration: " + ", ".join(missing))

    def sender_configs(self) -> list[SenderConfig]:
        result: list[SenderConfig] = []
        host_default = _env("IMAP_HOST", "imap.gmail.com")
        port_default = int(_env("IMAP_PORT", "993"))
        imap_ssl_default = _bool(_env("IMAP_USE_SSL", "true"), True)
        for i in range(1, 11):
            result.append(
                SenderConfig(
                    sender_id=f"SENDER_{i}",
                    email=_env(f"SENDER_{i}_EMAIL"),
                    credential_env=f"SENDER_{i}",
                    imap_host=_env(f"SENDER_{i}_IMAP_HOST", host_default),
                    imap_port=int(_env(f"SENDER_{i}_IMAP_PORT", str(port_default))),
                    imap_ssl=_bool(_env(f"SENDER_{i}_IMAP_USE_SSL", str(imap_ssl_default)), imap_ssl_default),
                    smtp_host=_env(f"SENDER_{i}_SMTP_HOST", "smtp.gmail.com"),
                    smtp_port=int(_env(f"SENDER_{i}_SMTP_PORT", "465")),
                    smtp_ssl=_bool(_env(f"SENDER_{i}_SMTP_USE_SSL", "true"), True),
                )
            )
        return result

    def validate(self) -> None:
        if self.target_new_initials < 1:
            raise ValueError("execution.target_new_initials must be >= 1")
        if self.batch_size != 10:
            raise ValueError("execution.batch_size must be exactly 10")
        if self.max_concurrency != 10:
            raise ValueError("execution.max_concurrency must be exactly 10")
        if self.retry_limit < 0 or self.retry_base_seconds < 0:
            raise ValueError("retry settings must be non-negative")
        if self.send_window_mode not in {"recipient", "application"}:
            raise ValueError("execution.send_window.mode must be recipient or application")
        if self.daily_initial_limit < 1 or self.daily_followup_limit < 1 or self.daily_total_limit < 1:
            raise ValueError("daily limits must be positive even when disabled")
        if self.daily_total_limit < max(self.daily_initial_limit, self.daily_followup_limit):
            raise ValueError("daily total limit must cover individual limits")
        if not self.allowed_country_codes:
            raise ValueError("discovery.allowed_country_codes must not be empty")
        if not self.discovery_queries:
            raise ValueError("discovery.queries must contain at least one query")
        if self.discovery_overage_buffer < 0 or self.max_candidates_per_run < 1:
            raise ValueError("discovery buffer/candidate bounds are invalid")
        if self.followup_1_delay_hours < 1 or self.followup_2_delay_days < 1 or self.followup_3_delay_days < 1:
            raise ValueError("follow-up delays must be positive")
        if not (0 <= self.min_personalization_confidence <= 1):
            raise ValueError("personalization.min_confidence must be between 0 and 1")
        if self.emergency_stop and self.send_enabled:
            raise ValueError("safety.emergency_stop cannot be combined with send_enabled=true")
        senders = self.sender_configs()
        missing_emails = [s.sender_id for s in senders if not EMAIL_RE.fullmatch(s.email)]
        if missing_emails and self.send_enabled and not self.dry_run:
            raise ValueError(f"Missing/malformed sender emails: {','.join(missing_emails)}")
        if self.send_enabled and not self.dry_run:
            missing_credentials = [s.credential_env for s in senders if not _env(s.credential_env)]
            if missing_credentials:
                raise ValueError(f"Missing sender credentials: {','.join(missing_credentials)}")
        if not _env("SUPABASE_DB_URL"):
            raise ValueError("SUPABASE_DB_URL is required in the environment")
        if not _env("GOOGLE_PLACES_API_KEY"):
            raise ValueError("GOOGLE_PLACES_API_KEY is required in the environment")
        if self.send_enabled and not self.dry_run and not _env("NVIDIA_API_KEY"):
            raise ValueError("NVIDIA_API_KEY is required when sending real outreach")
