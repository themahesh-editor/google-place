# AttachAI full-system quality update

## Root cause in supplied run log

The run had 999 raw results, 208 newly deduplicated candidates, 21 qualified leads, 24 research failures, 258 retryable candidate evaluations, 1 personalized draft and no successful initial sends because dry-run was enabled. The Places request budget was exhausted at 60.

Many retry errors show malformed URL authorities built from telephone numbers (`Port could not be cast to integer` / `Port out of range`). Some research and personalization calls received invalid/non-object JSON from the compatible LLM endpoint. Discovery also spent work on social/profile and third-party directory websites.

## Changes included

- `app/research.py`: stricter HTTP(S) URL canonicalization, malformed hrefs are skipped, telephone-like host values are rejected.
- `app/llm.py`: unwrap only a one-item array containing a single dictionary for object operations; other invalid shapes remain rejected.
- `app/discovery.py`: reject a defined set of obvious social/profile/directory domains before website crawling.
- `app/db.py`: startup requeues only retryable candidates with the known old crawler port-parse error, leaving unrelated retries untouched.
- `monitor.yaml`: Places request budget increased from 60 to 120; check Google quota/billing impact.
- `tests/test_system.py`: focused regression tests added.

## Verification

`python -m unittest discover -s tests -p 'test_*.py' -v` passed 62 tests locally in the packaged source. `python -m compileall -q app tests` also passes.

These tests use fakes/SQLite and are not live integration validation. No claim is made that the packaged run has been tested against the user's Supabase instance, API quotas, model endpoint, mailboxes or sender SMTP accounts.
