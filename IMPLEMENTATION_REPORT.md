# AttachAI Outreach Engine — Implementation Report

## Repository inspection

Inspected the actual public repository `themahesh-editor/google-place` before implementation.

Observed root components include `lead_collector.py`, `.github/workflows/lead-discovery.yml`, `tests/test_lead_collector.py`, `leads_crm.csv`, `seen_domains.csv`, `candidate_memory.jsonl`, `retry_queue.csv`, `run_log.jsonl`, `README.md`, `README_FIXES.md`, `requirements.txt`, and `.env.example`.

The current Lead Engine pipeline is preserved as the discovery authority. The current lead-discovery workflow was observed to run Python 3.11, execute the existing test suite, run `lead_collector.py`, and commit its CRM/memory files back to `main`.

## Files created in this bundle

- `app/config.py`
- `app/models.py`
- `app/storage/repository.py`
- `app/integrations/lead_engine.py`
- `app/research/crawler.py`
- `app/research/research_service.py`
- `app/llm/client.py`
- `app/personalization/prompts.py`
- `app/personalization/generator.py`
- `app/personalization/validator.py`
- `app/outreach/queue.py`
- `app/outreach/scheduler.py`
- `app/outreach/state.py`
- `app/outreach/health.py`
- `app/followups/scheduler.py`
- `app/followups/generator.py`
- `app/email/provider.py`
- `app/email/smtp_provider.py`
- `app/email/mailbox_provider.py`
- `app/email/imap_mailbox.py`
- `app/email/message_parser.py`
- `app/email/classifier.py`
- `app/email/monitor.py`
- `app/suppression/service.py`
- `app/reporting/metrics.py`
- `app/main.py`
- `tests/test_outreach_engine.py`
- `.github/workflows/outreach-engine.yml`
- `.github/workflows/outreach-send.yml`
- `.github/workflows/outreach-mailbox.yml`
- `.github/workflows/outreach-tests.yml`
- `.env.example`
- `.gitignore`
- `requirements-outreach.txt`
- `README_OUTREACH.md`
- `APPLY.md`
- `IMPLEMENTATION_REPORT.md`

## Existing files modified

None in the remote repository. The connected GitHub session reports pull-only repository permissions and a write attempt was rejected. This bundle is therefore the tested local implementation to apply to the repository.

## Storage schema

Production backend: Postgres via `psycopg[binary]`.

Local backend: SQLite.

Tables: `leads`, `research`, `outreach`, `sender_daily_state`, `suppression`, `event_log`, `workflow_run`, `mailbox_state`, `inbound_message`.

Persistent state covers sender assignment, exact sent time, sequence state, retries, suppression, mailbox cursor/UIDVALIDITY, inbound idempotency, events, and sender health.

## State machine

Lead: `NEW → ELIGIBLE → RESEARCHING → RESEARCHED → OUTREACH_PREPARED → SCHEDULED → ACTIVE → REPLIED | BOUNCED | UNSUBSCRIBED | COMPLETED`.

Message: `DRAFT → VALIDATED → QUEUED → SCHEDULED → SENDING → SENT`, with `FAILED_RETRYABLE`, `FAILED_TERMINAL`, `CANCELLED`, and `REVIEW_NEEDED` outcomes.

## Tests executed

Local command:

`python -m unittest discover -s tests -p 'test_*.py' -v`

Result: **27 tests passed**.

Coverage includes CRM ingestion, deterministic IDs, client isolation, evidence validation, duplicate prevention, suppression, unsubscribe, hard/soft bounce classification, reply correlation, follow-up timing, sender persistence, sender limits, spacing, atomic claims, retry states, workflow interruption recovery, dry-run no-send behavior, UIDVALIDITY rebasing, and production secret/config validation.

Additional checks:

- Python `compileall`: passed.
- YAML parsing for the 4 new workflows: passed.
- CLI dry-run smoke test with an empty CRM: passed; zero sends were attempted.

## Dry-run result

Executed:

`CRM_FILE=smoke/empty_leads.csv OUTREACH_DB_PATH=smoke/dryrun.db SEND_ENABLED=false DRY_RUN=true python -m app.main dry_run --lead-limit 100`

Observed: `send_results=[]`, zero new leads, zero queued, zero sent, zero replies/bounces/unsubscribes/mailbox checks.

## Production workflows

- `outreach-engine.yml`: daily orchestration at 17:00 IST / 11:30 UTC; manual dispatch with dry-run default.
- `outreach-send.yml`: every 10 minutes; sends only due, eligible messages inside configured windows.
- `outreach-mailbox.yml`: hourly IMAP monitor.
- `outreach-tests.yml`: tests on push/PR and manual dispatch.

All workflows use read-only repository permissions. Operational state is external to the runner filesystem.

## GitHub Secrets

`NVIDIA_API_KEY`, `GOOGLE_PLACES_API_KEY`, `OUTREACH_DATABASE_URL`, `SENDER_1` … `SENDER_10`.

## GitHub Variables

`APP_TIMEZONE`, `DAILY_NEW_LEADS_TARGET`, `DAILY_NEW_OUTREACH_TARGET`, `SENDER_COUNT`, `DAILY_NEW_OUTREACH_LIMIT_PER_SENDER`, `DAILY_FOLLOWUP_LIMIT_PER_SENDER`, `DAILY_TOTAL_LIMIT_PER_SENDER`, `SEND_INTERVAL_MINUTES`, `FOLLOWUP_1_DELAY_HOURS`, `FOLLOWUP_2_DELAY_DAYS`, `FOLLOWUP_3_DELAY_DAYS`, `SENDING_WINDOW_START`, `SENDING_WINDOW_END`, `MAILBOX_PROVIDER`, `IMAP_HOST`, `IMAP_PORT`, `IMAP_USE_SSL`, `MAILBOX_CHECK_LOOKBACK_MINUTES`, `MAILBOX_MAX_MESSAGES_PER_RUN`, `REQUIRE_FRESH_MAILBOX_CHECK_BEFORE_FOLLOWUP`, `MAX_CONCURRENT_SENDS`, `MAX_RETRIES`, `RETRY_BASE_SECONDS`, prompt-version variables, `MIN_PERSONALIZATION_CONFIDENCE`, NVIDIA endpoint/model variables, crawler variables, and `SENDER_1_EMAIL` … `SENDER_10_EMAIL`.

## Not tested

- Remote GitHub write/integration.
- Live NVIDIA API.
- Live Google Places API.
- Live production website crawling.
- Live SMTP.
- Live IMAP.
- Live Postgres execution (`psycopg` was not installed in this runtime).
- Real production GitHub Action runs for the new workflows.

No claim of “production ready” or “working in production” is made from these tests alone.
