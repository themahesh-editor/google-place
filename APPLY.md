# Applying this bundle to `google-place`

From the root of a checked-out `themahesh-editor/google-place` repository, copy the bundle contents over the matching paths. The bundle does not replace the existing `lead_collector.py`, CRM files, or lead-discovery workflow.

```bash
cp -R app .
cp -R tests/test_outreach_engine.py tests/
cp -R .github/workflows/outreach-engine.yml .github/workflows/
cp -R .github/workflows/outreach-send.yml .github/workflows/
cp -R .github/workflows/outreach-mailbox.yml .github/workflows/
cp -R .github/workflows/outreach-tests.yml .github/workflows/
cp .env.example requirements-outreach.txt .gitignore README_OUTREACH.md .
```

Then run:

```bash
python -m pip install -r requirements.txt -r requirements-outreach.txt
python -m unittest discover -s tests -p 'test_*.py' -v
```

The existing lead-discovery workflow remains separate. Production outreach state must live outside the runner filesystem using `OUTREACH_DATABASE_URL`.
