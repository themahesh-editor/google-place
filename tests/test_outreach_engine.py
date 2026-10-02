from __future__ import annotations
import email
import os
import tempfile
import unittest
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from email.message import EmailMessage
from unittest.mock import patch

from app.models import Lead, Evidence, WebsiteResearch, PersonalizationDraft, InboundEventType
from app.storage.repository import open_store, deterministic_lead_id, deterministic_outreach_id
from app.integrations.lead_engine import LeadEngineCSV
from app.personalization.prompts import OUTREACH_SYSTEM_PROMPT
from app.personalization.generator import PersonalizationGenerator
from app.personalization.validator import PersonalizationValidator
from app.followups.scheduler import FollowupScheduler
from app.email.message_parser import parse_message
from app.email.classifier import classify_inbound
from app.outreach.scheduler import SenderCapacity
from app.outreach.queue import OutreachQueue
from app.outreach.state import SendController
from app.email.monitor import MailboxMonitor
from app.email.imap_mailbox import IMAPMailboxProvider
from app.llm.client import LLMClient,LLMTemporaryError
from app.research.crawler import WebsiteCrawler
from app.research.research_service import ResearchService


@dataclass(frozen=True)
class S:
    sender_id:str; email:str='sender@example.com'; credential_env:str='SENDER_1'; imap_host:str='imap.example'; imap_port:int=993; imap_ssl:bool=True; smtp_host:str='smtp.example'; smtp_port:int=465; smtp_ssl:bool=True

class Settings:
    sender_count=10; daily_total_limit_per_sender=40; daily_new_outreach_limit_per_sender=10; daily_followup_limit_per_sender=10
    send_interval_minutes=10; sending_window_start=datetime.strptime('00:00','%H:%M').time(); sending_window_end=datetime.strptime('23:59','%H:%M').time()
    followup_1_delay_hours=24; followup_2_delay_days=7; followup_3_delay_days=14; require_fresh_mailbox_check_before_followup=True
    daily_new_outreach_target=100; max_retries=3; retry_base_seconds=1; send_enabled=True; dry_run=True; app_timezone='Asia/Kolkata'; mailbox_check_lookback_minutes=180; mailbox_max_messages_per_run=100
    def timezone(self):
        from zoneinfo import ZoneInfo; return ZoneInfo(self.app_timezone)
    def sender_configs(self): return [S(f'SENDER_{i}',f'sender{i}@example.com',f'SENDER_{i}') for i in range(1,11)]


def lead(company='Client A',email='contact@a.example',website='https://a.example/',status='Verified'):
    return Lead(deterministic_lead_id(email,website),email,company,website,'Dallas','TX','America/Chicago','src','PASS','place',website,'facts','LOCAL',0.95,status,'','')

def research(l):
    return WebsiteResearch('r1',l.lead_id,'2026-10-02T00:00:00Z',f'{l.company} summary',['service'],['customers'],['Dallas'],[],['booking'],['request'],['faq'],[Evidence(l.website,f'{l.company} provides service and has a booking page.')],'RESEARCHED','1.0')

def draft(l,body=None,confidence=.9,eligible=True,evidence=None):
    return PersonalizationDraft(eligible,'summary',['Observation'],'help visitors', 'About '+l.company, body or f'I noticed {l.company} provides a service. AttachAI could help answer common website questions before a booking.', 'Would a quick look be useful?','Best, AttachAI',confidence,evidence or [l.website],[])

class FakeSender:
    def __init__(self,config): self.config=config
    def send(self,**kwargs): return kwargs['message_id']
    def classify_error(self,exc): return 'TERMINAL'

class FakeMailbox:
    def __init__(self,items): self.items=items
    def connect(self): pass
    def check_new_messages(self,last_processed_uid,lookback_minutes,max_messages): return self.items
    def close(self): pass

class OutreachTests(unittest.TestCase):
    def setUp(self):
        self.td=tempfile.TemporaryDirectory(); self.store=open_store(os.path.join(self.td.name,'db.sqlite')); self.settings=Settings()
    def tearDown(self): self.store.close(); self.td.cleanup()

    def test_deterministic_ids(self):
        self.assertEqual(deterministic_lead_id('A@EXAMPLE.COM','https://www.example.com/x'),deterministic_lead_id('a@example.com','example.com'))
        a=deterministic_outreach_id('lead','INITIAL',1); b=deterministic_outreach_id('lead','INITIAL',1); self.assertEqual(a,b)
        self.assertNotEqual(a,deterministic_outreach_id('lead','FOLLOWUP_1',1))

    def test_crm_ingestion_only_verified(self):
        with tempfile.NamedTemporaryFile('w+',suffix='.csv',delete=False) as f:
            f.write('Email,Company,Website,City,State,Timezone,LeadSource,Verified,PlaceId,EmailSourceURL,WebsiteFacts,ScaleClass,QualificationConfidence,Status,FirstSeenDate,Notes\n')
            f.write('a@example.com,A,https://a.example,City,TX,America/Chicago,src,PASS,p,url,facts,LOCAL,0.9,Verified,date,note\n')
            f.write('b@example.com,B,https://b.example,City,TX,America/Chicago,src,FAIL,p,url,facts,LOCAL,0.9,Rejected,date,note\n')
            path=f.name
        try:
            got=LeadEngineCSV(path).read_verified(100); self.assertEqual(len(got),1); self.assertEqual(got[0].company,'A')
        finally: os.unlink(path)

    def test_client_isolation_prompt(self):
        a=lead('Client A','a@a.example','https://a.example/')
        b=lead('Client B','b@b.example','https://b.example/')
        g=PersonalizationGenerator(type('LLM',(),{})())
        pa=g._prompt(a,research(a),[],'INITIAL','sender@example.com')
        pb=g._prompt(b,research(b),[],'INITIAL','sender@example.com')
        self.assertIn('Client A',pa); self.assertNotIn('Client B',pa); self.assertIn('Client B',pb); self.assertNotIn('Client A',pb)

    def test_validator_rejects_wrong_evidence(self):
        l=lead(); r=research(l); d=draft(l,evidence=['https://other.example/'])
        v=PersonalizationValidator().validate(l,r,d)
        self.assertFalse(v.ok); self.assertIn('evidence_url_not_in_current_research',v.reason)

    def test_validator_rejects_hallucination_phrase(self):
        l=lead(); r=research(l); d=draft(l,body=f'{l.company} is losing leads and your competitors are using AI.')
        v=PersonalizationValidator().validate(l,r,d)
        self.assertFalse(v.ok); self.assertIn('unsupported_claim',v.reason)

    def test_validator_rejects_duplicate_body(self):
        l=lead(); r=research(l); d=draft(l)
        v=PersonalizationValidator().validate(l,r,d,previous_bodies=[d.body])
        self.assertFalse(v.ok)

    def test_queue_idempotency(self):
        l=lead(); self.store.upsert_lead(l); s=S('SENDER_1'); q=OutreachQueue(self.store)
        when=datetime(2026,10,2,12,tzinfo=timezone.utc)
        oid1=q.create(l,draft(l),s,when); oid2=q.create(l,draft(l),s,when)
        self.assertEqual(oid1,oid2); self.assertIsNotNone(self.store.get_sequence(l.lead_id,'INITIAL',1))

    def test_suppression_blocks_queue(self):
        l=lead(); self.store.upsert_lead(l); self.store.suppress(l.email,l.lead_id,'unsubscribe')
        self.assertIsNone(OutreachQueue(self.store).create(l,draft(l),S('SENDER_1'),datetime.now(timezone.utc)))

    def test_followup_timing_exact_anchor(self):
        settings=self.settings; s=FollowupScheduler(settings); base='2026-10-02T12:10:00Z'
        self.assertEqual(s.followup_due(base,1).isoformat(),'2026-10-03T12:10:00+00:00')
        self.assertEqual(s.followup_due(base,2).isoformat(),'2026-10-09T12:10:00+00:00')
        self.assertEqual(s.followup_due(base,3).isoformat(),'2026-10-16T12:10:00+00:00')

    def test_sender_capacity_limits_and_spacing(self):
        l=lead(); self.store.upsert_lead(l); now=datetime(2026,10,2,12,tzinfo=timezone.utc)
        self.store.sender_daily_state('SENDER_1','2026-10-02'); self.store.db.execute("UPDATE sender_daily_state SET total=1,last_successful_send_utc=? WHERE sender_id=? AND date_key=?",['2026-10-02T12:00:00Z','SENDER_1','2026-10-02'])
        ok,reason=SenderCapacity(self.store,self.settings).can_send('SENDER_1',False,now); self.assertFalse(ok); self.assertEqual(reason,'send_spacing')

    def test_dry_run_never_calls_sender(self):
        l=lead(); self.store.upsert_lead(l); q=OutreachQueue(self.store); oid=q.create(l,draft(l),S('SENDER_1'),datetime.now(timezone.utc))
        calls=[]
        class P(FakeSender):
            def send(self,**kwargs): calls.append(1); return kwargs['message_id']
        ctl=SendController(self.store,self.settings,P); result=ctl.send_one(oid,dry_run=True)
        self.assertEqual(result,'dry_run'); self.assertEqual(calls,[]); self.assertEqual(self.store.get_outreach(oid)['status'],'SCHEDULED')

    def test_real_send_stores_exact_timestamp_and_message_id(self):
        l=lead(); self.store.upsert_lead(l); oid=OutreachQueue(self.store).create(l,draft(l),S('SENDER_1'),datetime.now(timezone.utc))
        sent=SendController(self.store,self.settings,FakeSender)
        result=sent.send_one(oid,dry_run=False,latest_mailbox_check_ok=True)
        self.assertEqual(result,'sent'); row=self.store.get_outreach(oid); self.assertEqual(row['status'],'SENT'); self.assertTrue(row['sent_at_utc']); self.assertTrue(row['message_id'].startswith('<attachai-'))

    def test_inflight_is_moved_to_review_without_resend(self):
        l=lead(); self.store.upsert_lead(l); oid=OutreachQueue(self.store).create(l,draft(l),S('SENDER_1'),datetime.now(timezone.utc)); self.store.claim_outreach(oid)
        ctl=SendController(self.store,self.settings,FakeSender); ctl.reconcile_inflight(); self.assertEqual(self.store.get_outreach(oid)['status'],'REVIEW_NEEDED')

    def _raw(self,from_email='owner@a.example',subject='Re: About Client A',body='Thanks for reaching out.'):
        m=EmailMessage(); m['From']=from_email; m['To']='sender1@example.com'; m['Subject']=subject; m['Date']='Fri, 02 Oct 2026 12:30:00 +0000'; m['Message-ID']='<reply-1@example.com>'; m['In-Reply-To']='<attachai-anchor@example.com>'; m.set_content(body); return m.as_bytes()

    def test_reply_correlation_cancels_followups(self):
        l=lead(); self.store.upsert_lead(l); s=S('SENDER_1')
        initial=OutreachQueue(self.store).create(l,draft(l),s,datetime.now(timezone.utc)); self.store.claim_outreach(initial); self.store.mark_sent(initial,'2026-10-01T12:00:00Z','<attachai-anchor@example.com>')
        follow=OutreachQueue(self.store).create(l,draft(l,body=f'Following up with {l.company}.'),s,datetime(2026,10,2,12,tzinfo=timezone.utc),__import__('app.models').models.SequenceType.FOLLOWUP_1,1)
        monitor=MailboxMonitor(self.store,self.settings,lambda sender,cred: FakeMailbox([type('I',(),{'uid':1,'raw':self._raw()})()]))
        count=monitor.run_sender(s); self.assertEqual(count,1); self.assertEqual(self.store.get_lead(l.lead_id).status,'REPLIED'); self.assertEqual(self.store.get_outreach(follow)['status'],'CANCELLED')
        self.assertEqual(monitor.run_sender(s),1)
        self.assertEqual(len(self.store.db.fetchall('SELECT * FROM inbound_message')),1)

    def test_unsubscribe_persistent_suppression(self):
        l=lead(); self.store.upsert_lead(l); s=S('SENDER_1')
        initial=OutreachQueue(self.store).create(l,draft(l),s,datetime.now(timezone.utc)); self.store.claim_outreach(initial); self.store.mark_sent(initial,'2026-10-01T12:00:00Z','<attachai-anchor@example.com>')
        raw=self._raw(from_email=l.email,body='Please unsubscribe me.'); monitor=MailboxMonitor(self.store,self.settings,lambda sender,cred: FakeMailbox([type('I',(),{'uid':1,'raw':raw})()]))
        monitor.run_sender(s); self.assertTrue(self.store.is_suppressed(l.email)); self.assertEqual(self.store.get_lead(l.lead_id).status,'UNSUBSCRIBED')

    def test_bounce_classification_requires_dsn_context(self):
        m=parse_message(self._raw(from_email='owner@a.example',body='I need to reschedule.')); self.assertEqual(classify_inbound(m)[0],InboundEventType.REPLY)
        b=parse_message(self._raw(from_email='mailer-daemon@example.com',subject='Mail delivery failure',body='550 user unknown')); self.assertEqual(classify_inbound(b)[0],InboundEventType.HARD_BOUNCE)

    def test_ambiguous_bounce_not_destructive(self):
        l=lead(); self.store.upsert_lead(l); s=S('SENDER_1')
        raw=self._raw(from_email='mailer-daemon@example.com',subject='Delivery report',body='Delivery report without a definitive status')
        monitor=MailboxMonitor(self.store,self.settings,lambda sender,cred: FakeMailbox([type('I',(),{'uid':1,'raw':raw})()]))
        monitor.run_sender(s); self.assertEqual(self.store.get_lead(l.lead_id).status,'Verified')

    def test_pre_followup_state_gate(self):
        l=lead(); self.store.upsert_lead(l); s=S('SENDER_1'); q=OutreachQueue(self.store); oid=q.create(l,draft(l),s,datetime.now(timezone.utc),__import__('app.models').models.SequenceType.FOLLOWUP_1,1)
        ctl=SendController(self.store,self.settings,FakeSender); self.assertEqual(ctl.send_one(oid,dry_run=False,latest_mailbox_check_ok=False),'blocked')


    def test_crm_reimport_does_not_reset_terminal_outreach_state(self):
        l=lead(); self.store.upsert_lead(l); self.store.set_lead_status(l.lead_id,'REPLIED')
        self.store.upsert_lead(l); self.assertEqual(self.store.get_lead(l.lead_id).status,'REPLIED')

    def test_crm_missing_headers_fails_closed(self):
        with tempfile.NamedTemporaryFile('w+',delete=False) as f: f.write('Email,Company\na@example.com,A\n'); path=f.name
        try:
            with self.assertRaises(ValueError): LeadEngineCSV(path).read_verified()
        finally: os.unlink(path)


    def test_hard_bounce_suppresses_recipient_not_mailer_daemon(self):
        l=lead(); self.store.upsert_lead(l); s=S('SENDER_1')
        initial=OutreachQueue(self.store).create(l,draft(l),s,datetime.now(timezone.utc)); self.store.claim_outreach(initial); self.store.mark_sent(initial,'2026-10-01T12:00:00Z','<attachai-anchor@example.com>')
        raw=self._raw(from_email='mailer-daemon@example.com',subject='Mail delivery failure',body='550 user unknown')
        monitor=MailboxMonitor(self.store,self.settings,lambda sender,cred: FakeMailbox([type('I',(),{'uid':1,'raw':raw})()]))
        monitor.run_sender(s); self.assertTrue(self.store.is_suppressed(l.email)); self.assertFalse(self.store.is_suppressed('mailer-daemon@example.com')); self.assertEqual(self.store.get_lead(l.lead_id).status,'BOUNCED')

    def test_sender_assignment_persists(self):
        from app.outreach.scheduler import SenderScheduler
        l=lead(); self.store.upsert_lead(l); sched=SenderScheduler(self.store,self.settings); a=sched.assign_sender(l.lead_id); b=sched.assign_sender(l.lead_id); self.assertEqual(a.sender_id,b.sender_id)

    def test_retry_state_transitions(self):
        l=lead(); self.store.upsert_lead(l); oid=OutreachQueue(self.store).create(l,draft(l),S('SENDER_1'),datetime.now(timezone.utc))
        self.store.claim_outreach(oid); self.store.mark_failure(oid,True,'temporary','2099-01-01T00:00:00Z'); self.assertEqual(self.store.get_outreach(oid)['status'],'FAILED_RETRYABLE'); self.assertTrue(self.store.get_outreach(oid)['next_retry_at_utc'])


    def test_sender_wide_schedule_spacing_uses_persisted_plan(self):
        from app.outreach.scheduler import SenderScheduler
        l1=lead('A','a@a.example','https://a.example/'); l2=lead('B','b@b.example','https://b.example/')
        self.store.upsert_lead(l1); self.store.upsert_lead(l2); sched=SenderScheduler(self.store,self.settings); a=sched.assign_sender(l1.lead_id); when=sched.next_send_time(a.sender_id,l1.timezone,datetime(2026,10,2,18,0,tzinfo=timezone.utc))
        oid=OutreachQueue(self.store).create(l1,draft(l1),a,when); self.assertIsNotNone(oid); b=sched.assign_sender(l2.lead_id); self.assertEqual(a.sender_id,b.sender_id)
        second=sched.next_send_time(b.sender_id,l2.timezone,datetime(2026,10,2,18,0,tzinfo=timezone.utc)); self.assertGreaterEqual(second,when+timedelta(minutes=self.settings.send_interval_minutes))

    def test_uidvalidity_change_resets_incremental_cursor(self):
        class MB(FakeMailbox):
            uidvalidity='222'
        s=S('SENDER_1'); self.store.save_mailbox_state(sender_id=s.sender_id,mailbox_identifier='INBOX',provider_type='imap',uidvalidity='111',last_processed_uid=99,last_checked_at_utc='2026-10-02T00:00:00Z')
        raw=self._raw(from_email='owner@a.example',body='Hello')
        monitor=MailboxMonitor(self.store,self.settings,lambda sender,cred: MB([type('I',(),{'uid':1,'raw':raw})()]))
        monitor.run_sender(s); self.assertEqual(self.store.mailbox_state(s.sender_id)['uidvalidity'],'222')

    def test_send_validation_fails_without_ten_sender_credentials(self):
        from app.config import Settings
        env={'OUTREACH_DATABASE_URL':'postgresql://x','SEND_ENABLED':'true','DRY_RUN':'false','SENDER_COUNT':'10'}
        
        for i in range(1,11):
            env[f'SENDER_{i}_EMAIL'] = f's{i}@example.com'
            env[f'SENDER_{i}'] = ''
        
        with patch.dict(os.environ,env,clear=False):
            with self.assertRaises(ValueError):
                Settings.from_env().validate_for_send()

    def test_parser_preserves_message_metadata_without_body_persistence(self):
        raw=self._raw(body='private reply body'); p=parse_message(raw); self.assertEqual(p.from_email,'owner@a.example'); self.assertEqual(p.received_at_utc,'2026-10-02T12:30:00Z'); self.assertIn('private reply body',p.text_excerpt)

if __name__=='__main__': unittest.main(verbosity=2)
