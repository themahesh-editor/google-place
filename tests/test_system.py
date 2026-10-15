from __future__ import annotations

import email
import os
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from app.config import Settings
from app.db import Store, deterministic_lead_id, deterministic_outreach_id
from app.mailbox import MailboxMonitor, ParsedInbound, classify
from app.mailer import BatchSendController
from app.models import InboundEventType, PersonalizationDraft
from app.orchestrator import Orchestrator, iso, parse_utc
from app.personalization import PersonalizationValidator


class TestSettings:
    def __init__(self):
        self.supabase_db_url = "sqlite://:memory:"
        self.app_timezone = "Asia/Kolkata"
        self.allowed_country_codes = ("US", "CA", "GB", "AU")
        self.discovery_target = 5
        self.max_places_search_requests = 30
        self.max_pages_per_search = 3
        self.places_page_size = 20
        self.max_raw_candidates = 50
        self.discovery_max_retries_per_run = 10
        self.discovery_transient_retry_hours = 24
        self.discovery_no_email_retry_days = 7
        self.crawler_timeout_seconds = 5
        self.crawler_max_bytes = 100000
        self.crawler_max_pages = 3
        self.crawler_request_delay_seconds = 0
        self.honor_robots = False
        self.initial_outreach_target = 10
        self.batch_size = 10
        self.batch_interval_minutes = 1
        self.daily_initial_limit = 10
        self.daily_followup_limit = 10
        self.daily_total_limit = 40
        self.enforce_send_window = False
        self.enforce_daily_limits = False
        self.max_concurrent_sends = 10
        self.retry_limit = 3
        self.retry_base_seconds = 1
        self.sending_window_start = datetime.strptime("00:00", "%H:%M").time()
        self.sending_window_end = datetime.strptime("23:59", "%H:%M").time()
        self.sending_window_mode = "app"
        self.followup_1_delay_hours = 24
        self.followup_2_delay_days = 7
        self.followup_3_delay_days = 14
        self.mailbox_check_lookback_minutes = 180
        self.mailbox_max_messages_per_run = 100
        self.max_batches_per_run = 20
        self.llm_base_url = ""
        self.llm_model = "fake"
        self.llm_timeout_seconds = 2
        self.llm_max_tokens = 100
        self.min_personalization_confidence = 0.75
        self.send_enabled = False
        self.dry_run = True
        self.reset_state = False
        self.personalization_retry_limit = 1
        self.reopen_personalization_reviews = False

    def timezone(self):
        from zoneinfo import ZoneInfo
        return ZoneInfo(self.app_timezone)

    def sender_configs(self):
        from app.config import SenderConfig
        return [SenderConfig(f"SENDER_{i}", f"sender{i}@example.com", f"SENDER_{i}", "imap", 993, True, "smtp", 465, True) for i in range(1, 11)]


def lead_row(i=1, status="ELIGIBLE"):
    email_addr = f"lead{i}@company{i}.example"
    website = f"https://company{i}.example/"
    return {
        "lead_id": deterministic_lead_id(email_addr, website), "email": email_addr, "company": f"Company {i}",
        "website": website, "website_domain": f"company{i}.example", "city": "Dallas", "region": "TX", "country_code": "US",
        "timezone": "America/Chicago", "lead_source": "test", "place_id": f"place-{i}", "scale_class": "LOCAL",
        "qualification_confidence": 0.95, "qualification_reason": "evidence", "discovery_facts": "facts", "status": status,
    }


def research_row(store, lead):
    rid = f"research-{lead['lead_id']}"
    store.save_research({
        "research_id": rid, "lead_id": lead["lead_id"], "website_domain": lead["website_domain"], "canonical_url": lead["website"],
        "company_identity": lead["company"], "business_summary": "summary", "services": ["service"], "business_facts": ["fact"],
        "locations": ["Dallas"], "specialties": [], "website_signals": ["booking"], "customer_journey_signals": ["request"],
        "ai_opportunity_signals": ["faq"], "important_public_text": "text", "evidence": [{"url": lead["website"], "snippet": f"{lead['company']} has a booking page."}],
        "research_timestamp_utc": "2026-10-01T00:00:00Z", "research_status": "RESEARCHED", "research_version": "2.0", "error": None,
        "retry_count": 0, "next_retry_at_utc": None,
    })
    return store.latest_research(lead["lead_id"])


class FakeSMTP:
    lock = threading.Lock(); active = 0; max_active = 0; calls = []
    def __init__(self, sender): self.sender = sender
    def send(self, row):
        with self.lock:
            type(self).active += 1; type(self).max_active = max(type(self).max_active, type(self).active); type(self).calls.append(self.sender.sender_id)
        time.sleep(0.05)
        with self.lock: type(self).active -= 1
        return row["message_id"]


class FakeLLM:
    def initial(self):
        return PersonalizationDraft(True, "summary", ["observation"], "help", "About Company", "The booking page could be supported with common answers before visitors request a booking.", "Would a quick look be useful?", "Best, AttachAI", .95, ["https://company1.example/"], [], ["booking page"])


class SystemTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.store = Store(f"sqlite://{os.path.join(self.td.name, 'db.sqlite')}")
        self.store.migrate("migrations")
        self.settings = TestSettings()

    def tearDown(self):
        self.store.close(); self.td.cleanup()

    def test_database_init_and_reset(self):
        run = self.store.start_workflow("MANUAL", False)
        lead = lead_row(1); self.store.upsert_lead(lead)
        self.assertEqual(self.store.scalar("SELECT count(*) FROM leads"), 1)
        self.store.reset_runtime_state()
        self.assertEqual(self.store.scalar("SELECT count(*) FROM leads"), 0)
        self.assertEqual(self.store.scalar("SELECT count(*) FROM workflow_run"), 0)

    def test_next_untouched_leads_not_fixed_prefix(self):
        run_id = self.store.start_workflow("MANUAL", False)
        for i in range(1, 6): self.store.upsert_lead(lead_row(i))
        first = self.store.claim_untouched_leads(2)
        for row in first:
            self.store.update_lead_status(row["lead_id"], "QUEUED")
        self.store.queue_initial(run_id=run_id, lead_id=first[0]["lead_id"], sender_id="UNASSIGNED", sender_email="", subject="s", body="body a Company 1", evidence_urls=[first[0]["website"]], confidence=.9)
        self.store.queue_initial(run_id=run_id, lead_id=first[1]["lead_id"], sender_id="UNASSIGNED", sender_email="", subject="s2", body="body b Company 2", evidence_urls=[first[1]["website"]], confidence=.9)
        nxt = self.store.claim_untouched_leads(2)
        self.assertTrue(set(x["lead_id"] for x in nxt).isdisjoint({x["lead_id"] for x in first}))

    def test_batch_assigns_one_message_per_sender(self):
        run_id = self.store.start_workflow("MANUAL", False)
        for i in range(1, 11):
            self.store.upsert_lead(lead_row(i))
            self.store.queue_initial(run_id=run_id, lead_id=lead_row(i)["lead_id"], sender_id="UNASSIGNED", sender_email="", subject="s", body=f"Company {i} useful message {i}", evidence_urls=[lead_row(i)["website"]], confidence=.9)
        batch = self.store.create_batch(run_id, 1, "INITIAL", "2026-10-02T12:00:00Z", 10)
        senders = self.settings.sender_configs()
        self.store.assign_batch(batch, [(self.store.fetchall("SELECT outreach_id,lead_id FROM outreach ORDER BY created_at_utc")[i]["outreach_id"], self.store.fetchall("SELECT outreach_id,lead_id FROM outreach ORDER BY created_at_utc")[i]["lead_id"], senders[i].sender_id, senders[i].email) for i in range(10)], "2026-10-02T12:00:00Z")
        rows = self.store.fetchall("SELECT * FROM outreach WHERE batch_id=?", [batch])
        self.assertEqual(len(rows), 10)
        self.assertEqual(len({r["sender_id"] for r in rows}), 10)

    def test_rerun_uses_global_success_count_and_only_sends_pending(self):
        run = self.store.start_workflow("MANUAL", False)
        senders = self.settings.sender_configs()
        for i in range(1, 5):
            lead = lead_row(i); self.store.upsert_lead(lead)
            self.store.queue_initial(run_id=run, lead_id=lead["lead_id"], sender_id=senders[i-1].sender_id, sender_email=senders[i-1].email, subject="s", body=f"Company {i} rerun", evidence_urls=[lead["website"]], confidence=.95)
        queued = self.store.fetchall("SELECT * FROM outreach ORDER BY created_at_utc")
        for row in queued[:3]:
            self.store.claim_outreach(row["outreach_id"]); self.store.mark_sent(row["outreach_id"], "2026-09-01T12:00:00Z", f"<sent-{row['outreach_id'][:8]}@example.com>")
        orch = Orchestrator(self.settings, self.store, object(), object(), object(), BatchSendController(self.store, self.settings, FakeSMTP))
        self.settings.batch_interval_minutes = 0
        self.settings.max_batches_per_run = 1
        orch._wait_until = lambda when: None
        result = orch.send_initial_until_target(run, 4, True)
        self.assertEqual(result["successful"], 4)
        self.assertEqual(self.store.scalar("SELECT count(*) FROM outreach WHERE sequence_type='INITIAL' AND status='SENT'"), 4)

    def test_real_batch_concurrency(self):
        run_id = self.store.start_workflow("MANUAL", False)
        for i in range(1, 11):
            self.store.upsert_lead(lead_row(i))
            self.store.queue_initial(run_id=run_id, lead_id=lead_row(i)["lead_id"], sender_id="UNASSIGNED", sender_email=f"sender{i}@example.com", subject="s", body=f"Company {i} useful {i}", evidence_urls=[lead_row(i)["website"]], confidence=.9)
        batch = self.store.create_batch(run_id, 1, "INITIAL", "2026-10-02T12:00:00Z", 10)
        senders = self.settings.sender_configs(); all_rows = self.store.fetchall("SELECT * FROM outreach ORDER BY created_at_utc")
        self.store.assign_batch(batch, [(all_rows[i]["outreach_id"], all_rows[i]["lead_id"], senders[i].sender_id, senders[i].email) for i in range(10)], "2026-10-02T12:00:00Z")
        FakeSMTP.active = FakeSMTP.max_active = 0; FakeSMTP.calls = []
        controller = BatchSendController(self.store, self.settings, FakeSMTP)
        result = controller.send_batch(batch, self.store.fetchall("SELECT * FROM outreach WHERE batch_id=?", [batch]), {s.sender_id:s for s in senders}, True)
        self.assertEqual(sum(x.status == "SENT" for x in result), 10)
        self.assertEqual(len(set(FakeSMTP.calls)), 10)
        self.assertGreater(FakeSMTP.max_active, 1)

    def test_crash_recovery_requeues_unsent_batch_rows_without_resending_sent_rows(self):
        run = self.store.start_workflow("MANUAL", False)
        senders = self.settings.sender_configs()
        for i in range(1, 11):
            lead = lead_row(i); self.store.upsert_lead(lead)
            self.store.queue_initial(run_id=run, lead_id=lead["lead_id"], sender_id="UNASSIGNED", sender_email="", subject="s", body=f"Company {i} crash recovery message", evidence_urls=[lead["website"]], confidence=.95)
        rows = self.store.fetchall("SELECT * FROM outreach ORDER BY created_at_utc")
        batch = self.store.create_batch(run, 1, "INITIAL", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), 10)
        self.store.assign_batch(batch, [(rows[i]["outreach_id"], rows[i]["lead_id"], senders[i].sender_id, senders[i].email) for i in range(10)], datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        for i in range(5):
            oid = rows[i]["outreach_id"]
            self.store.claim_outreach(oid); self.store.mark_sent(oid, "2026-10-02T12:00:00Z", f"<sent-{i}@example.com>")
        stale = (datetime.now(timezone.utc) - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.store.execute("UPDATE outreach_batches SET status='RUNNING',updated_at_utc=? WHERE batch_id=?", [stale, batch])
        self.store.execute("UPDATE outreach SET updated_at_utc=? WHERE batch_id=? AND status='SCHEDULED'", [stale, batch])
        self.store.reconcile_stale_batches(cutoff)
        self.assertEqual(self.store.scalar("SELECT count(*) FROM outreach WHERE status='SENT'"), 5)
        self.assertEqual(self.store.scalar("SELECT count(*) FROM outreach WHERE status='QUEUED' AND batch_id IS NULL"), 5)
        self.assertEqual(self.store.scalar("SELECT count(*) FROM outreach WHERE status='SENT' AND message_id IS NOT NULL"), 5)

    def test_stopped_sender_is_not_selected(self):
        day = datetime.now(self.settings.timezone()).date().isoformat()
        self.store.set_sender_health("SENDER_1", day, "STOPPED")
        orch = Orchestrator(self.settings, self.store, object(), object(), object(), object())
        available = [s.sender_id for s in orch._available_senders(datetime.now(timezone.utc), False)]
        self.assertNotIn("SENDER_1", available)

    def test_sender_health_degraded_is_restored_after_successful_mailbox_check(self):
        sender = self.settings.sender_configs()[0]
        day = datetime.now(self.settings.timezone()).date().isoformat()
        self.store.set_sender_health(sender.sender_id, day, "DEGRADED", None)
        class FakeMailbox:
            uidvalidity = "1"
            def __init__(self, sender, credential): pass
            def connect(self): pass
            def fetch_since(self, last_uid, lookback_minutes, max_messages): return []
            def close(self): pass
        run = self.store.start_workflow("MANUAL", False)
        monitor = MailboxMonitor(self.store, self.settings, run, FakeMailbox)
        monitor.run_sender(sender)
        self.assertEqual(self.store.sender_day(sender.sender_id, day)["health_state"], "HEALTHY")

    def test_dry_run_does_not_mutate_message_state(self):
        run = self.store.start_workflow("MANUAL", False)
        lead = lead_row(1); self.store.upsert_lead(lead)
        sender = self.settings.sender_configs()[0]
        self.store.queue_initial(run_id=run, lead_id=lead["lead_id"], sender_id=sender.sender_id, sender_email=sender.email, subject="s", body="Company 1 dry run message", evidence_urls=[lead["website"]], confidence=.95)
        row = self.store.fetchone("SELECT * FROM outreach WHERE lead_id=?", [lead["lead_id"]])
        batch = self.store.create_batch(run, 1, "INITIAL", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), 1)
        self.store.assign_batch(batch, [(row["outreach_id"], lead["lead_id"], sender.sender_id, sender.email)], datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        controller = BatchSendController(self.store, self.settings, FakeSMTP)
        result = controller.send_batch(batch, [dict(self.store.fetchone("SELECT * FROM outreach WHERE outreach_id=?", [row["outreach_id"]]))], {sender.sender_id: sender}, False)
        self.assertEqual(result[0].status, "DRY_RUN")
        self.assertEqual(self.store.get_outreach(row["outreach_id"])["status"], "SCHEDULED")

    def test_interrupted_research_and_batches_are_recovered_on_next_run(self):
        old_run = self.store.start_workflow("MANUAL", False)
        lead = lead_row(1, status="RESEARCHING")
        self.store.upsert_lead(lead)
        research_row(self.store, lead)
        sender = self.settings.sender_configs()[0]
        self.store.queue_initial(run_id=old_run, lead_id=lead["lead_id"], sender_id=sender.sender_id, sender_email=sender.email, subject="s", body="Company 1 recovery", evidence_urls=[lead["website"]], confidence=.95)
        queued = self.store.fetchone("SELECT * FROM outreach WHERE lead_id=?", [lead["lead_id"]])
        batch = self.store.create_batch(old_run, 1, "INITIAL", now := datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), 1)
        self.store.assign_batch(batch, [(queued["outreach_id"], lead["lead_id"], sender.sender_id, sender.email)], now)
        self.store.update_lead_status(lead["lead_id"], "RESEARCHING")
        current_run = self.store.start_workflow("MANUAL", False)
        self.store.claim_outreach(queued["outreach_id"])
        self.store.recover_interrupted_workflow_state(current_run)
        self.assertEqual(self.store.fetchone("SELECT status FROM workflow_run WHERE workflow_run_id=?", [old_run])["status"], "FAILED")
        self.assertEqual(self.store.get_lead(lead["lead_id"])["status"], "RESEARCHED")
        self.assertEqual(self.store.get_outreach(queued["outreach_id"])["status"], "REVIEW_NEEDED")

    def test_resume_prefers_existing_researched_leads_and_does_not_call_research_again(self):
        run = self.store.start_workflow("MANUAL", False)
        lead = lead_row(1)
        self.store.upsert_lead(lead)
        research_row(self.store, lead)
        class ShouldNotResearch:
            def run(self, *args, **kwargs):
                raise AssertionError("existing researched lead was crawled/researched again")
        class GoodPersonalization:
            def initial(self, lead, research, sender_signature):
                return PersonalizationDraft(True, "summary", ["observation"], "help", "Subject", "The booking page could answer common visitor questions.", "", "", .95, [lead["website"]], [], ["booking page"])
        orch = Orchestrator(self.settings, self.store, object(), ShouldNotResearch(), GoodPersonalization(), object())
        result = orch.prepare_initial_messages(run, 1)
        self.assertEqual(result["prepared"], 1)
        self.assertIsNotNone(self.store.get_sequence(lead["lead_id"], "INITIAL", 1))

    def test_resume_existing_pipeline_sends_before_discovery(self):
        run = self.store.start_workflow("MANUAL", False)
        for i in range(1, 11):
            lead = lead_row(i)
            self.store.upsert_lead(lead)
            research_row(self.store, lead)
        class GoodPersonalization:
            def initial(self, lead, research, sender_signature):
                return PersonalizationDraft(True, "summary", ["observation"], "help", f"Subject {lead['lead_id'][:4]}", f"The booking page for {lead['company']} could answer common visitor questions.", "", "", .95, [lead["website"]], [], ["booking page"])
        class ForbiddenDiscovery:
            def __init__(self): self.calls = 0
            def run(self, *args, **kwargs):
                self.calls += 1
                raise AssertionError("discovery should not run while existing leads can satisfy the target")
        discovery = ForbiddenDiscovery()
        controller = BatchSendController(self.store, self.settings, FakeSMTP)
        orch = Orchestrator(self.settings, self.store, discovery, object(), GoodPersonalization(), controller)
        self.settings.batch_interval_minutes = 0
        orch._wait_until = lambda when: None
        result = orch.run_initial_phase(run, 10, True)
        self.assertEqual(result["send"]["successful"], 10)
        self.assertEqual(discovery.calls, 0)

    def test_terminal_personalization_rejection_is_not_reprocessed_as_eligible(self):
        run = self.store.start_workflow("MANUAL", False)
        lead = lead_row(1)
        self.store.upsert_lead(lead)
        research_row(self.store, lead)
        class BadPersonalization:
            def initial(self, lead, research, sender_signature):
                return PersonalizationDraft(False, "", [], "", "", "", "", "", .10, [], [], [])
        orch = Orchestrator(self.settings, self.store, object(), object(), BadPersonalization(), object())
        result = orch.prepare_initial_messages(run, 1)
        self.assertEqual(result["prepared"], 0)
        self.assertEqual(self.store.get_lead(lead["lead_id"])["status"], "REVIEW_NEEDED")
        self.assertEqual(self.store.count_eligible_untouched(), 0)

    def test_validator_enforces_configured_threshold(self):
        lead = lead_row(1); self.store.upsert_lead(lead); research = research_row(self.store, lead)
        draft = PersonalizationDraft(True, "", [], "", "Subject", "The booking page could answer common visitor questions.", "", "", .70, [lead["website"]], [], ["booking page"])
        v = PersonalizationValidator(.75).validate(lead, research, draft, [], self.store)
        self.assertFalse(v.ok); self.assertIn("low_confidence", v.reason)

    def test_followup_chain_requires_previous_success(self):
        run = self.store.start_workflow("MANUAL", False)
        lead = lead_row(1); self.store.upsert_lead(lead); research_row(self.store, lead)
        initial_id = deterministic_outreach_id(lead["lead_id"], "INITIAL", 1)
        body = "Company 1 initial message"
        self.store.insert_outreach({"outreach_id":initial_id,"workflow_run_id":run,"lead_id":lead["lead_id"],"sequence_type":"INITIAL","sequence_number":1,"sender_id":"SENDER_1","sender_email":"sender1@example.com","email":lead["email"],"subject":"s","body":body,"status":"SENT","sent_at_utc":"2026-09-01T12:00:00Z","message_id":"<m1@example.com>","evidence_urls":[lead["website"]],"personalization_confidence":.9,"body_hash":"h1"})
        class FakePersonalization:
            def followup(self,*args,**kwargs): return PersonalizationDraft(True,"",[],"","F1","The booking page could answer common visitor questions.","","",.95,[lead["website"]],[],["booking page"])
        orch = Orchestrator(self.settings,self.store,object(),object(),FakePersonalization(),BatchSendController(self.store,self.settings))
        orch._wait_until=lambda x: None
        orch.prepare_and_send_followups(run, False, True)
        self.assertIsNotNone(self.store.get_sequence(lead["lead_id"],"FOLLOWUP_1",1))
        self.assertIsNone(self.store.get_sequence(lead["lead_id"],"FOLLOWUP_2",2))

    def test_classifier_bounce_and_unsubscribe(self):
        reply = ParsedInbound("<r@x>","","", "Mail delivery failure", "mailer-daemon@x", "2026-10-02T00:00:00Z", "550 user unknown")
        self.assertEqual(classify(reply)[0], InboundEventType.HARD_BOUNCE)
        opt = ParsedInbound("<r2@x>","","", "Re: hello", "owner@x", "2026-10-02T00:00:00Z", "please unsubscribe me")
        self.assertEqual(classify(opt)[0], InboundEventType.UNSUBSCRIBED)

    def test_deterministic_ids(self):
        self.assertEqual(deterministic_lead_id("A@X.COM", "x.example"), deterministic_lead_id("a@x.com", "https://www.x.example/"))
        self.assertNotEqual(deterministic_outreach_id("x", "INITIAL", 1), deterministic_outreach_id("x", "FOLLOWUP_1", 1))

    def test_100_successful_initial_target_uses_ten_sender_batches(self):
        run_id = self.store.start_workflow("MANUAL", False)
        for i in range(1, 101):
            lead = lead_row(i); self.store.upsert_lead(lead)
            self.store.queue_initial(run_id=run_id, lead_id=lead["lead_id"], sender_id="UNASSIGNED", sender_email="", subject=f"s{i}", body=f"Company {i} useful message {i}", evidence_urls=[lead["website"]], confidence=.95)
        self.settings.batch_interval_minutes = 0
        self.settings.max_batches_per_run = 10
        controller = BatchSendController(self.store, self.settings, FakeSMTP)
        orch = Orchestrator(self.settings, self.store, object(), object(), object(), controller)
        orch._wait_until = lambda when: None
        result = orch.send_initial_until_target(run_id, 100, True)
        self.assertEqual(result["successful"], 100)
        batches = self.store.fetchall("SELECT * FROM outreach_batches WHERE workflow_run_id=? ORDER BY batch_number", [run_id])
        self.assertEqual(len(batches), 10)
        self.assertTrue(all(int(b["target_count"]) == 10 for b in batches))
        self.assertEqual(self.store.scalar("SELECT count(*) FROM outreach WHERE workflow_run_id=? AND status='SENT'", [run_id]), 100)
        self.assertEqual(self.store.scalar("SELECT count(*) FROM sender_daily_state WHERE date_key=? AND initials=10", [datetime.now(self.settings.timezone()).date().isoformat()]), 10)

    def test_followup_f2_and_f3_wait_for_successful_previous_stage(self):
        run_id = self.store.start_workflow("MANUAL", False)
        lead = lead_row(1); self.store.upsert_lead(lead); research_row(self.store, lead)
        self.store.insert_outreach({"outreach_id":deterministic_outreach_id(lead["lead_id"],"INITIAL",1),"workflow_run_id":run_id,"lead_id":lead["lead_id"],"sequence_type":"INITIAL","sequence_number":1,"sender_id":"SENDER_1","sender_email":"sender1@example.com","email":lead["email"],"subject":"s","body":"Company 1 initial","status":"SENT","sent_at_utc":"2026-09-01T12:00:00Z","message_id":"<m1@example.com>","evidence_urls":[lead["website"]],"personalization_confidence":.9,"body_hash":"h1"})
        class FakePersonalization:
            def followup(self, lead, research, history, sequence, sender):
                return PersonalizationDraft(True,"",[],"",sequence,f"The booking page could support a {sequence} follow-up.","","",.95,[lead["website"]],[],["booking page"])
        orch = Orchestrator(self.settings,self.store,object(),object(),FakePersonalization(),BatchSendController(self.store,self.settings))
        orch.prepare_and_send_followups(run_id, False, True)
        f1 = self.store.get_sequence(lead["lead_id"],"FOLLOWUP_1",1)
        self.assertIsNotNone(f1); self.assertIsNone(self.store.get_sequence(lead["lead_id"],"FOLLOWUP_2",2))
        self.store.claim_outreach(f1["outreach_id"]); self.store.mark_sent(f1["outreach_id"],"2026-09-02T12:00:00Z","<m2@example.com>")
        orch.prepare_and_send_followups(run_id, False, True)
        f2 = self.store.get_sequence(lead["lead_id"],"FOLLOWUP_2",2)
        self.assertIsNotNone(f2); self.assertEqual(f2["sender_id"],"SENDER_1"); self.assertIsNone(self.store.get_sequence(lead["lead_id"],"FOLLOWUP_3",3))
        self.store.claim_outreach(f2["outreach_id"]); self.store.mark_sent(f2["outreach_id"],"2026-09-09T12:00:00Z","<m3@example.com>")
        orch.prepare_and_send_followups(run_id, False, True)
        f3 = self.store.get_sequence(lead["lead_id"],"FOLLOWUP_3",3)
        self.assertIsNotNone(f3); self.assertEqual(f3["in_reply_to"],"<m3@example.com>")

    def test_reset_false_preserves_state(self):
        lead = lead_row(1); self.store.upsert_lead(lead)
        self.assertEqual(self.store.scalar("SELECT count(*) FROM leads"), 1)
        self.assertEqual(self.store.get_lead(lead["lead_id"])["email"], lead["email"])

    def test_mailbox_reply_suppresses_followups(self):
        run = self.store.start_workflow("MANUAL", False)
        lead = lead_row(1); self.store.upsert_lead(lead)
        initial_id = deterministic_outreach_id(lead["lead_id"],"INITIAL",1)
        self.store.insert_outreach({"outreach_id":initial_id,"workflow_run_id":run,"lead_id":lead["lead_id"],"sequence_type":"INITIAL","sequence_number":1,"sender_id":"SENDER_1","sender_email":"sender1@example.com","email":lead["email"],"subject":"s","body":"Company 1 initial","status":"SENT","sent_at_utc":"2026-10-01T12:00:00Z","message_id":"<m1@example.com>","evidence_urls":[lead["website"]],"personalization_confidence":.9,"body_hash":"reply-hash"})
        msg = EmailMessage(); msg["From"]=lead["email"]; msg["To"]="sender1@example.com"; msg["Date"]=datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000"); msg["Message-ID"]="<reply@example.com>"; msg["In-Reply-To"]="<m1@example.com>"; msg["Subject"]="Re: s"; msg.set_content("Thanks, let's talk.")
        class FakeMailbox:
            uidvalidity = "1"
            def __init__(self, sender, credential): pass
            def connect(self): pass
            def fetch_since(self, last_uid, lookback_minutes, max_messages): return [(1,msg.as_bytes())]
            def close(self): pass
        monitor = MailboxMonitor(self.store,self.settings,run,FakeMailbox)
        result = monitor.run_sender(self.settings.sender_configs()[0])
        self.assertEqual(result["replies"],1)
        self.assertEqual(self.store.get_lead(lead["lead_id"])["status"],"REPLIED")

    def test_manual_test_mode_ignores_send_window_and_daily_limits(self):
        orch = Orchestrator(self.settings, self.store, object(), object(), object(), object())
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        self.assertEqual(orch._next_batch_slot(now, "America/New_York"), now)
        day = now.astimezone(self.settings.timezone()).date().isoformat()
        for sender in self.settings.sender_configs():
            self.store.sender_day(sender.sender_id, day)
            self.store.execute("UPDATE sender_daily_state SET initials=100, followups=100, total=100 WHERE sender_id=? AND date_key=?", [sender.sender_id, day])
        available = orch._available_senders(now, False)
        self.assertEqual(len(available), 10)

    def test_batch_gap_is_ten_minutes_when_enabled_by_configuration(self):
        orch = Orchestrator(self.settings, self.store, object(), object(), object(), object())
        self.settings.batch_interval_minutes = 10
        waits = []
        orch._wait_until = lambda when: waits.append(when)
        before = datetime.now(timezone.utc)
        orch._arm_batch_gap()
        armed = orch.next_batch_allowed_at
        self.assertIsNotNone(armed)
        self.assertGreaterEqual((armed - before).total_seconds(), 599)
        orch._wait_for_next_batch()
        self.assertEqual(len(waits), 1)
        self.assertIsNone(orch.next_batch_allowed_at)

    def test_validator_low_confidence_is_retryable(self):
        lead = lead_row(1); self.store.upsert_lead(lead); research = research_row(self.store, lead)
        draft = PersonalizationDraft(True, "", [], "", "Subject", "The booking page could answer common visitor questions.", "", "", .70, [lead["website"]], [], ["booking page"])
        result = PersonalizationValidator(.75).validate(lead, research, draft, [], self.store)
        self.assertFalse(result.ok)
        self.assertTrue(result.retryable)
        self.assertIn("low_confidence", result.reason)

    def test_validator_company_name_is_not_required_when_anchor_is_grounded_and_used(self):
        lead = lead_row(1); self.store.upsert_lead(lead); research = research_row(self.store, lead)
        draft = PersonalizationDraft(True, "", [], "", "Subject", "The booking page could answer common visitor questions.", "", "", .95, [lead["website"]], [], ["booking page"])
        result = PersonalizationValidator(.75).validate(lead, research, draft, [], self.store)
        self.assertTrue(result.ok, result.reason)
        self.assertNotIn("company_not_personalized", result.reason)

    def test_validator_anchor_not_used_is_retryable(self):
        lead = lead_row(1); self.store.upsert_lead(lead); research = research_row(self.store, lead)
        draft = PersonalizationDraft(True, "", [], "", "Subject", "We help answer common website questions.", "", "", .95, [lead["website"]], [], ["booking page"])
        result = PersonalizationValidator(.75).validate(lead, research, draft, [], self.store)
        self.assertFalse(result.ok)
        self.assertTrue(result.retryable)
        self.assertIn("personalization_anchor_not_used", result.reason)

    def test_validator_accepts_equivalent_evidence_urls(self):
        lead = lead_row(1); self.store.upsert_lead(lead); research = research_row(self.store, lead)
        draft = PersonalizationDraft(True, "", [], "", "Subject", "The booking page could answer common visitor questions.", "", "", .95, ["HTTPS://COMPANY1.EXAMPLE"], [], ["booking page"])
        result = PersonalizationValidator(.75).validate(lead, research, draft, [], self.store)
        self.assertTrue(result.ok, result.reason)

    def test_validator_hard_failure_is_not_retryable(self):
        lead = lead_row(1); self.store.upsert_lead(lead); research = research_row(self.store, lead)
        draft = PersonalizationDraft(True, "", [], "", "", "The booking page could answer common visitor questions.", "", "", .70, [lead["website"]], [], ["booking page"])
        result = PersonalizationValidator(.75).validate(lead, research, draft, [], self.store)
        self.assertFalse(result.ok)
        self.assertFalse(result.retryable)
        self.assertIn("empty_subject", result.reason)
        self.assertIn("low_confidence", result.reason)

    def test_initial_validation_failure_is_repaired_once_and_queued(self):
        run = self.store.start_workflow("MANUAL", False)
        lead = lead_row(1); self.store.upsert_lead(lead); research_row(self.store, lead)

        class RepairingPersonalization:
            def __init__(self): self.repair_calls = 0
            def initial(self, lead, research, sender_signature):
                return PersonalizationDraft(True, "", [], "", "Subject", "The booking page could answer common visitor questions.", "", "", .50, [lead["website"]], [], ["booking page"])
            def repair_initial(self, lead, research, draft, reason, sender_signature):
                self.repair_calls += 1
                return PersonalizationDraft(True, "", [], "", "Subject", "The booking page could answer common visitor questions.", "", "", .95, [lead["website"]], [], ["booking page"])

        personalization = RepairingPersonalization()
        orch = Orchestrator(self.settings, self.store, object(), object(), personalization, object())
        result = orch.prepare_initial_messages(run, 1)
        self.assertEqual(result["prepared"], 1)
        self.assertEqual(result["personalization_retries"], 1)
        self.assertEqual(personalization.repair_calls, 1)
        self.assertEqual(self.store.count_event(run, "personalization_retry"), 1)

    def test_failed_repair_becomes_review_needed_after_bound(self):
        run = self.store.start_workflow("MANUAL", False)
        lead = lead_row(1); self.store.upsert_lead(lead); research_row(self.store, lead)

        class BrokenRepairPersonalization:
            def initial(self, lead, research, sender_signature):
                return PersonalizationDraft(True, "", [], "", "Subject", "The booking page could answer common visitor questions.", "", "", .50, [lead["website"]], [], ["booking page"])
            def repair_initial(self, lead, research, draft, reason, sender_signature):
                return PersonalizationDraft(True, "", [], "", "Subject", "The booking page could answer common visitor questions.", "", "", .50, [lead["website"]], [], ["booking page"])

        orch = Orchestrator(self.settings, self.store, object(), object(), BrokenRepairPersonalization(), object())
        result = orch.prepare_initial_messages(run, 1)
        self.assertEqual(result["prepared"], 0)
        self.assertEqual(result["personalization_retries"], 1)
        self.assertEqual(self.store.get_lead(lead["lead_id"])["status"], "REVIEW_NEEDED")
        self.assertEqual(self.store.count_event(run, "personalization_rejected"), 1)

    def test_reopen_personalization_reviews_reopens_only_latest_rejection(self):
        run = self.store.start_workflow("MANUAL", False)
        lead1 = lead_row(1); lead2 = lead_row(2)
        self.store.upsert_lead({**lead1, "status": "REVIEW_NEEDED"})
        self.store.upsert_lead({**lead2, "status": "REVIEW_NEEDED"})
        self.store.add_event("personalization_rejected", run_id=run, lead_id=lead1["lead_id"], status="FAILED_TERMINAL", reason="weak_personalization")
        self.store.add_event("personalization_rejected", run_id=run, lead_id=lead2["lead_id"], status="FAILED_TERMINAL", reason="weak_personalization")
        self.store.add_event("personalization_review_reopened", run_id=run, lead_id=lead2["lead_id"], status="REOPENED")
        reopened = self.store.reopen_personalization_reviews(50)
        self.assertEqual(reopened, [lead1["lead_id"]])
        self.assertEqual(self.store.get_lead(lead1["lead_id"])["status"], "RESEARCHED")
        self.assertEqual(self.store.get_lead(lead2["lead_id"])["status"], "REVIEW_NEEDED")



if __name__ == "__main__":
    unittest.main(verbosity=2)
