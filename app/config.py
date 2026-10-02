from __future__ import annotations
import os,re
from dataclasses import dataclass
from datetime import time
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
EMAIL_RE=re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
def _bool(name,default=False):
    v=os.getenv(name); return default if v is None else v.strip().lower() in {'1','true','yes','on'}
def _int(name,default): return int(os.getenv(name,str(default)))
def _float(name,default): return float(os.getenv(name,str(default)))
def _clock(name,default):
    h,m=map(int,os.getenv(name,default).split(':',1)); return time(h,m)
@dataclass(frozen=True)
class SenderConfig:
    sender_id:str; credential_env:str; email:str; imap_host:str; imap_port:int; imap_ssl:bool; smtp_host:str; smtp_port:int; smtp_ssl:bool
@dataclass(frozen=True)
class Settings:
    app_timezone:str; daily_new_leads_target:int; daily_new_outreach_target:int; sender_count:int
    daily_new_outreach_limit_per_sender:int; daily_followup_limit_per_sender:int; daily_total_limit_per_sender:int
    send_interval_minutes:int; followup_1_delay_hours:int; followup_2_delay_days:int; followup_3_delay_days:int
    sending_window_start:time; sending_window_end:time; mailbox_provider:str; imap_host:str; imap_port:int; imap_use_ssl:bool
    mailbox_check_lookback_minutes:int; mailbox_max_messages_per_run:int; require_fresh_mailbox_check_before_followup:bool
    max_concurrent_sends:int; max_retries:int; retry_base_seconds:int; send_enabled:bool; dry_run:bool; sender_test_mode:bool
    database_url:str; sqlite_path:str; honor_robots:bool; crawler_timeout_seconds:int; crawler_max_bytes:int; crawler_max_pages:int
    crawler_request_delay_seconds:float; research_prompt_version:str; outreach_prompt_version:str; followup_prompt_version:str
    quality_prompt_version:str; min_personalization_confidence:float; llm_base_url:str; llm_model:str; llm_timeout_seconds:int
    @classmethod
    def from_env(cls):
        tz=os.getenv('APP_TIMEZONE','Asia/Kolkata').strip()
        try: ZoneInfo(tz)
        except ZoneInfoNotFoundError as exc: raise ValueError(f'Unknown APP_TIMEZONE: {tz}') from exc
        start=_clock('SENDING_WINDOW_START','18:00'); end=_clock('SENDING_WINDOW_END','20:00')
        if start==end: raise ValueError('SENDING_WINDOW_END must differ from SENDING_WINDOW_START')
        return cls(
            tz,_int('DAILY_NEW_LEADS_TARGET',100),_int('DAILY_NEW_OUTREACH_TARGET',100),_int('SENDER_COUNT',10),
            _int('DAILY_NEW_OUTREACH_LIMIT_PER_SENDER',10),_int('DAILY_FOLLOWUP_LIMIT_PER_SENDER',10),_int('DAILY_TOTAL_LIMIT_PER_SENDER',40),
            _int('SEND_INTERVAL_MINUTES',10),_int('FOLLOWUP_1_DELAY_HOURS',24),_int('FOLLOWUP_2_DELAY_DAYS',7),_int('FOLLOWUP_3_DELAY_DAYS',14),
            start,end,os.getenv('MAILBOX_PROVIDER','imap').strip().lower(),os.getenv('IMAP_HOST','imap.gmail.com').strip(),_int('IMAP_PORT',993),_bool('IMAP_USE_SSL',True),
            _int('MAILBOX_CHECK_LOOKBACK_MINUTES',180),_int('MAILBOX_MAX_MESSAGES_PER_RUN',100),_bool('REQUIRE_FRESH_MAILBOX_CHECK_BEFORE_FOLLOWUP',True),
            _int('MAX_CONCURRENT_SENDS',1),_int('MAX_RETRIES',3),_int('RETRY_BASE_SECONDS',60),_bool('SEND_ENABLED',False),_bool('DRY_RUN',True),_bool('SENDER_TEST_MODE',False),
            os.getenv('OUTREACH_DATABASE_URL','').strip(),os.getenv('OUTREACH_DB_PATH','runtime/outreach.db').strip(),_bool('HONOR_ROBOTS',True),
            _int('CRAWLER_TIMEOUT_SECONDS',15),_int('CRAWLER_MAX_BYTES',2_000_000),_int('CRAWLER_MAX_PAGES',10),_float('CRAWLER_REQUEST_DELAY_SECONDS',0.25),
            os.getenv('RESEARCH_PROMPT_VERSION','1.0').strip(),os.getenv('OUTREACH_PROMPT_VERSION','1.0').strip(),os.getenv('FOLLOWUP_PROMPT_VERSION','1.0').strip(),os.getenv('QUALITY_PROMPT_VERSION','1.0').strip(),
            _float('MIN_PERSONALIZATION_CONFIDENCE',0.75),os.getenv('NVIDIA_BASE_URL','https://integrate.api.nvidia.com/v1').rstrip('/'),os.getenv('NVIDIA_MODEL','nvidia/nemotron-3-ultra-550b-a55b').strip(),_int('NVIDIA_TIMEOUT_SECONDS',90)
        )
    def timezone(self): return ZoneInfo(self.app_timezone)
    def sender_configs(self):
        return [SenderConfig(f'SENDER_{i}',f'SENDER_{i}',os.getenv(f'SENDER_{i}_EMAIL','').strip(),os.getenv(f'SENDER_{i}_IMAP_HOST',self.imap_host).strip(),_int(f'SENDER_{i}_IMAP_PORT',self.imap_port),_bool(f'SENDER_{i}_IMAP_USE_SSL',self.imap_use_ssl),os.getenv(f'SENDER_{i}_SMTP_HOST','smtp.gmail.com').strip(),_int(f'SENDER_{i}_SMTP_PORT',465),_bool(f'SENDER_{i}_SMTP_USE_SSL',True)) for i in range(1,self.sender_count+1)]
    def validate_for_send(self):
        if self.sender_count!=10: raise ValueError('SENDER_COUNT must remain exactly 10')
        if not self.send_enabled or self.dry_run: raise ValueError('Real sending is disabled')
        if not self.database_url: raise ValueError('OUTREACH_DATABASE_URL is required for production persistence')
        for s in self.sender_configs():
            if not EMAIL_RE.fullmatch(s.email): raise ValueError(f'{s.sender_id}_EMAIL is missing or malformed')
            if not os.getenv(s.credential_env,'').strip(): raise ValueError(f'{s.credential_env} secret is missing')
    def validate_for_dry_run(self):
        if self.sender_count!=10: raise ValueError('SENDER_COUNT must remain exactly 10')
def settings_from_env(): return Settings.from_env()
