# AttachAI — durable outreach, not a local queue

Python 3.11+ • PostgreSQL / Supabase • Google Places Text Search (New) • one structured LLM client • SMTP/IMAP

**Safe on checkout:** automatic campaigns are disabled, SMTP is disabled, and dry-run is enabled. Sending windows, daily sender/total caps and artificial batch waits are OFF. Due follow-up delays remain active. Nothing is sent just because this repository is pushed.

## What a campaign means

A logical **real campaign** requests a target of *new successful INITIAL SMTP sends*, normally 100. Queued messages, drafts, dry-run results and previous campaigns' successes do not count. An interrupted campaign resumes its existing durable progress before another real campaign starts. A completed campaign lets the next invocation start a new target.

For example, an interruption after 27 successful initials leaves 73 outstanding for a target of 100. Rerun with the **same target**, `reset_state=false`, `send_enabled=true`, `dry_run=false`. Previously SENT messages are never automatically resent. A different target while recovering produces an error; do not reset merely to change it.

RUN 2 handles any genuinely due follow-ups, then 100 additional new initials. RUN 3 continues eligible chains plus another 100 new initials. F1 is due 24 hours after INITIAL SENT; F2 is due 7 days after F1 SENT; F3 is due 14 days after F2 SENT. Each stage requires the immediately preceding successful stage, preserves that sender, and threads to it with In-Reply-To/References. A failed F1 never unlocks F2. Reply, hard bounce or unsubscribe suppresses further follow-ups.

Targets are objectives, **not guaranteed deliverability promises**. Exhausted discovery budgets, insufficient public contacts/evidence, provider capacity, stopped senders or the runtime limit can leave a campaign incomplete. Inspect the remaining target and failure reason, fix the cause and resume.

## Architecture and durable safety

* `monitor.yaml` is the non-secret operational control plane; workflow dispatch inputs override only the six supported manual controls. Monitor feature disables and emergency stop always win.
* PostgreSQL is the sole durable state source, in the isolated `attachai` schema. No SQLite, CSV/JSONL runtime state, or Git-tracked queue is used.
* The coordinator acquires a session-level PostgreSQL advisory lock **before** migration/reset/reconciliation/work and holds it until exit. GitHub production concurrency adds a second guard.
* Database business-key constraints protect lead email, sequence, Message-ID and inbound event identity. Sharing a website domain does not itself collapse distinct contacts.
* Research, structured drafts, validation, sender assignments, retries, campaigns, messages, sender health and mailbox cursors persist. A bounded thread pool returns independent network outcomes; the coordinator persists individual completions without waiting for an entire batch to finish.
* One crawler bounds pages, response bytes and timeouts, respects configurable robots controls, and extracts deterministic evidence. One LLM implementation drafts against that evidence; validation rejects unsupported observations. Opportunity language is hypothetical, not an invented business fact.
* Initial batches contain at most ten messages, at most one per sender. There are up to ten concurrent network operations and no default artificial batch delay.
* SMTP and PostgreSQL cannot commit atomically. SMTP acceptance means the server accepted the message, **not inbox delivery**. An uncertain DATA timeout/disconnect or stale SENDING record becomes REVIEW, never an automatic resend.
* Ambiguous initials reserve unfilled target slots without counting as successes. For example, 97 SENT plus 3 unknown outcomes blocks further initials until those 3 are verified. Confirmed acceptance completes 100; confirmed non-acceptance releases safe retries. This avoids overshooting the target by automatically replacing unknown deliveries.
* Follow-up draft retries and SMTP attempts have separate durable counters. Temporary/invalid draft failures get bounded retries; network preparation is concurrent. Only successful SMTP acceptance creates the next stage.

## GitHub and Supabase setup

1. Replace the old repository contents with this repository, excluding `.git`, local credentials, environments and caches. Commit and push to the default branch. Remove any old competing production workflows; this replacement has exactly one production workflow and one CI workflow.
2. Provision PostgreSQL (Supabase supported). Choose a connection reachable from GitHub-hosted runners, allowing the app user to create/use its own schema. Use a **direct or session-pooled connection**, not a transaction-pooling endpoint: the long-lived advisory lock requires session affinity. Where a direct Supabase endpoint is IPv6-only, use its documented session-pooler connection reachable by your runner. Require TLS with `sslmode=require` (or verify-full with appropriate trust configuration).
3. Enable Google Places API **Text Search (New)** on a billing-enabled Google Cloud project. Restrict the API key to the needed API and suitable runner access; runner egress IPs are not fixed by default. Provide funded API access to the configured NVIDIA-compatible LLM endpoint/model. Verify model availability for your account.
4. Prepare ten distinct sending accounts with working authenticated SMTP and IMAP, provider-supported TLS and any required app passwords. Configure SPF/DKIM/DMARC and appropriate permissions/compliance for your outreach. Ten accounts do not bypass provider quotas or anti-abuse policies.
5. In GitHub **Settings → Secrets and variables → Actions**, create these four repository **Secrets**, exactly:

   | Secret | Content |
   | --- | --- |
   | `DATABASE_URL` | PostgreSQL URL including database, username/password and TLS options |
   | `GOOGLE_PLACES_API_KEY` | Google Places API key |
   | `LLM_API_KEY` | API key accepted by `llm.base_url` |
   | `SENDER_ACCOUNTS_JSON` | JSON array of ten complete accounts |

   No GitHub Variables are required. Never put passwords/API keys in monitor.yaml, workflow inputs, commit history or screenshots.
6. Edit `monitor.yaml`: choose geographically specific discovery queries, truthful offer/signature and **your genuine postal address** under `llm.postal_address`. The empty default intentionally prevents real sends. Confirm rating/review thresholds and budgets. Keep `automation.enabled=false` during verification.
7. Run CI and a safe dry-run before authorizing real sending. Migrations are applied by run startup; you can also run `python -m attachai.cli migrate` with only `DATABASE_URL` exported.

### Existing legacy database: do not silently start over

This is a clean schema rewrite, not an automatic legacy-state conversion. If populated `public.outreach` or `public.suppression` tables from the supplied old implementation exist, startup **refuses to proceed** rather than ignoring already-contacted recipients or lost suppressions. It neither deletes nor converts those legacy rows. Back up the database and carry out a separately audited history/sequence migration before using that same populated deployment. Do not point a fresh deployment at the same recipients to evade this safeguard. The included lifecycle tests start with an empty application database and verify resume across this replacement's own runs. Existing legacy follow-up chains are not automatically continued; this is an explicit deployment limitation.

An account has this exact shape (repeat with ten unique ids/emails):

```json
{
  "id": "sender01",
  "email": "sender01@your-domain.example",
  "password": "your-provider-app-password",
  "smtp_host": "smtp.your-provider.example",
  "smtp_port": 465,
  "imap_host": "imap.your-provider.example",
  "imap_port": 993,
  "tls_mode": "ssl"
}
```

`tls_mode` is `ssl` (implicit TLS) or `starttls`; set the correct ports for your provider. Optional `imap_password` overrides the shared SMTP password. Ports are JSON numbers, not strings. All required fields must exist; ids and normalized emails must be unique. The example host/address is explanatory, not a working provider configuration. Store only your complete real array in the Secret. No API operation needs these example credentials.

## Manual workflow settings

Open **Actions → AttachAI production → Run workflow** on the configured branch.

| Input | First safe dry-run | First real FULL test | Recovery |
| --- | --- | --- | --- |
| `reset_state` | false | false | **false** |
| `target_new_initials` | 100 | **100** | same unfinished target |
| `send_enabled` | false | **true** | true |
| `dry_run` | true | **false** | false |
| `process_followups` | true | **true** | true |
| `process_new_outreach` | true | **true** | true |

Dry-run can call discovery/research/LLM and consume provider quota; it does **not** send SMTP or satisfy the real campaign target. Dry campaigns are separate from real campaign accounting. You can choose a smaller target for a deliberate small real test *before* beginning the 100-target campaign; do not change an unfinished campaign's target.

For **FOLLOWUPS ONLY**, use `process_followups=true`, `process_new_outreach=false`. For **NEW OUTREACH ONLY**, use the inverse. FULL is both true. `outreach.enabled=false` / `followups.enabled=false` in the monitor blocks the respective feature even if dispatch requests it. Emergency stop blocks sending and processing regardless of dispatch overrides. `send_enabled=true` still does not send while `dry_run=true`.

Local equivalents, from the repository root:

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
# Securely export credentials first. .env.example is documentation, not auto-loaded.
python -m attachai.cli migrate
python -m attachai.cli run --reset-state false --target-new-initials 100 \
  --send-enabled false --dry-run true \
  --process-followups true --process-new-outreach true
```

Use explicit `true`/`false`, not truthy strings such as `yes` or `1`. For a different control-file path, the global argument precedes the subcommand: `python -m attachai.cli --config path/to/monitor.yaml run ...`. Validation failures name settings, never secret values. Follow-up drafting needs the LLM key; new-outreach preparation needs both Places and LLM keys, even in dry-run. Real sends require ten valid accounts. Migrate and manual review require only the database secret. Disabled scheduled polls exit before loading secrets or opening the database.

## Reset is destructive, not recovery

`reset_state=true` clears application runtime/campaign data in `attachai`, respecting foreign keys. It does not delete GitHub configuration, environment credentials or the Supabase project, and does not wipe other schemas.

**Reset erases contact history and suppression history. Those erased recipients can be discovered and contacted again.** Back up application state first, preserve required suppression records externally for legal compliance, and never use reset for routine resume, provider trouble or target changes. Do not reset a database that another deployment uses. Test resets against a disposable database.

## REVIEW: establish evidence before resolving

No system can infer whether an SMTP server accepted a message after every network failure. Before resolving REVIEW, inspect your provider's delivery/transaction logs or authoritative sent-message evidence for the exact stable Message-ID, sender, recipient and time. Merely not seeing a recipient reply is not proof of non-delivery; some SMTP submissions do not automatically create an IMAP Sent item.

```sh
python -m attachai.cli review --message-id MESSAGE_ROW_ID --resolution sent \
  --evidence 'Provider transaction log reference ABC123 verified by operator' \
  --sent-at '2026-10-11T10:00:00+00:00' --confirm
# Only with positive evidence that SMTP acceptance did NOT happen:
python -m attachai.cli review --message-id MESSAGE_ROW_ID --resolution not-sent \
  --evidence 'Provider rejection log reference XYZ456 verified by operator' --confirm
```

Use the database message row id reported for REVIEW, not a guessed recipient. Replace the example evidence reference with a real operator verification reference; do not include credentials or message bodies. `--evidence` is required for both resolutions; `--sent-at` is additionally required for `sent` and must be the verified actual SMTP acceptance time as a timezone-aware ISO timestamp, not the review time. `sent` records confirmed acceptance; `not-sent` authorizes normal retry eligibility and can cause duplicates if your conclusion is wrong. Preserve supporting evidence in your operational audit records. If evidence is inconclusive, **leave REVIEW unresolved**. The confirmation flag is your assertion that you verified the outcome; it is not an automatic provider reconciliation service.

REVIEW can also hold a follow-up whose draft exhausted its retry/validation budget before any SMTP operation. After correcting the research/provider problem and verifying no submission occurred, `not-sent` resets that message's draft budget and allows re-preparation. This does not reset other leads or successful stages.

## Future automation: one monitor file, real polling

The production GitHub workflow has an actual `*/15 * * * *` UTC polling trigger. A cron string in monitor.yaml **cannot wake GitHub Actions itself**. Each poll loads monitor.yaml and determines the latest due outreach/follow-up slot in `automation.timezone`. The app recognizes slots up to 20 minutes late; database-unique feature/UTC slot claims prevent duplicate execution. Simultaneously due features run together. Disabled/no-due schedules are safe no-ops without credentials.

After manual verification, set `automation.enabled=true`, select the two five-field cron schedules/timezone and desired feature toggles. To automate real SMTP also deliberately set `safety.send_enabled=true`, `safety.dry_run=false` and configure the required postal address/secrets. Manual dispatch defaults remain safe independent of those automatic settings. Disable automation to stop scheduled work; emergency stop is the stronger global gate.

GitHub schedules run from the default branch and can be delayed, dropped, disabled by repository inactivity/policies, or queued behind an active run. Slots older than 20 minutes are **not backfilled**; frequent cron schedules produce only their latest due slot per poll, not every missed minute. GitHub concurrency can replace an older pending run with a newer one; this is not a guaranteed scheduler. Long campaigns can therefore miss later schedule slots. UTC slot identity and IANA timezone handling avoid naive local timestamps: nonexistent spring-forward minutes do not run; repeated fall-back minutes are distinct UTC slots and can run twice. Choose UTC to avoid this daylight-saving wall-clock behavior. For guaranteed punctuality/backfill, use a separately managed reliable scheduler calling this same CLI, with the same durable lock and slot semantics.

## Controls and logs

Control sections: `automation` (activation/crons/timezone), `safety` (emergency/send/dry), `outreach` (target/batch/concurrency), `followups` (three chained delays/run budget), `limits` (optional sending windows/caps, gap/runtime), `retry` (attempts/backoff/cooldown), `discovery` (queries/provider budgets/buffer/qualification), `research` (cache version/crawler bounds/robots/evidence), `llm` (endpoint/model/offer/footer), `mailbox` (sync bounds/lookback).

Invalid values fail at startup; batch/concurrency are bounded to 1–10. Unknown controls, duplicate YAML keys and malformed booleans fail rather than being silently ignored. Follow-up delays are seconds; `[0, 0, 0]` is an explicit accelerated-testing choice, **not the default**. Changing research version invalidates reuse as designed. Budgets and max runtime bound work; increasing the target alone cannot overcome external capacity.

Inspect Actions logs for START, stage progress, individual sends, batches and FINAL. Distinguish initial SENT, follow-ups sent, dry results and remaining target. A failure/nonzero exit with remaining target is not a completed campaign. PostgreSQL remains authoritative if a runner dies before printing its final line. Consult the migration for table definitions; inspect campaigns/messages/senders/inbound state using a trusted database console, not public logs. Do not paste credential-bearing URLs or recipient bodies into issues.

## Tests and troubleshooting

CI starts a **PostgreSQL 16 service** and runs `python -m pytest -q`; it receives no production secrets and uses network fakes, never real SMTP. Integration tests require PostgreSQL, not SQLite. Local tests:

```sh
# Create a disposable PostgreSQL database, then:
export TEST_DATABASE_URL='postgresql://attachai:attachai@localhost:5432/attachai_test'
python -m pytest -q
```

Never point `TEST_DATABASE_URL` at production: integration tests manipulate application state. No external live-send test is included; successful unit/integration tests do not prove your provider credentials, quota, deliverability or runner connectivity.

* **Places failure / few contacts:** verify billing, API enablement/key restrictions, focused queries, website quality and budgets. The system extracts public emails; it does not fabricate contacts.
* **LLM 503/timeouts:** bounded retry/backoff isolates items. Verify quota/model availability; rerun recovery rather than resetting. HTTP 200 invalid JSON is invalid output, not successful preparation.
* **Evidence rejected:** inspect actual researched evidence and website access/robots. Unsupported claims are rejected intentionally; increasing confidence is not a substitute for evidence.
* **SMTP auth:** affected sender stops; fix app-password/TLS/provider policy before recovery. Terminal recipient failures suppress the recipient; temporary failures cool down/retry. Provider network restrictions can block runner SMTP ports; use a supported authenticated endpoint.
* **Mailbox failure:** recorded degraded sender state; new outreach is not destroyed. Restore IMAP permissions/reachability and resync. Only bounded UID progress actually processed is advanced. Inbound lookback limits and classification are not a perfect spam/bounce service.
* **Database lock / URL:** use session-affine connectivity. Do not forcibly bypass the lock during another process's work. Verify database privilege, TLS and connection reachability without printing the URL.
* **REVIEW or incomplete campaign:** resolve only with evidence, retain the target and resume. Ambiguous sends can prevent automatic completion; avoiding duplicate sends has priority over an unconditional 100-success claim.

STOPPED sender health is intentionally durable, even after replacing a password in GitHub Secrets. After independently validating the repaired account, restore **only that account** from a trusted PostgreSQL console (replace the example id with your actual immutable sender id):

```sql
UPDATE attachai.sender
SET health='HEALTHY', cooldown_until=NULL, last_error=NULL, updated_at=now()
WHERE id='sender01' AND health='STOPPED';
```

Do not globally clear stopped senders or bypass the database lock. A due follow-up remains bound to its original sender and will not jump to another account. Degraded IMAP health is restored by a successful mailbox sync; cooldown expires automatically.

## Repository layout

```text
.github/workflows/attachai.yml   one production poll/dispatch workflow
.github/workflows/tests.yml      isolated PostgreSQL CI
attachai/config.py               controls + separate secret loading
attachai/scheduling.py           pure latest-due-slot calculation
attachai/db.py                   migrations, lock, persistence
attachai/engine.py               durable coordinator / recovery
attachai/providers.py            canonical network/evidence implementations
attachai/cli.py                  migrate, run, scheduled, review
migrations/001_initial.sql       isolated application schema
tests/                          deterministic provider/config + PostgreSQL tests
monitor.yaml                    human-editable runtime controls
.env.example                    secret shape documentation, never live values
pyproject.toml / requirements.txt
```

Install/run from the extracted repository root so `monitor.yaml` and `migrations` are available. A bare wheel without deployment configuration is not the deployment artifact. External legal/compliance review, provider reputation, verified contact suitability and actual inbox delivery remain your responsibility.
