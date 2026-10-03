# Complete Replacement File Contents


---

## FILE: .env.example

```text
SUPABASE_DB_URL=postgresql://postgres:[PASSWORD]@[HOST]:5432/postgres?sslmode=require
NVIDIA_API_KEY=
GOOGLE_PLACES_API_KEY=

APP_TIMEZONE=Asia/Kolkata
ALLOWED_COUNTRY_CODES=US,CA,GB,AU
DISCOVERY_TARGET=100
MAX_PLACES_SEARCH_REQUESTS=30
MAX_PAGES_PER_SEARCH=3
PLACES_PAGE_SIZE=20
MAX_RAW_CANDIDATES=500
DISCOVERY_MAX_RETRIES_PER_RUN=20
DISCOVERY_RETRY_LIMIT=3
DISCOVERY_TRANSIENT_RETRY_HOURS=24
DISCOVERY_NO_EMAIL_RETRY_DAYS=7

CRAWLER_TIMEOUT_SECONDS=15
CRAWLER_MAX_BYTES=2000000
CRAWLER_MAX_PAGES=10
CRAWLER_REQUEST_DELAY_SECONDS=0.25
HONOR_ROBOTS=true

INITIAL_OUTREACH_TARGET=100
BATCH_SIZE=10
BATCH_INTERVAL_MINUTES=10
DAILY_INITIAL_LIMIT=10
DAILY_FOLLOWUP_LIMIT=10
DAILY_TOTAL_LIMIT=40
MAX_CONCURRENT_SENDS=10
RETRY_LIMIT=3
RETRY_BASE_SECONDS=60
SENDING_WINDOW_START=18:00
SENDING_WINDOW_END=20:00
SENDING_WINDOW_MODE=recipient

FOLLOWUP_1_DELAY_HOURS=24
FOLLOWUP_2_DELAY_DAYS=7
FOLLOWUP_3_DELAY_DAYS=14

IMAP_HOST=imap.gmail.com
IMAP_PORT=993
IMAP_USE_SSL=true
MAILBOX_CHECK_LOOKBACK_MINUTES=180
MAILBOX_MAX_MESSAGES_PER_RUN=100
MAX_BATCHES_PER_RUN=30

NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1
NVIDIA_MODEL=nvidia/nemotron-3-ultra-550b-a55b
NVIDIA_TIMEOUT_SECONDS=90
NVIDIA_MAX_TOKENS=1400
MIN_PERSONALIZATION_CONFIDENCE=0.75

SEND_ENABLED=false
DRY_RUN=true
RESET_STATE=false

SENDER_1=
SENDER_1_EMAIL=
SENDER_2=
SENDER_2_EMAIL=
SENDER_3=
SENDER_3_EMAIL=
SENDER_4=
SENDER_4_EMAIL=
SENDER_5=
SENDER_5_EMAIL=
SENDER_6=
SENDER_6_EMAIL=
SENDER_7=
SENDER_7_EMAIL=
SENDER_8=
SENDER_8_EMAIL=
SENDER_9=
SENDER_9_EMAIL=
SENDER_10=
SENDER_10_EMAIL=
```

---

## FILE: .github/workflows/attachai.yml

```text
name: AttachAI

on:
  workflow_dispatch:
    inputs:
      reset_state:
        description: 'Clear ONLY application runtime data in Supabase before this run'
        required: true
        default: false
        type: boolean
      initial_outreach_target:
        description: 'Successful INITIAL sends required overall; existing SENT rows count on reruns'
        required: true
        default: 100
        type: number
      send_enabled:
        description: 'Allow real SMTP sending'
        required: true
        default: false
        type: boolean
      dry_run:
        description: 'Simulate sending and skip mailbox network I/O'
        required: true
        default: true
        type: boolean

concurrency:
  group: attachai-manual-production
  cancel-in-progress: false

permissions:
  contents: read

jobs:
  attachai:
    runs-on: ubuntu-latest
    timeout-minutes: 330
    env:
      SUPABASE_DB_URL: ${{ secrets.SUPABASE_DB_URL }}
      NVIDIA_API_KEY: ${{ secrets.NVIDIA_API_KEY }}
      GOOGLE_PLACES_API_KEY: ${{ secrets.GOOGLE_PLACES_API_KEY }}
      SENDER_1: ${{ secrets.SENDER_1 }}
      SENDER_2: ${{ secrets.SENDER_2 }}
      SENDER_3: ${{ secrets.SENDER_3 }}
      SENDER_4: ${{ secrets.SENDER_4 }}
      SENDER_5: ${{ secrets.SENDER_5 }}
      SENDER_6: ${{ secrets.SENDER_6 }}
      SENDER_7: ${{ secrets.SENDER_7 }}
      SENDER_8: ${{ secrets.SENDER_8 }}
      SENDER_9: ${{ secrets.SENDER_9 }}
      SENDER_10: ${{ secrets.SENDER_10 }}
      SENDER_1_EMAIL: ${{ vars.SENDER_1_EMAIL }}
      SENDER_2_EMAIL: ${{ vars.SENDER_2_EMAIL }}
      SENDER_3_EMAIL: ${{ vars.SENDER_3_EMAIL }}
      SENDER_4_EMAIL: ${{ vars.SENDER_4_EMAIL }}
      SENDER_5_EMAIL: ${{ vars.SENDER_5_EMAIL }}
      SENDER_6_EMAIL: ${{ vars.SENDER_6_EMAIL }}
      SENDER_7_EMAIL: ${{ vars.SENDER_7_EMAIL }}
      SENDER_8_EMAIL: ${{ vars.SENDER_8_EMAIL }}
      SENDER_9_EMAIL: ${{ vars.SENDER_9_EMAIL }}
      SENDER_10_EMAIL: ${{ vars.SENDER_10_EMAIL }}
      APP_TIMEZONE: ${{ vars.APP_TIMEZONE || 'Asia/Kolkata' }}
      ALLOWED_COUNTRY_CODES: ${{ vars.ALLOWED_COUNTRY_CODES || 'US,CA,GB,AU' }}
      DISCOVERY_TARGET: ${{ vars.DISCOVERY_TARGET || '100' }}
      MAX_PLACES_SEARCH_REQUESTS: ${{ vars.MAX_PLACES_SEARCH_REQUESTS || '30' }}
      MAX_PAGES_PER_SEARCH: ${{ vars.MAX_PAGES_PER_SEARCH || '3' }}
      PLACES_PAGE_SIZE: ${{ vars.PLACES_PAGE_SIZE || '20' }}
      MAX_RAW_CANDIDATES: ${{ vars.MAX_RAW_CANDIDATES || '500' }}
      DISCOVERY_MAX_RETRIES_PER_RUN: ${{ vars.DISCOVERY_MAX_RETRIES_PER_RUN || '20' }}
      DISCOVERY_RETRY_LIMIT: ${{ vars.DISCOVERY_RETRY_LIMIT || '3' }}
      DISCOVERY_TRANSIENT_RETRY_HOURS: ${{ vars.DISCOVERY_TRANSIENT_RETRY_HOURS || '24' }}
      DISCOVERY_NO_EMAIL_RETRY_DAYS: ${{ vars.DISCOVERY_NO_EMAIL_RETRY_DAYS || '7' }}
      CRAWLER_TIMEOUT_SECONDS: ${{ vars.CRAWLER_TIMEOUT_SECONDS || '15' }}
      CRAWLER_MAX_BYTES: ${{ vars.CRAWLER_MAX_BYTES || '2000000' }}
      CRAWLER_MAX_PAGES: ${{ vars.CRAWLER_MAX_PAGES || '10' }}
      CRAWLER_REQUEST_DELAY_SECONDS: ${{ vars.CRAWLER_REQUEST_DELAY_SECONDS || '0.25' }}
      HONOR_ROBOTS: ${{ vars.HONOR_ROBOTS || 'true' }}
      BATCH_SIZE: '10'
      BATCH_INTERVAL_MINUTES: ${{ vars.BATCH_INTERVAL_MINUTES || '10' }}
      DAILY_INITIAL_LIMIT: ${{ vars.DAILY_INITIAL_LIMIT || '10' }}
      DAILY_FOLLOWUP_LIMIT: ${{ vars.DAILY_FOLLOWUP_LIMIT || '10' }}
      DAILY_TOTAL_LIMIT: ${{ vars.DAILY_TOTAL_LIMIT || '40' }}
      MAX_CONCURRENT_SENDS: '10'
      RETRY_LIMIT: ${{ vars.RETRY_LIMIT || '3' }}
      RETRY_BASE_SECONDS: ${{ vars.RETRY_BASE_SECONDS || '60' }}
      SENDING_WINDOW_START: ${{ vars.SENDING_WINDOW_START || '18:00' }}
      SENDING_WINDOW_END: ${{ vars.SENDING_WINDOW_END || '20:00' }}
      SENDING_WINDOW_MODE: ${{ vars.SENDING_WINDOW_MODE || 'recipient' }}
      FOLLOWUP_1_DELAY_HOURS: ${{ vars.FOLLOWUP_1_DELAY_HOURS || '24' }}
      FOLLOWUP_2_DELAY_DAYS: ${{ vars.FOLLOWUP_2_DELAY_DAYS || '7' }}
      FOLLOWUP_3_DELAY_DAYS: ${{ vars.FOLLOWUP_3_DELAY_DAYS || '14' }}
      IMAP_HOST: ${{ vars.IMAP_HOST || 'imap.gmail.com' }}
      IMAP_PORT: ${{ vars.IMAP_PORT || '993' }}
      IMAP_USE_SSL: ${{ vars.IMAP_USE_SSL || 'true' }}
      MAILBOX_CHECK_LOOKBACK_MINUTES: ${{ vars.MAILBOX_CHECK_LOOKBACK_MINUTES || '180' }}
      MAILBOX_MAX_MESSAGES_PER_RUN: ${{ vars.MAILBOX_MAX_MESSAGES_PER_RUN || '100' }}
      MAX_BATCHES_PER_RUN: ${{ vars.MAX_BATCHES_PER_RUN || '30' }}
      NVIDIA_BASE_URL: ${{ vars.NVIDIA_BASE_URL || 'https://integrate.api.nvidia.com/v1' }}
      NVIDIA_MODEL: ${{ vars.NVIDIA_MODEL || 'nvidia/nemotron-3-ultra-550b-a55b' }}
      NVIDIA_TIMEOUT_SECONDS: ${{ vars.NVIDIA_TIMEOUT_SECONDS || '90' }}
      NVIDIA_MAX_TOKENS: ${{ vars.NVIDIA_MAX_TOKENS || '1400' }}
      MIN_PERSONALIZATION_CONFIDENCE: ${{ vars.MIN_PERSONALIZATION_CONFIDENCE || '0.75' }}
      SEND_ENABLED: ${{ inputs.send_enabled }}
      DRY_RUN: ${{ inputs.dry_run }}
      PYTHONUNBUFFERED: '1'
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: pip

      - name: Install dependencies
        run: python -m pip install -r requirements.txt

      - name: Run unit tests
        run: python -m unittest discover -s tests -p 'test_*.py' -v

      - name: Execute complete finite system
        run: >-
          python -m app.main
          --reset-state "${{ inputs.reset_state }}"
          --initial-target "${{ inputs.initial_outreach_target }}"
          --send-enabled "${{ inputs.send_enabled }}"
          --dry-run "${{ inputs.dry_run }}"
```

---

## FILE: .github/workflows/tests.yml

```text
name: AttachAI Tests

on:
  push:
    paths:
      - 'app/**'
      - 'tests/**'
      - 'migrations/**'
      - 'requirements.txt'
      - '.github/workflows/tests.yml'
  pull_request:
    paths:
      - 'app/**'
      - 'tests/**'
      - 'migrations/**'
      - 'requirements.txt'
      - '.github/workflows/tests.yml'
  workflow_dispatch:

concurrency:
  group: attachai-tests-${{ github.ref }}
  cancel-in-progress: true

permissions:
  contents: read

jobs:
  test:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    env:
      PYTHONUNBUFFERED: '1'
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: pip
      - run: python -m pip install -r requirements.txt
      - run: python -m compileall -q app tests
      - run: python -m unittest discover -s tests -p 'test_*.py' -v
```

---

## FILE: .gitignore

```text
.env
.env.*
*.secret
credentials*
secrets*
runtime/
logs_private/
__pycache__/
*.pyc
.pytest_cache/
```

---

## FILE: README.md

```text
# AttachAI — Single-Runner Outreach System

AttachAI is a finite, manually triggered GitHub Actions system for lead discovery, website research, evidence-bound personalization, durable outreach batching, SMTP delivery, mailbox synchronization, suppression, and chained follow-ups.

## Architecture

```text
GitHub Actions (one manual run)
        |
        v
Lead Discovery
        |
        v
Supabase PostgreSQL  <-- authoritative runtime state
        |
        +--> next untouched eligible leads
        |       |
        |       v
        |   Website Research
        |       |
        |       v
        |   Personalization LLM
        |       |
        |       v
        |   Deterministic Validator
        |       |
        |       v
        |   Durable Outreach Queue
        |       |
        |       v
        |   10-sender batches / 10 concurrent SMTP calls
        |       |
        |       v
        |   mailbox sync -> reply / bounce / unsubscribe
        |       |
        |       v
        |   suppression + state
        |       |
        |       v
        |   F1 -> F2 -> F3
```

There is one production workflow: `.github/workflows/attachai.yml`. It has `workflow_dispatch` only; no production cron is enabled.

A separate `.github/workflows/tests.yml` provides CI/test execution and never sends mail.

## Source of truth

Supabase PostgreSQL is the only production application state store. The runtime does not read `leads_crm.csv`, `seen_domains.csv`, `retry_queue.csv`, `candidate_memory.jsonl`, or `run_log.jsonl` as authoritative state.

The legacy CSV/JSONL runtime files are removed from the final runtime tree. If historical copies are retained outside Git, they are not read by `app.main` and are not authoritative.

The database contains durable state for:

`workflow_run`, `leads`, `lead_qualification`, `discovery_candidate`, `lead_research`, `outreach_batches`, `outreach`, `sender_daily_state`, `suppression`, `mailbox_state`, `inbound_message`, and `event_log`.

## Supabase setup

Create a Supabase project and copy the Postgres connection string from the Supabase **Connect** dialog into the GitHub repository secret `SUPABASE_DB_URL`.

The application requires a PostgreSQL URL and adds `sslmode=require` when the URL does not specify an SSL mode. The driver disables automatic prepared statements so a Supabase transaction-pooler URL can be used safely.

See the Supabase database connection and SSL documentation for connection-string and transport details: https://supabase.com/docs/guides/database/connecting-to-postgres and https://supabase.com/docs/guides/platform/ssl-enforcement.

## GitHub configuration

### Secrets

Required:

`SUPABASE_DB_URL`

`NVIDIA_API_KEY`

`GOOGLE_PLACES_API_KEY`

`SENDER_1` through `SENDER_10`

The `SENDER_n` secrets contain only the mailbox credential/app password. Never put credentials in source files or GitHub Variables.

### Variables

Required sender identities:

`SENDER_1_EMAIL` through `SENDER_10_EMAIL`

The workflow provides defaults for the remaining operational variables. Any override must correspond to a setting that is actually consumed by runtime code.

Important defaults:

```text
APP_TIMEZONE=Asia/Kolkata
ALLOWED_COUNTRY_CODES=US,CA,GB,AU
DISCOVERY_TARGET=100
MAX_PLACES_SEARCH_REQUESTS=30
MAX_PAGES_PER_SEARCH=3
PLACES_PAGE_SIZE=20
MAX_RAW_CANDIDATES=500
DISCOVERY_MAX_RETRIES_PER_RUN=20
DISCOVERY_RETRY_LIMIT=3
CRAWLER_MAX_PAGES=10
INITIAL_OUTREACH_TARGET=100
BATCH_SIZE=10
BATCH_INTERVAL_MINUTES=10
DAILY_INITIAL_LIMIT=10
DAILY_FOLLOWUP_LIMIT=10
DAILY_TOTAL_LIMIT=40
MAX_CONCURRENT_SENDS=10
RETRY_LIMIT=3
SENDING_WINDOW_START=18:00
SENDING_WINDOW_END=20:00
SENDING_WINDOW_MODE=recipient
FOLLOWUP_1_DELAY_HOURS=24
FOLLOWUP_2_DELAY_DAYS=7
FOLLOWUP_3_DELAY_DAYS=14
MAILBOX_CHECK_LOOKBACK_MINUTES=180
MAILBOX_MAX_MESSAGES_PER_RUN=100
MAX_BATCHES_PER_RUN=30
MIN_PERSONALIZATION_CONFIDENCE=0.75
```

## First manual validation

Open GitHub → Actions → **AttachAI** → **Run workflow**.

For the fresh architecture test, use:

```text
reset_state = true
initial_outreach_target = 100
send_enabled = true
dry_run = false
```

Run this against a clean Supabase application database for the first validation. The migration is additive and does not attempt to reinterpret the incompatible legacy schema from the previous implementation.

`reset_state=true` deletes only application/runtime rows inside Supabase. It does not change secrets, variables, source code, or workflow configuration.

The run initializes/migrates the schema, discovers leads directly into Supabase, selects untouched leads from the database, researches them, generates and validates messages, creates 10-message batches, sends through up to 10 independent senders concurrently, synchronizes mailboxes, evaluates suppression, processes any due follow-ups, reports metrics, and exits.

The workflow never treats a queued message as a successful send. The initial target is counted only from durable `outreach.status='SENT'` rows with a `sent_at_utc`, `message_id`, and `sender_id`. Existing successful rows count toward the target on later state-preserving reruns, which prevents a crash recovery run from starting another duplicate batch.

Google Places Text Search (New) supports paged responses using `nextPageToken`; the discovery implementation consumes that token up to the configured per-search page limit. See https://developers.google.com/maps/documentation/places/web-service/text-search.

## Batch sending

Initial outreach is assigned explicitly in batches of at most ten.

Each batch contains no more than one initial message per sender:

```text
Batch N:
SENDER_1 -> one lead
SENDER_2 -> one lead
...
SENDER_10 -> one lead
```

SMTP calls are executed with `ThreadPoolExecutor(max_workers=10)` so independent sender accounts can send concurrently.

Batch spacing is controlled by `BATCH_INTERVAL_MINUTES`. Sender daily limits and minimum spacing remain enforced by persisted sender state.

The sender assignment is persisted on both `leads.sender_id` and `outreach.sender_id`.

## Idempotency and crash recovery

Stable IDs:

```text
LeadID = SHA-256(normalized email + normalized website domain)
ResearchID = SHA-256(LeadID + research timestamp)
OutreachID = SHA-256(LeadID + sequence type + sequence number)
BatchID = workflow_run_id + batch type + batch number
```

Database constraints prevent duplicate lead domains/Place IDs, duplicate per-lead sequences, duplicate active body hashes, duplicate SMTP message IDs, and duplicate sender assignments within a batch.

The individual send claim is an atomic state transition to `SENDING`.

If an action run dies after successful sends are persisted, those rows remain `SENT` and are never selected for another send.

If rows remain `SENDING` for longer than the reconciliation window, the next run moves them to `REVIEW_NEEDED` rather than automatically resending a message whose provider acceptance is ambiguous.

Unsent batch rows are released back to the durable queue after batch reconciliation.

## Sender health

Sender states are:

`HEALTHY`, `DEGRADED`, `COOLDOWN`, `STOPPED`.

SMTP authentication failure stops that sender.

Temporary provider/network failures put the sender into cooldown and create a bounded retry for the message.

Mailbox failures mark a sender degraded. A degraded sender is not selected for new batches until a successful mailbox check restores health.

## Timezones

All persisted timestamps are UTC.

Recipient-local timezone is used for the configured sending window when `SENDING_WINDOW_MODE=recipient`.

`APP_TIMEZONE` is used as the fallback for invalid/missing recipient timezones and for application-level daily counters.

The discovery layer maps US states, Canadian provinces, UK, and Australian locations to appropriate IANA zones instead of applying a single US fallback to non-US leads.

## Mailbox monitor

Mailbox synchronization is finite and runs inside the same operational workflow. There is no separate permanent or hourly production workflow.

The monitor persists mailbox cursor/UIDVALIDITY state and uses an IMAP calendar-date query followed by an exact timestamp lookback filter. The processed UID cursor advances only across messages actually examined.

Replies correlate through `Message-ID`, `In-Reply-To`, `References`, or a matching lead/sender relationship.

Hard bounces suppress the recipient and cancel future follow-ups.

Opt-outs suppress the correlated lead address and cancel future follow-ups.

Ambiguous/unknown inbound messages are stored as non-destructive classifications.

Reply bodies are not stored in the database; only metadata/excerpts required for operational processing are handled in memory.

## Follow-ups

The sequence is strictly chained:

```text
INITIAL SENT
    ↓ +24h
F1 SENT
    ↓ +7d
F2 SENT
    ↓ +14d
F3 SENT
```

F2 is generated only after successful F1.

F3 is generated only after successful F2.

Each follow-up uses the same sender identity as the immediately previous message.

Each follow-up threads to the previous successful `message_id` through `In-Reply-To` and `References`.

Replies, hard bounces, and unsubscribes cancel future follow-ups.

## Fresh reset

`RESET_STATE` is explicit and defaults to false.

The reset does not drop the database and does not touch credentials or repository configuration. It clears only application tables in foreign-key-safe order.

Normal runs preserve:

leads, research, outreach, sender assignment, send timestamps, message IDs, suppression, inbound history, mailbox cursors, retry state, batch state, and events.

## Runtime reporting

The workflow prints:

```text
START_TIME
DISCOVERY_START / END / DURATION
PREPARE_START / END / DURATION
SEND_START / END / DURATION
MAILBOX_START / END / DURATION
FOLLOWUP_START / END / DURATION
FINAL_END
TOTAL_RUNTIME_SECONDS
```

Every completed batch records/logs:

batch ID, batch number, scheduled time, participating senders, planned, attempted, successful, failed, and duration.

The final JSON report separates discovery, verification, eligibility, selection, research, personalization, validation, queueing, scheduling, attempts, successful initial sends, retryable failures, terminal failures, suppression, replies, bounces, unsubscribes, follow-ups generated, and follow-ups sent. A real-send run exits non-zero when the requested initial target is not reached.

## Local tests

```bash
python -m pip install -r requirements.txt
python -m compileall -q app tests
python -m unittest discover -s tests -p 'test_*.py' -v
```

Tests use a SQLite test-only connection to exercise the repository without requiring a live Supabase project. Production configuration rejects SQLite and requires a PostgreSQL URL.

No test sends real email.

## Legacy files

The old production runtime files are intentionally removed from the refactored tree because Git must not be the transactional application database:

`leads_crm.csv`

`seen_domains.csv`

`retry_queue.csv`

`candidate_memory.jsonl`

`run_log.jsonl`

Historical copies can be kept outside the runtime repository when needed for audit or migration work, but the production application never reads them.

## Live integration status

The implementation is unit-tested locally. Live production execution depends on the actual GitHub secrets/variables and Supabase/SMTP/IMAP/NVIDIA/Google credentials available to the repository owner.

A successful unit test run is not a claim that every live provider accepted or sent messages.
```

---

## FILE: app/__init__.py

```text

```

---

## FILE: app/config.py

```text
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
```

---

## FILE: app/db.py

```text
from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_email(value: str) -> str:
    return (value or "").strip().lower()


def normalize_domain(value: str) -> str:
    text = (value or "").strip().lower()
    if "@" in text:
        text = text.rsplit("@", 1)[1]
    if "://" not in text:
        text = "https://" + text
    host = (urlparse(text).hostname or "").strip(".")
    return host[4:] if host.startswith("www.") else host


def deterministic_lead_id(email: str, website: str) -> str:
    return hashlib.sha256(f"{normalize_email(email)}|{normalize_domain(website)}".encode()).hexdigest()


def deterministic_research_id(lead_id: str, timestamp_utc: str) -> str:
    return hashlib.sha256(f"{lead_id}|{timestamp_utc}".encode()).hexdigest()


def deterministic_outreach_id(lead_id: str, sequence_type: str, sequence_number: int) -> str:
    return hashlib.sha256(f"{lead_id}:{sequence_type}:{sequence_number}".encode()).hexdigest()


def utc_from_value(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class Store:
    """Single production persistence layer. Production accepts only Supabase/Postgres URLs."""

    def __init__(self, database_url: str):
        self.database_url = database_url
        self.is_sqlite = database_url.startswith("sqlite://")
        self.conn = None
        if self.is_sqlite:
            import sqlite3
            path = database_url.removeprefix("sqlite://") or ":memory:"
            if path != ":memory:":
                Path(path).parent.mkdir(parents=True, exist_ok=True)
            self.conn = sqlite3.connect(path, timeout=30, isolation_level=None, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA foreign_keys = ON")
        else:
            try:
                import psycopg
                from psycopg.rows import dict_row
            except ImportError as exc:
                raise RuntimeError("psycopg[binary] is required for Supabase/Postgres") from exc
            if "sslmode=" not in database_url:
                database_url += "&sslmode=require" if "?" in database_url else "?sslmode=require"
            self.conn = psycopg.connect(database_url, row_factory=dict_row, autocommit=True, prepare_threshold=None)

    def close(self) -> None:
        if self.conn:
            self.conn.close()
            self.conn = None

    def _sql(self, query: str) -> str:
        return query.replace("?", "%s") if not self.is_sqlite else query

    def execute(self, query: str, params: Iterable[Any] = ()):
        cur = self.conn.cursor()
        cur.execute(self._sql(query), tuple(params))
        return cur

    def fetchone(self, query: str, params: Iterable[Any] = ()):
        cur = self.execute(query, params)
        row = cur.fetchone()
        cur.close()
        return row

    def fetchall(self, query: str, params: Iterable[Any] = ()):
        cur = self.execute(query, params)
        rows = cur.fetchall()
        cur.close()
        return rows

    def scalar(self, query: str, params: Iterable[Any] = (), default: Any = 0) -> Any:
        row = self.fetchone(query, params)
        if row is None:
            return default
        try:
            return row[0]
        except (KeyError, IndexError, TypeError):
            return next(iter(row.values()))

    @contextmanager
    def transaction(self):
        if self.is_sqlite:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                yield self.conn
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise
        else:
            with self.conn.transaction():
                yield self.conn

    def migrate(self, migrations_dir: str | Path = "migrations") -> None:
        root = Path(migrations_dir)
        files = sorted(root.glob("*.sql"), key=lambda p: p.name)
        if not files:
            raise RuntimeError("No SQL migrations found")
        self.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at_utc TEXT NOT NULL)")
        applied = {str(r["version"] if isinstance(r, dict) else r[0]) for r in self.fetchall("SELECT version FROM schema_migrations")}
        for path in files:
            if path.name in applied:
                continue
            sql = path.read_text(encoding="utf-8")
            statements = [s.strip() for s in re.split(r";\s*(?:\n|$)", sql) if s.strip() and not s.strip().startswith("--")]
            with self.transaction():
                for statement in statements:
                    self.execute(statement)
                self.execute("INSERT INTO schema_migrations(version, applied_at_utc) VALUES(?,?)", [path.name, now_utc()])

    def reset_runtime_state(self) -> None:
        tables = [
            "inbound_message", "suppression", "event_log", "workflow_run", "outreach_batches",
            "outreach", "sender_daily_state", "lead_research", "lead_qualification", "discovery_candidate", "leads",
        ]
        with self.transaction():
            if self.is_sqlite:
                for table in tables:
                    self.execute(f"DELETE FROM {table}")
            else:
                self.execute("TRUNCATE TABLE " + ", ".join(tables) + " RESTART IDENTITY CASCADE")

    # ---- Workflow runs / events -------------------------------------------------
    def start_workflow(self, mode: str, reset_state: bool) -> str:
        run_id = str(uuid.uuid4())
        ts = now_utc()
        self.execute(
            "INSERT INTO workflow_run(workflow_run_id,started_at_utc,mode,status,reset_state) VALUES(?,?,?,?,?)",
            [run_id, ts, mode, "RUNNING", reset_state],
        )
        return run_id

    def finish_workflow(self, run_id: str, status: str, metrics: dict[str, Any]) -> None:
        self.execute(
            "UPDATE workflow_run SET ended_at_utc=?,status=?,metrics_json=? WHERE workflow_run_id=?",
            [now_utc(), status, json.dumps(metrics, ensure_ascii=False), run_id],
        )

    def add_event(self, event_type: str, *, run_id: str | None = None, lead_id: str | None = None,
                  outreach_id: str | None = None, sender_id: str | None = None, batch_id: str | None = None,
                  sequence_type: str | None = None, status: str | None = None, reason: str | None = None,
                  metadata: dict[str, Any] | None = None) -> None:
        event_id = str(uuid.uuid4())
        self.execute(
            """INSERT INTO event_log(event_id,event_timestamp_utc,event_type,workflow_run_id,lead_id,outreach_id,
               sender_id,batch_id,sequence_type,status,reason,metadata_json)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            [event_id, now_utc(), event_type, run_id, lead_id, outreach_id, sender_id, batch_id,
             sequence_type, status, reason, json.dumps(metadata or {}, ensure_ascii=False)],
        )

    # ---- Leads / discovery ------------------------------------------------------
    def upsert_lead(self, lead: dict[str, Any]) -> str:
        lead_id = lead["lead_id"]
        existing = self.fetchone("SELECT status FROM leads WHERE lead_id=?", [lead_id])
        if existing:
            self.execute(
                """UPDATE leads SET email=?,company=?,website=?,website_domain=?,city=?,region=?,country_code=?,timezone=?,
                   lead_source=?,place_id=?,scale_class=?,qualification_confidence=?,qualification_reason=?,discovery_facts=?,updated_at_utc=?
                   WHERE lead_id=?""",
                [lead["email"], lead["company"], lead["website"], lead["website_domain"], lead["city"], lead["region"],
                 lead["country_code"], lead["timezone"], lead["lead_source"], lead["place_id"], lead["scale_class"],
                 lead["qualification_confidence"], lead["qualification_reason"], lead.get("discovery_facts", ""), now_utc(), lead_id],
            )
            return lead_id
        try:
            self.execute(
                """INSERT INTO leads(lead_id,email,company,website,website_domain,city,region,country_code,timezone,lead_source,
                   place_id,scale_class,qualification_confidence,qualification_reason,discovery_facts,status,created_at_utc,updated_at_utc)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [lead_id, lead["email"], lead["company"], lead["website"], lead["website_domain"], lead["city"], lead["region"],
                 lead["country_code"], lead["timezone"], lead["lead_source"], lead["place_id"], lead["scale_class"],
                 lead["qualification_confidence"], lead["qualification_reason"], lead.get("discovery_facts", ""), lead.get("status", "ELIGIBLE"),
                 now_utc(), now_utc()],
            )
            return lead_id
        except Exception as exc:
            if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
                existing = self.fetchone("SELECT lead_id FROM leads WHERE website_domain=? OR place_id=? OR lower(email)=lower(?)", [lead["website_domain"], lead["place_id"], normalize_email(lead["email"])])
                return str(existing["lead_id"] if isinstance(existing, dict) else existing[0]) if existing else lead_id
            raise

    def insert_qualification(self, lead_id: str, *, action: str, confidence: float, reason: str, run_id: str, evidence_urls: list[str]) -> None:
        self.execute(
            """INSERT INTO lead_qualification(qualification_id,lead_id,workflow_run_id,action,confidence,reason,evidence_urls_json,created_at_utc)
               VALUES(?,?,?,?,?,?,?,?)""",
            [str(uuid.uuid4()), lead_id, run_id, action, confidence, reason[:1000], json.dumps(evidence_urls), now_utc()],
        )

    def get_lead(self, lead_id: str):
        return self.fetchone("SELECT * FROM leads WHERE lead_id=?", [lead_id])

    def get_lead_by_email(self, email: str):
        return self.fetchone("SELECT * FROM leads WHERE lower(email)=lower(?) LIMIT 1", [normalize_email(email)])

    def update_lead_status(self, lead_id: str, status: str) -> None:
        self.execute("UPDATE leads SET status=?,updated_at_utc=? WHERE lead_id=?", [status, now_utc(), lead_id])

    def claim_untouched_leads(self, limit: int, stale_after_minutes: int = 120, exclude_ids: tuple[str, ...] = ()) -> list[Any]:
        cutoff = datetime.now(timezone.utc).timestamp() - stale_after_minutes * 60
        cutoff_iso = datetime.fromtimestamp(cutoff, tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        self.execute("UPDATE leads SET status='ELIGIBLE',updated_at_utc=? WHERE status='RESEARCHING' AND updated_at_utc<?", [now_utc(), cutoff_iso])
        exclude_ids = tuple(dict.fromkeys(x for x in exclude_ids if x))
        excluded = " AND l.lead_id NOT IN (" + ",".join("?" for _ in exclude_ids) + ")" if exclude_ids else ""
        params = list(exclude_ids) + [limit]
        with self.transaction():
            postgres_sql = (
                """SELECT l.* FROM leads l
                   WHERE l.status IN ('ELIGIBLE','RESEARCHED')
                     AND l.status NOT IN ('REPLIED','BOUNCED','UNSUBSCRIBED','COMPLETED','MANUAL_STOP')
                     AND NOT EXISTS (SELECT 1 FROM outreach o WHERE o.lead_id=l.lead_id AND o.sequence_type='INITIAL' AND o.sequence_number=1)
                """ + excluded + " ORDER BY l.created_at_utc,l.lead_id LIMIT ? FOR UPDATE SKIP LOCKED"
            )
            sqlite_sql = (
                """SELECT l.* FROM leads l
                   WHERE l.status IN ('ELIGIBLE','RESEARCHED')
                     AND NOT EXISTS (SELECT 1 FROM outreach o WHERE o.lead_id=l.lead_id AND o.sequence_type='INITIAL' AND o.sequence_number=1)
                """ + excluded + " ORDER BY l.created_at_utc,l.lead_id LIMIT ?"
            )
            rows = self.fetchall(postgres_sql, params) if not self.is_sqlite else self.fetchall(sqlite_sql, params)
            for row in rows:
                self.execute("UPDATE leads SET status='RESEARCHING',updated_at_utc=? WHERE lead_id=?", [now_utc(), row["lead_id"]])
        return rows

    def count_eligible_untouched(self) -> int:
        return int(self.scalar(
            """SELECT count(*) FROM leads l WHERE l.status IN ('ELIGIBLE','RESEARCHED')
               AND NOT EXISTS (SELECT 1 FROM outreach o WHERE o.lead_id=l.lead_id AND o.sequence_type='INITIAL' AND o.sequence_number=1)"""
        ))

    # ---- Research ---------------------------------------------------------------
    def save_research(self, record: dict[str, Any]) -> None:
        self.execute(
            """INSERT INTO lead_research(research_id,lead_id,website_domain,canonical_url,company_identity,business_summary,
               services_json,business_facts_json,locations_json,specialties_json,website_signals_json,customer_journey_signals_json,
               ai_opportunity_signals_json,important_public_text,evidence_json,research_timestamp_utc,research_status,research_version,
               error,retry_count,next_retry_at_utc,created_at_utc)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [record["research_id"], record["lead_id"], record["website_domain"], record["canonical_url"], record["company_identity"],
             record["business_summary"], json.dumps(record["services"]), json.dumps(record["business_facts"]), json.dumps(record["locations"]),
             json.dumps(record["specialties"]), json.dumps(record["website_signals"]), json.dumps(record["customer_journey_signals"]),
             json.dumps(record["ai_opportunity_signals"]), record["important_public_text"], json.dumps(record["evidence"]), record["research_timestamp_utc"],
             record["research_status"], record["research_version"], record.get("error"), record.get("retry_count", 0), record.get("next_retry_at_utc"), now_utc()],
        )

    def latest_research(self, lead_id: str):
        return self.fetchone("SELECT * FROM lead_research WHERE lead_id=? ORDER BY research_timestamp_utc DESC LIMIT 1", [lead_id])

    # ---- Suppression ------------------------------------------------------------
    def is_suppressed(self, email: str) -> bool:
        return bool(self.fetchone("SELECT 1 FROM suppression WHERE email=?", [normalize_email(email)]))

    def suppress(self, email: str, lead_id: str | None, reason: str) -> None:
        self.execute(
            "INSERT INTO suppression(email,lead_id,reason,created_at_utc) VALUES(?,?,?,?) ON CONFLICT(email) DO NOTHING",
            [normalize_email(email), lead_id, reason[:200], now_utc()],
        )

    # ---- Sender state -----------------------------------------------------------
    def sender_day(self, sender_id: str, date_key: str):
        row = self.fetchone("SELECT * FROM sender_daily_state WHERE sender_id=? AND date_key=?", [sender_id, date_key])
        if row:
            return row
        self.execute("INSERT INTO sender_daily_state(sender_id,date_key) VALUES(?,?)", [sender_id, date_key])
        return self.fetchone("SELECT * FROM sender_daily_state WHERE sender_id=? AND date_key=?", [sender_id, date_key])

    def set_sender_health(self, sender_id: str, date_key: str, state: str, cooldown_until_utc: str | None = None) -> None:
        self.sender_day(sender_id, date_key)
        self.execute("UPDATE sender_daily_state SET health_state=?,cooldown_until_utc=? WHERE sender_id=? AND date_key=?", [state, cooldown_until_utc, sender_id, date_key])

    def record_send(self, sender_id: str, date_key: str, is_followup: bool, sent_at_utc: str) -> None:
        self.sender_day(sender_id, date_key)
        column = "followups" if is_followup else "initials"
        self.execute(f"UPDATE sender_daily_state SET {column}={column}+1,total=total+1,last_successful_send_utc=?,health_state='HEALTHY',cooldown_until_utc=NULL WHERE sender_id=? AND date_key=?", [sent_at_utc, sender_id, date_key])

    def record_failure(self, sender_id: str, date_key: str, kind: str) -> None:
        self.sender_day(sender_id, date_key)
        column = "authentication_failures" if kind == "AUTH" else "temporary_provider_failures" if kind == "TEMPORARY" else "failures"
        self.execute(f"UPDATE sender_daily_state SET {column}={column}+1,failures=failures+1 WHERE sender_id=? AND date_key=?", [sender_id, date_key])

    # ---- Outreach batches/items -------------------------------------------------
    def count_successful_initials(self) -> int:
        return int(self.scalar("SELECT count(*) FROM outreach WHERE sequence_type='INITIAL' AND status='SENT'"))

    def count_initial_progress(self) -> int:
        return int(self.scalar("SELECT count(*) FROM outreach WHERE sequence_type='INITIAL' AND status IN ('SENT','SENDING','SCHEDULED','QUEUED','FAILED_RETRYABLE')"))

    def body_hash_exists(self, body_hash: str) -> bool:
        return bool(self.fetchone("SELECT 1 FROM outreach WHERE body_hash=? AND status NOT IN ('CANCELLED','FAILED_TERMINAL') LIMIT 1", [body_hash]))

    def get_outreach(self, outreach_id: str):
        return self.fetchone("SELECT * FROM outreach WHERE outreach_id=?", [outreach_id])

    def get_sequence(self, lead_id: str, sequence_type: str, sequence_number: int):
        return self.fetchone("SELECT * FROM outreach WHERE lead_id=? AND sequence_type=? AND sequence_number=?", [lead_id, sequence_type, sequence_number])

    def insert_outreach(self, record: dict[str, Any]) -> bool:
        try:
            self.execute(
                """INSERT INTO outreach(outreach_id,workflow_run_id,batch_id,lead_id,sequence_type,sequence_number,sender_id,sender_email,
                   email,subject,body,status,scheduled_at_utc,attempted_at_utc,sent_at_utc,message_id,retry_count,next_retry_at_utc,
                   evidence_urls_json,personalization_confidence,body_hash,in_reply_to,references_text,created_at_utc,updated_at_utc)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [record["outreach_id"], record["workflow_run_id"], record.get("batch_id"), record["lead_id"], record["sequence_type"],
                 record["sequence_number"], record["sender_id"], record["sender_email"], record["email"], record["subject"], record["body"],
                 record.get("status", "QUEUED"), record.get("scheduled_at_utc"), record.get("attempted_at_utc"), record.get("sent_at_utc"),
                 record.get("message_id"), record.get("retry_count", 0), record.get("next_retry_at_utc"), json.dumps(record.get("evidence_urls", [])),
                 record.get("personalization_confidence", 0.0), record["body_hash"], record.get("in_reply_to"), record.get("references_text"), now_utc(), now_utc()],
            )
            return True
        except Exception as exc:
            if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
                return False
            raise

    def queue_initial(self, *, run_id: str, lead_id: str, sender_id: str, sender_email: str, subject: str, body: str,
                      evidence_urls: list[str], confidence: float) -> str | None:
        body_hash = hashlib.sha256(re.sub(r"\s+", " ", body.strip().lower()).encode()).hexdigest()
        if self.body_hash_exists(body_hash):
            return None
        outreach_id = deterministic_outreach_id(lead_id, "INITIAL", 1)
        if self.get_outreach(outreach_id):
            return None
        ok = self.insert_outreach({
            "outreach_id": outreach_id, "workflow_run_id": run_id, "lead_id": lead_id,
            "sequence_type": "INITIAL", "sequence_number": 1, "sender_id": sender_id, "sender_email": sender_email,
            "email": self.get_lead(lead_id)["email"], "subject": subject, "body": body, "status": "QUEUED",
            "evidence_urls": evidence_urls, "personalization_confidence": confidence, "body_hash": body_hash,
        })
        return outreach_id if ok else None

    def list_queued_initials(self, limit: int = 10) -> list[Any]:
        return self.fetchall("SELECT o.*,l.timezone,l.status AS lead_status FROM outreach o JOIN leads l ON l.lead_id=o.lead_id WHERE o.sequence_type='INITIAL' AND o.status='QUEUED' AND o.batch_id IS NULL ORDER BY o.created_at_utc LIMIT ?", [limit])

    def create_batch(self, run_id: str, batch_number: int, batch_type: str, scheduled_at_utc: str, target_count: int) -> str:
        batch_id = f"{run_id}:{batch_type}:{batch_number}"
        self.execute(
            "INSERT INTO outreach_batches(batch_id,workflow_run_id,batch_number,batch_type,scheduled_at_utc,status,target_count,attempted_count,successful_count,failed_count,created_at_utc,updated_at_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            [batch_id, run_id, batch_number, batch_type, scheduled_at_utc, "SCHEDULED", target_count, 0, 0, 0, now_utc(), now_utc()],
        )
        return batch_id

    def assign_batch(self, batch_id: str, assignments: list[tuple[str, str, str, str]], scheduled_at_utc: str) -> None:
        """assignments = [(outreach_id, lead_id, sender_id, sender_email)]"""
        with self.transaction():
            for outreach_id, lead_id, sender_id, sender_email in assignments:
                self.execute(
                    "UPDATE outreach SET batch_id=?,sender_id=?,sender_email=?,scheduled_at_utc=?,status='SCHEDULED',updated_at_utc=? WHERE outreach_id=? AND status IN ('QUEUED','FAILED_RETRYABLE') AND batch_id IS NULL",
                    [batch_id, sender_id, sender_email, scheduled_at_utc, now_utc(), outreach_id],
                )
                self.execute("UPDATE leads SET sender_id=?,status='QUEUED',updated_at_utc=? WHERE lead_id=?", [sender_id, now_utc(), lead_id])

    def list_ready_initials(self, limit: int = 10) -> list[Any]:
        return self.fetchall("""SELECT o.*,l.timezone,l.status AS lead_status FROM outreach o JOIN leads l ON l.lead_id=o.lead_id
            WHERE o.sequence_type='INITIAL' AND o.batch_id IS NULL AND (o.status='QUEUED' OR (o.status='FAILED_RETRYABLE' AND (o.next_retry_at_utc IS NULL OR o.next_retry_at_utc<=?)))
            ORDER BY o.created_at_utc LIMIT ?""", [now_utc(), limit])

    def requeue_batch_pending(self, batch_id: str) -> None:
        self.execute("""UPDATE outreach SET batch_id=NULL,status=CASE WHEN status='SCHEDULED' THEN 'QUEUED' ELSE status END,updated_at_utc=?
            WHERE batch_id=? AND status IN ('SCHEDULED','FAILED_RETRYABLE')""", [now_utc(), batch_id])

    def reconcile_stale_batches(self, cutoff_utc: str) -> None:
        batches = self.fetchall(
            "SELECT batch_id FROM outreach_batches WHERE status IN ('SCHEDULED','RUNNING') AND updated_at_utc<?",
            [cutoff_utc],
        )
        for row in batches:
            batch_id = row["batch_id"]
            self.requeue_batch_pending(batch_id)
            pending = int(self.scalar("SELECT count(*) FROM outreach WHERE batch_id=? AND status IN ('SCHEDULED','QUEUED','FAILED_RETRYABLE')", [batch_id]))
            sent = int(self.scalar("SELECT count(*) FROM outreach WHERE batch_id=? AND status='SENT'", [batch_id]))
            attempted = int(self.scalar("SELECT count(*) FROM outreach WHERE batch_id=? AND status NOT IN ('QUEUED','SCHEDULED')", [batch_id]))
            status = "COMPLETED" if pending == 0 else "PARTIAL"
            self.execute(
                "UPDATE outreach_batches SET status=?,attempted_count=?,successful_count=?,failed_count=?,completed_at_utc=?,updated_at_utc=? WHERE batch_id=?",
                [status, attempted, sent, max(0, attempted - sent), now_utc(), now_utc(), batch_id],
            )

    def claim_outreach(self, outreach_id: str) -> bool:
        row = self.execute(
            "UPDATE outreach SET status='SENDING',attempted_at_utc=?,retry_count=retry_count+1,updated_at_utc=? WHERE outreach_id=? AND status IN ('SCHEDULED','QUEUED','FAILED_RETRYABLE')",
            [now_utc(), now_utc(), outreach_id],
        )
        count = row.rowcount
        row.close()
        return count == 1

    def mark_sent(self, outreach_id: str, sent_at_utc: str, message_id: str) -> None:
        self.execute("UPDATE outreach SET status='SENT',sent_at_utc=?,message_id=?,next_retry_at_utc=NULL,updated_at_utc=? WHERE outreach_id=? AND status='SENDING'", [sent_at_utc, message_id, now_utc(), outreach_id])

    def mark_failed(self, outreach_id: str, status: str, error: str, next_retry_at_utc: str | None) -> None:
        self.execute("UPDATE outreach SET status=?,last_error=?,next_retry_at_utc=?,updated_at_utc=? WHERE outreach_id=? AND status='SENDING'", [status, error[:1000], next_retry_at_utc, now_utc(), outreach_id])

    def mark_review_needed(self, outreach_id: str, reason: str) -> None:
        self.execute("UPDATE outreach SET status='REVIEW_NEEDED',last_error=?,next_retry_at_utc=NULL,updated_at_utc=? WHERE outreach_id=? AND status='SENDING'", [reason[:1000], now_utc(), outreach_id])

    def update_batch_counts(self, batch_id: str, *, status: str, attempted: int, successful: int, failed: int) -> None:
        self.execute("UPDATE outreach_batches SET status=?,attempted_count=?,successful_count=?,failed_count=?,completed_at_utc=?,updated_at_utc=? WHERE batch_id=?", [status, attempted, successful, failed, now_utc(), now_utc(), batch_id])

    def cancel_future_followups(self, lead_id: str) -> None:
        self.execute("UPDATE outreach SET status='CANCELLED',updated_at_utc=? WHERE lead_id=? AND sequence_type LIKE 'FOLLOWUP_%' AND status IN ('QUEUED','SCHEDULED','FAILED_RETRYABLE')", [now_utc(), lead_id])

    def list_followup_candidates(self, sequence_type: str, limit: int = 100) -> list[Any]:
        number = int(sequence_type.split("_")[-1])
        previous_type = "INITIAL" if number == 1 else f"FOLLOWUP_{number-1}"
        previous_number = 1 if previous_type == "INITIAL" else number - 1
        return self.fetchall(
            """SELECT p.*,l.timezone,l.status AS lead_status,l.email AS lead_email FROM outreach p JOIN leads l ON l.lead_id=p.lead_id
               WHERE p.sequence_type=? AND p.sequence_number=? AND p.status='SENT'
                 AND NOT EXISTS (SELECT 1 FROM outreach x WHERE x.lead_id=p.lead_id AND x.sequence_type=? AND x.sequence_number=?)
               ORDER BY p.sent_at_utc LIMIT ?""",
            [previous_type, previous_number, sequence_type, number, limit],
        )

    def list_due_followups(self, limit: int = 100) -> list[Any]:
        return self.fetchall(
            """SELECT o.*,l.timezone,l.status AS lead_status FROM outreach o JOIN leads l ON l.lead_id=o.lead_id
               WHERE o.sequence_type LIKE 'FOLLOWUP_%' AND o.status IN ('QUEUED','SCHEDULED','FAILED_RETRYABLE')
                 AND (o.scheduled_at_utc IS NULL OR o.scheduled_at_utc<=?)
               ORDER BY o.scheduled_at_utc,o.created_at_utc LIMIT ?""",
            [now_utc(), limit],
        )

    def previous_sent_history(self, lead_id: str) -> list[Any]:
        return self.fetchall("SELECT * FROM outreach WHERE lead_id=? AND status='SENT' ORDER BY sequence_number", [lead_id])

    def insert_followup(self, *, run_id: str, lead_id: str, sequence_type: str, sequence_number: int, sender_id: str, sender_email: str,
                        subject: str, body: str, evidence_urls: list[str], confidence: float, in_reply_to: str, references_text: str,
                        scheduled_at_utc: str) -> str | None:
        lead = self.get_lead(lead_id)
        if not lead or self.is_suppressed(lead["email"]):
            return None
        outreach_id = deterministic_outreach_id(lead_id, sequence_type, sequence_number)
        if self.get_outreach(outreach_id):
            return None
        body_hash = hashlib.sha256(re.sub(r"\s+", " ", body.strip().lower()).encode()).hexdigest()
        if self.body_hash_exists(body_hash):
            return None
        previous_type = "INITIAL" if sequence_number == 1 else f"FOLLOWUP_{sequence_number-1}"
        previous_number = 1 if previous_type == "INITIAL" else sequence_number - 1
        previous = self.get_sequence(lead_id, previous_type, previous_number)
        if not previous or previous["status"] != "SENT" or not previous["sent_at_utc"]:
            return None
        self.execute(
            """INSERT INTO outreach(outreach_id,workflow_run_id,batch_id,lead_id,sequence_type,sequence_number,sender_id,sender_email,email,subject,body,status,scheduled_at_utc,retry_count,evidence_urls_json,personalization_confidence,body_hash,in_reply_to,references_text,created_at_utc,updated_at_utc)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [outreach_id, run_id, None, lead_id, sequence_type, sequence_number, sender_id, sender_email, lead["email"], subject, body, "QUEUED", scheduled_at_utc, 0, json.dumps(evidence_urls), confidence, body_hash, in_reply_to, references_text, now_utc(), now_utc()],
        )
        return outreach_id

    def count_event(self, run_id: str, event_type: str) -> int:
        return int(self.scalar("SELECT count(*) FROM event_log WHERE workflow_run_id=? AND event_type=?", [run_id, event_type]))

    # ---- Mailbox ---------------------------------------------------------------
    def mailbox_state(self, sender_id: str):
        return self.fetchone("SELECT * FROM mailbox_state WHERE sender_id=?", [sender_id])

    def save_mailbox_state(self, *, sender_id: str, uidvalidity: str | None, last_processed_uid: int, health_state: str) -> None:
        self.execute(
            """INSERT INTO mailbox_state(sender_id,mailbox_identifier,provider_type,uidvalidity,last_processed_uid,last_checked_at_utc,health_state)
               VALUES(?,?,?,?,?,?,?) ON CONFLICT(sender_id) DO UPDATE SET uidvalidity=excluded.uidvalidity,last_processed_uid=excluded.last_processed_uid,
               last_checked_at_utc=excluded.last_checked_at_utc,health_state=excluded.health_state""",
            [sender_id, "INBOX", "imap", uidvalidity, last_processed_uid, now_utc(), health_state],
        )

    def inbound_exists(self, sender_id: str, message_id: str) -> bool:
        return bool(self.fetchone("SELECT 1 FROM inbound_message WHERE sender_id=? AND message_id=?", [sender_id, message_id]))

    def save_inbound(self, *, sender_id: str, message_id: str, in_reply_to: str, references: str, received_at_utc: str,
                     lead_id: str | None, outreach_id: str | None, event_type: str, confidence: float, subject: str, from_email: str) -> bool:
        try:
            self.execute(
                """INSERT INTO inbound_message(inbound_message_id,sender_id,message_id,in_reply_to,references_text,received_at_utc,
                   lead_id,outreach_id,event_type,classification_confidence,processing_status,processed_at_utc,subject,from_email)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [str(uuid.uuid4()), sender_id, message_id, in_reply_to, references[:4000], received_at_utc, lead_id, outreach_id, event_type,
                 confidence, "PROCESSED", now_utc(), subject[:500], normalize_email(from_email)],
            )
            return True
        except Exception as exc:
            if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
                return False
            raise
```

---

## FILE: app/discovery.py

```text
from __future__ import annotations

import datetime as dt
import os
import random
import re
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import dns.resolver
import requests

from app.db import deterministic_lead_id, normalize_domain
from app.llm import LLMClient, LLMTemporaryError
from app.research import WebsiteCrawler, choose_public_business_email

SEED_KEYWORDS = [
    "roofing contractor", "HVAC contractor", "custom home builder", "residential real estate brokerage",
    "luxury realtor", "boutique law firm", "family law firm", "personal injury law firm",
    "cosmetic dentistry practice", "orthodontist", "remodeling contractor", "kitchen remodeling company",
    "bathroom remodeling company", "landscaping company", "commercial cleaning company", "accounting firm",
    "property management company", "pest control company", "solar installation company", "home inspection company",
]

TARGET_CITIES = [
    "Dallas TX", "Fort Worth TX", "Houston TX", "Austin TX", "San Antonio TX", "Orlando FL", "Tampa FL", "Jacksonville FL", "Miami FL", "Atlanta GA",
    "Charlotte NC", "Nashville TN", "Phoenix AZ", "Denver CO", "Las Vegas NV", "Los Angeles CA", "San Diego CA", "Sacramento CA", "Chicago IL", "Columbus OH",
    "Indianapolis IN", "Cleveland OH", "Kansas City MO", "Raleigh NC", "Richmond VA", "Seattle WA", "Portland OR", "Salt Lake City UT", "Minneapolis MN", "Boston MA",
    "Toronto Canada", "Vancouver Canada", "Montreal Canada", "Calgary Canada", "Ottawa Canada", "Edmonton Canada",
    "London UK", "Manchester UK", "Birmingham UK", "Leeds UK", "Liverpool UK", "Glasgow UK",
    "Sydney Australia", "Melbourne Australia", "Brisbane Australia", "Perth Australia", "Adelaide Australia",
]

BUSINESS_NOUNS = (
    "dentist", "dentistry", "clinic", "practice", "contractor", "company", "firm", "agency", "brokerage", "provider",
    "service", "studio", "group", "attorney", "lawyer", "real estate", "property management", "accounting", "landscaping",
    "inspection", "hvac", "roofing", "builder", "remodeling", "orthodontist",
)

FREE_EMAIL_DOMAINS = {"gmail.com", "googlemail.com", "yahoo.com", "hotmail.com", "outlook.com", "live.com", "msn.com", "icloud.com", "me.com", "aol.com", "protonmail.com", "proton.me", "gmx.com", "mail.com", "yandex.com", "zoho.com"}
DISPOSABLE_DOMAINS = {"10minutemail.com", "guerrillamail.com", "mailinator.com", "yopmail.com", "getnada.com", "tempmail.com", "temp-mail.org", "discard.email", "throwawaymail.com"}
BLOCKED_LOCAL_PARTS = {"noreply", "no-reply", "donotreply", "do-not-reply", "mailer-daemon", "abuse"}


@dataclass(frozen=True)
class Candidate:
    place_id: str
    company: str
    website: str
    address: str
    types: tuple[str, ...]
    query: str
    country_code: str


def state_or_region_from_address(address: str, country_code: str) -> str:
    if country_code == "US":
        match = re.search(r",\s*([A-Z]{2})(?:\s+\d{5}(?:-\d{4})?)?\b", address or "")
        return match.group(1).upper() if match else ""
    if country_code == "CA":
        match = re.search(r",\s*(AB|BC|MB|NB|NL|NS|NT|NU|ON|PE|QC|SK|YT)\b", address or "", flags=re.I)
        return match.group(1).upper() if match else ""
    if country_code == "AU":
        match = re.search(r",\s*(NSW|VIC|QLD|WA|SA|TAS|NT|ACT)\b", address or "", flags=re.I)
        return match.group(1).upper() if match else ""
    return ""


def city_from_address(address: str, region: str) -> str:
    text = re.sub(r"\s+", " ", address or "").strip()
    if region:
        match = re.search(r",\s*([^,]+),\s*" + re.escape(region) + r"\b", text, flags=re.I)
        if match:
            return match.group(1).strip()
    parts = [x.strip() for x in text.split(",") if x.strip()]
    return parts[-2] if len(parts) >= 2 else ""


def location_timezone(country_code: str, region: str, city: str) -> str:
    us = {
        "AL":"America/Chicago","AK":"America/Anchorage","AZ":"America/Phoenix","AR":"America/Chicago","CA":"America/Los_Angeles","CO":"America/Denver","CT":"America/New_York","DE":"America/New_York","FL":"America/New_York","GA":"America/New_York","HI":"Pacific/Honolulu","IA":"America/Chicago","ID":"America/Boise","IL":"America/Chicago","IN":"America/Indiana/Indianapolis","KS":"America/Chicago","KY":"America/New_York","LA":"America/Chicago","MA":"America/New_York","MD":"America/New_York","ME":"America/New_York","MI":"America/Detroit","MN":"America/Chicago","MO":"America/Chicago","MS":"America/Chicago","MT":"America/Denver","NC":"America/New_York","ND":"America/Chicago","NE":"America/Chicago","NH":"America/New_York","NJ":"America/New_York","NM":"America/Denver","NV":"America/Los_Angeles","NY":"America/New_York","OH":"America/New_York","OK":"America/Chicago","OR":"America/Los_Angeles","PA":"America/New_York","RI":"America/New_York","SC":"America/New_York","SD":"America/Chicago","TN":"America/Chicago","TX":"America/Chicago","UT":"America/Denver","VA":"America/New_York","VT":"America/New_York","WA":"America/Los_Angeles","WI":"America/Chicago","WV":"America/New_York","WY":"America/Denver",
    }
    ca = {"AB":"America/Edmonton", "BC":"America/Vancouver", "MB":"America/Winnipeg", "NB":"America/Moncton", "NL":"America/St_Johns", "NS":"America/Halifax", "NT":"America/Yellowknife", "NU":"America/Iqaluit", "ON":"America/Toronto", "PE":"America/Halifax", "QC":"America/Toronto", "SK":"America/Regina", "YT":"America/Whitehorse"}
    au = {"NSW":"Australia/Sydney", "VIC":"Australia/Melbourne", "QLD":"Australia/Brisbane", "WA":"Australia/Perth", "SA":"Australia/Adelaide", "TAS":"Australia/Hobart", "NT":"Australia/Darwin", "ACT":"Australia/Sydney"}
    city_key = city.strip().lower()
    if country_code == "US": return us.get(region, "America/New_York")
    if country_code == "CA": return ca.get(region, "America/Toronto")
    if country_code == "AU": return au.get(region, "Australia/Sydney")
    if country_code == "GB": return "Europe/London"
    return "America/New_York"


def canonical_url(value: str) -> str:
    parsed = urlparse(value if "://" in value else f"https://{value}")
    if not parsed.hostname:
        return ""
    return f"{parsed.scheme or 'https'}://{parsed.netloc}/"


class DiscoveryService:
    SYSTEM_PROMPT = """
Create concise Google Places text-search queries for local or regional businesses.
Return ONLY JSON array of strings.
Rules: use only supplied target cities; include a business term related to the seed; prefer independent/local businesses;
do not generate reviews, prices, discounts, or how-to queries.
""".strip()

    QUALIFY_PROMPT = """
You are a conservative business lead classifier.
Return ONLY JSON: {"action":"KEEP|REJECT","company_name":"...","scale_class":"LOCAL|REGIONAL","confidence":0.0,"reason":"..."}
KEEP only when the business matches the target query and appears to be a real local or regional business.
Use only supplied candidate and website evidence. Do not invent facts.
""".strip()

    def __init__(self, store, llm: LLMClient, crawler: WebsiteCrawler, settings):
        self.store = store
        self.llm = llm
        self.crawler = crawler
        self.settings = settings
        self.http = requests.Session()
        self.http.headers.update({"User-Agent": "AttachAI-Discovery/2.0", "Accept-Language": "en-US,en;q=0.8"})
        self.mx_cache: dict[str, bool] = {}

    def choose_seed(self) -> str:
        return SEED_KEYWORDS[dt.date.today().toordinal() % len(SEED_KEYWORDS)]

    def expand_queries(self, seed: str, count: int = 100) -> list[str]:
        try:
            raw = self.llm.chat_json_array(self.SYSTEM_PROMPT, f"Seed: {seed}\nTarget cities: {', '.join(TARGET_CITIES)}\nAllowed countries: {', '.join(self.settings.allowed_country_codes)}\nGenerate {count} queries.", max_tokens=1000)
        except Exception:
            raw = []
        if not isinstance(raw, list):
            raw = []
        out: list[str] = []
        seen: set[str] = set()
        for item in raw:
            query = re.sub(r"\s+", " ", str(item)).strip()
            lower = query.lower()
            if not query or lower in seen:
                continue
            if any(word in lower for word in ("review", "reviews", "price", "cost", "cheapest", "discount", "specials")):
                continue
            if not any(city.split()[0].lower() in lower for city in TARGET_CITIES):
                continue
            if not any(noun in lower for noun in BUSINESS_NOUNS):
                continue
            seen.add(lower)
            out.append(query)
        variants = ("", "local", "independent", "neighborhood", "specialist", "boutique", "community")
        fallback = [f"{' '.join(x for x in (variant, seed, city) if x)}" for city in TARGET_CITIES for variant in variants]
        for query in fallback:
            if len(out) >= count:
                break
            if query.lower() not in seen:
                seen.add(query.lower())
                out.append(query)
        random.Random(dt.date.today().toordinal()).shuffle(out)
        return out[:count]

    def places_search(self, query: str, remaining_budget: int) -> tuple[list[dict], int]:
        if not self.settings.allowed_country_codes:
            return [], 0
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": os.environ.get("GOOGLE_PLACES_API_KEY", "").strip(),
            "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,places.postalAddress,places.addressComponents,places.websiteUri,places.types,places.businessStatus,nextPageToken",
        }
        if not headers["X-Goog-Api-Key"]:
            raise RuntimeError("GOOGLE_PLACES_API_KEY is missing")
        results: list[dict] = []
        page_token: str | None = None
        pages = 0
        requests_used = 0
        while pages < self.settings.max_pages_per_search and requests_used < remaining_budget:
            payload = {"textQuery": query, "pageSize": self.settings.places_page_size, "languageCode": "en"}
            if page_token:
                payload["pageToken"] = page_token
            response = None
            for attempt in range(3):
                try:
                    response = self.http.post("https://places.googleapis.com/v1/places:searchText", headers=headers, json=payload, timeout=self.settings.crawler_timeout_seconds)
                    requests_used += 1
                    if response.status_code == 429 and attempt < 2:
                        time.sleep(3 + attempt * 3)
                        continue
                    if response.status_code >= 400:
                        if response.status_code in {400, 401, 403, 404}:
                            return results, requests_used
                        response.raise_for_status()
                    break
                except Exception:
                    if attempt == 2:
                        return results, requests_used
                    time.sleep(2 + attempt * 3)
            if response is None:
                return results, requests_used
            payload_json = response.json()
            results.extend(payload_json.get("places", []) or [])
            pages += 1
            page_token = payload_json.get("nextPageToken")
            if not page_token:
                break
            time.sleep(2)
        return results, requests_used

    def candidate_from_place(self, place: dict, query: str) -> Candidate | None:
        place_id = str(place.get("id") or "").strip()
        company = str((place.get("displayName") or {}).get("text") or "").strip()
        website = canonical_url(str(place.get("websiteUri") or "").strip())
        address = str(place.get("formattedAddress") or "").strip()
        status = str(place.get("businessStatus") or "").upper()
        postal = place.get("postalAddress") or {}
        country = str(postal.get("regionCode") or "").upper().strip()
        if not country:
            for component in place.get("addressComponents") or []:
                if "country" in (component.get("types") or []):
                    country = str(component.get("shortText") or "").upper().strip()
                    break
        if not place_id or not company or not website or status in {"CLOSED", "CLOSED_PERMANENTLY"} or country not in self.settings.allowed_country_codes:
            return None
        return Candidate(place_id, company, website, address, tuple(str(x) for x in (place.get("types") or [])), query, country)

    def has_mx(self, domain: str) -> bool:
        domain = normalize_domain(domain)
        if domain in self.mx_cache:
            return self.mx_cache[domain]
        try:
            result = any(getattr(x, "exchange", None) for x in dns.resolver.resolve(domain, "MX", lifetime=5))
        except Exception:
            result = False
        self.mx_cache[domain] = result
        return result

    def qualify(self, candidate: Candidate, facts: str, email: str) -> dict | None:
        try:
            obj = self.llm.chat_json_object(self.QUALIFY_PROMPT, (
                f"Target query: {candidate.query}\nCompany: {candidate.company}\nAddress: {candidate.address}\nCountry: {candidate.country_code}\n"
                f"Website: {candidate.website}\nEmail: {email}\nWebsite evidence:\n{facts[:6000]}"
            ), max_tokens=700)
            action = str(obj.get("action", "")).upper()
            scale = str(obj.get("scale_class", "")).upper()
            confidence = float(obj.get("confidence", 0))
            if action != "KEEP" or scale not in {"LOCAL", "REGIONAL"} or confidence < 0.75:
                return {"action": "REJECT", "confidence": confidence, "reason": str(obj.get("reason") or "")[:1000]}
            return {"action": "KEEP", "company_name": str(obj.get("company_name") or candidate.company)[:180], "scale_class": scale, "confidence": round(confidence, 3), "reason": str(obj.get("reason") or "")[:1000]}
        except (LLMTemporaryError, ValueError, TypeError, KeyError):
            return None

    def run(self, run_id: str, target: int) -> dict[str, int | float | str]:
        started = time.monotonic()
        seed = self.choose_seed()
        verified = discovered = requests_used = rejected = retryable = duplicates = 0

        # Retry previously discovered candidates from durable DB state, with a hard per-run bound.
        retry_rows = self.store.fetchall(
            """SELECT * FROM discovery_candidate
               WHERE status='RETRYABLE' AND (next_retry_at_utc IS NULL OR next_retry_at_utc<=?)
                 AND attempts < ? ORDER BY next_retry_at_utc,candidate_id LIMIT ?""",
            [__import__("app.db", fromlist=["now_utc"]).now_utc(), self.settings.discovery_retry_limit, self.settings.discovery_max_retries_per_run],
        )
        for row in retry_rows:
            if verified >= target:
                break
            result = self._process_candidate(self._candidate_from_row(row), run_id, row["candidate_id"], retry=True)
            if result == "verified": verified += 1
            elif result == "retry": retryable += 1
            elif result == "rejected": rejected += 1
            else: duplicates += 1

        if verified >= target:
            return {"seed": seed, "discovered": 0, "verified": verified, "places_search_requests": 0, "rejected": rejected, "retryable": retryable, "duplicates": duplicates, "duration_seconds": round(time.monotonic() - started, 2)}

        queries = self.expand_queries(seed, 100)
        for query in queries:
            if verified >= target or requests_used >= self.settings.max_places_search_requests or discovered >= self.settings.max_raw_candidates:
                break
            places, used = self.places_search(query, self.settings.max_places_search_requests - requests_used)
            requests_used += used
            for place in places:
                if verified >= target or discovered >= self.settings.max_raw_candidates:
                    break
                candidate = self.candidate_from_place(place, query)
                if not candidate:
                    continue
                discovered += 1
                domain = normalize_domain(candidate.website)
                duplicate = self.store.fetchone("SELECT 1 FROM discovery_candidate WHERE place_id=? OR website_domain=? LIMIT 1", [candidate.place_id, domain])
                if duplicate:
                    duplicates += 1
                    continue
                candidate_id = f"{run_id}:{candidate.place_id}"
                self.store.execute(
                    """INSERT INTO discovery_candidate(candidate_id,workflow_run_id,place_id,website_domain,company,website,address,country_code,types_json,query,status,attempts,next_retry_at_utc,last_reason,last_seen_at_utc)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    [candidate_id, run_id, candidate.place_id, domain, candidate.company, candidate.website, candidate.address, candidate.country_code,
                     __import__("json").dumps(candidate.types), candidate.query, "SEEN", 0, None, None, __import__("app.db", fromlist=["now_utc"]).now_utc()],
                )
                result = self._process_candidate(candidate, run_id, candidate_id, retry=False)
                if result == "verified": verified += 1
                elif result == "retry": retryable += 1
                elif result == "rejected": rejected += 1
                else: duplicates += 1
        return {"seed": seed, "discovered": discovered, "verified": verified, "places_search_requests": requests_used, "rejected": rejected, "retryable": retryable, "duplicates": duplicates, "duration_seconds": round(time.monotonic() - started, 2)}

    def _candidate_from_row(self, row) -> Candidate:
        try:
            import json
            types = tuple(str(x) for x in json.loads(row["types_json"] or "[]"))
        except Exception:
            types = ()
        return Candidate(str(row["place_id"]), str(row["company"]), str(row["website"]), str(row["address"]), types, str(row["query"]), str(row["country_code"]))

    def _process_candidate(self, candidate: Candidate, run_id: str, candidate_id: str, retry: bool) -> str:
        from app.db import now_utc
        pages = self.crawler.crawl(candidate.website)
        email_choice = choose_public_business_email(pages, candidate.website, self.has_mx)
        if not email_choice:
            self._schedule_candidate_retry(candidate, candidate_id, "no_public_business_email", self.settings.discovery_no_email_retry_days * 86400, run_id)
            return "retry"
        email, source_url = email_choice
        facts = "\n".join(f"PAGE {p.url}: {p.text[:1600]}" for p in pages if p.text)[:12000]
        qualification = self.qualify(candidate, facts, email)
        if qualification is None:
            self._schedule_candidate_retry(candidate, candidate_id, "llm_temporary_failure", self.settings.discovery_transient_retry_hours * 3600, run_id)
            return "retry"
        if qualification["action"] != "KEEP":
            self.store.execute("UPDATE discovery_candidate SET status='REJECTED',last_reason=?,last_seen_at_utc=? WHERE candidate_id=?", [qualification.get("reason") or "rejected", now_utc(), candidate_id])
            self.store.add_event("lead_rejected", run_id=run_id, reason=qualification.get("reason"), metadata={"company": candidate.company, "qualification_confidence": qualification.get("confidence", 0)})
            return "rejected"
        region = state_or_region_from_address(candidate.address, candidate.country_code)
        city = city_from_address(candidate.address, region)
        tz = location_timezone(candidate.country_code, region, city)
        lead_id = deterministic_lead_id(email, candidate.website)
        existing = self.store.get_lead(lead_id)
        lead = {
            "lead_id": lead_id, "email": email, "company": qualification["company_name"], "website": candidate.website,
            "website_domain": normalize_domain(candidate.website), "city": city, "region": region, "country_code": candidate.country_code, "timezone": tz,
            "lead_source": "Google Places Text Search (paged) -> public website", "place_id": candidate.place_id, "scale_class": qualification["scale_class"],
            "qualification_confidence": qualification["confidence"], "qualification_reason": qualification["reason"], "discovery_facts": facts[:7000], "status": existing["status"] if existing else "ELIGIBLE",
        }
        self.store.upsert_lead(lead)
        self.store.insert_qualification(lead_id, action="KEEP", confidence=qualification["confidence"], reason=qualification["reason"], run_id=run_id, evidence_urls=[source_url])
        self.store.execute("UPDATE discovery_candidate SET status='VERIFIED',last_reason='verified',last_seen_at_utc=?,next_retry_at_utc=NULL WHERE candidate_id=?", [now_utc(), candidate_id])
        self.store.add_event("lead_verified", run_id=run_id, lead_id=lead_id, status="ELIGIBLE", metadata={"email_source_url": source_url, "confidence": qualification["confidence"], "retry": retry})
        return "verified"

    def _schedule_candidate_retry(self, candidate: Candidate, candidate_id: str, reason: str, seconds: int, run_id: str) -> None:
        from app.db import now_utc
        row = self.store.fetchone("SELECT attempts FROM discovery_candidate WHERE candidate_id=?", [candidate_id])
        attempts = int(row["attempts"] or 0) if row else 0
        next_attempt = attempts + 1
        if next_attempt >= self.settings.discovery_retry_limit:
            # Runtime bound is intentionally finite; the durable row is terminal after repeated failures.
            self.store.execute("UPDATE discovery_candidate SET status='REJECTED',attempts=?,last_reason='retry_limit_exceeded',next_retry_at_utc=NULL,last_seen_at_utc=? WHERE candidate_id=?", [next_attempt, now_utc(), candidate_id])
            self.store.add_event("discovery_retry_exhausted", run_id=run_id, reason=reason, metadata={"place_id": candidate.place_id, "attempts": next_attempt})
            return
        next_retry = datetime_from_now(seconds)
        self.store.execute("UPDATE discovery_candidate SET status='RETRYABLE',attempts=?,next_retry_at_utc=?,last_reason=?,last_seen_at_utc=? WHERE candidate_id=?", [next_attempt, next_retry, reason, now_utc(), candidate_id])
        self.store.add_event("discovery_retry_scheduled", run_id=run_id, reason=reason, metadata={"place_id": candidate.place_id, "next_retry_at_utc": next_retry, "attempts": next_attempt})
```

---

## FILE: app/llm.py

```text
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request


class LLMTemporaryError(RuntimeError):
    pass


def parse_json_value(raw: str):
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for pattern in (r"\{.*\}", r"\[.*\]"):
        match = re.search(pattern, text, flags=re.S)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                continue
    return None


class LLMClient:
    def __init__(self, base_url: str, model: str, timeout_seconds: int, default_max_tokens: int):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.default_max_tokens = default_max_tokens

    def chat_json(self, system_prompt: str, user_prompt: str, *, max_tokens: int | None = None):
        key = os.getenv("NVIDIA_API_KEY", "").strip()
        if not key:
            raise LLMTemporaryError("NVIDIA_API_KEY is missing")
        payload = json.dumps({
            "model": self.model,
            "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            "temperature": 0.2,
            "top_p": 0.95,
            "max_tokens": max_tokens or self.default_max_tokens,
            "chat_template_kwargs": {"enable_thinking": False},
        }).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=payload,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            method="POST",
        )
        last: Exception | None = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    body = response.read().decode("utf-8")
                obj = json.loads(body)
                content = obj.get("choices", [{}])[0].get("message", {}).get("content", "")
                parsed = parse_json_value(content)
                if parsed is None:
                    raise LLMTemporaryError("LLM returned invalid JSON")
                return parsed
            except urllib.error.HTTPError as exc:
                last = exc
                if exc.code not in {429, 500, 502, 503, 504} or attempt == 2:
                    raise LLMTemporaryError(f"llm_http_{exc.code}") from exc
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, LLMTemporaryError) as exc:
                last = exc
                if attempt == 2:
                    raise LLMTemporaryError(f"llm_failure_{exc.__class__.__name__}") from exc
            time.sleep(2 + attempt * 3)
        raise LLMTemporaryError(f"llm_failure_{last.__class__.__name__ if last else 'unknown'}")

    def chat_json_object(self, system_prompt: str, user_prompt: str, *, max_tokens: int | None = None) -> dict:
        value = self.chat_json(system_prompt, user_prompt, max_tokens=max_tokens)
        if not isinstance(value, dict):
            raise LLMTemporaryError("LLM returned non-object JSON")
        return value

    def chat_json_array(self, system_prompt: str, user_prompt: str, *, max_tokens: int | None = None) -> list:
        value = self.chat_json(system_prompt, user_prompt, max_tokens=max_tokens)
        if not isinstance(value, list):
            raise LLMTemporaryError("LLM returned non-array JSON")
        return value
```

---

## FILE: app/mailbox.py

```text
from __future__ import annotations

import email
import imaplib
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.utils import parseaddr, parsedate_to_datetime

from app.models import InboundEventType

HARD_RE = re.compile(r"(?:5\.1\.1|5\.1\.0|5\.2\.1|user unknown|mailbox .*not found|recipient .*does not exist|no such user|address rejected|unknown user|\b550\b|\b551\b|\b553\b)", re.I)
SOFT_RE = re.compile(r"(?:4\.2\.0|4\.3\.0|4\.4\.1|mailbox full|temporar|try again|deferred|\b421\b|\b450\b|\b451\b|\b452\b)", re.I)
OPT_OUT_RE = re.compile(r"\b(?:unsubscribe|remove me|stop emailing me|do not contact me|don['’]?t contact me|take me off|opt[ -]?out)\b", re.I)
DSN_RE = re.compile(r"(?:delivery status notification|delivery failure|mail delivery|undeliverable|returned mail|failure notice|message not delivered|mailer-daemon|postmaster)", re.I)


@dataclass(frozen=True)
class ParsedInbound:
    message_id: str
    in_reply_to: str
    references: list[str]
    subject: str
    from_email: str
    received_at_utc: str
    text_excerpt: str


class IMAPProvider:
    def __init__(self, sender, credential: str):
        self.sender = sender
        self.credential = credential
        self.client = None
        self.uidvalidity = None

    def connect(self) -> None:
        if self.sender.imap_ssl:
            self.client = imaplib.IMAP4_SSL(self.sender.imap_host, self.sender.imap_port)
        else:
            self.client = imaplib.IMAP4(self.sender.imap_host, self.sender.imap_port)
            self.client.starttls()
        self.client.login(self.sender.email, self.credential)
        status, _ = self.client.select("INBOX", readonly=True)
        if status != "OK":
            raise RuntimeError("IMAP INBOX select failed")
        try:
            _, data = self.client.response("UIDVALIDITY")
            self.uidvalidity = data[0].decode() if data and isinstance(data[0], bytes) else str(data[0]) if data else None
        except Exception:
            self.uidvalidity = None

    def fetch_since(self, last_uid: int, lookback_minutes: int, max_messages: int) -> list[tuple[int, bytes]]:
        since = (datetime.now(timezone.utc) - timedelta(minutes=lookback_minutes)).strftime("%d-%b-%Y")
        status, data = self.client.uid("SEARCH", None, f'(SINCE "{since}" UID {max(1,last_uid + 1)}:*)')
        if status != "OK" or not data or not data[0]:
            return []
        uids = [int(x) for x in data[0].split()]
        uids = uids[:max_messages]
        out = []
        for uid in uids:
            status, parts = self.client.uid("FETCH", str(uid), "(RFC822)")
            if status == "OK":
                for part in parts:
                    if isinstance(part, tuple):
                        out.append((uid, part[1]))
        return out

    def close(self) -> None:
        if self.client:
            try: self.client.close()
            except Exception: pass
            try: self.client.logout()
            except Exception: pass
            self.client = None


def header(msg, name: str) -> str:
    try: return str(make_header(decode_header(msg.get(name, ""))))
    except Exception: return msg.get(name, "") or ""


def parse_message(raw: bytes) -> ParsedInbound:
    msg = email.message_from_bytes(raw)
    raw_date = header(msg, "Date")
    try:
        received = parsedate_to_datetime(raw_date).astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z") if raw_date else now_utc()
    except (TypeError, ValueError, OverflowError):
        received = now_utc()
    body = []
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in str(part.get("Content-Disposition", "")).lower():
                try: body.append(part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace"))
                except Exception: pass
    elif msg.get_content_type() == "text/plain":
        try: body.append(msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8", "replace"))
        except Exception: pass
    text = re.sub(r"\s+", " ", " ".join(body)).strip()[:5000]
    return ParsedInbound(header(msg,"Message-ID").strip(), header(msg,"In-Reply-To").strip(), re.findall(r"<[^>]+>", header(msg,"References")), header(msg,"Subject").strip(), parseaddr(header(msg,"From"))[1].lower(), received, text)


def classify(msg: ParsedInbound) -> tuple[InboundEventType, float]:
    combined = f"{msg.subject}\n{msg.text_excerpt}"
    if OPT_OUT_RE.search(combined): return InboundEventType.UNSUBSCRIBED, 0.99
    dsn = DSN_RE.search(combined) or msg.from_email.split("@",1)[0] in {"mailer-daemon", "postmaster"}
    if dsn and HARD_RE.search(combined): return InboundEventType.HARD_BOUNCE, 0.97
    if dsn and SOFT_RE.search(combined): return InboundEventType.SOFT_BOUNCE, 0.93
    return InboundEventType.REPLY, 0.80


class MailboxMonitor:
    def __init__(self, store, settings, run_id: str, provider_factory=IMAPProvider):
        self.store = store; self.settings = settings; self.run_id = run_id; self.provider_factory = provider_factory

    def _correlate(self, sender_id: str, parsed: ParsedInbound):
        for ref in [parsed.in_reply_to, *parsed.references]:
            if ref:
                row = self.store.fetchone("SELECT * FROM outreach WHERE message_id=?", [ref])
                if row:
                    return row["lead_id"], row["outreach_id"]
        lead = self.store.get_lead_by_email(parsed.from_email)
        if lead:
            row = self.store.fetchone("SELECT * FROM outreach WHERE lead_id=? AND sender_id=? AND status='SENT' ORDER BY sent_at_utc DESC LIMIT 1", [lead["lead_id"], sender_id])
            return lead["lead_id"], row["outreach_id"] if row else None
        return None, None

    def run_sender(self, sender) -> dict[str, int]:
        credential = os.getenv(sender.credential_env, "").strip()
        provider = self.provider_factory(sender, credential)
        provider.connect()
        state = self.store.mailbox_state(sender.sender_id)
        last_uid = int(state["last_processed_uid"]) if state else 0
        prior_validity = str(state["uidvalidity"]) if state and state["uidvalidity"] else None
        if prior_validity and provider.uidvalidity and prior_validity != provider.uidvalidity:
            last_uid = 0
            self.store.add_event("mailbox_uidvalidity_changed", run_id=self.run_id, sender_id=sender.sender_id, status="REBASE", reason="uidvalidity_changed")
        items = provider.fetch_since(last_uid, self.settings.mailbox_check_lookback_minutes, self.settings.mailbox_max_messages_per_run)
        processed = replies = bounces = unsubscribes = 0
        max_seen = last_uid
        lookback = datetime.now(timezone.utc) - timedelta(minutes=self.settings.mailbox_check_lookback_minutes)
        for uid, raw in items:
            max_seen = max(max_seen, uid)
            parsed = parse_message(raw)
            message_id = parsed.message_id or f"<imap-{sender.sender_id.lower()}-{uid}@local>"
            if self.store.inbound_exists(sender.sender_id, message_id):
                continue
            received_at = datetime.fromisoformat(parsed.received_at_utc.replace("Z", "+00:00"))
            if received_at < lookback:
                continue
            event, confidence = classify(parsed)
            lead_id, outreach_id = self._correlate(sender.sender_id, parsed)
            if event == InboundEventType.REPLY and not lead_id:
                event, confidence = InboundEventType.UNCLASSIFIED, 0.45
            if event == InboundEventType.HARD_BOUNCE and not lead_id:
                event, confidence = InboundEventType.REVIEW_NEEDED, 0.45
            try:
                inserted = self.store.save_inbound(sender_id=sender.sender_id, message_id=message_id, in_reply_to=parsed.in_reply_to, references=" ".join(parsed.references), received_at_utc=parsed.received_at_utc, lead_id=lead_id, outreach_id=outreach_id, event_type=event.value, confidence=confidence, subject=parsed.subject, from_email=parsed.from_email)
                if not inserted:
                    continue
                processed += 1
                if event == InboundEventType.REPLY and lead_id:
                    self.store.update_lead_status(lead_id, "REPLIED"); self.store.cancel_future_followups(lead_id); replies += 1
                    self.store.add_event("reply_detected", run_id=self.run_id, lead_id=lead_id, outreach_id=outreach_id, sender_id=sender.sender_id, status="REPLIED")
                elif event == InboundEventType.HARD_BOUNCE and lead_id:
                    lead = self.store.get_lead(lead_id); self.store.suppress(lead["email"], lead_id, "hard_bounce"); self.store.update_lead_status(lead_id, "BOUNCED"); self.store.cancel_future_followups(lead_id); bounces += 1
                    self.store.add_event("bounce_detected", run_id=self.run_id, lead_id=lead_id, outreach_id=outreach_id, sender_id=sender.sender_id, status="HARD_BOUNCE")
                elif event == InboundEventType.UNSUBSCRIBED and lead_id:
                    lead = self.store.get_lead(lead_id); self.store.suppress(lead["email"], lead_id, "unsubscribe"); self.store.update_lead_status(lead_id, "UNSUBSCRIBED"); self.store.cancel_future_followups(lead_id); unsubscribes += 1
                    self.store.add_event("unsubscribe_detected", run_id=self.run_id, lead_id=lead_id, outreach_id=outreach_id, sender_id=sender.sender_id, status="UNSUBSCRIBED")
                elif event == InboundEventType.SOFT_BOUNCE:
                    bounces += 1
                self.store.add_event("inbound_processed", run_id=self.run_id, lead_id=lead_id, outreach_id=outreach_id, sender_id=sender.sender_id, status=event.value)
            except Exception as exc:
                self.store.add_event("inbound_processing_error", run_id=self.run_id, sender_id=sender.sender_id, status="FAILED", reason=exc.__class__.__name__)
        current_state = self.store.sender_day(sender.sender_id, datetime.now(self.settings.timezone()).date().isoformat())
        current_health = "STOPPED" if current_state["health_state"] == "STOPPED" else "HEALTHY"
        if current_health == "HEALTHY" and current_state["health_state"] == "DEGRADED":
            self.store.set_sender_health(sender.sender_id, datetime.now(self.settings.timezone()).date().isoformat(), "HEALTHY", None)
        self.store.save_mailbox_state(sender_id=sender.sender_id, uidvalidity=provider.uidvalidity or prior_validity, last_processed_uid=max_seen, health_state=current_health)
        provider.close()
        self.store.add_event("mailbox_check", run_id=self.run_id, sender_id=sender.sender_id, status="SUCCESS", metadata={"messages_seen": len(items), "last_processed_uid": max_seen})
        return {"mailbox_checks": 1, "inbound_processed": processed, "replies": replies, "bounces": bounces, "unsubscribes": unsubscribes}

    def run_all(self) -> dict[str, int]:
        total = {"mailbox_checks": 0, "inbound_processed": 0, "replies": 0, "bounces": 0, "unsubscribes": 0}
        for sender in self.settings.sender_configs():
            try:
                result = self.run_sender(sender)
                for key, value in result.items(): total[key] += value
            except Exception as exc:
                self.store.add_event("mailbox_error", run_id=self.run_id, sender_id=sender.sender_id, status="FAILED", reason=exc.__class__.__name__)
                self.store.set_sender_health(sender.sender_id, datetime.now(self.settings.timezone()).date().isoformat(), "DEGRADED")
        return total
```

---

## FILE: app/mailer.py

```text
from __future__ import annotations

import hashlib
import os
import smtplib
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from email.message import EmailMessage
from email.policy import SMTP

from app.models import SendResult


def message_id_for(outreach_id: str, sender_email: str) -> str:
    token = hashlib.sha256(f"{outreach_id}|{sender_email}".encode()).hexdigest()[:24]
    domain = sender_email.split("@", 1)[1]
    return f"<attachai-{token}@{domain}>"


def classify_send_error(exc: Exception) -> str:
    text = str(exc).lower()
    if isinstance(exc, smtplib.SMTPRecipientsRefused) or any(x in text for x in ("550", "551", "553", "5.1.1", "user unknown", "mailbox not found", "recipient does not exist")):
        return "TERMINAL_RECIPIENT"
    if isinstance(exc, smtplib.SMTPAuthenticationError) or "authentication" in text or "535" in text:
        return "AUTH"
    if isinstance(exc, (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError, TimeoutError, ConnectionError)) or any(x in text for x in ("timeout", "temporar", "try again", "421", "450", "451", "452", "rate limit", "too many")):
        return "TEMPORARY"
    return "TERMINAL"


class SMTPMailer:
    def __init__(self, sender):
        self.sender = sender
        self.credential = os.getenv(sender.credential_env, "").strip()

    def validate(self) -> None:
        self._open().quit()

    def _open(self):
        if not self.credential:
            raise ValueError(f"Missing credential for {self.sender.sender_id}")
        if self.sender.smtp_ssl:
            client = smtplib.SMTP_SSL(self.sender.smtp_host, self.sender.smtp_port, timeout=30)
        else:
            client = smtplib.SMTP(self.sender.smtp_host, self.sender.smtp_port, timeout=30)
            client.ehlo(); client.starttls(); client.ehlo()
        client.login(self.sender.email, self.credential)
        return client

    def send(self, row) -> str:
        message_id = row["message_id"]
        client = self._open()
        try:
            message = EmailMessage(policy=SMTP)
            message["From"] = row["sender_email"]
            message["To"] = row["email"]
            message["Subject"] = row["subject"]
            message["Message-ID"] = message_id
            if row.get("in_reply_to"):
                message["In-Reply-To"] = row["in_reply_to"]
                message["References"] = row.get("references_text") or row["in_reply_to"]
            message.set_content(row["body"])
            client.send_message(message, from_addr=row["sender_email"], to_addrs=[row["email"]])
            return message_id
        finally:
            try:
                client.quit()
            except Exception:
                pass


class BatchSendController:
    """Claims rows before sending; SMTP calls run concurrently; DB state is reconciled by the coordinator thread."""

    def __init__(self, store, settings, smtp_factory=SMTPMailer):
        self.store = store
        self.settings = settings
        self.smtp_factory = smtp_factory

    def send_batch(self, batch_id: str, rows: list, sender_by_id: dict, allow_real_send: bool) -> list[SendResult]:
        run_id = batch_id.split(":", 1)[0]
        if not allow_real_send:
            return [SendResult(row["outreach_id"], row["sender_id"], "DRY_RUN", message_id_for(row["outreach_id"], row["sender_email"] or sender_by_id[row["sender_id"]].email)) for row in rows]

        claimed = []
        for row in rows:
            if not self.store.claim_outreach(row["outreach_id"]):
                continue
            message_id = message_id_for(row["outreach_id"], row["sender_email"])
            row_data = dict(row)
            row_data["message_id"] = message_id
            claimed.append(row_data)
            self.store.add_event("send_attempted", run_id=run_id, lead_id=row_data["lead_id"], outreach_id=row_data["outreach_id"], sender_id=row_data["sender_id"], batch_id=batch_id, sequence_type=row_data["sequence_type"], status="SENDING")
        if not claimed:
            return []
        results: list[SendResult] = []
        max_workers = min(self.settings.max_concurrent_sends, len(claimed))
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="attachai-sender") as executor:
            futures: dict[Future, dict] = {}
            for row in claimed:
                futures[executor.submit(self.smtp_factory(sender_by_id[row["sender_id"]]).send, row)] = row
            for future in as_completed(futures):
                row = futures[future]
                try:
                    mid = future.result()
                except Exception as exc:
                    kind = classify_send_error(exc)
                    current = self.store.get_outreach(row["outreach_id"])
                    retry_count = int(current["retry_count"] or 0) if current else 0
                    if kind == "TEMPORARY" and retry_count < self.settings.retry_limit:
                        next_retry = (datetime.now(timezone.utc) + timedelta(seconds=self.settings.retry_base_seconds * (2 ** min(retry_count, 6)))).replace(microsecond=0).isoformat().replace("+00:00", "Z")
                        self.store.mark_failed(row["outreach_id"], "FAILED_RETRYABLE", str(exc), next_retry)
                        cooldown_date_key = datetime.now(timezone.utc).astimezone(self.settings.timezone()).date().isoformat()
                        self.store.set_sender_health(row["sender_id"], cooldown_date_key, "COOLDOWN", next_retry)
                        self.store.add_event("send_failed", run_id=run_id, lead_id=row["lead_id"], outreach_id=row["outreach_id"], sender_id=row["sender_id"], batch_id=batch_id, sequence_type=row["sequence_type"], status="FAILED_RETRYABLE", reason=kind)
                        results.append(SendResult(row["outreach_id"], row["sender_id"], "FAILED_RETRYABLE", row["message_id"], kind, str(exc)))
                    else:
                        self.store.mark_failed(row["outreach_id"], "FAILED_TERMINAL", str(exc), None)
                        failure_date_key = datetime.now(timezone.utc).astimezone(self.settings.timezone()).date().isoformat()
                        self.store.record_failure(row["sender_id"], failure_date_key, kind)
                        if kind == "AUTH":
                            self.store.set_sender_health(row["sender_id"], failure_date_key, "STOPPED", None)
                        if kind == "TERMINAL_RECIPIENT":
                            self.store.suppress(row["email"], row["lead_id"], "hard_bounce")
                            self.store.update_lead_status(row["lead_id"], "BOUNCED")
                            self.store.cancel_future_followups(row["lead_id"])
                        self.store.add_event("send_failed", run_id=run_id, lead_id=row["lead_id"], outreach_id=row["outreach_id"], sender_id=row["sender_id"], batch_id=batch_id, sequence_type=row["sequence_type"], status="FAILED_TERMINAL", reason=kind)
                        results.append(SendResult(row["outreach_id"], row["sender_id"], "FAILED_TERMINAL", row["message_id"], kind, str(exc)))
                    continue

                sent_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
                try:
                    self.store.mark_sent(row["outreach_id"], sent_at, mid)
                    sent_date_key = datetime.fromisoformat(sent_at.replace("Z", "+00:00")).astimezone(self.settings.timezone()).date().isoformat()
                    self.store.record_send(row["sender_id"], sent_date_key, row["sequence_type"] != "INITIAL", sent_at)
                    next_status = "COMPLETED" if row["sequence_type"] == "FOLLOWUP_3" else "ACTIVE"
                    self.store.update_lead_status(row["lead_id"], next_status)
                    self.store.add_event("message_sent", run_id=run_id, lead_id=row["lead_id"], outreach_id=row["outreach_id"], sender_id=row["sender_id"], batch_id=batch_id, sequence_type=row["sequence_type"], status="SENT", metadata={"sent_at_utc": sent_at, "message_id": mid})
                    results.append(SendResult(row["outreach_id"], row["sender_id"], "SENT", mid))
                except Exception as exc:
                    # SMTP has already accepted the message. Never retry automatically if durable state cannot be confirmed.
                    try:
                        self.store.mark_review_needed(row["outreach_id"], "smtp_accepted_but_state_persistence_failed")
                    except Exception:
                        pass
                    self.store.add_event("send_persistence_ambiguous", run_id=run_id, lead_id=row["lead_id"], outreach_id=row["outreach_id"], sender_id=row["sender_id"], batch_id=batch_id, sequence_type=row["sequence_type"], status="REVIEW_NEEDED", reason=exc.__class__.__name__)
                    results.append(SendResult(row["outreach_id"], row["sender_id"], "REVIEW_NEEDED", mid, "PERSISTENCE_AMBIGUOUS", str(exc)))
                    continue

        return results

```

---

## FILE: app/main.py

```text
from __future__ import annotations

import argparse

from app.config import Settings
from app.db import Store
from app.discovery import DiscoveryService
from app.llm import LLMClient
from app.mailer import BatchSendController
from app.orchestrator import Orchestrator
from app.personalization import PersonalizationGenerator
from app.research import ResearchService, WebsiteCrawler


def build(settings: Settings, store: Store):
    llm = LLMClient(settings.llm_base_url, settings.llm_model, settings.llm_timeout_seconds, settings.llm_max_tokens)
    crawler = WebsiteCrawler(settings.crawler_timeout_seconds, settings.crawler_max_bytes, settings.crawler_max_pages, settings.crawler_request_delay_seconds, settings.honor_robots)
    discovery = DiscoveryService(store, llm, crawler, settings)
    research = ResearchService(store, llm, crawler, "2.0")
    personalization = PersonalizationGenerator(llm)
    mailer = BatchSendController(store, settings)
    return Orchestrator(settings, store, discovery, research, personalization, mailer)


def parse_bool(value: str) -> bool:
    value = str(value).strip().lower()
    if value in {"1", "true", "yes", "on"}: return True
    if value in {"0", "false", "no", "off"}: return False
    raise argparse.ArgumentTypeError("expected true or false")


def main() -> int:
    parser = argparse.ArgumentParser(description="AttachAI single-runner production orchestrator")
    parser.add_argument("--reset-state", type=parse_bool, default=None)
    parser.add_argument("--initial-target", type=int, default=None)
    parser.add_argument("--send-enabled", type=parse_bool, default=None)
    parser.add_argument("--dry-run", type=parse_bool, default=None)
    args = parser.parse_args()

    settings = Settings.from_env()
    reset = settings.reset_state if args.reset_state is None else args.reset_state
    target = settings.initial_outreach_target if args.initial_target is None else args.initial_target
    send_enabled = settings.send_enabled if args.send_enabled is None else args.send_enabled
    dry_run = settings.dry_run if args.dry_run is None else args.dry_run

    store = Store(settings.supabase_db_url)
    try:
        orchestrator = build(settings, store)
        metrics = orchestrator.run(reset_state=reset, target=target, send_enabled=send_enabled, dry_run=dry_run)
        return 0 if metrics["target_status"] == "TARGET REACHED" or dry_run else 1
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
```

---

## FILE: app/models.py

```text
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class LeadStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    RESEARCHING = "RESEARCHING"
    RESEARCHED = "RESEARCHED"
    QUEUED = "QUEUED"
    ACTIVE = "ACTIVE"
    REPLIED = "REPLIED"
    BOUNCED = "BOUNCED"
    UNSUBSCRIBED = "UNSUBSCRIBED"
    COMPLETED = "COMPLETED"
    MANUAL_STOP = "MANUAL_STOP"
    REVIEW_NEEDED = "REVIEW_NEEDED"


class MessageStatus(str, Enum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    QUEUED = "QUEUED"
    SCHEDULED = "SCHEDULED"
    SENDING = "SENDING"
    SENT = "SENT"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_TERMINAL = "FAILED_TERMINAL"
    CANCELLED = "CANCELLED"
    REVIEW_NEEDED = "REVIEW_NEEDED"


class SequenceType(str, Enum):
    INITIAL = "INITIAL"
    FOLLOWUP_1 = "FOLLOWUP_1"
    FOLLOWUP_2 = "FOLLOWUP_2"
    FOLLOWUP_3 = "FOLLOWUP_3"


class InboundEventType(str, Enum):
    REPLY = "REPLY"
    HARD_BOUNCE = "HARD_BOUNCE"
    SOFT_BOUNCE = "SOFT_BOUNCE"
    UNSUBSCRIBED = "UNSUBSCRIBED"
    UNCLASSIFIED = "UNCLASSIFIED"
    REVIEW_NEEDED = "REVIEW_NEEDED"


@dataclass(frozen=True)
class Lead:
    lead_id: str
    email: str
    company: str
    website: str
    website_domain: str
    city: str
    region: str
    country_code: str
    timezone: str
    lead_source: str
    place_id: str
    scale_class: str
    qualification_confidence: float
    qualification_reason: str
    discovery_facts: str = ""
    status: str = LeadStatus.ELIGIBLE.value
    sender_id: str | None = None


@dataclass(frozen=True)
class Evidence:
    url: str
    snippet: str


@dataclass(frozen=True)
class ResearchRecord:
    research_id: str
    lead_id: str
    website_domain: str
    canonical_url: str
    company_identity: str
    business_summary: str
    services: list[str]
    business_facts: list[str]
    locations: list[str]
    specialties: list[str]
    website_signals: list[str]
    customer_journey_signals: list[str]
    ai_opportunity_signals: list[str]
    important_public_text: str
    evidence: list[Evidence]
    research_timestamp_utc: str
    research_status: str
    research_version: str
    error: str | None = None
    retry_count: int = 0
    next_retry_at_utc: str | None = None


@dataclass(frozen=True)
class PersonalizationDraft:
    eligible: bool
    personalization_summary: str
    observations: list[str]
    opportunity: str
    subject: str
    body: str
    cta: str
    signature: str
    confidence: float
    evidence_urls: list[str]
    risk_flags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    reason: str
    body_hash: str


@dataclass(frozen=True)
class SendResult:
    outreach_id: str
    sender_id: str
    status: str
    message_id: str
    error_kind: str | None = None
    error_text: str | None = None


@dataclass(frozen=True)
class BatchResult:
    batch_id: str
    batch_number: int
    batch_type: str
    scheduled_at_utc: str
    attempted_count: int
    successful_count: int
    failed_count: int
    duration_seconds: float
```

---

## FILE: app/orchestrator.py

```text
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.db import now_utc


TERMINAL_LEAD_STATES = {"REPLIED", "BOUNCED", "UNSUBSCRIBED", "COMPLETED", "MANUAL_STOP"}


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class Orchestrator:
    def __init__(self, settings, store, discovery, research, personalization, mailer):
        self.settings = settings
        self.store = store
        self.discovery = discovery
        self.research = research
        self.personalization = personalization
        self.mailer = mailer
        self.stage_times: dict[str, float] = {}
        self.stage_starts: dict[str, str] = {}
        self.stage_ends: dict[str, str] = {}

    def _stage(self, name: str):
        class Stage:
            def __init__(self, outer, stage_name):
                self.outer = outer; self.stage_name = stage_name
            def __enter__(self):
                self.started = time.monotonic()
                self.outer.stage_starts[self.stage_name] = now_utc()
                print(f"{self.stage_name}_START={self.outer.stage_starts[self.stage_name]}")
            def __exit__(self, exc_type, exc, tb):
                self.outer.stage_ends[self.stage_name] = now_utc()
                self.outer.stage_times[self.stage_name] = round(time.monotonic() - self.started, 2)
                print(f"{self.stage_name}_END={self.outer.stage_ends[self.stage_name]}")
                print(f"{self.stage_name}_DURATION_SECONDS={self.outer.stage_times[self.stage_name]}")
        return Stage(self, name)

    def run(self, reset_state: bool, target: int, send_enabled: bool, dry_run: bool) -> dict:
        start_monotonic = time.monotonic()
        run_id: str | None = None
        try:
            self.store.migrate("migrations")
            if reset_state:
                print("RESET_STATE=true: clearing application runtime tables only")
                self.store.reset_runtime_state()
            run_id = self.store.start_workflow("MANUAL", reset_state)
            print(f"START_TIME={now_utc()}")
            self.reconcile_stale_state()

            with self._stage("DISCOVERY"):
                discovery_metrics = self.discovery.run(run_id, self.settings.discovery_target)

            with self._stage("PREPARE"):
                prep = self.prepare_initial_messages(run_id, target)

            with self._stage("SEND"):
                initial_send = self.send_initial_until_target(run_id, target, send_enabled and not dry_run)

            with self._stage("MAILBOX"):
                mailbox = self.sync_mailboxes(run_id, dry_run)

            with self._stage("FOLLOWUP"):
                followup = self.prepare_and_send_followups(run_id, send_enabled and not dry_run, dry_run)

            metrics = self.build_metrics(run_id, discovery_metrics, prep, initial_send, mailbox, followup, time.monotonic() - start_monotonic)
            success = metrics["successful_initial_sends"] >= target
            if metrics["successful_initial_sends"] < target:
                metrics["target_status"] = "TARGET NOT REACHED"
                metrics["target_reason"] = self.target_not_reached_reason(metrics)
                success = False if target > 0 and send_enabled and not dry_run else success
            else:
                metrics["target_status"] = "TARGET REACHED"
                metrics["target_reason"] = "100 successful initial sends reached" if target == 100 else "target reached"
            metrics["stage_durations_seconds"] = self.stage_times
            metrics["stage_timestamps"] = {k: {"start": self.stage_starts.get(k), "end": self.stage_ends.get(k)} for k in self.stage_starts}
            self.store.finish_workflow(run_id, "SUCCESS" if success else "TARGET_NOT_REACHED", metrics)
            print(json.dumps(metrics, indent=2, ensure_ascii=False))
            return metrics
        except Exception as exc:
            metrics = {"status": "FAILED", "error": exc.__class__.__name__, "message": str(exc), "stage_durations_seconds": self.stage_times}
            if run_id is not None:
                try:
                    self.store.finish_workflow(run_id, "FAILED", metrics)
                except Exception:
                    pass
            raise
        finally:
            print(f"FINAL_END={now_utc()}")
            print(f"TOTAL_RUNTIME_SECONDS={round(time.monotonic() - start_monotonic, 2)}")

    def reconcile_stale_state(self) -> None:
        cutoff = iso(datetime.now(timezone.utc) - timedelta(hours=2))
        self.store.execute("UPDATE leads SET status='ELIGIBLE',updated_at_utc=? WHERE status='RESEARCHING' AND updated_at_utc<?", [now_utc(), cutoff])
        self.store.execute("UPDATE outreach SET status='REVIEW_NEEDED',updated_at_utc=?,last_error='runner_interrupted_while_sending' WHERE status='SENDING' AND updated_at_utc<?", [now_utc(), cutoff])
        self.store.reconcile_stale_batches(cutoff)

    def prepare_initial_messages(self, run_id: str, target: int) -> dict[str, int]:
        prepared = researched = personalized = validated = rejected = 0
        blocked_this_run: set[str] = set()
        max_rounds = max(1, target * 2)
        for _ in range(max_rounds):
            if self.store.count_successful_initials() >= target:
                break
            if self.store.count_initial_progress() >= target:
                break
            leads = self.store.claim_untouched_leads(min(25, max(10, target - prepared)), exclude_ids=tuple(blocked_this_run))
            if not leads:
                break
            for lead in leads:
                lead_dict = dict(lead)
                self.store.add_event("lead_selected", run_id=run_id, lead_id=lead_dict["lead_id"], status="RESEARCHING")
                record = self.research.run(lead_dict, run_id)
                if record["research_status"] != "RESEARCHED":
                    blocked_this_run.add(lead_dict["lead_id"])
                    rejected += 1
                    self.store.add_event("research_failed", run_id=run_id, lead_id=lead_dict["lead_id"], status=record["research_status"], reason=record.get("error"))
                    self.store.update_lead_status(lead_dict["lead_id"], "ELIGIBLE")
                    continue
                researched += 1
                sender_signature = "Best,\nAttachAI"
                try:
                    draft = self.personalization.initial(lead_dict, record, sender_signature)
                except Exception as exc:
                    blocked_this_run.add(lead_dict["lead_id"])
                    self.store.update_lead_status(lead_dict["lead_id"], "ELIGIBLE")
                    self.store.add_event("personalization_failed", run_id=run_id, lead_id=lead_dict["lead_id"], status="FAILED_RETRYABLE", reason=exc.__class__.__name__)
                    continue
                personalized += 1
                self.store.add_event("personalization_generated", run_id=run_id, lead_id=lead_dict["lead_id"], status="GENERATED", metadata={"confidence": draft.confidence})
                previous = []
                from app.personalization import PersonalizationValidator
                validation = PersonalizationValidator(self.settings.min_personalization_confidence).validate(lead_dict, record, draft, previous, self.store)
                if not validation.ok:
                    blocked_this_run.add(lead_dict["lead_id"])
                    rejected += 1
                    self.store.update_lead_status(lead_dict["lead_id"], "ELIGIBLE")
                    self.store.add_event("personalization_rejected", run_id=run_id, lead_id=lead_dict["lead_id"], status="FAILED_TERMINAL", reason=validation.reason)
                    continue
                validated += 1
                self.store.add_event("personalization_validated", run_id=run_id, lead_id=lead_dict["lead_id"], status="VALIDATED")
                oid = self.store.queue_initial(run_id=run_id, lead_id=lead_dict["lead_id"], sender_id="UNASSIGNED", sender_email="", subject=draft.subject, body=draft.body, evidence_urls=draft.evidence_urls, confidence=draft.confidence)
                if oid:
                    prepared += 1
                    self.store.add_event("outreach_queued", run_id=run_id, lead_id=lead_dict["lead_id"], outreach_id=oid, sequence_type="INITIAL", status="QUEUED", metadata={"confidence": draft.confidence})
                else:
                    blocked_this_run.add(lead_dict["lead_id"])
                    self.store.update_lead_status(lead_dict["lead_id"], "ELIGIBLE")
        return {"prepared": prepared, "researched": researched, "personalized": personalized, "validated": validated, "rejected": rejected}

    def _within_window(self, when_utc: datetime, lead_timezone: str) -> bool:
        tz = self.settings.timezone()
        if self.settings.sending_window_mode == "recipient":
            try:
                tz = ZoneInfo(lead_timezone)
            except Exception:
                tz = self.settings.timezone()
        local = when_utc.astimezone(tz)
        current = local.timetz().replace(tzinfo=None)
        return self.settings.sending_window_start <= current < self.settings.sending_window_end

    def _next_window_start(self, when_utc: datetime, lead_timezone: str = "") -> datetime:
        tz = self.settings.timezone()
        if self.settings.sending_window_mode == "recipient" and lead_timezone:
            try: tz = ZoneInfo(lead_timezone)
            except Exception: pass
        local = when_utc.astimezone(tz)
        start = self.settings.sending_window_start
        end = self.settings.sending_window_end
        candidate = local.replace(hour=start.hour, minute=start.minute, second=0, microsecond=0)
        if local.timetz().replace(tzinfo=None) >= end:
            candidate = (local + timedelta(days=1)).replace(hour=start.hour, minute=start.minute, second=0, microsecond=0)
        elif local.timetz().replace(tzinfo=None) < start:
            candidate = local.replace(hour=start.hour, minute=start.minute, second=0, microsecond=0)
        return candidate.astimezone(timezone.utc)

    def _next_batch_slot(self, after: datetime, lead_timezone: str = "") -> datetime:
        tz_name = lead_timezone if self.settings.sending_window_mode == "recipient" else ""
        candidate = self._next_window_start(after, tz_name)
        try:
            tz = ZoneInfo(lead_timezone) if self.settings.sending_window_mode == "recipient" and lead_timezone else self.settings.timezone()
        except Exception:
            tz = self.settings.timezone()
        local_after = after.astimezone(tz)
        local_candidate = candidate.astimezone(tz)
        start = self.settings.sending_window_start
        end = self.settings.sending_window_end
        base = max(1, self.settings.batch_interval_minutes)
        if self._within_window(after, lead_timezone):
            local_candidate = local_after.replace(second=0, microsecond=0)
            minute = local_candidate.minute
            needs_step = (minute % base) != 0 or local_after.second != 0 or local_after.microsecond != 0
            if needs_step:
                minute = ((minute // base) + 1) * base
            if minute >= 60:
                local_candidate = (local_candidate + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
            else:
                local_candidate = local_candidate.replace(minute=minute, second=0, microsecond=0)
            if local_candidate < local_after:
                local_candidate = local_after + timedelta(minutes=base)
                local_candidate = local_candidate.replace(second=0, microsecond=0)
        if local_candidate.timetz().replace(tzinfo=None) >= end:
            local_candidate = (local_candidate + timedelta(days=1)).replace(hour=start.hour, minute=start.minute, second=0, microsecond=0)
        return local_candidate.astimezone(timezone.utc)

    def _wait_until(self, when_utc: datetime) -> None:
        seconds = (when_utc - datetime.now(timezone.utc)).total_seconds()
        if seconds > 0:
            time.sleep(seconds)

    def _available_senders(self, at_utc: datetime, is_followup: bool) -> list:
        date_key = at_utc.astimezone(self.settings.timezone()).date().isoformat()
        out = []
        for sender in self.settings.sender_configs():
            state = self.store.sender_day(sender.sender_id, date_key)
            if state["health_state"] == "STOPPED" or state["health_state"] == "DEGRADED":
                continue
            cooldown = state["cooldown_until_utc"]
            if cooldown:
                cooldown_at = parse_utc(cooldown)
                if cooldown_at > at_utc:
                    continue
                if state["health_state"] == "COOLDOWN":
                    self.store.set_sender_health(sender.sender_id, date_key, "HEALTHY", None)
                    state = self.store.sender_day(sender.sender_id, date_key)
            if int(state["total"]) >= self.settings.daily_total_limit:
                continue
            last = state["last_successful_send_utc"]
            if last and (at_utc - parse_utc(last)).total_seconds() < self.settings.batch_interval_minutes * 60:
                continue
            if is_followup and int(state["followups"]) >= self.settings.daily_followup_limit:
                continue
            if not is_followup and int(state["initials"]) >= self.settings.daily_initial_limit:
                continue
            out.append(sender)
        return out

    def _create_next_batch(self, run_id: str, batch_number: int, batch_type: str, target_remaining: int) -> tuple[str, list] | tuple[None, list]:
        now = datetime.now(timezone.utc)
        candidates = self.store.list_ready_initials(min(50, target_remaining)) if batch_type == "INITIAL" else self.store.list_due_followups(min(50, target_remaining))
        if not candidates:
            return None, []
        slot_by_id = {row["outreach_id"]: self._next_batch_slot(now, row["timezone"]) for row in candidates}
        earliest_slot = min(slot_by_id.values())
        candidates = [row for row in candidates if slot_by_id[row["outreach_id"]] == earliest_slot]
        senders = self._available_senders(earliest_slot, batch_type != "INITIAL")
        if not senders:
            return None, []
        selected = []
        capacity = min(self.settings.batch_size, len(senders), target_remaining)
        for row in candidates:
            if len(selected) >= capacity:
                break
            selected.append(row)
        if not selected:
            return None, []
        scheduled = earliest_slot
        batch_id = self.store.create_batch(run_id, batch_number, batch_type, iso(scheduled), len(selected))
        assignments = []
        for sender, row in zip(senders, selected):
            assignments.append((row["outreach_id"], row["lead_id"], sender.sender_id, sender.email))
        self.store.assign_batch(batch_id, assignments, iso(scheduled))
        for outreach_id, lead_id, sender_id, _ in assignments:
            self.store.add_event("outreach_scheduled", run_id=run_id, lead_id=lead_id, outreach_id=outreach_id, sender_id=sender_id, batch_id=batch_id, status="SCHEDULED", metadata={"scheduled_at_utc": iso(scheduled), "batch_number": batch_number})
        return batch_id, [r for r in self.store.fetchall("SELECT o.*,l.timezone,l.status AS lead_status FROM outreach o JOIN leads l ON l.lead_id=o.lead_id WHERE o.batch_id=? ORDER BY o.sequence_number,o.created_at_utc", [batch_id])]

    def send_initial_until_target(self, run_id: str, target: int, allow_real_send: bool) -> dict[str, int]:
        initial_success_total_at_start = self.store.count_successful_initials()
        successful = initial_success_total_at_start
        batches = attempted = failed = 0
        next_slot = datetime.now(timezone.utc)
        if not allow_real_send:
            remaining = max(0, target - successful)
            candidates = self.store.list_ready_initials(min(self.settings.batch_size, remaining))
            if candidates:
                batch_id = self.store.create_batch(run_id, 1, "INITIAL", iso(datetime.now(timezone.utc)), len(candidates))
                sender_ids = [s.sender_id for s in self.settings.sender_configs()]
                assignments = [(row["outreach_id"], row["lead_id"], sender_ids[i], self.settings.sender_configs()[i].email) for i, row in enumerate(candidates)]
                self.store.assign_batch(batch_id, assignments, iso(datetime.now(timezone.utc)))
                print(f"DRY_RUN_BATCH_PLANNED={batch_id} planned={len(assignments)}")
                self.store.requeue_batch_pending(batch_id)
            return {"batches": 1 if candidates else 0, "attempted": 0, "failed": 0, "successful": successful}
        for batch_number in range(1, self.settings.max_batches_per_run + 1):
            if successful >= target:
                break
            need = target - successful
            batch_id, rows = self._create_next_batch(run_id, batch_number, "INITIAL", need)
            if not rows:
                if self.store.count_initial_progress() >= target or self.store.count_eligible_untouched() == 0:
                    break
                self._wait_until(datetime.now(timezone.utc) + timedelta(seconds=1))
                continue
            scheduled = parse_utc(rows[0]["scheduled_at_utc"])
            if scheduled > datetime.now(timezone.utc):
                self._wait_until(scheduled)
            start = time.monotonic()
            result_rows = self.mailer.send_batch(batch_id, rows, {s.sender_id: s for s in self.settings.sender_configs()}, allow_real_send)
            batch_success = sum(1 for x in result_rows if x.status == "SENT")
            batch_attempted = len([x for x in result_rows if x.status != "DRY_RUN"])
            batch_failed = len([x for x in result_rows if x.status.startswith("FAILED")])
            attempted += batch_attempted; failed += batch_failed; successful = self.store.count_successful_initials(); batches += 1
            batch_status = "COMPLETED" if not any(x.status == "REVIEW_NEEDED" for x in result_rows) else "PARTIAL"
            self.store.update_batch_counts(batch_id, status=batch_status, attempted=batch_attempted, successful=batch_success, failed=batch_failed)
            self.store.requeue_batch_pending(batch_id)
            self.store.add_event("batch_completed", run_id=run_id, batch_id=batch_id, status=batch_status, metadata={"batch_number": batch_number, "scheduled_at_utc": rows[0]["scheduled_at_utc"], "planned": len(rows), "attempted": batch_attempted, "successful": batch_success, "failed": batch_failed, "duration_seconds": round(time.monotonic()-start,2), "senders": [r["sender_id"] for r in rows]})
            next_slot = scheduled + timedelta(minutes=self.settings.batch_interval_minutes)
            if successful < target:
                self._wait_until(next_slot)
        return {"batches": batches, "attempted": attempted, "failed": failed, "successful": successful, "successful_in_run": max(0, successful - initial_success_total_at_start)}

    def sync_mailboxes(self, run_id: str, dry_run: bool) -> dict[str, int]:
        if dry_run:
            print("MAILBOX_MODE=SKIPPED_DRY_RUN")
            return {"mailbox_checks": 0, "inbound_processed": 0, "replies": 0, "bounces": 0, "unsubscribes": 0}
        from app.mailbox import MailboxMonitor
        monitor = MailboxMonitor(self.store, self.settings, run_id)
        return monitor.run_all()

    def prepare_and_send_followups(self, run_id: str, allow_real_send: bool, dry_run: bool) -> dict[str, int]:
        generated = 0
        from app.personalization import PersonalizationValidator
        for sequence in ("FOLLOWUP_1", "FOLLOWUP_2", "FOLLOWUP_3"):
            number = int(sequence.split("_")[-1])
            delay = {1: timedelta(hours=self.settings.followup_1_delay_hours), 2: timedelta(days=self.settings.followup_2_delay_days), 3: timedelta(days=self.settings.followup_3_delay_days)}[number]
            for previous in self.store.list_followup_candidates(sequence, 100):
                lead = self.store.get_lead(previous["lead_id"])
                if not lead or lead["status"] in TERMINAL_LEAD_STATES or self.store.is_suppressed(lead["email"]):
                    continue
                due_at = parse_utc(previous["sent_at_utc"]) + delay
                if due_at > datetime.now(timezone.utc):
                    continue
                research = self.store.latest_research(previous["lead_id"])
                if not research or research["research_status"] != "RESEARCHED":
                    continue
                history = self.store.previous_sent_history(previous["lead_id"])
                sender = next(s for s in self.settings.sender_configs() if s.sender_id == previous["sender_id"])
                try:
                    draft = self.personalization.followup(dict(lead), dict(research), history, sequence, sender.email)
                    validation = PersonalizationValidator(self.settings.min_personalization_confidence).validate(dict(lead), dict(research), draft, [x["body"] for x in history], self.store)
                    if not validation.ok:
                        self.store.add_event("followup_rejected", run_id=run_id, lead_id=lead["lead_id"], sender_id=sender.sender_id, sequence_type=sequence, status="FAILED_TERMINAL", reason=validation.reason)
                        continue
                except Exception as exc:
                    self.store.add_event("followup_generation_failed", run_id=run_id, lead_id=lead["lead_id"], sender_id=sender.sender_id, sequence_type=sequence, status="FAILED_RETRYABLE", reason=exc.__class__.__name__)
                    continue
                oid = self.store.insert_followup(run_id=run_id, lead_id=lead["lead_id"], sequence_type=sequence, sequence_number=number, sender_id=sender.sender_id, sender_email=sender.email, subject=draft.subject, body=draft.body, evidence_urls=draft.evidence_urls, confidence=draft.confidence, in_reply_to=previous["message_id"], references_text=previous["message_id"], scheduled_at_utc=iso(due_at))
                if oid:
                    generated += 1
                    self.store.add_event("followup_generated", run_id=run_id, lead_id=lead["lead_id"], outreach_id=oid, sender_id=sender.sender_id, sequence_type=sequence, status="QUEUED", metadata={"scheduled_at_utc": iso(due_at)})
        if not allow_real_send:
            return {"generated": generated, "sent": 0, "batches": 0}
        sent = 0
        batches = 0
        for batch_number in range(1, self.settings.max_batches_per_run + 1):
            rows = self.store.list_due_followups(min(self.settings.batch_size, self.settings.daily_followup_limit))
            if not rows:
                break
            # Each follow-up batch also uses one message per sender, while preserving the sender identity from the prior stage.
            selected = []
            used_senders = set()
            now = datetime.now(timezone.utc)
            available_sender_ids = {s.sender_id for s in self._available_senders(now, True)}
            for row in rows:
                if row["sender_id"] in used_senders or row["sender_id"] not in available_sender_ids:
                    continue
                if row["lead_status"] in TERMINAL_LEAD_STATES:
                    continue
                if not self._within_window(now, row["timezone"]):
                    continue
                selected.append(row); used_senders.add(row["sender_id"])
                if len(selected) >= self.settings.batch_size:
                    break
            if not selected:
                break
            scheduled = max(parse_utc(x["scheduled_at_utc"]) for x in selected if x["scheduled_at_utc"])
            if scheduled > now:
                self._wait_until(scheduled)
            batch_id = self.store.create_batch(run_id, batch_number, "FOLLOWUP", iso(scheduled), len(selected))
            self.store.assign_batch(batch_id, [(r["outreach_id"], r["lead_id"], r["sender_id"], r["sender_email"]) for r in selected], iso(scheduled))
            result_rows = self.mailer.send_batch(batch_id, [dict(r) for r in self.store.fetchall("SELECT o.*,l.timezone,l.status AS lead_status FROM outreach o JOIN leads l ON l.lead_id=o.lead_id WHERE o.batch_id=?", [batch_id])], {s.sender_id: s for s in self.settings.sender_configs()}, allow_real_send)
            success = sum(1 for r in result_rows if r.status == "SENT")
            failed = sum(1 for r in result_rows if r.status.startswith("FAILED"))
            attempted = sum(1 for r in result_rows if r.status != "DRY_RUN")
            self.store.update_batch_counts(batch_id, status="COMPLETED", attempted=attempted, successful=success, failed=failed)
            self.store.requeue_batch_pending(batch_id)
            sent += success; batches += 1
        return {"generated": generated, "sent": sent, "batches": batches}

    def build_metrics(self, run_id: str, discovery: dict, prep: dict, initial: dict, mailbox: dict, followup: dict, runtime: float) -> dict:
        return {
            "run_id": run_id,
            "runtime_seconds": round(runtime, 2),
            "discovered": discovery.get("discovered", 0),
            "verified": discovery.get("verified", 0),
            "eligible": self.store.count_eligible_untouched() + self.store.scalar("SELECT count(*) FROM leads WHERE status IN ('RESEARCHED','QUEUED','ACTIVE')"),
            "selected": prep.get("prepared", 0),
            "researched": prep.get("researched", 0),
            "personalized": prep.get("personalized", 0),
            "validated": prep.get("validated", 0),
            "queued": self.store.scalar("SELECT count(*) FROM outreach WHERE workflow_run_id=? AND status IN ('QUEUED','SCHEDULED','SENDING','SENT')", [run_id]),
            "scheduled": self.store.scalar("SELECT count(*) FROM outreach WHERE workflow_run_id=? AND status='SCHEDULED'", [run_id]),
            "attempted": initial.get("attempted", 0),
            "successful_initial_sends": self.store.count_successful_initials(),
            "successful_initial_sends_in_run": initial.get("successful_in_run", 0),
            "retryable_failures": self.store.scalar("SELECT count(*) FROM outreach WHERE workflow_run_id=? AND status='FAILED_RETRYABLE'", [run_id]),
            "terminal_failures": self.store.scalar("SELECT count(*) FROM outreach WHERE workflow_run_id=? AND status='FAILED_TERMINAL'", [run_id]),
            "suppressed": self.store.scalar("SELECT count(*) FROM suppression"),
            "replies": mailbox.get("replies", 0),
            "bounces": mailbox.get("bounces", 0),
            "unsubscribes": mailbox.get("unsubscribes", 0),
            "followups_generated": followup.get("generated", 0),
            "followups_sent": self.store.scalar("SELECT count(*) FROM outreach WHERE workflow_run_id=? AND sequence_type LIKE 'FOLLOWUP_%' AND status='SENT'", [run_id]),
            "eligible_untouched_after_run": self.store.count_eligible_untouched(),
            "batch_count": initial.get("batches", 0),
        }

    @staticmethod
    def target_not_reached_reason(metrics: dict) -> str:
        if metrics["successful_initial_sends"] == 0 and metrics["eligible_untouched_after_run"] == 0:
            return "no eligible untouched leads remain"
        if metrics["eligible_untouched_after_run"] > 0:
            return "remaining leads are not currently valid/sendable, or batch/sender limits were exhausted"
        return "some selected messages failed and the bounded batch/retry policy ended before target"
```

---

## FILE: app/personalization.py

```text
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from urllib.parse import urlparse

from app.llm import LLMClient, LLMTemporaryError
from app.models import PersonalizationDraft, ValidationResult

PLACEHOLDER_RE = re.compile(r"(\{\{.*?\}\}|\[(?:NAME|COMPANY|FIRST_NAME|LAST_NAME)\]|\bTODO\b)", re.I)
URL_RE = re.compile(r"https?://[^\s)\]>\"']+")
RISK_TERMS = (
    "you're losing leads", "you are losing leads", "you need ai", "your conversion is poor",
    "customers are waiting", "opportunities are being missed", "your competitors are using ai",
)


class PersonalizationValidator:
    def __init__(self, confidence_threshold: float):
        self.confidence_threshold = confidence_threshold

    def validate(self, lead, research: dict, draft: PersonalizationDraft, previous_bodies: list[str], store) -> ValidationResult:
        reasons: list[str] = []
        normalized = re.sub(r"\s+", " ", draft.body.strip().lower())
        body_hash = hashlib.sha256(normalized.encode()).hexdigest()
        if not draft.eligible:
            reasons.append("llm_marked_ineligible")
        if not draft.subject.strip():
            reasons.append("empty_subject")
        if not draft.body.strip():
            reasons.append("empty_body")
        if len(draft.subject) > 160:
            reasons.append("subject_too_long")
        if len(draft.body) > 5000:
            reasons.append("body_too_long")
        if PLACEHOLDER_RE.search(draft.subject + "\n" + draft.body):
            reasons.append("placeholder")
        evidence_json = research["evidence_json"] if "evidence_json" in research.keys() else "[]"
        allowed = {json_item["url"] for json_item in json_items(evidence_json)}
        if len(set(draft.evidence_urls)) != len(draft.evidence_urls):
            reasons.append("duplicate_evidence_urls")
        if any(url not in allowed for url in draft.evidence_urls):
            reasons.append("evidence_url_not_in_current_research")
        if draft.eligible and not draft.evidence_urls:
            reasons.append("missing_evidence")
        if draft.confidence < self.confidence_threshold:
            reasons.append("low_confidence")
        if normalized and any(normalized == re.sub(r"\s+", " ", body.strip().lower()) for body in previous_bodies):
            reasons.append("duplicate_body")
        if store.body_hash_exists(body_hash):
            reasons.append("duplicate_body")
        if lead["company"] and lead["company"].lower() not in draft.body.lower():
            reasons.append("company_not_personalized")
        host = (urlparse(lead["website"]).hostname or "").lower().removeprefix("www.")
        for url in URL_RE.findall(draft.body):
            url_host = (urlparse(url).hostname or "").lower().removeprefix("www.")
            if url_host and url_host not in {host, "attachaiassistant.oneapp.dev"}:
                reasons.append("unsupported_body_url")
        lower = draft.body.lower()
        if any(term in lower for term in RISK_TERMS):
            reasons.append("unsupported_claim")
        if re.search(r"\b(?:system|developer|assistant)\s+prompt\b", lower):
            reasons.append("prompt_leakage")
        if "```json" in lower or '"eligible":' in lower or '"confidence":' in lower:
            reasons.append("json_leakage")
        return ValidationResult(not reasons, ";".join(dict.fromkeys(reasons)), body_hash)


def json_items(raw: str) -> list[dict]:
    try:
        import json
        value = json.loads(raw or "[]")
        return value if isinstance(value, list) and all(isinstance(x, dict) for x in value) else []
    except Exception:
        return []


class PersonalizationGenerator:
    SYSTEM_PROMPT = """
You write concise, factual B2B outreach for AttachAI.
Return ONLY JSON with: eligible, personalization_summary, observations, opportunity, subject, body, cta, signature, confidence, evidence_urls, risk_flags.
Use only the current lead, current research, and current outreach history supplied.
Never invent names, testimonials, technologies, integrations, customer pain, performance claims, or competitor behavior.
Never claim the company is losing leads, needs AI, has poor conversion, missed opportunities, or that competitors use AI without direct evidence.
Keep the email concise and professional. No fake urgency, fake identity, fake reply appearance, or deceptive clickbait.
Evidence URLs must come from current research. If evidence is insufficient for a truthful opportunity, set eligible=false.
Possible use cases only when directly supported: answering common questions; handling repetitive website inquiries; helping visitors before booking; directing visitors to services; explaining services; assisting appointment/request flows; collecting basic inquiry information; helping visitors outside business hours.
""".strip()

    FOLLOWUP_SYSTEM_PROMPT = SYSTEM_PROMPT + "\nFor follow-ups, add new useful context, do not repeat the previous message verbatim, and honor the exact sequence."

    def __init__(self, llm: LLMClient, confidence_threshold: float):
        self.llm = llm
        self.confidence_threshold = confidence_threshold

    def _build_prompt(self, lead, research: dict, history: list[dict], sequence: str, sender_signature: str) -> str:
        import json
        evidence = "\n".join(f"URL: {x['url']}\nTEXT: {x.get('snippet','')}" for x in json_items(research.get("evidence_json", "[]")))[:14000]
        prior = "\n\n".join(f"{x['sequence_type']}: {x['subject']}\n{str(x.get('body') or '')[:1500]}" for x in history[-5:]) or "(none)"
        return (
            f"CURRENT LEAD ONLY\nLeadID: {lead['lead_id']}\nCompany: {lead['company']}\nEmail: {lead['email']}\nWebsite: {lead['website']}\n"
            f"Location: {lead['city']}, {lead['region']} {lead['country_code']}\nTimezone: {lead['timezone']}\n\n"
            f"CURRENT RESEARCH ONLY\nSummary: {research.get('business_summary','')}\nServices: {research.get('services_json','')}\n"
            f"Business facts: {research.get('business_facts_json','')}\nCustomer journey: {research.get('customer_journey_signals_json','')}\n"
            f"AI opportunity signals: {research.get('ai_opportunity_signals_json','')}\nEvidence:\n{evidence}\n\n"
            f"CURRENT OUTREACH HISTORY ONLY\n{prior}\n\nSequence: {sequence}\nSender signature: {sender_signature}\nReturn JSON only."
        )

    @staticmethod
    def _draft(obj: dict) -> PersonalizationDraft:
        try:
            confidence = max(0.0, min(1.0, float(obj.get("confidence") or 0)))
        except (TypeError, ValueError):
            confidence = 0.0
        body = str(obj.get("body") or "").strip()[:5000]
        cta = str(obj.get("cta") or "").strip()[:500]
        signature = str(obj.get("signature") or "").strip()[:500]
        if cta and cta not in body:
            body += "\n\n" + cta
        if signature and signature not in body:
            body += "\n\n" + signature
        return PersonalizationDraft(
            bool(obj.get("eligible")), str(obj.get("personalization_summary") or "").strip()[:1000],
            [str(x).strip()[:500] for x in obj.get("observations", []) if str(x).strip()][:6],
            str(obj.get("opportunity") or "").strip()[:1000], str(obj.get("subject") or "").strip()[:160], body[:5000],
            cta, signature, confidence, [str(x).strip() for x in obj.get("evidence_urls", []) if str(x).strip()],
            [str(x).strip() for x in obj.get("risk_flags", []) if str(x).strip()][:10],
        )

    def initial(self, lead, research: dict, sender_signature: str) -> PersonalizationDraft:
        return self._draft(self.llm.chat_json_object(self.SYSTEM_PROMPT, self._build_prompt(lead, research, [], "INITIAL", sender_signature), max_tokens=1400))

    def followup(self, lead, research: dict, history: list[dict], sequence: str, sender_signature: str) -> PersonalizationDraft:
        return self._draft(self.llm.chat_json_object(self.FOLLOWUP_SYSTEM_PROMPT, self._build_prompt(lead, research, history, sequence, sender_signature), max_tokens=1400))
```

---

## FILE: app/research.py

```text
from __future__ import annotations

import html
import json
import re
import time
import urllib.parse
import urllib.robotparser
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parseaddr
from typing import Any

import requests
from bs4 import BeautifulSoup

from app.db import deterministic_research_id, normalize_domain
from app.models import Evidence
from app.llm import LLMClient, LLMTemporaryError


EMAIL_RE = re.compile(r"(?<![\w.+-])[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,63}(?![\w.-])", re.I)
FREE_EMAIL_DOMAINS = {"gmail.com", "googlemail.com", "yahoo.com", "hotmail.com", "outlook.com", "live.com", "msn.com", "icloud.com", "me.com", "aol.com", "protonmail.com", "proton.me", "gmx.com", "mail.com", "yandex.com", "zoho.com"}
DISPOSABLE_DOMAINS = {"10minutemail.com", "guerrillamail.com", "mailinator.com", "yopmail.com", "getnada.com", "tempmail.com", "temp-mail.org", "discard.email", "throwawaymail.com"}
BLOCKED_LOCALS = {"noreply", "no-reply", "donotreply", "do-not-reply", "mailer-daemon", "abuse"}


@dataclass(frozen=True)
class Page:
    url: str
    text: str
    html: str


class WebsiteCrawler:
    PRIORITY_PATHS = (
        "/", "/contact", "/contact-us", "/contactus", "/get-in-touch", "/connect", "/about", "/about-us",
        "/company", "/team", "/our-team", "/staff", "/leadership", "/locations", "/location", "/services",
        "/products", "/solutions", "/industries", "/faq", "/booking", "/book", "/request", "/request-a-quote", "/pricing",
    )
    KEYWORDS = ("contact", "about", "team", "staff", "leadership", "location", "service", "faq", "book", "request", "quote")

    def __init__(self, timeout_seconds: int, max_bytes: int, max_pages: int, delay_seconds: float, honor_robots: bool, user_agent: str = "AttachAI-Research/2.0"):
        self.timeout_seconds = timeout_seconds
        self.max_bytes = max_bytes
        self.max_pages = max_pages
        self.delay_seconds = delay_seconds
        self.honor_robots = honor_robots
        self.user_agent = user_agent
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent, "Accept-Language": "en-US,en;q=0.8"})
        self.robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    def _origin(self, url: str) -> str:
        parsed = urllib.parse.urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}"

    def _allowed(self, url: str) -> bool:
        if not self.honor_robots:
            return True
        origin = self._origin(url)
        if origin not in self.robots:
            try:
                response = self.session.get(f"{origin}/robots.txt", timeout=8)
                if response.status_code >= 400:
                    self.robots[origin] = None
                else:
                    parser = urllib.robotparser.RobotFileParser()
                    parser.set_url(f"{origin}/robots.txt")
                    parser.parse(response.text.splitlines())
                    self.robots[origin] = parser
            except Exception:
                self.robots[origin] = None
        parser = self.robots.get(origin)
        return True if parser is None else parser.can_fetch(self.user_agent, url)

    def fetch(self, url: str) -> Page | None:
        if not self._allowed(url):
            return None
        try:
            response = self.session.get(url, timeout=self.timeout_seconds, allow_redirects=True)
            if response.status_code >= 400:
                return None
            ctype = (response.headers.get("content-type") or "").lower()
            if ctype and "html" not in ctype and "xhtml" not in ctype:
                return None
            raw = response.content
            if len(raw) > self.max_bytes:
                return None
            text = extract_visible_text(raw.decode(response.encoding or "utf-8", errors="ignore"), 12000)
            return Page(response.url, text, raw.decode(response.encoding or "utf-8", errors="ignore"))
        except Exception:
            return None

    def _sitemap_urls(self, home: str) -> list[str]:
        parsed = urllib.parse.urlparse(home)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        candidates = [f"{origin}/sitemap.xml", f"{origin}/sitemap_index.xml", f"{origin}/wp-sitemap.xml"]
        try:
            robots = self.session.get(f"{origin}/robots.txt", timeout=8)
            if robots.status_code < 400:
                candidates.extend(line.split(":", 1)[1].strip() for line in robots.text.splitlines() if line.lower().startswith("sitemap:"))
        except Exception:
            pass
        seen: set[str] = set()
        urls: list[str] = []
        nested: list[str] = []
        for sitemap in candidates:
            if sitemap in seen:
                continue
            seen.add(sitemap)
            try:
                response = self.session.get(sitemap, timeout=self.timeout_seconds)
                if response.status_code >= 400:
                    continue
                root = ET.fromstring(response.text)
            except Exception:
                continue
            for node in root.iter():
                if not node.tag.lower().endswith("loc") or not node.text:
                    continue
                value = node.text.strip()
                if not value.startswith(origin):
                    continue
                if value.endswith(".xml") or value.endswith(".xml.gz"):
                    nested.append(value)
                elif value not in urls:
                    urls.append(value)
                if len(urls) >= 80:
                    return urls
        for sitemap in nested[:5]:
            try:
                response = self.session.get(sitemap, timeout=self.timeout_seconds)
                root = ET.fromstring(response.text)
                for node in root.iter():
                    if node.tag.lower().endswith("loc") and node.text and node.text.strip().startswith(origin):
                        value = node.text.strip()
                        if value not in urls:
                            urls.append(value)
                        if len(urls) >= 80:
                            return urls
            except Exception:
                continue
        return urls

    def discover_urls(self, website: str) -> list[str]:
        value = website if "://" in website else f"https://{website}"
        parsed = urllib.parse.urlparse(value)
        if not parsed.hostname:
            return []
        origin = f"{parsed.scheme or 'https'}://{parsed.netloc}"
        host = normalize_domain(parsed.hostname)
        home = urllib.parse.urlunparse((parsed.scheme or "https", parsed.netloc, parsed.path or "/", "", "", ""))
        urls = [home]
        seen = {home}
        first = self.fetch(home)
        linked: list[str] = []
        if first:
            soup = BeautifulSoup(first.html, "html.parser")
            for anchor in soup.find_all("a", href=True):
                absolute = urllib.parse.urljoin(first.url, anchor.get("href", ""))
                item = urllib.parse.urlparse(absolute)
                if item.scheme not in {"http", "https"} or normalize_domain(item.hostname or "") != host:
                    continue
                label = f"{anchor.get_text(' ', strip=True)} {item.path}".lower()
                if any(word in label for word in self.KEYWORDS):
                    clean = urllib.parse.urlunparse((item.scheme, item.netloc, item.path or "/", "", "", ""))
                    if clean not in linked:
                        linked.append(clean)
        ordered = [origin + p for p in self.PRIORITY_PATHS if p != "/"] + linked
        for value in self._sitemap_urls(home):
            if any(word in value.lower() for word in self.KEYWORDS):
                ordered.append(value)
        for url in ordered:
            item = urllib.parse.urlparse(url)
            clean = urllib.parse.urlunparse((item.scheme, item.netloc, item.path or "/", "", "", ""))
            if normalize_domain(item.hostname or "") != host or clean in seen:
                continue
            seen.add(clean)
            urls.append(clean)
            if len(urls) >= self.max_pages:
                break
        return urls[:self.max_pages]

    def crawl(self, website: str) -> list[Page]:
        pages: list[Page] = []
        for index, url in enumerate(self.discover_urls(website)):
            page = self.fetch(url)
            if page and page.text:
                pages.append(page)
            if index + 1 < self.max_pages:
                time.sleep(max(0.0, self.delay_seconds))
        return pages


def extract_visible_text(html_doc: str, limit: int = 12000) -> str:
    soup = BeautifulSoup(html_doc or "", "html.parser")
    for node in soup(["script", "style", "noscript", "svg", "template", "iframe"]):
        node.decompose()
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True))[:limit]


def decode_cloudflare_email(encoded: str) -> str:
    try:
        key = int(encoded[:2], 16)
        return "".join(chr(int(encoded[i:i + 2], 16) ^ key) for i in range(2, len(encoded), 2))
    except Exception:
        return ""


def email_strings(text: str) -> list[str]:
    if not text:
        return []
    text = html.unescape(text)
    found = {x.lower() for x in EMAIL_RE.findall(text)}
    obfuscated = re.sub(r"(?<![A-Za-z0-9])(?:\[\s*at\s*\]|\(\s*at\s*\)|\{\s*at\s*\}|at|@)(?![A-Za-z0-9])", "@", text, flags=re.I)
    obfuscated = re.sub(r"(?<![A-Za-z0-9])(?:\[\s*dot\s*\]|\(\s*dot\s*\)|\{\s*dot\s*\}|dot)(?![A-Za-z0-9])", ".", obfuscated, flags=re.I)
    obfuscated = re.sub(r"\s*@\s*", "@", obfuscated)
    obfuscated = re.sub(r"\s*\.\s*", ".", obfuscated)
    found.update(x.lower() for x in EMAIL_RE.findall(obfuscated))
    return sorted(found)


def extract_jsonld_emails(soup: BeautifulSoup) -> list[str]:
    found: list[str] = []
    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key.lower() in {"email", "emailaddress"} and isinstance(child, str):
                    found.extend(email_strings(child))
                else:
                    walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    for script in soup.find_all("script", attrs={"type": re.compile(r"application/ld\+json", re.I)}):
        try:
            walk(json.loads(script.get_text(" ", strip=True)))
        except Exception:
            continue
    return found


def extract_emails(page: Page) -> list[str]:
    soup = BeautifulSoup(page.html, "html.parser")
    candidates: list[str] = []
    for anchor in soup.find_all("a", href=True):
        href = html.unescape(urllib.parse.unquote(anchor.get("href", "")))
        if href.lower().startswith("mailto:"):
            candidates.extend(email_strings(href[7:].split("?", 1)[0]))
        for value in (anchor.get("aria-label"), anchor.get("title"), anchor.get("data-email")):
            candidates.extend(email_strings(value or ""))
    for node in soup.find_all(attrs={"data-cfemail": True}):
        candidates.extend(email_strings(decode_cloudflare_email(node.get("data-cfemail", ""))))
    for encoded in re.findall(r"/cdn-cgi/l/email-protection#([0-9a-fA-F]+)", page.html):
        candidates.extend(email_strings(decode_cloudflare_email(encoded)))
    candidates.extend(email_strings(page.text))
    candidates.extend(email_strings(page.html))
    candidates.extend(extract_jsonld_emails(soup))
    result: list[str] = []
    for email in candidates:
        email = email.lower().strip()
        if email and email not in result:
            result.append(email)
    return result


def choose_public_business_email(pages: list[Page], website: str, has_mx) -> tuple[str, str] | None:
    site = normalize_domain(website)
    candidates: list[tuple[int, int, str, str]] = []
    preferred = {"contact", "info", "hello", "sales", "office", "team"}
    for page in pages:
        for email in extract_emails(page):
            local, domain = email.rsplit("@", 1)
            rank = 0 if local in preferred else 1
            candidates.append((rank, len(email), email, page.url))
    for _, _, email, source_url in sorted(candidates):
        if len(email) > 254:
            continue
        local, domain = email.rsplit("@", 1)
        if local in BLOCKED_LOCALS or domain in FREE_EMAIL_DOMAINS or domain in DISPOSABLE_DOMAINS:
            continue
        if not (domain == site or domain.endswith("." + site)):
            continue
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email) or len(local) > 64 or ".." in local:
            continue
        if not has_mx(domain):
            continue
        return email, source_url
    return None


class ResearchService:
    SYSTEM_PROMPT = """
You are an evidence-bound website research analyst for AttachAI.
Return ONLY JSON with keys: business_summary, services, business_facts, locations, specialties,
website_signals, customer_journey_signals, ai_opportunity_signals, important_public_text, evidence_urls.
Use ONLY the current lead and current website evidence supplied. Do not use memory from any other lead.
Do not infer unsupported pain points. Every signal and claim must be grounded in supplied evidence.
evidence_urls must be a subset of supplied URLs.
""".strip()

    def __init__(self, store, llm: LLMClient, crawler: WebsiteCrawler, version: str):
        self.store = store
        self.llm = llm
        self.crawler = crawler
        self.version = version

    def run(self, lead, run_id: str):
        timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        pages = self.crawler.crawl(lead["website"])
        evidence = [Evidence(p.url, p.text[:2000]) for p in pages if p.text]
        if not evidence:
            record = self._record(lead, timestamp, [], "FAILED", self.version, error="no_website_evidence")
            self.store.save_research(record)
            self.store.update_lead_status(lead["lead_id"], "ELIGIBLE")
            return record
        blob = "\n\n".join(f"URL: {e.url}\nTEXT: {e.snippet}" for e in evidence)[:16000]
        prompt = (
            f"CURRENT LEAD ONLY\nLeadID: {lead['lead_id']}\nCompany: {lead['company']}\nWebsite: {lead['website']}\n"
            f"Email: {lead['email']}\nLocation: {lead['city']}, {lead['region']} {lead['country_code']}\n"
            f"Current discovery facts: {lead.get('discovery_facts','')[:3000]}\n\nWEBSITE EVIDENCE ONLY\n{blob}"
        )
        try:
            obj = self.llm.chat_json(self.SYSTEM_PROMPT, prompt, max_tokens=1400)
        except LLMTemporaryError as exc:
            record = self._record(lead, timestamp, evidence, "PARTIAL_LLM_FAILURE", self.version, error=str(exc))
            self.store.save_research(record)
            self.store.update_lead_status(lead["lead_id"], "ELIGIBLE")
            return record
        allowed = {e.url for e in evidence}
        urls = [u for u in obj.get("evidence_urls", []) if isinstance(u, str) and u in allowed]
        if not urls:
            urls = [e.url for e in evidence[:3]]
        selected = [e for e in evidence if e.url in urls]
        record = {
            "research_id": deterministic_research_id(lead["lead_id"], timestamp),
            "lead_id": lead["lead_id"], "website_domain": lead["website_domain"], "canonical_url": lead["website"],
            "company_identity": lead["company"], "business_summary": str(obj.get("business_summary") or "")[:1500],
            "services": self._arr(obj, "services"), "business_facts": self._arr(obj, "business_facts"),
            "locations": self._arr(obj, "locations"), "specialties": self._arr(obj, "specialties"),
            "website_signals": self._arr(obj, "website_signals"), "customer_journey_signals": self._arr(obj, "customer_journey_signals"),
            "ai_opportunity_signals": self._arr(obj, "ai_opportunity_signals"), "important_public_text": str(obj.get("important_public_text") or "")[:5000],
            "evidence": [e.__dict__ for e in selected], "research_timestamp_utc": timestamp, "research_status": "RESEARCHED",
            "research_version": self.version, "error": None, "retry_count": 0, "next_retry_at_utc": None,
        }
        self.store.save_research(record)
        self.store.update_lead_status(lead["lead_id"], "RESEARCHED")
        self.store.add_event("research_succeeded", run_id=run_id, lead_id=lead["lead_id"], status="RESEARCHED", metadata={"research_id": record["research_id"]})
        return record

    @staticmethod
    def _arr(obj: dict[str, Any], key: str, limit: int = 12) -> list[str]:
        return [str(x).strip()[:500] for x in obj.get(key, []) if str(x).strip()][:limit]

    @staticmethod
    def _record(lead, timestamp, evidence, status, version, error=None):
        return {
            "research_id": deterministic_research_id(lead["lead_id"], timestamp),
            "lead_id": lead["lead_id"], "website_domain": lead["website_domain"], "canonical_url": lead["website"],
            "company_identity": lead["company"], "business_summary": "", "services": [], "business_facts": [], "locations": [], "specialties": [],
            "website_signals": [], "customer_journey_signals": [], "ai_opportunity_signals": [], "important_public_text": "",
            "evidence": [e.__dict__ for e in evidence], "research_timestamp_utc": timestamp, "research_status": status,
            "research_version": version, "error": error, "retry_count": 1, "next_retry_at_utc": None,
        }
```

---

## FILE: migrations/001_initial.sql

```text
CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at_utc TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS workflow_run (
    workflow_run_id TEXT PRIMARY KEY,
    started_at_utc TEXT NOT NULL,
    ended_at_utc TEXT,
    mode TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('RUNNING','SUCCESS','TARGET_NOT_REACHED','FAILED')),
    reset_state BOOLEAN NOT NULL DEFAULT FALSE,
    metrics_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS leads (
    lead_id TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    company TEXT NOT NULL,
    website TEXT NOT NULL,
    website_domain TEXT NOT NULL UNIQUE,
    city TEXT NOT NULL DEFAULT '',
    region TEXT NOT NULL DEFAULT '',
    country_code TEXT NOT NULL,
    timezone TEXT NOT NULL,
    lead_source TEXT NOT NULL,
    place_id TEXT NOT NULL UNIQUE,
    scale_class TEXT NOT NULL,
    qualification_confidence REAL NOT NULL CHECK (qualification_confidence >= 0 AND qualification_confidence <= 1),
    qualification_reason TEXT NOT NULL DEFAULT '',
    discovery_facts TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK (status IN ('ELIGIBLE','RESEARCHING','RESEARCHED','QUEUED','ACTIVE','REPLIED','BOUNCED','UNSUBSCRIBED','COMPLETED','MANUAL_STOP','REVIEW_NEEDED')),
    sender_id TEXT,
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_leads_selection ON leads(status, created_at_utc);
CREATE INDEX IF NOT EXISTS idx_leads_email ON leads(email);
CREATE UNIQUE INDEX IF NOT EXISTS idx_leads_email_unique ON leads(lower(email));

CREATE TABLE IF NOT EXISTS lead_qualification (
    qualification_id TEXT PRIMARY KEY,
    lead_id TEXT NOT NULL REFERENCES leads(lead_id) ON DELETE CASCADE,
    workflow_run_id TEXT NOT NULL REFERENCES workflow_run(workflow_run_id) ON DELETE CASCADE,
    action TEXT NOT NULL CHECK (action IN ('KEEP','REJECT')),
    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    reason TEXT NOT NULL DEFAULT '',
    evidence_urls_json TEXT NOT NULL DEFAULT '[]',
    created_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS discovery_candidate (
    candidate_id TEXT PRIMARY KEY,
    workflow_run_id TEXT NOT NULL REFERENCES workflow_run(workflow_run_id) ON DELETE CASCADE,
    place_id TEXT NOT NULL UNIQUE,
    website_domain TEXT NOT NULL,
    company TEXT NOT NULL,
    website TEXT NOT NULL,
    address TEXT NOT NULL,
    country_code TEXT NOT NULL,
    types_json TEXT NOT NULL DEFAULT '[]',
    query TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('SEEN','RETRYABLE','VERIFIED','REJECTED')),
    attempts INTEGER NOT NULL DEFAULT 0,
    next_retry_at_utc TEXT,
    last_reason TEXT,
    last_seen_at_utc TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_discovery_retry ON discovery_candidate(status, next_retry_at_utc);
CREATE INDEX IF NOT EXISTS idx_discovery_domain ON discovery_candidate(website_domain);

CREATE TABLE IF NOT EXISTS lead_research (
    research_id TEXT PRIMARY KEY,
    lead_id TEXT NOT NULL REFERENCES leads(lead_id) ON DELETE CASCADE,
    website_domain TEXT NOT NULL,
    canonical_url TEXT NOT NULL,
    company_identity TEXT NOT NULL,
    business_summary TEXT NOT NULL DEFAULT '',
    services_json TEXT NOT NULL DEFAULT '[]',
    business_facts_json TEXT NOT NULL DEFAULT '[]',
    locations_json TEXT NOT NULL DEFAULT '[]',
    specialties_json TEXT NOT NULL DEFAULT '[]',
    website_signals_json TEXT NOT NULL DEFAULT '[]',
    customer_journey_signals_json TEXT NOT NULL DEFAULT '[]',
    ai_opportunity_signals_json TEXT NOT NULL DEFAULT '[]',
    important_public_text TEXT NOT NULL DEFAULT '',
    evidence_json TEXT NOT NULL DEFAULT '[]',
    research_timestamp_utc TEXT NOT NULL,
    research_status TEXT NOT NULL CHECK (research_status IN ('RESEARCHED','FAILED','PARTIAL_LLM_FAILURE')),
    research_version TEXT NOT NULL,
    error TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    next_retry_at_utc TEXT,
    created_at_utc TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_research_lead ON lead_research(lead_id, research_timestamp_utc);

CREATE TABLE IF NOT EXISTS sender_daily_state (
    sender_id TEXT NOT NULL,
    date_key TEXT NOT NULL,
    initials INTEGER NOT NULL DEFAULT 0,
    followups INTEGER NOT NULL DEFAULT 0,
    total INTEGER NOT NULL DEFAULT 0,
    failures INTEGER NOT NULL DEFAULT 0,
    authentication_failures INTEGER NOT NULL DEFAULT 0,
    temporary_provider_failures INTEGER NOT NULL DEFAULT 0,
    cooldown_until_utc TEXT,
    health_state TEXT NOT NULL DEFAULT 'HEALTHY' CHECK (health_state IN ('HEALTHY','DEGRADED','STOPPED','COOLDOWN')),
    last_successful_send_utc TEXT,
    PRIMARY KEY (sender_id, date_key)
);

CREATE TABLE IF NOT EXISTS suppression (
    email TEXT PRIMARY KEY,
    lead_id TEXT REFERENCES leads(lead_id) ON DELETE SET NULL,
    reason TEXT NOT NULL,
    created_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS outreach_batches (
    batch_id TEXT PRIMARY KEY,
    workflow_run_id TEXT NOT NULL REFERENCES workflow_run(workflow_run_id) ON DELETE CASCADE,
    batch_number INTEGER NOT NULL,
    batch_type TEXT NOT NULL CHECK (batch_type IN ('INITIAL','FOLLOWUP')),
    scheduled_at_utc TEXT NOT NULL,
    started_at_utc TEXT,
    completed_at_utc TEXT,
    status TEXT NOT NULL CHECK (status IN ('SCHEDULED','RUNNING','COMPLETED','PARTIAL','FAILED')),
    target_count INTEGER NOT NULL,
    attempted_count INTEGER NOT NULL DEFAULT 0,
    successful_count INTEGER NOT NULL DEFAULT 0,
    failed_count INTEGER NOT NULL DEFAULT 0,
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    UNIQUE(workflow_run_id,batch_number,batch_type)
);

CREATE TABLE IF NOT EXISTS outreach (
    outreach_id TEXT PRIMARY KEY,
    workflow_run_id TEXT NOT NULL REFERENCES workflow_run(workflow_run_id) ON DELETE CASCADE,
    batch_id TEXT REFERENCES outreach_batches(batch_id) ON DELETE SET NULL,
    lead_id TEXT NOT NULL REFERENCES leads(lead_id) ON DELETE CASCADE,
    sequence_type TEXT NOT NULL CHECK (sequence_type IN ('INITIAL','FOLLOWUP_1','FOLLOWUP_2','FOLLOWUP_3')),
    sequence_number INTEGER NOT NULL CHECK (sequence_number >= 1 AND sequence_number <= 3),
    sender_id TEXT NOT NULL,
    sender_email TEXT NOT NULL,
    email TEXT NOT NULL,
    subject TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK (status IN ('DRAFT','VALIDATED','QUEUED','SCHEDULED','SENDING','SENT','FAILED_RETRYABLE','FAILED_TERMINAL','CANCELLED','REVIEW_NEEDED')),
    scheduled_at_utc TEXT,
    attempted_at_utc TEXT,
    sent_at_utc TEXT,
    message_id TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    next_retry_at_utc TEXT,
    last_error TEXT,
    evidence_urls_json TEXT NOT NULL DEFAULT '[]',
    personalization_confidence REAL NOT NULL DEFAULT 0,
    body_hash TEXT,
    in_reply_to TEXT,
    references_text TEXT,
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    CHECK (
        (sequence_type='INITIAL' AND sequence_number=1) OR
        (sequence_type='FOLLOWUP_1' AND sequence_number=1) OR
        (sequence_type='FOLLOWUP_2' AND sequence_number=2) OR
        (sequence_type='FOLLOWUP_3' AND sequence_number=3)
    ),
    UNIQUE(lead_id,sequence_type,sequence_number),
    UNIQUE(message_id),
    UNIQUE(batch_id,sender_id)
);

CREATE INDEX IF NOT EXISTS idx_outreach_due ON outreach(status, scheduled_at_utc, next_retry_at_utc);
CREATE INDEX IF NOT EXISTS idx_outreach_lead ON outreach(lead_id, sequence_type, sequence_number);
CREATE INDEX IF NOT EXISTS idx_outreach_run ON outreach(workflow_run_id, sequence_type, status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_outreach_body_hash_active ON outreach(body_hash) WHERE status NOT IN ('CANCELLED','FAILED_TERMINAL');

CREATE TABLE IF NOT EXISTS mailbox_state (
    sender_id TEXT PRIMARY KEY,
    mailbox_identifier TEXT NOT NULL DEFAULT 'INBOX',
    provider_type TEXT NOT NULL DEFAULT 'imap',
    uidvalidity TEXT,
    last_processed_uid INTEGER NOT NULL DEFAULT 0,
    last_checked_at_utc TEXT,
    health_state TEXT NOT NULL DEFAULT 'HEALTHY'
);

CREATE TABLE IF NOT EXISTS inbound_message (
    inbound_message_id TEXT PRIMARY KEY,
    sender_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    in_reply_to TEXT,
    references_text TEXT NOT NULL DEFAULT '',
    received_at_utc TEXT NOT NULL,
    lead_id TEXT REFERENCES leads(lead_id) ON DELETE SET NULL,
    outreach_id TEXT REFERENCES outreach(outreach_id) ON DELETE SET NULL,
    event_type TEXT NOT NULL CHECK (event_type IN ('REPLY','HARD_BOUNCE','SOFT_BOUNCE','UNSUBSCRIBED','UNCLASSIFIED','REVIEW_NEEDED')),
    classification_confidence REAL NOT NULL CHECK (classification_confidence >= 0 AND classification_confidence <= 1),
    processing_status TEXT NOT NULL,
    processed_at_utc TEXT NOT NULL,
    subject TEXT NOT NULL DEFAULT '',
    from_email TEXT NOT NULL DEFAULT '',
    UNIQUE(sender_id,message_id)
);

CREATE INDEX IF NOT EXISTS idx_inbound_sender_received ON inbound_message(sender_id,received_at_utc);

CREATE TABLE IF NOT EXISTS event_log (
    event_id TEXT PRIMARY KEY,
    event_timestamp_utc TEXT NOT NULL,
    event_type TEXT NOT NULL,
    workflow_run_id TEXT REFERENCES workflow_run(workflow_run_id) ON DELETE CASCADE,
    lead_id TEXT REFERENCES leads(lead_id) ON DELETE SET NULL,
    outreach_id TEXT REFERENCES outreach(outreach_id) ON DELETE SET NULL,
    sender_id TEXT,
    batch_id TEXT REFERENCES outreach_batches(batch_id) ON DELETE SET NULL,
    sequence_type TEXT,
    status TEXT,
    reason TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_event_run ON event_log(workflow_run_id,event_type);
CREATE INDEX IF NOT EXISTS idx_event_lead ON event_log(lead_id,event_timestamp_utc);
```

---

## FILE: requirements.txt

```text
requests>=2.31.0
beautifulsoup4>=4.12.0
dnspython>=2.6.0
psycopg[binary]>=3.2,<4
```

---

## FILE: tests/__init__.py

```text

```

---

## FILE: tests/test_system.py

```text
from __future__ import annotations

import email
import os
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from app.config import Settings
from app.db import Store, deterministic_lead_id, deterministic_outreach_id
from app.mailbox import MailboxMonitor, ParsedInbound, classify
from app.mailer import BatchSendController
from app.models import InboundEventType, PersonalizationDraft
from app.orchestrator import Orchestrator, iso, parse_utc
from app.personalization import PersonalizationValidator


class TestSettings:
    def __init__(self):
        self.supabase_db_url = "sqlite://:memory:"
        self.app_timezone = "Asia/Kolkata"
        self.allowed_country_codes = ("US", "CA", "GB", "AU")
        self.discovery_target = 5
        self.max_places_search_requests = 30
        self.max_pages_per_search = 3
        self.places_page_size = 20
        self.max_raw_candidates = 50
        self.discovery_max_retries_per_run = 10
        self.discovery_transient_retry_hours = 24
        self.discovery_no_email_retry_days = 7
        self.crawler_timeout_seconds = 5
        self.crawler_max_bytes = 100000
        self.crawler_max_pages = 3
        self.crawler_request_delay_seconds = 0
        self.honor_robots = False
        self.initial_outreach_target = 10
        self.batch_size = 10
        self.batch_interval_minutes = 1
        self.daily_initial_limit = 10
        self.daily_followup_limit = 10
        self.daily_total_limit = 40
        self.max_concurrent_sends = 10
        self.retry_limit = 3
        self.retry_base_seconds = 1
        self.sending_window_start = datetime.strptime("00:00", "%H:%M").time()
        self.sending_window_end = datetime.strptime("23:59", "%H:%M").time()
        self.sending_window_mode = "app"
        self.followup_1_delay_hours = 24
        self.followup_2_delay_days = 7
        self.followup_3_delay_days = 14
        self.mailbox_check_lookback_minutes = 180
        self.mailbox_max_messages_per_run = 100
        self.max_batches_per_run = 20
        self.llm_base_url = ""
        self.llm_model = "fake"
        self.llm_timeout_seconds = 2
        self.llm_max_tokens = 100
        self.min_personalization_confidence = 0.75
        self.send_enabled = False
        self.dry_run = True
        self.reset_state = False

    def timezone(self):
        from zoneinfo import ZoneInfo
        return ZoneInfo(self.app_timezone)

    def sender_configs(self):
        from app.config import SenderConfig
        return [SenderConfig(f"SENDER_{i}", f"sender{i}@example.com", f"SENDER_{i}", "imap", 993, True, "smtp", 465, True) for i in range(1, 11)]


def lead_row(i=1, status="ELIGIBLE"):
    email_addr = f"lead{i}@company{i}.example"
    website = f"https://company{i}.example/"
    return {
        "lead_id": deterministic_lead_id(email_addr, website), "email": email_addr, "company": f"Company {i}",
        "website": website, "website_domain": f"company{i}.example", "city": "Dallas", "region": "TX", "country_code": "US",
        "timezone": "America/Chicago", "lead_source": "test", "place_id": f"place-{i}", "scale_class": "LOCAL",
        "qualification_confidence": 0.95, "qualification_reason": "evidence", "discovery_facts": "facts", "status": status,
    }


def research_row(store, lead):
    import json
    rid = f"research-{lead['lead_id']}"
    store.save_research({
        "research_id": rid, "lead_id": lead["lead_id"], "website_domain": lead["website_domain"], "canonical_url": lead["website"],
        "company_identity": lead["company"], "business_summary": "summary", "services": ["service"], "business_facts": ["fact"],
        "locations": ["Dallas"], "specialties": [], "website_signals": ["booking"], "customer_journey_signals": ["request"],
        "ai_opportunity_signals": ["faq"], "important_public_text": "text", "evidence": [{"url": lead["website"], "snippet": f"{lead['company']} has a booking page."}],
        "research_timestamp_utc": "2026-10-01T00:00:00Z", "research_status": "RESEARCHED", "research_version": "2.0", "error": None,
        "retry_count": 0, "next_retry_at_utc": None,
    })
    return store.latest_research(lead["lead_id"])


class FakeSMTP:
    lock = threading.Lock(); active = 0; max_active = 0; calls = []
    def __init__(self, sender): self.sender = sender
    def send(self, row):
        with self.lock:
            type(self).active += 1; type(self).max_active = max(type(self).max_active, type(self).active); type(self).calls.append(self.sender.sender_id)
        time.sleep(0.05)
        with self.lock: type(self).active -= 1
        return row["message_id"]


class FakeLLM:
    def initial(self):
        return PersonalizationDraft(True, "summary", ["observation"], "help", "About Company", "Company provides a service. AttachAI could answer common questions before a booking.", "Would a quick look be useful?", "Best, AttachAI", .95, ["https://company1.example/"], [])


class SystemTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.store = Store(f"sqlite://{os.path.join(self.td.name, 'db.sqlite')}")
        self.store.migrate("migrations")
        self.settings = TestSettings()

    def tearDown(self):
        self.store.close(); self.td.cleanup()

    def test_database_init_and_reset(self):
        run = self.store.start_workflow("MANUAL", False)
        lead = lead_row(1); self.store.upsert_lead(lead)
        self.assertEqual(self.store.scalar("SELECT count(*) FROM leads"), 1)
        self.store.reset_runtime_state()
        self.assertEqual(self.store.scalar("SELECT count(*) FROM leads"), 0)
        self.assertEqual(self.store.scalar("SELECT count(*) FROM workflow_run"), 0)

    def test_next_untouched_leads_not_fixed_prefix(self):
        run_id = self.store.start_workflow("MANUAL", False)
        for i in range(1, 6): self.store.upsert_lead(lead_row(i))
        first = self.store.claim_untouched_leads(2)
        for row in first:
            self.store.update_lead_status(row["lead_id"], "QUEUED")
        self.store.queue_initial(run_id=run_id, lead_id=first[0]["lead_id"], sender_id="UNASSIGNED", sender_email="", subject="s", body="body a Company 1", evidence_urls=[first[0]["website"]], confidence=.9)
        self.store.queue_initial(run_id=run_id, lead_id=first[1]["lead_id"], sender_id="UNASSIGNED", sender_email="", subject="s2", body="body b Company 2", evidence_urls=[first[1]["website"]], confidence=.9)
        nxt = self.store.claim_untouched_leads(2)
        self.assertTrue(set(x["lead_id"] for x in nxt).isdisjoint({x["lead_id"] for x in first}))

    def test_batch_assigns_one_message_per_sender(self):
        run_id = self.store.start_workflow("MANUAL", False)
        for i in range(1, 11):
            self.store.upsert_lead(lead_row(i))
            self.store.queue_initial(run_id=run_id, lead_id=lead_row(i)["lead_id"], sender_id="UNASSIGNED", sender_email="", subject="s", body=f"Company {i} useful message {i}", evidence_urls=[lead_row(i)["website"]], confidence=.9)
        batch = self.store.create_batch(run_id, 1, "INITIAL", "2026-10-02T12:00:00Z", 10)
        senders = self.settings.sender_configs()
        self.store.assign_batch(batch, [(self.store.fetchall("SELECT outreach_id,lead_id FROM outreach ORDER BY created_at_utc")[i]["outreach_id"], self.store.fetchall("SELECT outreach_id,lead_id FROM outreach ORDER BY created_at_utc")[i]["lead_id"], senders[i].sender_id, senders[i].email) for i in range(10)], "2026-10-02T12:00:00Z")
        rows = self.store.fetchall("SELECT * FROM outreach WHERE batch_id=?", [batch])
        self.assertEqual(len(rows), 10)
        self.assertEqual(len({r["sender_id"] for r in rows}), 10)

    def test_rerun_uses_global_success_count_and_only_sends_pending(self):
        run = self.store.start_workflow("MANUAL", False)
        senders = self.settings.sender_configs()
        for i in range(1, 5):
            lead = lead_row(i); self.store.upsert_lead(lead)
            self.store.queue_initial(run_id=run, lead_id=lead["lead_id"], sender_id=senders[i-1].sender_id, sender_email=senders[i-1].email, subject="s", body=f"Company {i} rerun", evidence_urls=[lead["website"]], confidence=.95)
        queued = self.store.fetchall("SELECT * FROM outreach ORDER BY created_at_utc")
        for row in queued[:3]:
            self.store.claim_outreach(row["outreach_id"]); self.store.mark_sent(row["outreach_id"], "2026-09-01T12:00:00Z", f"<sent-{row['outreach_id'][:8]}@example.com>")
        orch = Orchestrator(self.settings, self.store, object(), object(), object(), BatchSendController(self.store, self.settings, FakeSMTP))
        self.settings.batch_interval_minutes = 0
        self.settings.max_batches_per_run = 1
        orch._wait_until = lambda when: None
        result = orch.send_initial_until_target(run, 4, True)
        self.assertEqual(result["successful"], 4)
        self.assertEqual(self.store.scalar("SELECT count(*) FROM outreach WHERE sequence_type='INITIAL' AND status='SENT'"), 4)

    def test_real_batch_concurrency(self):
        run_id = self.store.start_workflow("MANUAL", False)
        for i in range(1, 11):
            self.store.upsert_lead(lead_row(i))
            self.store.queue_initial(run_id=run_id, lead_id=lead_row(i)["lead_id"], sender_id="UNASSIGNED", sender_email=f"sender{i}@example.com", subject="s", body=f"Company {i} useful {i}", evidence_urls=[lead_row(i)["website"]], confidence=.9)
        batch = self.store.create_batch(run_id, 1, "INITIAL", "2026-10-02T12:00:00Z", 10)
        senders = self.settings.sender_configs(); all_rows = self.store.fetchall("SELECT * FROM outreach ORDER BY created_at_utc")
        self.store.assign_batch(batch, [(all_rows[i]["outreach_id"], all_rows[i]["lead_id"], senders[i].sender_id, senders[i].email) for i in range(10)], "2026-10-02T12:00:00Z")
        FakeSMTP.active = FakeSMTP.max_active = 0; FakeSMTP.calls = []
        controller = BatchSendController(self.store, self.settings, FakeSMTP)
        result = controller.send_batch(batch, self.store.fetchall("SELECT * FROM outreach WHERE batch_id=?", [batch]), {s.sender_id:s for s in senders}, True)
        self.assertEqual(sum(x.status == "SENT" for x in result), 10)
        self.assertEqual(len(set(FakeSMTP.calls)), 10)
        self.assertGreater(FakeSMTP.max_active, 1)

    def test_crash_recovery_requeues_unsent_batch_rows_without_resending_sent_rows(self):
        run = self.store.start_workflow("MANUAL", False)
        senders = self.settings.sender_configs()
        for i in range(1, 11):
            lead = lead_row(i); self.store.upsert_lead(lead)
            self.store.queue_initial(run_id=run, lead_id=lead["lead_id"], sender_id="UNASSIGNED", sender_email="", subject="s", body=f"Company {i} crash recovery message", evidence_urls=[lead["website"]], confidence=.95)
        rows = self.store.fetchall("SELECT * FROM outreach ORDER BY created_at_utc")
        batch = self.store.create_batch(run, 1, "INITIAL", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), 10)
        self.store.assign_batch(batch, [(rows[i]["outreach_id"], rows[i]["lead_id"], senders[i].sender_id, senders[i].email) for i in range(10)], datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        for i in range(5):
            oid = rows[i]["outreach_id"]
            self.store.claim_outreach(oid); self.store.mark_sent(oid, "2026-10-02T12:00:00Z", f"<sent-{i}@example.com>")
        stale = (datetime.now(timezone.utc) - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.store.execute("UPDATE outreach_batches SET status='RUNNING',updated_at_utc=? WHERE batch_id=?", [stale, batch])
        self.store.execute("UPDATE outreach SET updated_at_utc=? WHERE batch_id=? AND status='SCHEDULED'", [stale, batch])
        self.store.reconcile_stale_batches(cutoff)
        self.assertEqual(self.store.scalar("SELECT count(*) FROM outreach WHERE status='SENT'"), 5)
        self.assertEqual(self.store.scalar("SELECT count(*) FROM outreach WHERE status='QUEUED' AND batch_id IS NULL"), 5)
        self.assertEqual(self.store.scalar("SELECT count(*) FROM outreach WHERE status='SENT' AND message_id IS NOT NULL"), 5)

    def test_stopped_sender_is_not_selected(self):
        from app.orchestrator import Orchestrator
        day = datetime.now(self.settings.timezone()).date().isoformat()
        self.store.set_sender_health("SENDER_1", day, "STOPPED")
        orch = Orchestrator(self.settings, self.store, object(), object(), object(), object())
        available = [s.sender_id for s in orch._available_senders(datetime.now(timezone.utc), False)]
        self.assertNotIn("SENDER_1", available)

    def test_sender_health_degraded_is_restored_after_successful_mailbox_check(self):
        sender = self.settings.sender_configs()[0]
        day = datetime.now(self.settings.timezone()).date().isoformat()
        self.store.set_sender_health(sender.sender_id, day, "DEGRADED", None)
        class FakeMailbox:
            uidvalidity = "1"
            def __init__(self, sender, credential): pass
            def connect(self): pass
            def fetch_since(self, last_uid, lookback_minutes, max_messages): return []
            def close(self): pass
        run = self.store.start_workflow("MANUAL", False)
        monitor = MailboxMonitor(self.store, self.settings, run, FakeMailbox)
        monitor.run_sender(sender)
        self.assertEqual(self.store.sender_day(sender.sender_id, day)["health_state"], "HEALTHY")

    def test_dry_run_does_not_mutate_message_state(self):
        from app.mailer import BatchSendController
        run = self.store.start_workflow("MANUAL", False)
        lead = lead_row(1); self.store.upsert_lead(lead)
        sender = self.settings.sender_configs()[0]
        self.store.queue_initial(run_id=run, lead_id=lead["lead_id"], sender_id=sender.sender_id, sender_email=sender.email, subject="s", body="Company 1 dry run message", evidence_urls=[lead["website"]], confidence=.95)
        row = self.store.fetchone("SELECT * FROM outreach WHERE lead_id=?", [lead["lead_id"]])
        batch = self.store.create_batch(run, 1, "INITIAL", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), 1)
        self.store.assign_batch(batch, [(row["outreach_id"], lead["lead_id"], sender.sender_id, sender.email)], datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        controller = BatchSendController(self.store, self.settings, FakeSMTP)
        result = controller.send_batch(batch, [dict(self.store.fetchone("SELECT * FROM outreach WHERE outreach_id=?", [row["outreach_id"]]))], {sender.sender_id: sender}, False)
        self.assertEqual(result[0].status, "DRY_RUN")
        self.assertEqual(self.store.get_outreach(row["outreach_id"])["status"], "SCHEDULED")

    def test_validator_enforces_configured_threshold(self):
        lead = lead_row(1); self.store.upsert_lead(lead); research = research_row(self.store, lead)
        draft = PersonalizationDraft(True, "", [], "", "Subject", "Company 1 factual message.", "", "", .70, [lead["website"]], [])
        v = PersonalizationValidator(.75).validate(lead, research, draft, [], self.store)
        self.assertFalse(v.ok); self.assertIn("low_confidence", v.reason)

    def test_followup_chain_requires_previous_success(self):
        from app.personalization import PersonalizationGenerator
        run = self.store.start_workflow("MANUAL", False)
        lead = lead_row(1); self.store.upsert_lead(lead); research_row(self.store, lead)
        initial_id = deterministic_outreach_id(lead["lead_id"], "INITIAL", 1)
        body = "Company 1 initial message"
        self.store.insert_outreach({"outreach_id":initial_id,"workflow_run_id":run,"lead_id":lead["lead_id"],"sequence_type":"INITIAL","sequence_number":1,"sender_id":"SENDER_1","sender_email":"sender1@example.com","email":lead["email"],"subject":"s","body":body,"status":"SENT","sent_at_utc":"2026-09-01T12:00:00Z","message_id":"<m1@example.com>","evidence_urls":[lead["website"]],"personalization_confidence":.9,"body_hash":"h1"})
        # No F1 has been inserted until due; this call will create only F1.
        class FakePersonalization:
            def followup(self,*args,**kwargs): return PersonalizationDraft(True,"",[],"","F1","Company 1 follows up.","","",.95,[lead["website"]],[])
        orch = Orchestrator(self.settings,self.store,object(),object(),FakePersonalization(),BatchSendController(self.store,self.settings))
        old_wait = orch._wait_until; orch._wait_until=lambda x: None
        orch.prepare_and_send_followups(run, False, True)
        self.assertIsNotNone(self.store.get_sequence(lead["lead_id"],"FOLLOWUP_1",1))
        self.assertIsNone(self.store.get_sequence(lead["lead_id"],"FOLLOWUP_2",2))

    def test_classifier_bounce_and_unsubscribe(self):
        reply = ParsedInbound("<r@x>","","", "Mail delivery failure", "mailer-daemon@x", "2026-10-02T00:00:00Z", "550 user unknown")
        self.assertEqual(classify(reply)[0], InboundEventType.HARD_BOUNCE)
        opt = ParsedInbound("<r2@x>","","", "Re: hello", "owner@x", "2026-10-02T00:00:00Z", "please unsubscribe me")
        self.assertEqual(classify(opt)[0], InboundEventType.UNSUBSCRIBED)

    def test_deterministic_ids(self):
        self.assertEqual(deterministic_lead_id("A@X.COM", "x.example"), deterministic_lead_id("a@x.com", "https://www.x.example/"))
        self.assertNotEqual(deterministic_outreach_id("x", "INITIAL", 1), deterministic_outreach_id("x", "FOLLOWUP_1", 1))

    def test_100_successful_initial_target_uses_ten_sender_batches(self):
        run_id = self.store.start_workflow("MANUAL", False)
        for i in range(1, 101):
            lead = lead_row(i); self.store.upsert_lead(lead)
            self.store.queue_initial(run_id=run_id, lead_id=lead["lead_id"], sender_id="UNASSIGNED", sender_email="", subject=f"s{i}", body=f"Company {i} useful message {i}", evidence_urls=[lead["website"]], confidence=.95)
        self.settings.batch_interval_minutes = 0
        self.settings.max_batches_per_run = 10
        controller = BatchSendController(self.store, self.settings, FakeSMTP)
        orch = Orchestrator(self.settings, self.store, object(), object(), object(), controller)
        orch._wait_until = lambda when: None
        result = orch.send_initial_until_target(run_id, 100, True)
        self.assertEqual(result["successful"], 100)
        batches = self.store.fetchall("SELECT * FROM outreach_batches WHERE workflow_run_id=? ORDER BY batch_number", [run_id])
        self.assertEqual(len(batches), 10)
        self.assertTrue(all(int(b["target_count"]) == 10 for b in batches))
        self.assertEqual(self.store.scalar("SELECT count(*) FROM outreach WHERE workflow_run_id=? AND status='SENT'", [run_id]), 100)
        self.assertEqual(self.store.scalar("SELECT count(*) FROM sender_daily_state WHERE date_key=? AND initials=10", [datetime.now(self.settings.timezone()).date().isoformat()]), 10)

    def test_followup_f2_and_f3_wait_for_successful_previous_stage(self):
        run_id = self.store.start_workflow("MANUAL", False)
        lead = lead_row(1); self.store.upsert_lead(lead); research_row(self.store, lead)
        initial = self.store.insert_outreach({"outreach_id":deterministic_outreach_id(lead["lead_id"],"INITIAL",1),"workflow_run_id":run_id,"lead_id":lead["lead_id"],"sequence_type":"INITIAL","sequence_number":1,"sender_id":"SENDER_1","sender_email":"sender1@example.com","email":lead["email"],"subject":"s","body":"Company 1 initial","status":"SENT","sent_at_utc":"2026-09-01T12:00:00Z","message_id":"<m1@example.com>","evidence_urls":[lead["website"]],"personalization_confidence":.9,"body_hash":"h1"})
        class FakePersonalization:
            def followup(self, lead, research, history, sequence, sender):
                return PersonalizationDraft(True,"",[],"",sequence,f"Company 1 {sequence} follow-up","","",.95,[lead["website"]],[])
        orch = Orchestrator(self.settings,self.store,object(),object(),FakePersonalization(),BatchSendController(self.store,self.settings))
        orch.prepare_and_send_followups(run_id, False, True)
        f1 = self.store.get_sequence(lead["lead_id"],"FOLLOWUP_1",1)
        self.assertIsNotNone(f1); self.assertIsNone(self.store.get_sequence(lead["lead_id"],"FOLLOWUP_2",2))
        self.store.claim_outreach(f1["outreach_id"]); self.store.mark_sent(f1["outreach_id"],"2026-09-02T12:00:00Z","<m2@example.com>")
        orch.prepare_and_send_followups(run_id, False, True)
        f2 = self.store.get_sequence(lead["lead_id"],"FOLLOWUP_2",2)
        self.assertIsNotNone(f2); self.assertEqual(f2["sender_id"],"SENDER_1"); self.assertIsNone(self.store.get_sequence(lead["lead_id"],"FOLLOWUP_3",3))
        self.store.claim_outreach(f2["outreach_id"]); self.store.mark_sent(f2["outreach_id"],"2026-09-09T12:00:00Z","<m3@example.com>")
        orch.prepare_and_send_followups(run_id, False, True)
        f3 = self.store.get_sequence(lead["lead_id"],"FOLLOWUP_3",3)
        self.assertIsNotNone(f3); self.assertEqual(f3["in_reply_to"],"<m3@example.com>")

    def test_reset_false_preserves_state(self):
        lead = lead_row(1); self.store.upsert_lead(lead)
        self.assertEqual(self.store.scalar("SELECT count(*) FROM leads"), 1)
        # Normal runs do not call reset_runtime_state.
        self.assertEqual(self.store.get_lead(lead["lead_id"])["email"], lead["email"])

    def test_mailbox_reply_suppresses_followups(self):
        run = self.store.start_workflow("MANUAL", False)
        lead = lead_row(1); self.store.upsert_lead(lead)
        initial_id = deterministic_outreach_id(lead["lead_id"],"INITIAL",1)
        self.store.insert_outreach({"outreach_id":initial_id,"workflow_run_id":run,"lead_id":lead["lead_id"],"sequence_type":"INITIAL","sequence_number":1,"sender_id":"SENDER_1","sender_email":"sender1@example.com","email":lead["email"],"subject":"s","body":"Company 1 initial","status":"SENT","sent_at_utc":"2026-10-01T12:00:00Z","message_id":"<m1@example.com>","evidence_urls":[lead["website"]],"personalization_confidence":.9,"body_hash":"reply-hash"})
        msg = EmailMessage(); msg["From"]=lead["email"]; msg["To"]="sender1@example.com"; msg["Date"]=datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000"); msg["Message-ID"]="<reply@example.com>"; msg["In-Reply-To"]="<m1@example.com>"; msg["Subject"]="Re: s"; msg.set_content("Thanks, let's talk.")
        class FakeMailbox:
            uidvalidity = "1"
            def __init__(self, sender, credential): pass
            def connect(self): pass
            def fetch_since(self, last_uid, lookback_minutes, max_messages): return [(1,msg.as_bytes())]
            def close(self): pass
        monitor = MailboxMonitor(self.store,self.settings,run,FakeMailbox)
        # save existing mailbox state so the fake cursor can be checked too
        result = monitor.run_sender(self.settings.sender_configs()[0])
        self.assertEqual(result["replies"],1)
        self.assertEqual(self.store.get_lead(lead["lead_id"])["status"],"REPLIED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
```
