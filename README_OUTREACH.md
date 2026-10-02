# AttachAI Outreach Engine

This bundle adds a client-isolated outreach layer beside the existing `google-place` Lead Engine. The Lead Engine remains the source of eligible leads; the outreach code consumes verified rows from `leads_crm.csv` through a read-only adapter. That preserves the existing discovery behavior rather than duplicating Google Places, crawling, email extraction, or qualification. The build requirements explicitly call for this separation and for client-scoped, stateless LLM requests. fileciteturn0file0L43-L97 fileciteturn0file0L209-L240

## Architecture

`leads_crm.csv`
→ `LeadEngineCSV`
→ deterministic `LeadID`
→ website research with evidence
→ structured LLM research
→ client-scoped personalization
→ deterministic quality validation
→ persistent outreach queue
→ persistent sender assignment
→ controlled SMTP send
→ exact `sent_at_utc`
→ incremental IMAP monitoring
→ reply / bounce / unsubscribe state transitions
→ follow-up eligibility
→ follow-up generation and validation
→ final state.

Operational state lives in a transactional SQLite database for local development and a Postgres database for production. The GitHub runner filesystem is treated as ephemeral; production workflows therefore require `OUTREACH_DATABASE_URL` and never commit the outreach database to Git.

## Local setup

Python 3.11+ is required.

```bash
python -m pip install -r requirements.txt -r requirements-outreach.txt
cp .env.example .env
```

For a safe local dry run, leave `SEND_ENABLED=false` and `DRY_RUN=true`, point `CRM_FILE` at a copy of the CRM, and use a local SQLite path:

```bash
CRM_FILE=leads_crm.csv OUTREACH_DB_PATH=runtime/outreach.db SEND_ENABLED=false DRY_RUN=true python -m app.main dry_run --lead-limit 100
```

## Modes

`all` runs intake, research, personalization, mailbox monitoring, follow-up generation, and any currently due sends.

`research_only` imports verified CRM rows and refreshes missing research.

`personalization_only` uses existing research to create and queue initial messages.

`send_only` sends only already-queued or retryable messages that are currently eligible.

`followup_only` creates and sends due follow-ups with a mailbox refresh before each follow-up send when configured.

`mailbox_check_only` performs only IMAP monitoring.

`dry_run` exercises intake/research/personalization/queue logic and simulates sends without calling SMTP.

## GitHub Secrets

Required existing secrets:

- `NVIDIA_API_KEY`
- `GOOGLE_PLACES_API_KEY`
- `SENDER_1` … `SENDER_10`

Required new operational secret:

- `OUTREACH_DATABASE_URL` — private Postgres connection string for production persistence.

Sender credentials are read only from the corresponding `SENDER_n` secret. They are never written to CSV, JSON, source, logs, README files, or workflow output. This matches the credential handling requirements. fileciteturn0file0L512-L553

## GitHub Variables

Core variables:

- `APP_TIMEZONE=Asia/Kolkata`
- `DAILY_NEW_LEADS_TARGET=100`
- `DAILY_NEW_OUTREACH_TARGET=100`
- `SENDER_COUNT=10`
- `DAILY_NEW_OUTREACH_LIMIT_PER_SENDER=10`
- `DAILY_FOLLOWUP_LIMIT_PER_SENDER=10`
- `DAILY_TOTAL_LIMIT_PER_SENDER=40`
- `SEND_INTERVAL_MINUTES=10`
- `FOLLOWUP_1_DELAY_HOURS=24`
- `FOLLOWUP_2_DELAY_DAYS=7`
- `FOLLOWUP_3_DELAY_DAYS=14`
- `SENDING_WINDOW_START=18:00`
- `SENDING_WINDOW_END=20:00`
- `MAILBOX_PROVIDER=imap`
- `IMAP_HOST=imap.gmail.com`
- `IMAP_PORT=993`
- `IMAP_USE_SSL=true`
- `MAILBOX_CHECK_LOOKBACK_MINUTES=180`
- `MAILBOX_MAX_MESSAGES_PER_RUN=100`
- `REQUIRE_FRESH_MAILBOX_CHECK_BEFORE_FOLLOWUP=true`
- `MAX_CONCURRENT_SENDS=1`
- `MAX_RETRIES=3`
- `RETRY_BASE_SECONDS=60`
- `RESEARCH_PROMPT_VERSION=1.0`
- `OUTREACH_PROMPT_VERSION=1.0`
- `FOLLOWUP_PROMPT_VERSION=1.0`
- `QUALITY_PROMPT_VERSION=1.0`
- `MIN_PERSONALIZATION_CONFIDENCE=0.75`

Sender identity variables:

- `SENDER_1_EMAIL` … `SENDER_10_EMAIL`

Optional per-sender overrides are supported as `SENDER_n_IMAP_HOST`, `SENDER_n_IMAP_PORT`, `SENDER_n_IMAP_USE_SSL`, `SENDER_n_SMTP_HOST`, `SENDER_n_SMTP_PORT`, and `SENDER_n_SMTP_USE_SSL`.

## IMAP

IMAP over TLS is the required inbound provider. Gmail API/OAuth is not required and can be added later behind the same provider abstraction. Each sender has independent credentials and mailbox state.

The monitor stores mailbox metadata, not private reply bodies. It tracks `UIDVALIDITY`, `last_processed_uid`, last check time, and health state. UIDVALIDITY changes cause a bounded-lookback resync; inbound messages remain idempotent through a unique `(SenderID, MessageID)` key.

Reply correlation prefers Message-ID, In-Reply-To, References, sender mailbox/account, and known recipient relationship before any subject-based evidence. A reply moves the lead to `REPLIED` and cancels future follow-ups. Hard bounces suppress the original recipient. Soft bounces are recorded without permanent suppression. Clear opt-outs create persistent suppression. Ambiguous classifications remain non-destructive. These behaviors match the required mailbox and suppression rules. fileciteturn0file0L631-L741 fileciteturn0file0L743-L834

Expected mailbox detection delay is generally up to the mailbox workflow cadence plus GitHub schedule delay. The hourly workflow in this bundle does not provide real-time monitoring. The sender workflow performs an additional mailbox refresh immediately before each follow-up send when `REQUIRE_FRESH_MAILBOX_CHECK_BEFORE_FOLLOWUP=true`. This follows the explicit “do not claim real-time monitoring” requirement. fileciteturn0file0L1333-L1349

## Send safety

Before a send, the controller checks state, suppression, sender health, daily limits, send spacing, configured sender identity, sending window, and (for follow-ups) fresh mailbox state. `SENT` records are never selected for sending. `SENDING` records left behind by an interrupted run are reconciled to `REVIEW_NEEDED` rather than automatically resent, which avoids the dangerous “SMTP accepted but process crashed before DB commit” duplicate-send ambiguity.

Production send is fail-closed: `SENDER_COUNT` must be exactly 10, all 10 sender addresses must be configured, all 10 credential secrets must be present, `SEND_ENABLED=true`, `DRY_RUN=false`, and a persistent Postgres URL must be configured.

## Scheduling

The daily orchestrator is scheduled for `11:30 UTC` (`17:00 IST`). The separate controlled sender worker runs every 10 minutes and sends only when a queued message is actually due and the configured recipient sending window permits it. The mailbox monitor runs hourly. GitHub schedule execution is not assumed to occur at an exact second. The separation keeps the runner finite and makes the sender cadence configurable. The build requirement specifically calls for GitHub Actions to be the scheduler/orchestrator rather than a permanent process. fileciteturn0file0L1297-L1329

## Follow-ups

Exactly three follow-ups are supported. They are anchored to the successful initial `sent_at_utc`, not generation time or workflow time:

- `FOLLOWUP_1`: +24 hours
- `FOLLOWUP_2`: +7 days
- `FOLLOWUP_3`: +14 days

Follow-ups are not generated after a reply, hard bounce, unsubscribe, suppression, or manual stop. After `FOLLOWUP_3` is successfully sent, the lead is marked `COMPLETED`. This uses the actual successful send timestamp as the anchor, as required. fileciteturn0file0L865-L928

## Storage schema

The database contains:

`leads`, `research`, `outreach`, `sender_daily_state`, `suppression`, `event_log`, `workflow_run`, `mailbox_state`, and `inbound_message`.

The stable identifiers are:

- `LeadID = sha256(normalized_email + normalized_website_host)`
- `ResearchID = sha256(LeadID + research_timestamp_utc)`
- `OutreachID = sha256(LeadID + ':' + SequenceType + ':' + SequenceNumber)`
- `SequenceKey = LeadID:SequenceType:SequenceNumber`

The schema deliberately keeps research, outreach, inbound events, suppression, and credentials separate. That reflects the required data-retention boundaries. fileciteturn0file0L1055-L1103 fileciteturn0file0L1977-L1993

## Existing Lead Engine integration

The existing repository currently uses `lead_collector.py`, a CSV CRM, JSONL memory/retry files, and a single lead-discovery workflow. The latest observed GitHub Action run for that workflow completed successfully. The outreach adapter consumes only verified CRM rows and does not reproduce Google Places discovery or the Lead Engine’s public website/email/qualification logic.

One repository inconsistency was observed but not changed: `.github/workflows/lead-discovery.yml` currently uses cron `20 6 * * *` (11:50 IST), while the README text says `23:47 IST / 18:17 UTC`. The build intentionally leaves this existing workflow untouched rather than changing working lead-discovery behavior without an integration reason.

## Deployment

1. Add `OUTREACH_DATABASE_URL` as a GitHub Secret pointing at a private Postgres database.
2. Add `SENDER_1` … `SENDER_10` as GitHub Secrets containing the mailbox SMTP/IMAP credentials or app passwords required by the ten configured accounts.
3. Add `SENDER_1_EMAIL` … `SENDER_10_EMAIL` as GitHub Variables.
4. Add the remaining operational variables with the values documented above.
5. Apply the `app/`, `tests/`, `.github/workflows/`, `.env.example`, `.gitignore`, and `requirements-outreach.txt` files from this bundle to the `google-place` repository.
6. Run the workflow manually with `mode=dry_run`, `dry_run=true`, and `send_enabled=false`.
7. Validate the Postgres schema, sender connections, and IMAP monitoring using `sender_test_mode` / `mailbox_check_only` before enabling the scheduled sender worker.
8. Enable the scheduled workflows only after mailbox correlation and suppression behavior has been verified against the real accounts.

## Known limitations / not tested here

The runtime environment used for this implementation is not connected to the production repository with write permissions, so the remote repository itself was not modified. The bundle is the implementation artifact to apply.

Live NVIDIA API calls, Google Places calls, real website crawls against the production CRM, live SMTP sends, live IMAP connections, and a real Postgres server were not exercised in this environment. Postgres code paths are implemented, but the local runtime did not have `psycopg` installed, so Postgres execution is explicitly **NOT TESTED** here.

GitHub Actions schedule semantics can delay runs. IMAP monitoring is periodic, not real-time. SMTP cannot provide a transactional two-phase commit with the external mailbox server; after a crash during SMTP, this implementation chooses `REVIEW_NEEDED` rather than automatically retrying and risking a duplicate.
