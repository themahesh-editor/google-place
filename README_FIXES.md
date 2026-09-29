# Lead Discovery Recovery Fixes

This patch is for the existing `themahesh-editor/google-place` experiment.

## Why leads were being missed

1. The old crawler inspected only up to 5 pages and relied heavily on homepage link labels. A real contact email can live on a predictable or custom contact page that was never fetched.
2. The old email extractor only handled `mailto:` and visible plain-text emails. It missed JSON-LD emails, Cloudflare email protection, and common public obfuscations such as `[at]` / `[dot]`.
3. The old code permanently added every candidate domain to `seen_domains.csv` before the candidate was verified. A temporary website failure, missed email, or temporary LLM failure could therefore make a valid lead impossible to retry.
4. The old Places client retried deterministic 4xx failures three times, wasting request budget.
5. The old query prompt could generate consumer-intent searches such as review/cost/specials queries instead of business-first discovery queries.

## What this patch changes

- 10 website pages per candidate by default.
- Common contact/about/team/location paths are probed.
- Sitemap XMLs are consulted for contact/about pages.
- Robots rules are cached per origin.
- Email extraction handles `mailto:`, visible text, JSON-LD, Cloudflare-protected mail links, and common `[at]`/`[dot]` obfuscation.
- Verified domains are permanent memory; failed candidates are kept in `retry_queue.csv` with a cooldown instead of being lost.
- NVIDIA temporary failures become retryable instead of terminal skips.
- Google Places deterministic 4xx errors are not repeatedly retried.
- Query generation is business-first with a deterministic Python fallback.
- Run logs now include email-missing, website-failure, LLM-retry, duplicate, and retry-queue counts.
- `MAX_RAW_CANDIDATES` is 500 while Places search calls remain capped at 30.

## Files to replace

- `lead_collector.py`
- `.github/workflows/lead-discovery.yml`
- `tests/test_lead_collector.py`

Add:

- `retry_queue.csv`
- `README_FIXES.md`

Keep your existing `leads_crm.csv`, `candidate_memory.jsonl`, `seen_domains.csv`, and `run_log.jsonl` data.

No email sending is included in this experiment.

Important: a site that truly does not publish a public business email, or one that blocks automated access under its robots rules, cannot be turned into a verified email lead by software without another permitted source.
