# AttachAI verification and deployment boundaries

## Verification status for this rebuild

The codebase includes unit tests and PostgreSQL integration tests described below, but a successful result must be recorded only after running them against the declared test dependencies and a disposable PostgreSQL database. A passing local check is not evidence that a production Supabase project, sender credentials, provider billing, or email delivery works.

Development must not use production credentials or a production database. No real SMTP send or production-data mutation is part of the development test plan. Read-only diagnostics must be exercised before any migration or campaign run.

## Automated coverage

* Configuration defaults and boolean parsing; unknown/duplicate YAML controls; TLS-required remote PostgreSQL URLs; safe redaction; sender JSON schema, duplicate keys, account identity, and limits.
* CLI fail-closed behavior, safe scheduled no-ops, safe manual defaults, read-only diagnostic execution without locks/migrations/campaigns, and safe failures.
* Numbered and idempotent schema migrations, legacy-table refusal, application database constraints, advisory-lock exclusion, and diagnostic checks that leave row counts unchanged.
* Resumable real campaign targets, uniqueness/deduplication, interruption recovery, ambiguous SMTP review rather than automatic resend, durable delivery events, and atomic operator-review history.
* Follow-up predecessor/sender/thread rules, due-time calculations, replies/bounces/unsubscribes and suppression handling, mailbox event deduplication, and cursor transaction safety.
* Dry-run workflow behavior, bounded retries, mocked Google Places/LLM/SMTP/IMAP providers, provider error classification, and email-content evidence validation.

The GitHub CI workflow provisions a PostgreSQL 16 service and runs Python 3.11 tests. Provider integrations are mocked in CI; CI must not receive production API keys, database credentials, or live sender accounts.

## Safe deployment gates

1. Back up the correct Supabase project and verify a restore to a disposable database before changing a populated deployment.
2. Run `python -m attachai.cli diagnose` (or set `diagnostic_only=true` in the GitHub Actions workflow). It must not write rows, take campaign locks, migrate, or process leads.
3. Inspect schema status. A populated legacy `public.outreach` or `public.suppression` table is a stop condition; use a separately reviewed legacy history/sequence conversion. The new system does not silently import legacy follow-up chains.
4. Run migrations deliberately and confirm the schema version, then use a dry-run and inspect persisted campaign/review/suppression state.
5. Only after separate authorization, set `send_enabled=true` and `dry_run=false`. Inspect provider acceptance logs and persisted state before enabling scheduled automation.

## Not verified by automated tests

* Actual production Supabase reachability, privileges, pooling mode, TLS configuration, restore readiness or migration outcome.
* Valid billing/quota, live authorization of Google Places/LLM API keys, deliverability, mailbox configuration or SMTP/IMAP authentication.
* Inbox placement, recipient suitability/consent, or perfect reply/bounce/unsubscribe classification.
* Unconditional fulfillment of a requested campaign target when providers, discovery budgets, sender accounts, or runtime are exhausted.
* Automatic resolution of ambiguous SMTP acceptance; authoritative provider evidence and operator review remain required.
* GitHub schedule punctuality or backfill guarantees.
