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
