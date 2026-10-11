# Local verification and deployment boundaries

## Result

The complete replacement suite passed **260 tests**, with **zero failures or skips**, against local PostgreSQL 17 and Python 3.12. Production workflow and CI select Python 3.11; CI configures PostgreSQL 16. The SQL and Python features used support those declared versions, but those exact CI services have not been executed from an attached GitHub account here.

All provider tests use deterministic network doubles. No real email, discovery query, paid LLM call, or live mailbox access was performed. The shipped archive excludes `.git`, credentials, environments, bytecode and test caches. Run from the extracted repository root.

## Verified lifecycle

* Three successive real-mode simulated FULL campaigns each persist 100 additional successful initials; prior successes are excluded. The next logical campaign starts only after the unfinished one has completed.
* Due F1/F2 stages are handled alongside each new campaign. A separate full-chain test verifies F3, immediate-predecessor delays, same sender, complete References/In-Reply-To and no fourth follow-up.
* Interruption after ten persisted sends resumes the same campaign and sends only ninety remaining initials. Previously successful IDs are not submitted again.
* Interruption after twenty-seven persisted sends leaves three concurrently submitted outcomes uncertain. Reconciliation marks them REVIEW. Seventy further accepted messages bring the known count to ninety-seven; unknown outcomes reserve the remaining three slots. After authoritative operator confirmation, the total becomes one hundred without additional SMTP submissions.
* Extensive research/draft failures, malformed LLM output, temporary 503/timeouts, SMTP retries and sender authentication failure trigger bounded retry/replenishment rather than an empty-cycle stall.
* PostgreSQL constraints and triggers guard email identity, one sequence per lead, immediate predecessor, sender/thread continuity, immutable SENT content/identity, unique Message-IDs, mailbox event identity and unique schedule slots.
* Inbound suppression and cursor advancement commit in one database transaction. A simulated crash between event insertion and suppression rolls everything back, so the next sync safely processes the event.
* Stable inbound message identity survives UID changes and UIDVALIDITY epochs when a valid original Message-ID exists. Missing/invalid IDs use a raw-byte digest; modified bytes are consequently a different fallback identity.
* Ten simultaneous SMTP operations are exercised, with at most one initial per sender per batch. Independent failures do not cancel other results.
* SMTP rejection classification is stage-aware. Sender or DATA policy failures are not automatically treated as invalid recipient addresses. DATA ambiguity is never blindly retried.
* Optional windows, sender/total daily limits, emergency stop, actual boolean overrides, scheduled no-op behavior and CLI secret-safe failures are tested. Testing defaults keep windows/caps/gaps off.
* Reset clears only application runtime data. Its deliberate destruction of contact/suppression history is documented; reset is never routine recovery.

## Not claimed or tested live

* Working customer credentials, billing/quota, NVIDIA model support, SMTP/IMAP permission, Supabase runner connectivity, provider policy compliance or inbox delivery.
* An unconditional 100-send guarantee when discovery/provider/runtime budgets are exhausted.
* Automatic proof of ambiguous SMTP acceptance. Operator evidence is required.
* Guaranteed GitHub polling punctuality/backfill. Slots older than twenty minutes are not backfilled.
* Automatic migration of existing legacy campaign data or follow-up chains. Populated legacy tables block startup instead of being silently ignored.
* A crawler that accepts every site: private/nonpublic destinations, nonstandard ports and cross-origin redirects are deliberately rejected. Robots handling is configurable and bounded.
* Perfect bounce/unsubscribe classification. Durable correlation, conservative handling and bounded lookback are implemented; an enterprise deliverability service is not included.

## Deployment acceptance still required

Follow README setup against a backed-up or empty appropriate database. Run CI in GitHub, then the safe dry-run. Validate evidence/contacts and account health, add a genuine postal address, and explicitly authorize the first real manual FULL run. Inspect PostgreSQL SENT counts and provider acceptance logs before enabling automation. Never erase suppression history or move to an empty database merely to bypass a migration safeguard.
