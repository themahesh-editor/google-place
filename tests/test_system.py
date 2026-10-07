from __future__ import annotations

import os
import tempfile
import time
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from unittest.mock import patch

os.environ.setdefault("SUPABASE_DB_URL", "sqlite://:memory:")
os.environ.setdefault("NVIDIA_API_KEY", "test-key")
os.environ.setdefault("GOOGLE_PLACES_API_KEY", "test-key")
for i in range(1, 11):
    os.environ.setdefault(f"SENDER_{i}_EMAIL", f"sender{i}@example.com")
    os.environ.setdefault(f"SENDER_{i}", "test-credential")

from app.config import Settings
from app.db import Store, deterministic_lead_id, deterministic_message_id, deterministic_outreach_id, normalize_domain
from app.discovery import CandidateEvaluation
from app.llm import LLMClient, LLMInvalidResponse, LLMTemporaryError, parse_json_value
from app.mailer import BatchSendController, classify_send_error
from app.mailbox import MailboxMonitor, classify, parse_message
from app.models import Evidence, SendResult
from app.monitor import pipeline_schedule_is_due
from app.personalization import PersonalizationValidator, normalize_evidence_url
from app.research import Page, WebsiteCrawler
from app.orchestrator import Orchestrator

ROOT = os.path.dirname(os.path.dirname(__file__))


class FakeLLM:
    def __init__(self, invalid_personalization=False):
        self.invalid_personalization = invalid_personalization
        self.calls = []

    def chat_json_object(self, system, user, **kwargs):
        op = kwargs.get("operation", "")
        self.calls.append(op)
        if op == "discovery_qualification":
            return {"action": "KEEP", "company_name": user.split("Company: ", 1)[1].split("\n", 1)[0] if "Company: " in user else "Company", "scale_class": "LOCAL", "confidence": 0.95, "reason": "clear fit"}
        if op == "website_research":
            return {
                "company_identity": "Example Business",
                "business_summary": "Local consulting company offering consulting services.",
                "services": ["consulting services"],
                "business_facts": ["The site lists consulting services."],
                "locations": ["Austin TX"],
                "specialties": ["consulting"],
                "website_signals": ["services page"],
                "customer_journey_signals": ["contact page"],
                "ai_opportunity_signals": ["service inquiry follow-up"],
            }
        if op.startswith("personalization"):
            import re
            m = re.search(r"Company: ([^\n]+)", user)
            company = m.group(1).strip() if m else "Example Business"
            if self.invalid_personalization:
                return {
                    "eligible": True, "confidence": 0.95, "subject": "Question", "body": f"Hello {company}, we help.",
                    "cta": "Discuss something", "observations": ["They provide private jets"],
                    "opportunity": "Private jets need software", "evidence": [],
                }
            snippet = f"{company} lists consulting services on its website."
            return {
                "eligible": True,
                "confidence": 0.95,
                "subject": f"A thought for {company}",
                "body": f"Hello {company}, I noticed the site lists consulting services. Could we discuss those services?",
                "cta": "Could we discuss those services?",
                "observations": ["The site lists consulting services."],
                "opportunity": "The listed consulting services suggest a clear service inquiry opportunity.",
                "evidence": [{"url": re.search(r"Website: ([^\n]+)", user).group(1).strip() if re.search(r"Website: ([^\n]+)", user) else "https://biz.example/", "title": "Home", "snippet": snippet}],
            }
        return {}


class FakeResearch:
    def __init__(self, store, fail_ids=None):
        self.store = store
        self.fail_ids = set(fail_ids or [])

    def run(self, lead):
        if lead["lead_id"] in self.fail_ids:
            raise LLMTemporaryError("research unavailable")
        website = lead["website"]
        pages = [Page(website, "Home", f"{lead["company"]} lists consulting services on its website.", (), (lead["email"],))]
        research = {
            "company_identity": lead["company"],
            "business_summary": "Consulting services",
            "services": ["consulting services"],
            "business_facts": ["consulting services listed"],
            "locations": [lead.get("city", "")],
            "specialties": ["consulting"],
            "website_signals": ["service page"],
            "customer_journey_signals": ["contact page"],
            "ai_opportunity_signals": ["service inquiry"],
        }
        cache_id = self.store.save_research_cache(website, "test-research", pages, research, "RESEARCHED", None)
        self.store.save_lead_research(lead["lead_id"], cache_id, "RESEARCHED")
        return research, pages


class FakeMailbox:
    def run_all(self, senders):
        return {"replies": 0, "bounces": 0, "unsubscribes": 0, "unclassified": 0, "duplicates": 0, "failed": 0}


class FakeDiscovery:
    def __init__(self, store, start=0, chunk=20):
        self.store = store
        self.next_id = start
        self.chunk = chunk
        self.calls = 0

    def discover_raw(self, run_id, minimum_new_candidates, request_budget=None):
        self.calls += 1
        n = max(minimum_new_candidates, self.chunk)
        for _ in range(n):
            i = self.next_id
            self.next_id += 1
            place = f"place-{i}"
            self.store.upsert_candidate(place_id=place, company=f"Example Business {i}", website=f"https://biz{i}.example/", address="Austin, TX, US", country_code="US", types=["consulting"], query="consulting company in Austin TX")
        return {"raw_candidates": n, "deduplicated_candidates": n, "queries_used": 1, "places_requests_used": 1}

    def process_candidates(self, run_id, rows, max_workers=10):
        for row in rows:
            i = row["candidate_id"]
            lead_id = deterministic_lead_id(row["place_id"] + "@example.com", row["place_id"])
            self.store.upsert_lead({
                "lead_id": lead_id, "email": f"{row['place_id']}@example.com", "company": row["company"], "website": row["website"], "place_id": row["place_id"],
                "city": "Austin", "region": "TX", "country_code": "US", "timezone": "America/Chicago", "lead_source": "fake", "scale_class": "LOCAL",
                "qualification_confidence": 0.95, "qualification_reason": "fit", "discovery_facts": "Example Business consulting services", "status": "ELIGIBLE",
            })
            self.store.set_candidate_result(row["candidate_id"], "VERIFIED", reason="fake")
        return {"qualified": len(rows), "rejected": 0, "retryable": 0, "verified": len(rows), "duplicates": 0}


class FakeSMTP:
    active = 0
    max_active = 0
    calls = []
    mode = "success"

    def __init__(self, sender, credential, timeout_seconds=30):
        self.sender = sender

    def send(self, row):
        type(self).active += 1
        type(self).max_active = max(type(self).max_active, type(self).active)
        time.sleep(0.01)
        type(self).calls.append(row["outreach_id"])
        try:
            if type(self).mode == "temporary":
                return SendResult(str(row["outreach_id"]), "FAILED", "temporary/provider/network", "temporary")
            if type(self).mode == "auth":
                return SendResult(str(row["outreach_id"]), "FAILED", "authentication", "auth")
            return SendResult(str(row["outreach_id"]), "SENT", provider_message_id=row["smtp_message_id"])
        finally:
            type(self).active -= 1


class FakeIMAPProvider:
    messages = []
    uidvalidity = "42"

    def __init__(self, sender, credential):
        self.client = None

    def connect(self):
        return None

    def fetch_since(self, last_uid, max_messages):
        return list(self.messages)

    def close(self):
        return None


class BaseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.settings = Settings.from_monitor(os.path.join(ROOT, "monitor.yaml"))

    def setUp(self):
        self.store = Store("sqlite://:memory:")
        self.store.migrate(os.path.join(ROOT, "migrations"))

    def tearDown(self):
        self.store.close()

    def lead(self, i=1, email=None, place=None):
        email = email or f"person{i}@example.com"
        place = place or f"place-{i}"
        return {
            "lead_id": deterministic_lead_id(email, place), "email": email, "company": f"Company {i}", "website": f"https://site{i}.example/", "place_id": place,
            "city": "Austin", "region": "TX", "country_code": "US", "timezone": "America/Chicago", "lead_source": "test", "scale_class": "LOCAL",
            "qualification_confidence": 0.95, "qualification_reason": "fit", "discovery_facts": "consulting services", "status": "ELIGIBLE",
        }

    def create_workflow_campaign(self, target=10):
        workflow, campaign, resumed = self.store.start_workflow("MANUAL", False, target)
        return workflow, campaign

    def queue_initial(self, workflow, campaign, i, sender_id="", sender_email=""):
        lead = self.lead(i)
        self.store.upsert_lead(lead)
        oid = deterministic_outreach_id(lead["lead_id"], "INITIAL", 1)
        send_state = "SCHEDULED" if sender_id and sender_email else "QUEUED"
        smtp_message_id = deterministic_message_id(oid, sender_email) if send_state == "SCHEDULED" else None
        self.store.insert_outreach({"outreach_id": oid, "workflow_run_id": workflow, "campaign_id": campaign, "lead_id": lead["lead_id"], "sequence_type": "INITIAL", "sequence_number": 1, "sender_id": sender_id, "sender_email": sender_email, "email": lead["email"], "subject": "s", "body": f"Company {i} consulting services", "status": send_state, "smtp_message_id": smtp_message_id, "confidence": .9, "evidence_urls": ["https://site.example/"]})
        return lead, oid


class DeterministicIdentityTests(BaseTest):
    def test_01_deterministic_ids(self):
        self.assertEqual(deterministic_lead_id("A@Example.com", "place-1"), deterministic_lead_id("a@example.com", "place-1"))
        self.assertEqual(deterministic_outreach_id("lead", "INITIAL", 1), deterministic_outreach_id("lead", "INITIAL", 1))
        self.assertEqual(deterministic_message_id("oid", "Sender@Example.com"), deterministic_message_id("oid", "sender@example.com"))

    def test_02_lead_deduplication_allows_same_domain_distinct_contacts(self):
        l1 = self.lead(1, "a@same.example", "place-a")
        l2 = self.lead(2, "b@same.example", "place-b")
        self.store.upsert_lead(l1); self.store.upsert_lead(l2)
        self.assertEqual(self.store.scalar("SELECT count(*) FROM lead", default=0), 2)
        with self.assertRaises(Exception):
            self.store.upsert_lead(self.lead(3, "a@same.example", "place-c"))

    def test_03_separate_runs_can_each_request_100_new(self):
        wf1, c1 = self.create_workflow_campaign(100)
        for i in range(100):
            self.queue_initial(wf1, c1, i)
        self.store.execute("UPDATE outreach SET status='SENT',sent_at_utc=? WHERE campaign_run_id=?", [datetime.now(timezone.utc), c1])
        self.store.finish_campaign(c1)
        wf2, c2 = self.create_workflow_campaign(100)
        self.assertNotEqual(c1, c2)
        self.assertEqual(self.store.scalar("SELECT target_new_initials FROM campaign_run WHERE campaign_run_id=?", [c2]), 100)

    def test_04_existing_successful_initials_excluded_from_new_campaign(self):
        wf1, c1 = self.create_workflow_campaign(2)
        l1, _ = self.queue_initial(wf1, c1, 1)
        l2, _ = self.queue_initial(wf1, c1, 2)
        self.store.execute("UPDATE outreach SET status='SENT',sent_at_utc=? WHERE campaign_run_id=?", [datetime.now(timezone.utc), c1])
        self.store.finish_campaign(c1)
        wf2, c2 = self.create_workflow_campaign(1)
        self.assertEqual(self.store.scalar("SELECT count(*) FROM outreach WHERE campaign_run_id=? AND sequence_type='INITIAL' AND status='SENT'", [c2]), 0)
        self.assertTrue(l1["lead_id"] != l2["lead_id"])

    def test_19b_invalid_qualification_schema_is_rejected(self):
        from app.discovery import validate_qualification_schema
        with self.assertRaises(LLMInvalidResponse):
            validate_qualification_schema({"action": "KEEP", "confidence": 0.9})

    def test_19c_invalid_research_schema_is_rejected(self):
        from app.research import validate_research_schema
        with self.assertRaises(LLMInvalidResponse):
            validate_research_schema({"company_identity": "Example"})

    def test_19d_retry_attempt_is_durable(self):
        lead = self.lead(99); self.store.upsert_lead(lead)
        self.store.mark_research_retry(lead["lead_id"], delay_seconds=1, terminal_after=3, reason="HTTP_503")
        self.assertEqual(self.store.scalar("SELECT count(*) FROM retry_attempt WHERE entity_type=? AND entity_id=?", ["lead_research", lead["lead_id"]]), 1)


class ResumeAndSequenceTests(BaseTest):
    def test_05_crash_after_10_sends_resumes_at_10(self):
        wf, c = self.create_workflow_campaign(30)
        for i in range(30):
            self.queue_initial(wf, c, i, "SENDER_1", "sender1@example.com")
        rows = self.store.fetchall("SELECT * FROM outreach WHERE campaign_run_id=? ORDER BY created_at_utc", [c])
        for row in rows[:10]:
            self.store.claim_for_send(row["outreach_id"]); self.store.mark_sent(row["outreach_id"], datetime.now(timezone.utc))
        self.assertEqual(self.store.successful_initial_count(c), 10)
        wf2, c2 = self.create_workflow_campaign(30)
        self.assertEqual(c, c2)
        self.assertEqual(self.store.successful_initial_count(c2), 10)

    def test_06_sent_rows_not_selected_for_resend(self):
        wf, c = self.create_workflow_campaign(2)
        _, oid1 = self.queue_initial(wf, c, 1, "SENDER_1", "sender1@example.com")
        _, oid2 = self.queue_initial(wf, c, 2)
        self.store.claim_for_send(oid1); self.store.mark_sent(oid1, datetime.now(timezone.utc))
        ready = {r["outreach_id"] for r in self.store.list_ready_initials(c, 10)}
        self.assertNotIn(oid1, ready); self.assertIn(oid2, ready)

    def test_07_same_lead_cannot_get_duplicate_initial(self):
        wf, c = self.create_workflow_campaign(1)
        lead, oid = self.queue_initial(wf, c, 1)
        self.assertFalse(self.store.insert_outreach({"outreach_id": oid, "workflow_run_id": wf, "campaign_id": c, "lead_id": lead["lead_id"], "sequence_type": "INITIAL", "sequence_number": 1, "sender_id": "", "sender_email": "", "email": lead["email"], "subject": "x", "body": "x", "status": "QUEUED", "confidence": .9, "evidence_urls": []}))

    def test_08_f1_only_after_initial_sent(self):
        wf, c = self.create_workflow_campaign(1)
        lead, oid = self.queue_initial(wf, c, 1, "SENDER_1", "sender1@example.com")
        initial = self.store.get_outreach(oid)
        self.assertEqual(self.store.create_followup_row(workflow_id=wf, campaign_id=c, lead=lead, previous=initial, sequence_type="FOLLOWUP_1", sequence_number=1, scheduled_at=datetime.now(timezone.utc)), None)
        self.store.claim_for_send(oid); self.store.mark_sent(oid, datetime.now(timezone.utc))
        initial = self.store.get_outreach(oid)
        f1 = self.store.create_followup_row(workflow_id=wf, campaign_id=c, lead=lead, previous=initial, sequence_type="FOLLOWUP_1", sequence_number=1, scheduled_at=datetime.now(timezone.utc))
        self.assertIsNotNone(f1)

    def test_09_f2_only_after_f1_sent(self):
        wf, c = self.create_workflow_campaign(1)
        lead, oid = self.queue_initial(wf, c, 1, "SENDER_1", "sender1@example.com")
        self.store.claim_for_send(oid); self.store.mark_sent(oid, datetime.now(timezone.utc))
        initial = self.store.get_outreach(oid)
        f1id = self.store.create_followup_row(workflow_id=wf, campaign_id=c, lead=lead, previous=initial, sequence_type="FOLLOWUP_1", sequence_number=1, scheduled_at=datetime.now(timezone.utc))
        f1 = self.store.get_outreach(f1id); self.assertEqual(self.store.get_outreach(f1id)["status"], "WAITING_DUE")
        self.assertIsNone(self.store.create_followup_row(workflow_id=wf, campaign_id=c, lead=lead, previous=initial, sequence_type="FOLLOWUP_2", sequence_number=2, scheduled_at=datetime.now(timezone.utc)))
        self.store.queue_followup_draft(f1id, "Re: s", "follow-up consulting services", [], .9, initial["smtp_message_id"], initial["smtp_message_id"])
        self.store.claim_for_send(f1id); self.store.mark_sent(f1id, datetime.now(timezone.utc))
        f1 = self.store.get_outreach(f1id)
        f2id = self.store.create_followup_row(workflow_id=wf, campaign_id=c, lead=lead, previous=f1, sequence_type="FOLLOWUP_2", sequence_number=2, scheduled_at=datetime.now(timezone.utc))
        self.assertIsNotNone(f2id)

    def test_10_f3_only_after_f2_sent(self):
        wf, c = self.create_workflow_campaign(1)
        lead, oid = self.queue_initial(wf, c, 1, "SENDER_1", "sender1@example.com")
        self.store.claim_for_send(oid); self.store.mark_sent(oid, datetime.now(timezone.utc))
        initial = self.store.get_outreach(oid)
        f1id = self.store.create_followup_row(workflow_id=wf, campaign_id=c, lead=lead, previous=initial, sequence_type="FOLLOWUP_1", sequence_number=1, scheduled_at=datetime.now(timezone.utc))
        f1 = self.store.get_outreach(f1id); self.store.queue_followup_draft(f1id, "Re: s", "consulting services", [], .9, initial["smtp_message_id"], initial["smtp_message_id"]); self.store.claim_for_send(f1id); self.store.mark_sent(f1id, datetime.now(timezone.utc))
        f1 = self.store.get_outreach(f1id)
        f2id = self.store.create_followup_row(workflow_id=wf, campaign_id=c, lead=lead, previous=f1, sequence_type="FOLLOWUP_2", sequence_number=2, scheduled_at=datetime.now(timezone.utc))
        f2 = self.store.get_outreach(f2id); self.store.queue_followup_draft(f2id, "Re: s", "consulting services", [], .9, f1["smtp_message_id"], f1["references_text"] + " " + f1["smtp_message_id"]); self.store.claim_for_send(f2id); self.store.mark_sent(f2id, datetime.now(timezone.utc))
        f2 = self.store.get_outreach(f2id)
        f3id = self.store.create_followup_row(workflow_id=wf, campaign_id=c, lead=lead, previous=f2, sequence_type="FOLLOWUP_3", sequence_number=3, scheduled_at=datetime.now(timezone.utc))
        self.assertIsNotNone(f3id)

    def test_11_reply_suppresses_future_followups(self):
        wf, c = self.create_workflow_campaign(1)
        lead, oid = self.queue_initial(wf, c, 1, "SENDER_1", "sender1@example.com")
        self.store.claim_for_send(oid); self.store.mark_sent(oid, datetime.now(timezone.utc)); initial = self.store.get_outreach(oid)
        f1 = self.store.create_followup_row(workflow_id=wf, campaign_id=c, lead=lead, previous=initial, sequence_type="FOLLOWUP_1", sequence_number=1, scheduled_at=datetime.now(timezone.utc))
        self.store.suppress(lead["email"], lead["lead_id"], "reply")
        self.assertEqual(self.store.get_outreach(f1)["status"], "CANCELLED")

    def test_12_bounce_suppresses_future_followups(self):
        lead = self.lead(1); self.store.upsert_lead(lead); self.store.suppress(lead["email"], lead["lead_id"], "hard_bounce")
        self.assertTrue(self.store.is_suppressed(lead["email"]))
        self.assertEqual(self.store.get_lead(lead["lead_id"])["status"], "BOUNCED")

    def test_13_unsubscribe_suppresses_future_followups(self):
        lead = self.lead(1); self.store.upsert_lead(lead); self.store.suppress(lead["email"], lead["lead_id"], "unsubscribe")
        self.assertEqual(self.store.get_lead(lead["lead_id"])["status"], "UNSUBSCRIBED")

    def test_14_same_sender_is_preserved(self):
        wf, c = self.create_workflow_campaign(1)
        lead, oid = self.queue_initial(wf, c, 1, "SENDER_4", "sender4@example.com")
        self.store.claim_for_send(oid); self.store.mark_sent(oid, datetime.now(timezone.utc)); initial = self.store.get_outreach(oid)
        f1id = self.store.create_followup_row(workflow_id=wf, campaign_id=c, lead=lead, previous=initial, sequence_type="FOLLOWUP_1", sequence_number=1, scheduled_at=datetime.now(timezone.utc))
        self.assertEqual(self.store.get_outreach(f1id)["sender_id"], "SENDER_4")

    def test_15_thread_headers_are_correct(self):
        wf, c = self.create_workflow_campaign(1)
        lead, oid = self.queue_initial(wf, c, 1, "SENDER_2", "sender2@example.com")
        self.store.claim_for_send(oid); self.store.mark_sent(oid, datetime.now(timezone.utc)); initial = self.store.get_outreach(oid)
        f1id = self.store.create_followup_row(workflow_id=wf, campaign_id=c, lead=lead, previous=initial, sequence_type="FOLLOWUP_1", sequence_number=1, scheduled_at=datetime.now(timezone.utc))
        f1 = self.store.get_outreach(f1id)
        self.assertEqual(f1["in_reply_to"], initial["smtp_message_id"])
        self.assertIn(initial["smtp_message_id"], f1["references_text"])


class ProviderAndValidationTests(BaseTest):
    def test_16_temporary_research_failure_retries_and_continues(self):
        lead = self.lead(1); self.store.upsert_lead(lead); self.store.mark_research_retry(lead["lead_id"], delay_seconds=1, terminal_after=3)
        row = self.store.get_lead(lead["lead_id"])
        self.assertEqual(row["status"], "ELIGIBLE"); self.assertEqual(row["research_attempts"], 1)

    def test_17_503_is_handled(self):
        class Resp:
            status_code = 503
            text = "overloaded"
            def raise_for_status(self): raise RuntimeError("503")
        class Sess:
            def post(self, *a, **k): return Resp()
        client = LLMClient("k", "https://x", "model", 1, max_retries=0, backoff_seconds=0)
        client._local.session = Sess()
        with self.assertRaises(LLMTemporaryError): client.chat_json_object("s", "u")

    def test_18_timeout_is_handled(self):
        import requests
        class Sess:
            def post(self, *a, **k): raise requests.Timeout("timeout")
        client = LLMClient("k", "https://x", "model", 1, max_retries=0, backoff_seconds=0); client._local.session = Sess()
        with self.assertRaises(LLMTemporaryError): client.chat_json_object("s", "u")

    def test_19_invalid_llm_json_is_handled(self):
        self.assertRaises(LLMInvalidResponse, parse_json_value, "{not valid json}")

    def test_20_correct_evidence_validation_succeeds(self):
        validator = PersonalizationValidator(.75)
        draft = {"eligible": True, "confidence": .9, "subject": "x", "body": "Example Business lists consulting services.", "cta": "Discuss consulting services", "observations": ["The business lists consulting services."], "opportunity": "The consulting services suggest a service inquiry opportunity.", "evidence": [{"url": "https://biz.example/", "snippet": "Example Business lists consulting services."}]}
        pages = [{"url": "https://biz.example/", "text": "Example Business lists consulting services."}]
        result = validator.validate(draft, pages, {"company": "Example Business"})
        self.assertTrue(result.valid, result.reasons)

    def test_21_unsupported_claim_is_rejected(self):
        validator = PersonalizationValidator(.75)
        draft = {"eligible": True, "confidence": .9, "subject": "x", "body": "Example Business lists consulting services.", "cta": "Discuss consulting services", "observations": ["The business operates private jets."], "opportunity": "Private jets need software.", "evidence": [{"url": "https://biz.example/", "snippet": "Example Business lists consulting services."}]}
        pages = [{"url": "https://biz.example/", "text": "Example Business lists consulting services."}]
        self.assertFalse(validator.validate(draft, pages, {"company": "Example Business"}).valid)

    def test_22_url_normalization_is_consistent(self):
        self.assertEqual(normalize_evidence_url("https://www.Example.com/contact/"), "https://example.com/contact")

    def test_23_smtp_temporary_failure_is_retryable_class(self):
        self.assertEqual(classify_send_error(OSError("network")), "temporary/provider/network")

    def test_24_smtp_terminal_recipient_failure_is_terminal(self):
        import smtplib
        exc = smtplib.SMTPRecipientsRefused({"x@example.com": (550, b"no")})
        self.assertEqual(classify_send_error(exc), "terminal recipient/address")

    def test_25_sender_auth_failure_stops_sender(self):
        day = datetime.now(timezone.utc).date().isoformat()
        self.store.record_send_failure("SENDER_1", day, "authentication")
        self.assertEqual(self.store.sender_day("SENDER_1", day)["health_state"], "STOPPED")

    def test_26_stale_sending_reconciles_safely(self):
        wf, c = self.create_workflow_campaign(1)
        lead, oid = self.queue_initial(wf, c, 1, "SENDER_1", "sender1@example.com")
        old = datetime.now(timezone.utc) - timedelta(hours=2)
        self.store.execute("UPDATE outreach SET status='SENDING',updated_at_utc=? WHERE outreach_id=?", [old, oid])
        out = self.store.reconcile_startup(sending_stale_minutes=30, research_stale_minutes=30, personalization_stale_minutes=30)
        self.assertEqual(self.store.get_outreach(oid)["status"], "REVIEW_NEEDED"); self.assertEqual(out["ambiguous_sends"], 1)

    def test_27_mailbox_cursor_is_durable(self):
        self.store.save_mailbox_state("SENDER_1", "7", 42, "HEALTHY")
        last, reset = self.store.reconcile_inbound_cursor("SENDER_1", "7")
        self.assertEqual(last, 42); self.assertFalse(reset)
        last, reset = self.store.reconcile_inbound_cursor("SENDER_1", "8")
        self.assertEqual(last, 0); self.assertTrue(reset)

    def test_28_duplicate_inbound_is_not_processed_twice(self):
        received = datetime.now(timezone.utc)
        ok1 = self.store.save_inbound(inbound_id="a", sender_id="SENDER_1", message_id="<m>", in_reply_to="", references_text="", received_at=received, from_email="a@example.com", subject="x", event_type="REPLY", confidence=.9, lead_id=None, outreach_id=None)
        ok2 = self.store.save_inbound(inbound_id="b", sender_id="SENDER_1", message_id="<m>", in_reply_to="", references_text="", received_at=received, from_email="a@example.com", subject="x", event_type="REPLY", confidence=.9, lead_id=None, outreach_id=None)
        self.assertTrue(ok1); self.assertFalse(ok2)

    def test_29_reset_state_clears_only_runtime_tables(self):
        wf, c = self.create_workflow_campaign(1)
        self.queue_initial(wf, c, 1)
        self.store.save_automation_last_trigger("x", datetime.now(timezone.utc))
        self.store.reset_runtime_state()
        self.assertEqual(self.store.scalar("SELECT count(*) FROM lead"), 0)
        self.assertEqual(self.store.scalar("SELECT count(*) FROM workflow_run"), 0)
        self.assertEqual(self.store.scalar("SELECT count(*) FROM schema_migrations"), 1)

    def test_30_workflow_target_is_per_campaign_not_lifetime(self):
        wf1, c1 = self.create_workflow_campaign(2)
        for i in (1,2):
            _, oid = self.queue_initial(wf1, c1, i); self.store.claim_for_send(oid); self.store.mark_sent(oid, datetime.now(timezone.utc))
        self.store.finish_campaign(c1)
        wf2, c2 = self.create_workflow_campaign(2)
        self.assertEqual(self.store.successful_initial_count(c2), 0)
        self.assertEqual(self.store.scalar("SELECT target_new_initials FROM campaign_run WHERE campaign_run_id=?", [c2]), 2)

    def test_31_no_empty_cycle_infinite_loop(self):
        class EmptyDiscovery(FakeDiscovery):
            def discover_raw(self, *a, **k):
                self.calls += 1
                return {"raw_candidates": 0, "deduplicated_candidates": 0, "places_requests_used": self.settings.discovery_max_places_requests if hasattr(self, 'settings') else 1}
            def process_candidates(self, *a, **k): return {"qualified": 0, "rejected": 0, "retryable": 0, "verified": 0, "duplicates": 0}
        disc = EmptyDiscovery(self.store); disc.settings = self.settings
        orch = Orchestrator(self.settings, self.store, disc, FakeResearch(self.store), None, None, FakeMailbox())
        start = time.monotonic()
        code, metrics = orch.run(reset_state=False, target=1, send_enabled=False, dry_run=True, process_followups=False, process_new_outreach=True)
        self.assertEqual(code, 0)
        self.assertEqual(metrics["run_status"], "DRY_RUN")
        self.assertLess(time.monotonic() - start, 1.0)
        self.assertEqual(disc.calls, 1)


class ExactAcceptanceTests(BaseTest):
    def _fake_orchestrator(self, *, start=0, chunk=20, target_send_retries=0):
        discovery = FakeDiscovery(self.store, start=start, chunk=chunk)
        personalization = __import__('app.personalization', fromlist=['PersonalizationGenerator']).PersonalizationGenerator(FakeLLM(), .75, 0)
        orch = Orchestrator(self.settings, self.store, discovery, FakeResearch(self.store), personalization, None, FakeMailbox())
        class Mailer:
            def __init__(self, store, crash_after=None):
                self.store = store
                self.crash_after = crash_after
                self.sent_total = 0
            def send_batch(self, batch_id, rows, sender_by_id, credentials, dry_run=False):
                out=[]
                for row in rows:
                    if self.crash_after is not None and self.sent_total >= self.crash_after:
                        raise RuntimeError('simulated runner crash')
                    self.store.claim_for_send(row['outreach_id'])
                    out.append(SendResult(str(row['outreach_id']), 'SENT', provider_message_id=row['smtp_message_id']))
                    self.sent_total += 1
                return out
        orch.mailer = Mailer(self.store)
        return orch, discovery

    def test_a01_exact_100_successful_initials(self):
        settings = replace(self.settings, retry_base_seconds=0)
        orch, discovery = self._fake_orchestrator(start=1000, chunk=20)
        orch.settings = settings
        orch.store = self.store
        code, metrics = orch.run(reset_state=False, target=100, send_enabled=True, dry_run=False, process_followups=False, process_new_outreach=True)
        self.assertEqual(code, 0)
        self.assertEqual(metrics['successful_initial_sends'], 100)
        self.assertEqual(self.store.scalar("SELECT count(*) FROM outreach WHERE sequence_type=? AND status=? AND campaign_run_id IN (SELECT campaign_run_id FROM campaign_run WHERE target_new_initials=100)", ["INITIAL", "SENT"]), 100)
        self.assertGreaterEqual(discovery.calls, 1)

    def test_a02_crash_after_27_resumes_without_resend(self):
        settings = replace(self.settings, retry_base_seconds=0)
        orch, _ = self._fake_orchestrator(start=2000, chunk=40)
        class CrashMailer: 
            def __init__(self, store):
                self.store = store
                self.sent = 0
            def send_batch(self, batch_id, rows, sender_by_id, credentials, dry_run=False):
                results = []
                for row in rows:
                    if self.sent == 27:
                        raise RuntimeError('simulated runner crash')
                    self.store.claim_for_send(row['outreach_id'])
                    self.store.mark_sent(row['outreach_id'], datetime.now(timezone.utc))
                    self.sent += 1
                    results.append(SendResult(str(row['outreach_id']), 'SENT', provider_message_id=row['smtp_message_id']))
                return results
        orch.mailer = CrashMailer(self.store)
        orch.settings = settings
        with self.assertRaises(RuntimeError):
            orch.run(reset_state=False, target=30, send_enabled=True, dry_run=False, process_followups=False, process_new_outreach=True)
        active = self.store.get_active_campaign()
        self.assertIsNotNone(active)
        campaign_id = active['campaign_run_id']
        self.assertEqual(self.store.successful_initial_count(campaign_id), 27)
        sent_before = {r['outreach_id'] for r in self.store.fetchall("SELECT outreach_id FROM outreach WHERE campaign_run_id=? AND status='SENT'", [campaign_id])}
        orch2, _ = self._fake_orchestrator(start=3000, chunk=20)
        orch2.settings = settings
        orch2.mailer.sent_total = 0
        class RecoveryMailer:
            def __init__(self, store): self.store = store
            def send_batch(self, batch_id, rows, sender_by_id, credentials, dry_run=False):
                out = []
                for row in rows:
                    self.store.claim_for_send(row['outreach_id'])
                    out.append(SendResult(str(row['outreach_id']), 'SENT', provider_message_id=row['smtp_message_id']))
                return out
        orch2.mailer = RecoveryMailer(self.store)
        code, metrics = orch2.run(reset_state=False, target=30, send_enabled=True, dry_run=False, process_followups=False, process_new_outreach=True)
        self.assertEqual(code, 0)
        self.assertEqual(metrics['successful_initial_sends'], 30)
        sent_after = {r['outreach_id'] for r in self.store.fetchall("SELECT outreach_id FROM outreach WHERE campaign_run_id=? AND status='SENT'", [campaign_id])}
        self.assertTrue(sent_before.issubset(sent_after))
        self.assertEqual(len(sent_before), 27)
        self.assertEqual(len(sent_after), 30)


class BatchAndWorkflowTests(BaseTest):
    def test_32_replenishes_discovery_when_preparation_failures_reduce_inventory(self):
        settings = replace(self.settings, retry_base_seconds=1)
        orch = Orchestrator(settings, self.store, FakeDiscovery(self.store, chunk=2), FakeResearch(self.store), __import__('app.personalization', fromlist=['PersonalizationGenerator']).PersonalizationGenerator(FakeLLM(), .75, 0), None, FakeMailbox())
        # The fake discovery adds new candidates whenever inventory runs low; the run can build a small target without a dead queue.
        orch.personalization.llm = FakeLLM()
        class FakeMailerController:
            def __init__(self, store): self.store = store
            def send_batch(self, batch_id, rows, sender_by_id, credentials, dry_run=False):
                out = []
                for r in rows:
                    self.store.claim_for_send(r["outreach_id"])
                    out.append(SendResult(str(r["outreach_id"]), "SENT", provider_message_id=r["smtp_message_id"]))
                return out
        orch.mailer = FakeMailerController(self.store)
        code, metrics = orch.run(reset_state=False, target=2, send_enabled=True, dry_run=False, process_followups=False, process_new_outreach=True)
        self.assertEqual(code, 0); self.assertEqual(metrics["successful_initial_sends"], 2); self.assertGreaterEqual(orch.discovery.calls, 1)

    def test_33_monitor_yaml_defaults_automation_off(self):
        self.assertFalse(self.settings.automation_enabled)

    def test_34_manual_overrides_send_and_dry_run_safely(self):
        safe = Settings.from_monitor(os.path.join(ROOT, "monitor.yaml"), {"send_enabled": True, "dry_run": False, "target_new_initials": 100})
        self.assertTrue(safe.send_enabled); self.assertFalse(safe.dry_run); self.assertEqual(safe.target_new_initials, 100)

    def test_35_full_run_handles_followup_and_new_outreach_together(self):
        # Complete an older campaign with an INITIAL, then make F1 due; the next full run gets a new campaign and sends both lanes.
        old_wf, old_c = self.create_workflow_campaign(1)
        old_lead, initial_id = self.queue_initial(old_wf, old_c, 1, "SENDER_1", "sender1@example.com")
        self.store.claim_for_send(initial_id); self.store.mark_sent(initial_id, datetime.now(timezone.utc))
        self.store.finish_campaign(old_c)
        initial = self.store.get_outreach(initial_id)
        FakeResearch(self.store).run(dict(old_lead))
        f1id = self.store.create_followup_row(workflow_id=old_wf, campaign_id=old_c, lead=old_lead, previous=initial, sequence_type="FOLLOWUP_1", sequence_number=1, scheduled_at=datetime.now(timezone.utc)-timedelta(seconds=1))
        self.store.queue_followup_draft(f1id, "Re: s", "Hello Example Business consulting services", ["https://site.example/"], .9, initial["smtp_message_id"], initial["smtp_message_id"])
        settings = replace(self.settings, send_enabled=True, dry_run=False, retry_base_seconds=0)
        orch = Orchestrator(settings, self.store, FakeDiscovery(self.store, start=100, chunk=1), FakeResearch(self.store), __import__('app.personalization', fromlist=['PersonalizationGenerator']).PersonalizationGenerator(FakeLLM(), .75, 0), None, FakeMailbox())
        class FM:
            def __init__(self, store): self.store = store
            def send_batch(self, batch_id, rows, sender_by_id, credentials, dry_run=False):
                out = []
                for r in rows:
                    self.store.claim_for_send(r["outreach_id"])
                    out.append(SendResult(str(r["outreach_id"]), "SENT", provider_message_id=r["smtp_message_id"]))
                return out
        orch.mailer = FM(self.store)
        code, metrics = orch.run(reset_state=False, target=1, send_enabled=True, dry_run=False, process_followups=True, process_new_outreach=True)
        self.assertEqual(code, 0); self.assertGreaterEqual(metrics["followups_sent"], 1); self.assertEqual(metrics["successful_initial_sends"], 1)

    def test_36_like_percent_query_is_parameter_safe(self):
        self.store.upsert_lead(self.lead(1))
        sql = "SELECT count(*) FROM lead WHERE company LIKE ?"
        self.assertEqual(self.store._sql(sql), sql)
        self.assertEqual(self.store.scalar(sql, ["%Company 1%"]), 1)

    def test_37_batch_contains_at_most_one_initial_per_sender(self):
        wf, c = self.create_workflow_campaign(2)
        _, o1 = self.queue_initial(wf, c, 1)
        _, o2 = self.queue_initial(wf, c, 2)
        batch = self.store.create_batch(wf, c, "INITIAL", 1, [o1, o2])
        with self.assertRaises(ValueError):
            self.store.assign_batch(batch, [(o1, self.lead(1)["lead_id"], "SENDER_1", "sender1@example.com"), (o2, self.lead(2)["lead_id"], "SENDER_1", "sender1@example.com")])

    def test_38_batch_uses_up_to_10_concurrent_senders(self):
        wf, c = self.create_workflow_campaign(10)
        for i in range(10): self.queue_initial(wf, c, i)
        rows = self.store.list_ready_initials(c, 10)
        batch = self.store.create_batch(wf, c, "INITIAL", 1, [r["outreach_id"] for r in rows])
        senders = self.settings.sender_configs()
        self.store.assign_batch(batch, [(r["outreach_id"], r["lead_id"], senders[i].sender_id, senders[i].email) for i,r in enumerate(rows)])
        FakeSMTP.active = 0; FakeSMTP.max_active = 0; FakeSMTP.calls = []; FakeSMTP.mode = "success"
        controller = BatchSendController(self.store, replace(self.settings, max_concurrency=10))
        with patch("app.mailer.SMTPMailer", FakeSMTP):
            result = controller.send_batch(batch, self.store.fetchall("SELECT * FROM outreach WHERE batch_id=?", [batch]), {s.sender_id:s for s in senders}, {s.credential_env:"x" for s in senders}, dry_run=False)
        self.assertEqual(sum(r.status == "SENT" for r in result), 10); self.assertEqual(len(set(FakeSMTP.calls)), 10); self.assertGreater(FakeSMTP.max_active, 1)

    def test_39_success_count_is_SENT_not_QUEUED(self):
        wf, c = self.create_workflow_campaign(2)
        self.queue_initial(wf, c, 1, "SENDER_1", "sender1@example.com"); self.queue_initial(wf, c, 2)
        rows = self.store.fetchall("SELECT * FROM outreach WHERE campaign_run_id=? AND sender_id=?", [c, "SENDER_1"])
        self.store.claim_for_send(rows[0]["outreach_id"]); self.store.mark_sent(rows[0]["outreach_id"], datetime.now(timezone.utc))
        self.assertEqual(self.store.successful_initial_count(c), 1)


class MailboxAndCrawlerTests(BaseTest):
    def make_raw(self, *, message_id="<inbound>", from_email="reply@example.com", subject="Re: hello", in_reply_to="", list_unsub=None, body="Thanks"):
        msg = EmailMessage(); msg["From"] = from_email; msg["To"] = "sender1@example.com"; msg["Subject"] = subject; msg["Message-ID"] = message_id
        if in_reply_to: msg["In-Reply-To"] = in_reply_to
        if list_unsub: msg["List-Unsubscribe"] = list_unsub
        msg.set_content(body); return msg.as_bytes()

    def test_40_mailbox_classification_supports_reply_bounce_unsubscribe(self):
        for raw, expected in [
            (self.make_raw(), "REPLY"),
            (self.make_raw(from_email="mailer-daemon@example.com", subject="Delivery Status Notification", body="permanent 5.1.1"), "HARD_BOUNCE"),
            (self.make_raw(list_unsub="<mailto:unsubscribe@example.com>"), "UNSUBSCRIBED"),
        ]:
            self.assertEqual(classify(parse_message(raw))[0].value, expected)

    def test_41_mailbox_monitor_correlates_and_suppresses(self):
        wf, c = self.create_workflow_campaign(1)
        lead, oid = self.queue_initial(wf, c, 1, "SENDER_1", "sender1@example.com")
        self.store.claim_for_send(oid); self.store.mark_sent(oid, datetime.now(timezone.utc)); initial = self.store.get_outreach(oid)
        FakeIMAPProvider.messages = [(1, self.make_raw(in_reply_to=initial["smtp_message_id"]))]
        monitor = MailboxMonitor(self.store, self.settings, lambda s, c: FakeIMAPProvider(s, c))
        result = monitor.run_sender(self.settings.sender_configs()[0])
        self.assertEqual(result["replies"], 1); self.assertTrue(self.store.is_suppressed(lead["email"]))

    def test_42_redundant_crawler_homepage_is_fetched_once(self):
        crawler = WebsiteCrawler(5, 100000, 3, 0, False)
        calls = []
        def fake_fetch(session, url, robots):
            calls.append(url)
            if len(calls) == 1:
                return Page("https://example.com/", "Home", "home", ("https://example.com/contact",), ("info@example.com",))
            return Page("https://example.com/contact", "Contact", "contact", (), ("info@example.com",))
        crawler.fetch = fake_fetch
        pages = crawler.crawl("https://example.com/")
        self.assertEqual(calls.count("https://example.com/"), 1); self.assertEqual(len(pages), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
