from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


def _clock(name: str, default: str) -> time:
    raw = _env(name, default)
    hour, minute = map(int, raw.split(":", 1))
    return time(hour, minute)


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
    supabase_db_url: str
    app_timezone: str
    allowed_country_codes: tuple[str, ...]
    discovery_target: int
    max_places_search_requests: int
    max_pages_per_search: int
    places_page_size: int
    max_raw_candidates: int
    discovery_max_retries_per_run: int
    discovery_retry_limit: int
    discovery_transient_retry_hours: int
    discovery_no_email_retry_days: int
    crawler_timeout_seconds: int
    crawler_max_bytes: int
    crawler_max_pages: int
    crawler_request_delay_seconds: float
    honor_robots: bool
    initial_outreach_target: int
    batch_size: int
    batch_interval_minutes: int
    daily_initial_limit: int
    daily_followup_limit: int
    daily_total_limit: int
    max_concurrent_sends: int
    retry_limit: int
    retry_base_seconds: int
    sending_window_start: time
    sending_window_end: time
    sending_window_mode: str
    followup_1_delay_hours: int
    followup_2_delay_days: int
    followup_3_delay_days: int
    mailbox_check_lookback_minutes: int
    mailbox_max_messages_per_run: int
    max_batches_per_run: int
    llm_base_url: str
    llm_model: str
    llm_timeout_seconds: int
    llm_max_tokens: int
    min_personalization_confidence: float
    send_enabled: bool
    dry_run: bool
    reset_state: bool
    enforce_send_window: bool
    enforce_daily_limits: bool
    personalization_retry_limit: int
    
    @classmethod
    def from_env(cls) -> "Settings":
        tz = _env("APP_TIMEZONE", "Asia/Kolkata")
        try:
            ZoneInfo(tz)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"Unknown APP_TIMEZONE: {tz}") from exc

        start = _clock("SENDING_WINDOW_START", "18:00")
        end = _clock("SENDING_WINDOW_END", "20:00")
        if start == end:
            raise ValueError("SENDING_WINDOW_START and SENDING_WINDOW_END must differ")
        mode = _env("SENDING_WINDOW_MODE", "recipient").lower()
        if mode not in {"recipient", "app"}:
            raise ValueError("SENDING_WINDOW_MODE must be recipient or app")

        countries = tuple(
            x.strip().upper()
            for x in _env("ALLOWED_COUNTRY_CODES", "US,CA,GB,AU").split(",")
            if x.strip()
        )

        settings = cls(
            supabase_db_url=_env("SUPABASE_DB_URL"),
            app_timezone=tz,
            allowed_country_codes=countries,
            discovery_target=_int("DISCOVERY_TARGET", 100),
            max_places_search_requests=_int("MAX_PLACES_SEARCH_REQUESTS", 30),
            max_pages_per_search=_int("MAX_PAGES_PER_SEARCH", 3),
            places_page_size=min(20, max(1, _int("PLACES_PAGE_SIZE", 20))),
            max_raw_candidates=_int("MAX_RAW_CANDIDATES", 500),
            discovery_max_retries_per_run=_int("DISCOVERY_MAX_RETRIES_PER_RUN", 20),
            discovery_retry_limit=_int("DISCOVERY_RETRY_LIMIT", 3),
            discovery_transient_retry_hours=_int("DISCOVERY_TRANSIENT_RETRY_HOURS", 24),
            discovery_no_email_retry_days=_int("DISCOVERY_NO_EMAIL_RETRY_DAYS", 7),
            crawler_timeout_seconds=_int("CRAWLER_TIMEOUT_SECONDS", 15),
            crawler_max_bytes=_int("CRAWLER_MAX_BYTES", 2_000_000),
            crawler_max_pages=_int("CRAWLER_MAX_PAGES", 10),
            crawler_request_delay_seconds=_float("CRAWLER_REQUEST_DELAY_SECONDS", 0.25),
            honor_robots=_bool("HONOR_ROBOTS", True),
            initial_outreach_target=_int("INITIAL_OUTREACH_TARGET", 100),
            batch_size=_int("BATCH_SIZE", 10),
            batch_interval_minutes=_int("BATCH_INTERVAL_MINUTES", 10),
            daily_initial_limit=_int("DAILY_INITIAL_LIMIT", 10),
            daily_followup_limit=_int("DAILY_FOLLOWUP_LIMIT", 10),
            daily_total_limit=_int("DAILY_TOTAL_LIMIT", 40),
            enforce_send_window=_bool("ENFORCE_SEND_WINDOW", True),
            enforce_daily_limits=_bool("ENFORCE_DAILY_LIMITS", True),
            personalization_retry_limit=_int("PERSONALIZATION_RETRY_LIMIT", 1),
            max_concurrent_sends=_int("MAX_CONCURRENT_SENDS", 10),
            retry_limit=_int("RETRY_LIMIT", 3),
            retry_base_seconds=_int("RETRY_BASE_SECONDS", 60),
            sending_window_start=start,
            sending_window_end=end,
            sending_window_mode=mode,
            followup_1_delay_hours=_int("FOLLOWUP_1_DELAY_HOURS", 24),
            followup_2_delay_days=_int("FOLLOWUP_2_DELAY_DAYS", 7),
            followup_3_delay_days=_int("FOLLOWUP_3_DELAY_DAYS", 14),
            mailbox_check_lookback_minutes=_int("MAILBOX_CHECK_LOOKBACK_MINUTES", 180),
            mailbox_max_messages_per_run=_int("MAILBOX_MAX_MESSAGES_PER_RUN", 100),
            max_batches_per_run=_int("MAX_BATCHES_PER_RUN", 30),
            llm_base_url=_env("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1").rstrip("/"),
            llm_model=_env("NVIDIA_MODEL", "nvidia/nemotron-3-ultra-550b-a55b"),
            llm_timeout_seconds=_int("NVIDIA_TIMEOUT_SECONDS", 90),
            llm_max_tokens=_int("NVIDIA_MAX_TOKENS", 1400),
            min_personalization_confidence=_float("MIN_PERSONALIZATION_CONFIDENCE", 0.75),
            send_enabled=_bool("SEND_ENABLED", False),
            dry_run=_bool("DRY_RUN", True),
            reset_state=_bool("RESET_STATE", False),
        )
        settings.validate()
        return settings

    def timezone(self) -> ZoneInfo:
        return ZoneInfo(self.app_timezone)

    def sender_configs(self) -> list[SenderConfig]:
        senders: list[SenderConfig] = []
        for i in range(1, 11):
            senders.append(
                SenderConfig(
                    sender_id=f"SENDER_{i}",
                    email=_env(f"SENDER_{i}_EMAIL"),
                    credential_env=f"SENDER_{i}",
                    imap_host=_env(f"SENDER_{i}_IMAP_HOST", _env("IMAP_HOST", "imap.gmail.com")),
                    imap_port=_int(f"SENDER_{i}_IMAP_PORT", _int("IMAP_PORT", 993)),
                    imap_ssl=_bool(f"SENDER_{i}_IMAP_USE_SSL", _bool("IMAP_USE_SSL", True)),
                    smtp_host=_env(f"SENDER_{i}_SMTP_HOST", "smtp.gmail.com"),
                    smtp_port=_int(f"SENDER_{i}_SMTP_PORT", 465),
                    smtp_ssl=_bool(f"SENDER_{i}_SMTP_USE_SSL", True),
                )
            )
        return senders

    def validate(self) -> None:
        if not self.supabase_db_url.startswith(("postgresql://", "postgres://")):
            raise ValueError("SUPABASE_DB_URL must be a PostgreSQL connection string")
        if self.personalization_retry_limit < 0:
            raise ValueError("PERSONALIZATION_RETRY_LIMIT cannot be negative")
        if len(self.allowed_country_codes) == 0:
            raise ValueError("ALLOWED_COUNTRY_CODES cannot be empty")
        if self.batch_size != 10:
            raise ValueError("BATCH_SIZE must be exactly 10")
        if self.max_concurrent_sends != 10:
            raise ValueError("MAX_CONCURRENT_SENDS must be exactly 10")
        if self.initial_outreach_target < 1:
            raise ValueError("INITIAL_OUTREACH_TARGET must be positive")
        if self.batch_interval_minutes < 1:
            raise ValueError("BATCH_INTERVAL_MINUTES must be positive")
        if self.daily_initial_limit < 1 or self.daily_followup_limit < 1 or self.daily_total_limit < 1:
            raise ValueError("Sender daily limits must be positive")
        if self.daily_total_limit < max(self.daily_initial_limit, self.daily_followup_limit):
            raise ValueError("DAILY_TOTAL_LIMIT must cover the individual category limits")

        senders = self.sender_configs()
        if any(not EMAIL_RE.fullmatch(s.email) for s in senders):
            missing = [s.sender_id for s in senders if not EMAIL_RE.fullmatch(s.email)]
            raise ValueError(f"Missing or malformed sender identities: {','.join(missing)}")
        if self.send_enabled and not self.dry_run:
            missing_credentials = [s.credential_env for s in senders if not _env(s.credential_env)]
            if missing_credentials:
                raise ValueError(f"Missing sender credentials: {','.join(missing_credentials)}")
        if self.max_places_search_requests < 1 or self.max_pages_per_search < 1:
            raise ValueError("Places request limits must be positive")
        if self.discovery_max_retries_per_run < 0 or self.discovery_retry_limit < 1 or self.max_batches_per_run < 1:
            raise ValueError("Retry/batch bounds are invalid")
