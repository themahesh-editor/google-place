"""PostgreSQL integration tests: no real network, SMTP or mailbox calls."""
import copy
import os
import threading
import time
from collections import Counter
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import psycopg
import pytest

from attachai.config import Config, DEFAULTS, Secrets
from attachai.db import Store, j
from attachai.engine import Engine
from attachai.providers import (CTA, OPPORTUNITY, SUBJECT, ProviderError, Sender,
                               _render, normalize_url, stable_id, validate_draft)


@pytest.fixture
def db():
    url = os.environ.get('TEST_DATABASE_URL')
    if not url:
        pytest.skip('TEST_DATABASE_URL is required for real PostgreSQL integration tests')
    store = Store(url)
    store.acquire()
    store.migrate()
    store.reset()
    yield store
    store.reset()
    store.close()


def configuration(target=10, real=True, followups=True):
    data = copy.deepcopy(DEFAULTS)
    data['retry'].update(base_seconds=0,max_seconds=0,sender_cooldown_seconds=0)
    data['followups']['delays_seconds'] = [0,0,0]
    data['mailbox']['enabled'] = False
    data['llm']['postal_address'] = '123 Test Road, Austin TX 78701'
    data['safety'].update(send_enabled=real,dry_run=not real)
    return Config(data,real,not real,followups,True,target)


def senders():
    return [Sender(f's{i}',f's{i}@sender.example','not-a-real-password','smtp.example',465,'imap.example',993,'ssl') for i in range(10)]


def research_payload(url):
    snippet = 'We offer professional dental services for families in our community.'
    url = normalize_url(url)
    return {'pages':[{'url':url,'text':snippet}],
            'evidence':[{'id':stable_id(url,snippet),'url':url,'snippet':snippet}],
            'emails':['contact@'+url.split('/')[2]]}


def valid_draft(research):
    ref = research['evidence'][0]
    draft = {'subject':SUBJECT,'cta':CTA,'opportunity':OPPORTUNITY,
             'observations':[{'claim':ref['snippet'],'evidence_ids':[ref['id']]}],
             'evidence_refs':[copy.deepcopy(ref)],'offer':'Our assistant helps with customer inquiries.',
             'signature':'AttachAI team','postal_address':'123 Test Road, Austin TX 78701'}
    draft['body'] = _render(draft)
    assert validate_draft(draft,research)==[]
    return draft


class FakeDiscovery:
    def __init__(self, total=2000, bad=0):
        self.total,self.bad,self.calls = total,bad,0

    def search(self,query,page_token=None):
        self.calls += 1
        offset = int(page_token or 0)
        stop = min(self.total,offset+20)
        return {'candidates':[{'place_id':f'p{i}','name':f'Business {i}',
                    'website':f'https://lead{i}.example.com/','rating':5,'reviews':20}
                    for i in range(offset,stop)],
                'next_page_token':str(stop) if stop<self.total else None}


class FakeResearch:
    def __init__(self,bad=0,temporary=0):
        self.bad,self.temporary = bad,temporary
        self.calls = Counter()
        self.lock = threading.Lock()

    def crawl(self,url):
        index = int(url.split('lead')[1].split('.')[0])
        with self.lock:
            self.calls[url] += 1
            attempt = self.calls[url]
        if index<self.bad:
            raise ProviderError('terminal','No usable website evidence')
        if index<self.temporary and attempt==1:
            raise ProviderError('temporary','Provider HTTP 503')
        return research_payload(url)


class FakeLLM:
    def __init__(self,invalid=0,temporary=0):
        self.invalid,self.temporary = invalid,temporary
        self.calls = Counter()
        self.lock = threading.Lock()

    def draft(self,lead,research,sequence,history):
        index = int(lead['website'].split('lead')[1].split('.')[0])
        key = (lead['id'],sequence)
        with self.lock:
            self.calls[key] += 1
            attempt = self.calls[key]
        if index<self.temporary and attempt==1:
            raise ProviderError('temporary','Provider timeout')
        if index<self.invalid:
            raise ProviderError('invalid','LLM returned invalid JSON')
        return valid_draft(research)


class FakeSMTP:
    def __init__(self, failures=None, latency=0):
        self.failures = failures or {}
        self.calls = []
        self.lock = threading.Lock()
        self.active,self.peak,self.latency = 0,0,latency

    def send(self,message,sender):
        with self.lock:
            self.active += 1
            self.peak = max(self.peak,self.active)
            self.calls.append((copy.deepcopy(message),sender.id))
        if self.latency:
            time.sleep(self.latency)
        with self.lock:
            self.active -= 1
        kind = self.failures.get(sender.id)
        if callable(kind):
            kind = kind(message)
        if kind:
            return {'status':'review' if kind=='ambiguous' else 'failed','kind':kind,'error':'Simulated SMTP failure'}
        return {'status':'sent','kind':None,'error':None}


class FakeMailbox:
    def __init__(self):
        self.events = {}
        self.fail = False

    def sync(self,sender,cursor):
        if self.fail:
            raise ProviderError('temporary','Mailbox timeout')
        events = self.events.get(sender.id,[])
        return {'uidvalidity':'v1','last_uid':max([e['uid'] for e in events] or [0]),'events':events}


def engine(db,target=10,real=True,followups=True,discovery=None,research=None,llm=None,smtp=None,mailbox=None):
    config = configuration(target,real,followups)
    secrets = Secrets('not-used','not-used','not-used',senders())
    return Engine(config,db,secrets,discovery or FakeDiscovery(),research or FakeResearch(),llm or FakeLLM(),smtp or FakeSMTP(),mailbox or FakeMailbox())


def test_three_runs_each_add_100_and_strict_chain(db):
    smtp = FakeSMTP()
    campaigns = []
    for run in range(3):
        e = engine(db,100,smtp=smtp)
        code,result = e.run()
        assert code==0
        assert result['successful_initial_sends']==100
        assert result['remaining_target']==0
        campaigns.append(result['campaign_id'])
        assert db.one("SELECT count(*) AS n FROM message WHERE sequence=0 AND status='sent'")['n']==100*(run+1)
    assert len(set(campaigns))==3
    assert db.one("SELECT count(*) AS n FROM message WHERE sequence=1 AND status='sent'")['n']==200
    assert db.one("SELECT count(*) AS n FROM message WHERE sequence=2 AND status='sent'")['n']==100
    assert db.one("SELECT count(*) AS n FROM message WHERE sequence=3 AND status='sent'")['n']==0
    for lead in db.all('SELECT id FROM lead'):
        rows = db.all("SELECT * FROM message WHERE lead_id=%s AND status='sent' ORDER BY sequence",[lead['id']])
        assert len({r['sender_id'] for r in rows})==1
        for previous,current in zip(rows,rows[1:]):
            assert current['in_reply_to']==previous['message_id']
            assert current['refs'][-1]==previous['message_id']
            assert current['sequence']==previous['sequence']+1
    assert len({m['id'] for m,s in smtp.calls})==len(smtp.calls)


def test_crash_after_ten_resumes_exact_progress_and_no_resend(db):
    e = engine(db,100,followups=False)
    original = db.accept
    counter = 0
    def interrupted(mid, delays, *args, **kwargs):
        nonlocal counter
        accepted = original(mid, delays, *args, **kwargs)
        counter += 1
        if counter == 10:
            raise KeyboardInterrupt('simulated runner termination')
        return accepted
    db.accept = interrupted
    with pytest.raises(KeyboardInterrupt):
        e.run()
    db.accept = original
    cid = e.cid
    assert db.count_sent(cid)==10
    sent_ids = {r['id'] for r in db.all("SELECT id FROM message WHERE status='sent'")}
    smtp = FakeSMTP()
    resumed = engine(db,100,followups=False,smtp=smtp)
    code,result = resumed.run()
    assert code==0 and result['campaign_id']==cid
    assert len(smtp.calls)==90
    assert all(m['id'] not in sent_ids for m,s in smtp.calls)
    assert result['successful_initial_sends']==100


def test_smtp_acceptance_without_durable_commit_requires_review_and_never_resends(db):
    e = engine(db,1,followups=False)
    def lose_commit(mid, delays, **kwargs):
        return False
    original = db.accept
    db.accept = lose_commit
    with pytest.raises(RuntimeError, match='manual review is required'):
        e.run()
    db.accept = original
    row = db.one("SELECT * FROM message WHERE sequence=0")
    
    # An uncertain SMTP acceptance must be quarantined immediately.
    assert row['status'] == 'review'
    assert row['error_kind'] == 'ambiguous'
    
    attempt = db.one(
        """
        SELECT status
        FROM attempt
        WHERE message_id=%s
        ORDER BY number DESC
        LIMIT 1
        """,
        [row['id']],
    )
    assert attempt['status'] == 'review'
    
    smtp = FakeSMTP()
    resumed = engine(db,1,followups=False,smtp=smtp)
    code,result = resumed.run()
    assert db.one('SELECT status FROM message WHERE id=%s',[row['id']])['status'] == 'review'
    assert all(message['id'] != row['id'] for message,sender in smtp.calls)
    assert result['successful_initial_sends'] == 0
    assert code == 2


def test_target_is_immutable_during_recovery(db):
    e = engine(db,10,discovery=FakeDiscovery(total=0))
    assert e.run()[0]==2
    with pytest.raises(RuntimeError,match='immutable'):
        engine(db,20).run()


def test_database_uniqueness_and_lead_identity(db):
    e = engine(db,1)
    assert e.run()[0]==0
    lead = db.one('SELECT * FROM lead LIMIT 1')
    with pytest.raises(psycopg.errors.UniqueViolation):
        db.execute('INSERT INTO lead(id,candidate_id,email,name,website,qualification) VALUES(%s,%s,%s,%s,%s,%s)', ['different',lead['candidate_id'],lead['email'],'Other',lead['website'],j({})])
    message = db.one("SELECT * FROM message WHERE sequence=0 AND status='sent' LIMIT 1")
    with pytest.raises(psycopg.errors.UniqueViolation):
        db.execute('INSERT INTO message(id,lead_id,campaign_id,sequence) VALUES(%s,%s,%s,0)',['another',message['lead_id'],message['campaign_id']])
    with pytest.raises(psycopg.errors.RaiseException):
        db.execute("UPDATE message SET status='queued' WHERE id=%s",[message['id']])


@pytest.mark.parametrize('sequence',[1,2,3])
def test_database_guard_prevents_sequence_skips(db,sequence):
    e = engine(db,1,real=False)
    e.run()
    previous = db.one('SELECT * FROM message WHERE sequence=0 LIMIT 1')
    with pytest.raises(psycopg.errors.RaiseException):
        db.execute('INSERT INTO message(id,lead_id,campaign_id,sequence,predecessor_id,sender_id) VALUES(%s,%s,%s,%s,%s,%s)', [f'invalid{sequence}',previous['lead_id'],previous['campaign_id'],sequence,previous['id'],'s0'])


def test_followup_due_rules_and_failed_f1_does_not_unlock_f2(db):
    e = engine(db,1)
    e.c.data['followups']['delays_seconds'] = [86400,604800,1209600]
    e.run()
    e2 = engine(db,1,smtp=FakeSMTP(failures={s.id:'temporary' for s in senders()}))
    e2.c = replace(e2.c,process_new_outreach=False)
    assert e2.run()[1].get('followups_sent',0)==0
    f1 = db.one('SELECT * FROM message WHERE sequence=1')
    initial = db.one("SELECT * FROM message WHERE sequence=0 AND status='sent'")
    assert f1['due_at']-initial['sent_at']==timedelta(days=1)
    db.execute("UPDATE message SET due_at=now()-interval '1 second' WHERE sequence=1")
    assert e2.run()[0]==2
    assert not db.one('SELECT 1 FROM message WHERE sequence=2')


@pytest.mark.parametrize('kind',['reply','hard_bounce','unsubscribe'])
def test_inbound_suppresses_and_is_incrementally_deduplicated(db,kind):
    engine(db,1).run()
    sent = db.one("SELECT m.*,l.email FROM message m JOIN lead l ON l.id=m.lead_id WHERE sequence=0 AND m.status='sent'")
    mailbox = FakeMailbox()
    mailbox.events[sent['sender_id']] = [{'key':'x','uid':1,'kind':kind,'email':sent['email'],'message_ids':[sent['message_id']],'occurred_at':datetime.now(timezone.utc).isoformat()}]
    e = engine(db,1,mailbox=mailbox)
    e.c.data['mailbox']['enabled'] = True
    e.c = replace(e.c,process_new_outreach=False)
    e.run()
    assert db.one('SELECT kind FROM suppression WHERE email=%s',[sent['email']])['kind']==kind
    assert db.one('SELECT status FROM message WHERE sequence=1')['status']=='cancelled'
    assert db.one('SELECT count(*) AS n FROM inbound')['n']==1
    assert db.one('SELECT last_uid FROM mailbox_cursor WHERE sender_id=%s',[sent['sender_id']])['last_uid']==1
    e2 = engine(db,1,mailbox=mailbox)
    e2.c.data['mailbox']['enabled'] = True
    e2.c = replace(e2.c,process_new_outreach=False)
    e2.run()
    assert db.one('SELECT count(*) AS n FROM inbound')['n']==1
    assert db.one("SELECT count(*) AS n FROM message WHERE sequence>0 AND status='sent'")['n']==0


def test_replenishment_after_research_llm_and_sender_failures(db):
    research = FakeResearch(bad=30,temporary=50)
    llm = FakeLLM(invalid=45,temporary=60)
    smtp = FakeSMTP(failures={'s0':'auth','s1':lambda m:'temporary' if m['attempt']==1 else None})
    e = engine(db,100,research=research,llm=llm,smtp=smtp)
    code,result = e.run()
    assert code==0 and result['successful_initial_sends']==100
    assert result['raw_candidates']>100
    assert result['research_failed']>=30
    assert result['retryable_failures']>0
    assert db.one("SELECT health FROM sender WHERE id='s0'")['health']=='STOPPED'


def test_terminal_recipient_is_suppressed_and_replaced(db):
    smtp = FakeSMTP(failures={s.id:lambda m:'recipient' if m['email'].startswith('contact@lead0.') else None for s in senders()})
    # Consume the entire first discovery page so the rejected contact is always
    # exercised regardless of concurrent preparation completion order.
    code,result = engine(db,20,smtp=smtp).run()
    assert code==0 and result['successful_initial_sends']==20
    assert db.one("SELECT kind FROM suppression WHERE email='contact@lead0.example.com'")['kind']=='hard_bounce'
    assert db.one("SELECT m.status FROM message m JOIN lead l ON l.id=m.lead_id WHERE email='contact@lead0.example.com' AND sequence=0")['status']=='terminal'


def test_ambiguous_sending_recovery_never_auto_resends(db):
    e = engine(db,10,real=False)
    e.run()
    message = db.one('SELECT * FROM message WHERE sequence=0 LIMIT 1')
    db.execute("UPDATE message SET status='sending',sender_id='s0',message_id=%s,attempts=1 WHERE id=%s",[f"<test-{message['id']}@sender.example>",message['id']])
    db.execute("INSERT INTO attempt(message_id,number,sender_id,status) VALUES(%s,1,'s0','sending')",[message['id']])
    smtp = FakeSMTP()
    resumed = engine(db,10,smtp=smtp)
    resumed.run()
    assert db.one('SELECT status FROM message WHERE id=%s',[message['id']])['status']=='review'
    assert all(m['id']!=message['id'] for m,s in smtp.calls)
    db.review(message['id'],'not-sent',[0,0,0])
    assert db.one('SELECT status FROM message WHERE id=%s',[message['id']])['status']=='retry'


def test_manual_acceptance_uses_verified_timestamp(db):
    e = engine(db,1,real=False)
    e.run()
    message = db.one('SELECT * FROM message WHERE sequence=0 LIMIT 1')
    db.execute("UPDATE message SET status='review',sender_id='s0',message_id='<verified@sender.example>' WHERE id=%s",[message['id']])
    at = datetime.now(timezone.utc)-timedelta(hours=2)
    db.review(message['id'],'sent',[86400,604800,1209600],at,'provider-log-123')
    assert db.one('SELECT sent_at FROM message WHERE id=%s',[message['id']])['sent_at']==at
    assert db.one('SELECT due_at FROM message WHERE sequence=1')['due_at']==at+timedelta(days=1)


def test_stuck_candidate_and_lead_are_recovered(db):
    e = engine(db,1,real=False)
    e.run()
    db.execute("UPDATE candidate SET status='working',lease_until=now()+interval '1 hour'")
    db.execute("UPDATE lead SET status='working',lease_until=now()+interval '1 hour'")
    db.reconcile()
    assert not db.one("SELECT 1 FROM candidate WHERE status='working'")
    assert not db.one("SELECT 1 FROM lead WHERE status='working'")


def test_no_empty_cycles_on_exhausted_or_bad_inventory(db):
    discovery = FakeDiscovery(total=30)
    e = engine(db,100,discovery=discovery,research=FakeResearch(bad=100))
    started = time.monotonic()
    code,result = e.run()
    assert code==2 and result['remaining_target']==100
    assert discovery.calls==2
    assert time.monotonic()-started<15
    assert result['reason']


def test_one_initial_per_sender_in_batch_and_ten_concurrent(db):
    smtp = FakeSMTP(latency=.05)
    engine(db,20,smtp=smtp,followups=False).run()
    assert smtp.peak==10
    for batch in db.all('SELECT * FROM batch'):
        counts = db.one('SELECT count(*) AS total,count(DISTINCT a.sender_id) AS unique_senders FROM attempt a JOIN message m ON m.id=a.message_id WHERE m.batch_id=%s',[batch['id']])
        assert counts['total']==counts['unique_senders']<=10
        assert batch['successful']==batch['attempted']==10


def test_dry_run_counts_no_sends_and_inventory_reused(db):
    smtp = FakeSMTP()
    first = engine(db,10,real=False,smtp=smtp)
    code,result = first.run()
    assert code==0 and not smtp.calls
    assert result['successful_initial_sends']==0 and result['run_status']=='DRY_RUN'
    assert db.one("SELECT count(*) AS n FROM message WHERE status='queued'")['n']>=10
    second = engine(db,10,smtp=smtp)
    second.run()
    assert len(smtp.calls)==10
    assert db.count_sent(second.cid)==10


def test_reset_is_isolated_and_credentials_not_stored(db):
    db.execute('CREATE TABLE IF NOT EXISTS public.attachai_unrelated_test(value text)')
    db.execute("INSERT INTO public.attachai_unrelated_test VALUES('retain')")
    engine(db,1).run()
    db.reset()
    assert db.one('SELECT count(*) AS n FROM campaign')['n']==0
    assert db.one('SELECT count(*) AS n FROM lead')['n']==0
    assert db.one('SELECT count(*) AS n FROM sender')['n']==0
    assert db.one('SELECT value FROM public.attachai_unrelated_test')['value']=='retain'
    assert db.one('SELECT version FROM schema_version')['version']==1
    db.execute('DROP TABLE public.attachai_unrelated_test')


def test_global_lock_prevents_second_coordinator(db):
    other = Store(os.environ['TEST_DATABASE_URL'])
    try:
        with pytest.raises(RuntimeError,match='Another'):
            other.acquire()
    finally:
        other.close()


def test_sql_like_percent_is_parameterized(db):
    assert db.one('SELECT %s LIKE %s AS matches',['FOLLOWUP_1','FOLLOWUP_%'])['matches']


def test_mailbox_failure_is_durable_and_pipeline_can_use_other_senders(db):
    mailbox = FakeMailbox()
    mailbox.fail = True
    e = engine(db,10,mailbox=mailbox)
    e.c.data['mailbox']['enabled'] = True
    code,result = e.run()
    assert code==2  # All senders degraded, so no unsafe new assignment.
    assert result['mailbox_failures']==10
    assert db.one("SELECT count(*) AS n FROM message WHERE status='queued'")['n']>0
    assert db.one("SELECT count(*) AS n FROM sender WHERE health='DEGRADED'")['n']==10
    mailbox.fail = False
    resumed = engine(db,10,mailbox=mailbox)
    resumed.c.data['mailbox']['enabled'] = True
    assert resumed.run()[0]==0


def test_stopped_sender_cannot_break_followup_identity(db):
    engine(db,1).run()
    initial = db.one("SELECT * FROM message WHERE sequence=0 AND status='sent'")
    db.execute("UPDATE sender SET health='STOPPED' WHERE id=%s",[initial['sender_id']])
    smtp = FakeSMTP()
    e = engine(db,1,smtp=smtp)
    e.c = replace(e.c,process_new_outreach=False)
    assert e.run()[0]==2
    assert not smtp.calls
    assert db.one('SELECT sender_id FROM message WHERE sequence=1')['sender_id']==initial['sender_id']


def test_daily_limit_and_window_are_optional_but_enforced(db):
    e = engine(db,10)
    e.c.data['limits'].update(daily_total_enabled=True,daily_total=5)
    code,result = e.run()
    assert code==2 and result['successful_initial_sends']==5
    e2 = engine(db,10)
    assert e2.run()[0]==0


def test_same_website_different_contacts_not_domain_deduped(db):
    e = engine(db,2,real=False)
    class SharedDiscovery:
        def search(self,*args):
            return {'candidates':[{'place_id':str(i),'name':str(i),'website':'https://lead1.example.com/','rating':5,'reviews':20} for i in range(2)],'next_page_token':None}
    class SharedResearch(FakeResearch):
        def crawl(self,url):
            payload = super().crawl(url)
            payload['emails'] = ['first@lead1.example.com','second@lead1.example.com']
            return payload
    research = SharedResearch()
    e.discovery,e.research = SharedDiscovery(),research
    assert e.run()[0]==0
    assert db.one('SELECT count(*) AS n FROM lead')['n']==2
    assert sum(research.calls.values())==1


def test_provider_budget_failure_leaves_durable_campaign_for_resume(db):
    class Broken:
        def search(self,*args):
            raise ProviderError('temporary','Provider HTTP 503')
    e = engine(db,10,discovery=Broken())
    assert e.run()[0]==2
    assert db.one('SELECT status FROM campaign')['status']=='blocked'
    assert engine(db,10).run()[0]==0


def test_crash_after_27_reserves_unknown_outcomes_and_cannot_oversend(db):
    e = engine(db,100,followups=False)
    original = db.accept
    accepted = 0

    def crash(mid, delays, **kwargs):
        nonlocal accepted
        result = original(mid, delays, **kwargs)
        accepted += 1
        if accepted == 27:
            raise KeyboardInterrupt()
        return result

    db.accept = crash
    with pytest.raises(KeyboardInterrupt):
        e.run()
    db.accept = original
    assert db.count_sent(e.cid)==27
    resumed = engine(db,100,followups=False)
    code,result = resumed.run()
    assert code==2
    reviews = db.all("SELECT * FROM message WHERE campaign_id=%s AND sequence=0 AND status='review'",[e.cid])
    assert len(reviews)==3
    assert db.count_sent(e.cid)==97
    assert 'reserve' in result['reason']
    for row in reviews:
        db.review(row['id'],'sent',[0,0,0],datetime.now(timezone.utc)-timedelta(seconds=1),'verified fake SMTP log')
    final = engine(db,100,followups=False)
    assert final.run()[0]==0 and not final.smtp.calls
    assert db.count_sent(e.cid)==100


def test_followup_draft_503_is_retried_without_consuming_smtp_attempts(db):
    engine(db,1).run()
    llm = FakeLLM(temporary=100)
    e = engine(db,1,llm=llm)
    e.c = replace(e.c,process_new_outreach=False)
    assert e.run()[0]==0
    f1 = db.one('SELECT * FROM message WHERE sequence=1')
    assert f1['draft_attempts']==2
    assert f1['attempts']==1 and f1['status']=='sent'


def test_inbound_event_dedup_survives_new_uid(db):
    engine(db,1).run()
    sent = db.one("SELECT m.*,l.email FROM message m JOIN lead l ON l.id=m.lead_id WHERE sequence=0 AND m.status='sent'")
    mailbox = FakeMailbox()
    event = {'key':'same-original-message-id','uid':1,'kind':'reply','email':sent['email'],'message_ids':[sent['message_id']],'occurred_at':datetime.now(timezone.utc).isoformat()}
    mailbox.events[sent['sender_id']] = [event]
    for uid in (1,2):
        event['uid'] = uid
        e = engine(db,1,mailbox=mailbox)
        e.c.data['mailbox']['enabled'] = True
        e.c = replace(e.c,process_new_outreach=False)
        e.run()
    assert db.one('SELECT count(*) AS n FROM inbound')['n']==1
    assert db.one('SELECT last_uid FROM mailbox_cursor WHERE sender_id=%s',[sent['sender_id']])['last_uid']==2


def test_populated_legacy_tables_are_not_silently_ignored(db):
    db.execute('CREATE TABLE public.outreach(id text)')
    try:
        db.execute("INSERT INTO public.outreach VALUES('old-history')")
        with pytest.raises(RuntimeError,match='legacy'):
            db.migrate()
    finally:
        db.execute('DROP TABLE public.outreach')


def test_sent_identity_and_thread_headers_cannot_be_mutated(db):
    engine(db,1).run()
    sent = db.one("SELECT * FROM message WHERE status='sent'")
    with pytest.raises(psycopg.errors.RaiseException):
        db.execute('UPDATE message SET sequence=1 WHERE id=%s',[sent['id']])
    with pytest.raises(psycopg.errors.RaiseException):
        db.execute("UPDATE message SET body='changed' WHERE id=%s",[sent['id']])
    with pytest.raises(psycopg.errors.RaiseException):
        db.execute("UPDATE message SET in_reply_to='<wrong@sender.example>' WHERE sequence=1")


def test_all_followup_delays_are_from_immediate_successful_predecessor(db):
    delays = [86400,604800,1209600]
    first = engine(db,1)
    first.c.data['followups']['delays_seconds'] = delays
    first.run()
    for sequence in range(1,4):
        previous = db.one("SELECT * FROM message WHERE sequence=%s AND status='sent'",[sequence-1])
        current = db.one('SELECT * FROM message WHERE sequence=%s',[sequence])
        assert current['due_at']==previous['sent_at']+timedelta(seconds=delays[sequence-1])
        assert current['sender_id']==previous['sender_id']
        assert current['in_reply_to']==previous['message_id']
        assert current['refs']==previous['refs']+[previous['message_id']]
        # Simulate business due time arriving without sleeping for weeks.
        db.execute("UPDATE message SET due_at=now()-interval '1 second' WHERE id=%s",[current['id']])
        next_engine = engine(db,1)
        next_engine.c.data['followups']['delays_seconds'] = delays
        next_engine.c = replace(next_engine.c,process_new_outreach=False)
        assert next_engine.run()[0]==0
        assert db.one('SELECT status FROM message WHERE id=%s',[current['id']])['status']=='sent'
    assert db.one('SELECT count(*) AS n FROM message WHERE sequence>3')['n']==0


def test_migrations_are_versioned_and_idempotent(db):
    assert [row['version'] for row in db.all('SELECT version FROM schema_version ORDER BY version')] == [1, 2]
    db.migrate()
    assert [row['version'] for row in db.all('SELECT version FROM schema_version ORDER BY version')] == [1, 2]


def test_read_only_diagnostic_does_not_change_records(db):
    engine(db,1,real=False).run()
    before = {
        table: db.one(f'SELECT count(*) AS n FROM {table}')['n']
        for table in ('campaign','invocation','candidate','lead','message','attempt','event','suppression')
    }
    diagnostic = Store(os.environ['TEST_DATABASE_URL'],read_only=True)
    try:
        result = diagnostic.diagnose()
        assert result['database'] == 'reachable'
        assert result['schema'] == 'initialized'
        assert result['read_only'] is True
    finally:
        diagnostic.close()
    after = {
        table: db.one(f'SELECT count(*) AS n FROM {table}')['n']
        for table in before
    }
    assert after == before


def test_delivery_acceptance_has_durable_event(db):
    e = engine(db,1,followups=False)
    assert e.run()[0] == 0
    sent = db.one("SELECT id,sequence FROM message WHERE status='sent' AND sequence=0")
    event = db.one("SELECT invocation_id,payload FROM event WHERE kind='delivery_accepted' AND payload->>'message'=%s",[sent['id']])
    assert event is not None
    assert event['invocation_id'] == e.iid
    assert event['payload']['sequence'] == sent['sequence']


def test_operator_review_update_and_history_roll_back_together(db):
    engine(db,1,real=False).run()
    row = db.one("SELECT * FROM message WHERE sequence=0 LIMIT 1")
    db.execute("UPDATE message SET status='review',sender_id='s0',message_id='<review-atomic@sender.example>' WHERE id=%s",[row['id']])
    original_event = db.event
    def fail_review_event(invocation_id,kind,payload):
        if kind == 'operator_delivery_resolution':
            raise RuntimeError('simulated audit persistence failure')
        return original_event(invocation_id,kind,payload)
    db.event = fail_review_event
    with pytest.raises(RuntimeError,match='audit persistence'):
        db.review(row['id'],'not-sent',[0,0,0],evidence='test evidence')
    db.event = original_event
    assert db.one('SELECT status FROM message WHERE id=%s',[row['id']])['status'] == 'review'
    assert db.one("SELECT 1 FROM event WHERE kind='operator_delivery_resolution'") is None


def test_failed_followup_still_allows_full_new_100_pipeline(db):
    engine(db,1).run()
    original = db.one("SELECT * FROM message WHERE sequence=0 AND status='sent'")
    db.execute("UPDATE sender SET health='STOPPED' WHERE id=%s",[original['sender_id']])
    e = engine(db,100)
    code,result = e.run()
    assert code==2 and result['run_status']=='PARTIAL_FOLLOWUPS'
    assert result['successful_initial_sends']==100
    assert not db.one("SELECT 1 FROM message WHERE sequence=2 AND lead_id=%s",[original['lead_id']])


def test_suppression_and_inbound_cursor_commit_atomically_after_crash(db):
    engine(db,1).run()
    sent = db.one("SELECT m.*,l.email FROM message m JOIN lead l ON l.id=m.lead_id WHERE sequence=0 AND m.status='sent'")
    mailbox = FakeMailbox()
    mailbox.events[sent['sender_id']] = [{'key':'atomic-inbound','uid':1,'kind':'reply','email':sent['email'],'message_ids':[sent['message_id']],'occurred_at':datetime.now(timezone.utc).isoformat()}]
    original = db.suppress
    def crash(*args):
        raise KeyboardInterrupt()
    db.suppress = crash
    e = engine(db,1,mailbox=mailbox)
    e.c.data['mailbox']['enabled'] = True
    e.c = replace(e.c,process_new_outreach=False)
    with pytest.raises(KeyboardInterrupt):
        e.run()
    db.suppress = original
    assert not db.one('SELECT 1 FROM inbound')
    assert not db.one('SELECT 1 FROM mailbox_cursor WHERE sender_id=%s',[sent['sender_id']])
    recovered = engine(db,1,mailbox=mailbox)
    recovered.c.data['mailbox']['enabled'] = True
    recovered.c = replace(recovered.c,process_new_outreach=False)
    assert recovered.run()[0]==0
    assert db.one('SELECT 1 FROM suppression WHERE email=%s',[sent['email']])
    assert db.one('SELECT last_uid FROM mailbox_cursor WHERE sender_id=%s',[sent['sender_id']])['last_uid']==1


def test_optional_sender_cap_blocks_without_wait_and_can_resume(db):
    e = engine(db,20)
    e.c.data['limits'].update(daily_sender_enabled=True,daily_sender=1)
    code,result = e.run()
    assert code==2 and result['successful_initial_sends']==10
    assert engine(db,20).run()[1]['successful_initial_sends']==20


def test_optional_window_blocks_sends_when_not_in_window(db):
    e = engine(db,10)
    now = datetime.now(timezone.utc)
    e.c.data['limits'].update(send_window_enabled=True,timezone='UTC',
        window_start=(now+timedelta(hours=1)).strftime('%H:%M'),
        window_end=(now+timedelta(hours=2)).strftime('%H:%M'))
    code,result = e.run()
    assert code==2 and not e.smtp.calls
    assert result['successful_initial_sends']==0


def test_backoff_cannot_sleep_past_runtime_deadline(db):
    e = engine(db,1)
    e.c.data['limits']['max_runtime_seconds'] = 1
    e.c.data['retry']['max_seconds'] = 60
    called = []
    e.sleep = called.append
    assert not e.wait_until(datetime.now(timezone.utc)+timedelta(seconds=20))
    assert not called

