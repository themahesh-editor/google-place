# AttachAI project map

## Primary objective

Maintain a durable, resumable outreach campaign whose target is a number of new, successfully accepted initial SMTP messages, not drafts or queued rows. PostgreSQL is the durable source of truth. A real campaign must never automatically resend a message with an ambiguous SMTP acceptance result.

## End-to-end data flow

1. **Control plane and entry points** — monitor.yaml holds non-secret controls; attachai/config.py validates controls and separately loads environment secrets; attachai/cli.py exposes diagnostic, migration, scheduled, run, and operator-review commands.
2. **Discovery** — providers.py Discovery queries Google Places. engine.py discover uses per-query durable page tokens in attachai.discovery_cursor and persists candidates by Place ID.
3. **Qualification and research** — Engine.prepare_candidates applies website/rating/review thresholds. Research fetches robots.txt and same-origin pages within DNS/IP, redirect, TLS, byte, page, and deadline bounds; evidence snippets must be usable and remain traceable to page text.
4. **Lead and draft preparation** — crawl output supplies public contact addresses and evidence. LLM.draft returns structured fields; deterministic validation in providers.py blocks unsupported observations and bodies.
5. **Delivery and response handling** — Engine.send_batch coordinates sender assignment, attempts, cooldowns, and bounded concurrency. SMTP.send distinguishes pre-DATA failures from unknown post-DATA outcomes. Mailbox.sync parses bounded mailbox events; engine logic deduplicates inbound events and suppresses replies, hard bounces, and opt-outs.
6. **Durability and recovery** — db.py Store coordinates a PostgreSQL advisory lock, numbered SQL migrations, durable campaign/message state, transaction boundaries, audit events, and operator review. Migration SQL enforces message/follow-up invariants at the database level.
7. **Scheduling and deployment** — scheduling.py maps polling times to due UTC slots; .github/workflows/attachai.yml is the production runner; .github/workflows/tests.yml runs the network-free test suite with disposable PostgreSQL integration tests. The production workflow must not be used as a development test harness.

## Core invariants

- Keep reset_state=false for normal recovery. Reset erases contact/suppression history and is destructive.
- Continue an unfinished real campaign with its original target; successful initial sends are counted from sent message rows.
- Never auto-resend review/ambiguous SMTP outcomes; resolve only from authoritative provider evidence.
- Never weaken public-IP validation, hostname/SNI certificate checks, same-origin redirect enforcement, HTTPS downgrade rejection, robots enforcement, or response/time bounds.
- Never put provider secrets, sender passwords, database URLs, recipient addresses, or raw LLM responses in diagnostics.
- Do not use production credentials or send real SMTP as part of verification.

## Review scope and limits

Review source, tests, control files, migrations, CI and production workflow for control-flow defects, error classification, resource bounds, data recovery, and safety invariant regressions. Tests use mocked provider adapters and a disposable PostgreSQL database. A passing suite does not certify live provider quotas, SMTP deliverability, or a production Supabase deployment.
