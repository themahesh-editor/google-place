# AttachAI deep-scan fixes

This package includes fixes for issues found in the GitHub Actions run on 2026-10-11.

## What changed

- Dry-run/preparation mode no longer exits just because an older campaign has a queued initial message. It continues sourcing and preparing until pending sendable inventory reaches the campaign target, without using SMTP.
- Lead research preparation is capped to the remaining target slots, so the discovery overage buffer is used for candidate inventory rather than creating excessive outbound message rows that can be stranded after campaign success.
- Pending initial inventory ignores suppressed/stopped leads; suppression cancels unsent initial and follow-up messages.
- Startup recovery immediately requeues batch-assigned messages that were never claimed for sending, while leaving ambiguous `SENDING` rows protected from duplicate sends.
- Mailbox replies/bounces are correlated to successfully sent outreach by Message-ID/In-Reply-To/References, with a matching prior sent subject as a fallback. Sender-address match alone no longer suppresses a lead.
- A received `List-Unsubscribe` header no longer means the sender of that inbound message has unsubscribed from AttachAI. Only explicit opt-out language is treated as an unsubscribe request.
- Added regression tests for resume/preparation behavior, mailbox false-suppression safeguards, and per-invocation batch caps for small pilot runs.

## Safety notes

- `dry_run: true` remains the default. This package does not enable real SMTP sending.
- Do not use `reset_state: true` to resolve queue behavior; it clears application runtime data in Supabase.
- The test suite uses SQLite/fakes. Passing tests do not prove live Supabase, Google Places, NVIDIA, IMAP, or SMTP integration.
- Before real sending, verify actual mailbox messages, sender configuration, suppression records, and provider responses. Start with a small manually reviewed batch rather than switching straight to 100 real sends.


Local verification: `python -m unittest discover -s tests -p 'test_*.py' -v` — 58 tests passed.
