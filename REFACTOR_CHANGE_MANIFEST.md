# AttachAI Refactor Change Manifest

Repository target: `themahesh-editor/google-place`
Baseline inspected: `main` at `a491be60e442267582ab8499187e7bbe35b1cefe`.

## Replace / create

- `.env.example`
- `.github/workflows/attachai.yml`
- `.github/workflows/tests.yml`
- `.gitignore`
- `README.md`
- `app/__init__.py`
- `app/config.py`
- `app/db.py`
- `app/discovery.py`
- `app/llm.py`
- `app/mailbox.py`
- `app/mailer.py`
- `app/main.py`
- `app/models.py`
- `app/orchestrator.py`
- `app/personalization.py`
- `app/research.py`
- `migrations/001_initial.sql`
- `requirements.txt`
- `tests/__init__.py`
- `tests/test_system.py`

## Delete

- `.github/workflows/lead-discovery.yml`
- `.github/workflows/outreach-engine.yml`
- `.github/workflows/outreach-mailbox.yml`
- `.github/workflows/outreach-send.yml`
- `.github/workflows/outreach-tests.yml`
- `lead_collector.py`
- `requirements-outreach.txt`
- `README_FIXES.md`
- `README_OUTREACH.md`
- `IMPLEMENTATION_REPORT.md`
- `APPLY.md`
- `leads_crm.csv`
- `seen_domains.csv`
- `retry_queue.csv`
- `candidate_memory.jsonl`
- `run_log.jsonl`
- `app/config.py` is replaced, not deleted as a final path.
- `app/email/*`
- `app/followups/*`
- `app/integrations/*`
- `app/llm/*` (including `app/llm/__init__.py` and `client.py`)
- `app/outreach/*`
- `app/personalization/*`
- `app/reporting/*`
- `app/research/*`
- `app/storage/*`
- `app/suppression/*`
- `tests/test_lead_collector.py`
- `tests/test_outreach_engine.py`

Empty package directories are not represented by Git and therefore disappear when their files are deleted.

## Architecture outcome

- Supabase PostgreSQL is the production source of truth.
- Lead discovery writes verified leads directly to the database.
- The runtime does not import CSV/JSONL discovery state.
- One production workflow is manual-only (`workflow_dispatch`).
- One CI workflow runs tests and never sends mail.
- One canonical research crawler and one LLM client are used.
- Initial sending uses durable database batches of at most 10, with one initial message per sender and real `ThreadPoolExecutor(max_workers=10)` concurrency.
- Initial target is measured from durable `SENT` rows; existing successful sends count on state-preserving reruns.
- Sender assignment, batch assignment, retries, SMTP state, mailbox state, suppression, replies, and follow-ups are durable.
- F1 depends on successful INITIAL; F2 depends on successful F1; F3 depends on successful F2.
- Sender health is enforced: STOPPED/DEGRADED senders are excluded; temporary failures enter COOLDOWN; successful mailbox checks can restore DEGRADED.
- Reset is explicit and only clears application tables.
