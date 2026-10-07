# AttachAI 3.0

AttachAI is a durable outreach automation system whose production source of truth is Supabase/PostgreSQL. It discovers new businesses from Google Places, verifies public business email addresses, researches websites, generates evidence-grounded outreach, validates each draft deterministically, and sends SMTP messages with durable recovery and strict `INITIAL -> F1 -> F2 -> F3` sequencing.

## Architecture

`app/main.py` loads **one operational control file, `monitor.yaml`**, and applies only per-run overrides from the GitHub workflow. Secrets never live in the repository.

The runtime is split into one canonical implementation of each responsibility:

- `app/discovery.py` — Google Places discovery, candidate deduplication, MX/email checks, conservative qualification.
- `app/research.py` — the single bounded website crawler and DB-backed research cache.
- `app/llm.py` — the single NVIDIA/OpenAI-compatible JSON client with bounded retries and malformed-JSON handling.
- `app/personalization.py` — evidence contract, deterministic validation, and one repair attempt.
- `app/mailer.py` — SMTP delivery, stable Message-ID generation, 10-way concurrency, error classification.
- `app/mailbox.py` — incremental IMAP cursor, reply/bounce/unsubscribe classification and durable suppression.
- `app/db.py` — the only runtime persistence layer.
- `app/orchestrator.py` — durable phase orchestration and campaign-target semantics.

### Two durable levels: campaign vs workflow execution

A **campaign run** owns the requested `target_new_initials` and the successful count. A GitHub workflow invocation is a separate **workflow run** attached to that campaign.

That means a run that sends 27 successful INITIAL messages and then crashes keeps those 27. The next execution resumes the same unfinished campaign until its target is reached. After a campaign reaches 100 successful INITIAL sends, the next FULL run creates a new campaign target of 100.

## Database source of truth

The PostgreSQL schema lives in `migrations/001_initial.sql`. Runtime state is not stored in CSV, JSONL, local queues, or Git-tracked files.

Important durable records include:

- workflow/campaign execution
- discovery candidates
- leads and qualification
- reusable website research cache and lead research links
- personalization drafts and validator results
- SMTP sender health and daily counters
- outreach batches and per-sequence messages
- retries and error events
- mailbox UID cursor and inbound message fingerprints
- suppression state
- event log and metrics

Persisted timestamps use UTC.

## Setup

1. Create a Supabase project and obtain its PostgreSQL connection string.
2. Apply `migrations/001_initial.sql`, or let the application apply it on first startup.
3. Configure the secrets and variables described below.
4. Review `monitor.yaml` and keep automation disabled until you have completed the safe dry run.
5. Use the GitHub Actions **AttachAI** workflow for test/manual execution.

The application validates required production configuration at startup and fails clearly when required secrets are missing.

## GitHub Secrets

Required secrets:

- `SUPABASE_DB_URL`
- `NVIDIA_API_KEY`
- `GOOGLE_PLACES_API_KEY`
- `SENDER_1` through `SENDER_10` — sender SMTP/IMAP credentials

Never commit these values.

## GitHub Variables

Required sender identity variables:

- `SENDER_1_EMAIL` through `SENDER_10_EMAIL`

Optional provider overrides are read from environment variables, including `IMAP_HOST`, `IMAP_PORT`, `IMAP_USE_SSL`, `NVIDIA_BASE_URL`, and `NVIDIA_MODEL`.

## monitor.yaml

`monitor.yaml` is the human-editable operational control plane. It controls:

- automation enabled/disabled
- outreach and follow-up schedules
- pipeline enable/disable flags
- default new-initial target
- batch size and concurrency
- send-window enforcement
- daily sender limits
- retry policy and SMTP lease timeout
- discovery categories/countries/budget/overage buffer
- crawler limits and robots behavior
- LLM limits
- follow-up delays
- mailbox lookback
- emergency stop

Safe defaults are intentionally off for automatic scheduling, real sending, send windows, and daily caps, with a zero artificial batch gap.

### Important GitHub scheduling detail

GitHub Actions cannot wake up just because a local YAML file contains a cron expression. The production workflow therefore polls every 15 minutes. `app/monitor.py` reads `monitor.yaml` and decides whether the outreach and/or follow-up schedule is due. To activate automation later, change `automation.enabled` to `true` in `monitor.yaml`; do not add a second competing workflow or hidden cron.

## Manual workflow inputs

The production workflow exposes:

- `reset_state`
- `target_new_initials` (default `100`)
- `send_enabled`
- `dry_run`
- `process_followups`
- `process_new_outreach`

These support FULL, FOLLOWUPS ONLY, NEW OUTREACH ONLY, and RESUME/RECOVERY behavior without source-code edits.

## First safe dry run

Use:

```text
reset_state = true
target_new_initials = 100
send_enabled = false
dry_run = true
process_followups = true
process_new_outreach = true
```

This validates discovery/research/personalization and leaves sendable INITIAL rows durable in the database. Dry-run rows do not become `SENT` and no real SMTP call is made.

## First real test

After checking the queued messages and provider credentials, use:

```text
reset_state = false
target_new_initials = 100
send_enabled = true
dry_run = false
process_followups = true
process_new_outreach = true
```

The target is **100 successful SMTP accepts**, not 100 discovered leads or 100 queued rows. The run keeps replenishing discovery inventory when candidates fail research, qualification, personalization, email extraction, or SMTP delivery.

## Run 2 / Run 3 behavior

### Run 2

The FULL run first syncs the mailboxes and processes due follow-ups from prior successful sequences. It then works on the unfinished/new campaign target. When Run 1 has already succeeded, a fresh campaign target of 100 NEW INITIAL sends is created.

### Run 3 and later

Each FULL run independently processes any follow-ups that are actually due and then works toward another fresh 100-INITIAL campaign once the previous campaign is complete.

A follow-up can only be created after the immediately previous sequence is `SENT`:

`INITIAL -> F1 -> F2 -> F3`

Replies, hard bounces, and unsubscribe events durably suppress future follow-ups. Each sequence preserves the immediately previous successful sender and threads with `In-Reply-To`/`References`.

## Resume and crash recovery

Startup reconciliation handles durable leases:

- stale research work is moved back to retryable state
- stale scheduled sends are requeued
- stale `SENDING` rows are moved to `REVIEW_NEEDED` because SMTP acceptance may be ambiguous; they are **not** blindly resent
- successful `SENT` rows are never resent
- follow-up sequence rows are created only after the predecessor is successfully sent

The database uniqueness constraints protect duplicate lead email identities, Google Place IDs, lead+sequence messages, SMTP Message-IDs, and inbound sender+message IDs.

## Reset behavior

`reset_state=true` clears only application runtime/campaign data. It does not remove GitHub secrets/variables and does not require dropping the Supabase project.

## Logs and metrics

Runtime logs are structured JSON and include milestones for:

`START`, discovery, qualification, research, personalization, queueing, batch execution, mailbox sync, follow-ups, and `FINAL_SUMMARY`.

Final metrics distinguish raw/deduplicated candidates, qualified/researched/research failures, personalization rejection, ready/queued/attempted sends, successful INITIAL sends, retryable/terminal failures, follow-ups, replies, bounces, unsubscribes, suppression, remaining target, status, per-stage duration, and total runtime.

A batch log includes batch id/number, planned, attempted, successful, failed, senders used, and duration.

## Local tests

The deterministic suite uses SQLite and fake providers. It never sends real email or calls external providers.

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -p 'test_*.py' -v
```

## Troubleshooting

**Google Places failures:** the discovery provider is bounded and retries transient HTTP failures. A run continues with other query/page work and stops with a precise target-not-reached reason when the configured discovery/provider budget is exhausted.

**NVIDIA 503/timeouts/invalid JSON:** `app/llm.py` classifies transient failures separately, retries with bounded exponential backoff, and treats malformed provider content as an isolated item failure. One bad LLM call does not terminate the whole campaign.

**Website failures:** the crawler is bounded by timeout, response size, page count, and robots policy. Temporary research failures become retryable and can be replenished with newly discovered candidates.

**SMTP failures:** temporary/provider/network failures are retryable; authentication failures stop the sender; terminal recipient/address failures become terminal for that message. Other senders continue in parallel.

**Mailbox failures:** mailbox state is marked degraded and the new-outreach pipeline is not destroyed. The next run retries mailbox processing.

## External provider requirements / remaining limitations

This repository is the complete application architecture, but successful production operation still depends on external services being correctly configured and available: Supabase/PostgreSQL, Google Places API access, the NVIDIA-compatible LLM endpoint/model, DNS resolution for MX, sender SMTP/IMAP access, and deliverability policies controlled by those providers.

The system deliberately does not pretend that an ambiguous `SENDING` SMTP state can be proven safe to resend from inside the same process. Such rows go to durable `REVIEW_NEEDED` instead of risking duplicate outreach.
