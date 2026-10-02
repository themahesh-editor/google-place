from __future__ import annotations
import argparse,json,os
from datetime import datetime,timezone
from app.config import settings_from_env
from app.integrations.lead_engine import LeadEngineCSV
from app.research.crawler import WebsiteCrawler
from app.research.research_service import ResearchService
from app.llm.client import LLMClient
from app.personalization.generator import PersonalizationGenerator
from app.personalization.validator import PersonalizationValidator
from app.outreach.scheduler import SenderScheduler,SenderCapacity
from app.outreach.queue import OutreachQueue
from app.outreach.state import SendController
from app.followups.scheduler import FollowupScheduler
from app.followups.generator import FollowupService
from app.email.imap_mailbox import IMAPMailboxProvider
from app.email.monitor import MailboxMonitor
from app.email.smtp_provider import SMTPEmailSender
from app.reporting.metrics import Metrics
from app.storage.repository import open_store

def build_services(settings):
    store=open_store(settings.sqlite_path,settings.database_url)
    llm=LLMClient(settings.llm_base_url,settings.llm_model,settings.llm_timeout_seconds)
    crawler=WebsiteCrawler(settings.crawler_timeout_seconds,settings.crawler_max_bytes,settings.crawler_max_pages,settings.crawler_request_delay_seconds,settings.honor_robots)
    research=ResearchService(store,llm,crawler,settings.research_prompt_version)
    generator=PersonalizationGenerator(llm); validator=PersonalizationValidator(settings.quality_prompt_version)
    scheduler=SenderScheduler(store,settings); queue=OutreachQueue(store); controller=SendController(store,settings)
    followups=FollowupService(store,generator,validator,queue,FollowupScheduler(settings))
    return store,llm,crawler,research,generator,validator,scheduler,queue,controller,followups

def import_verified(settings,store,limit):
    leads=LeadEngineCSV(os.getenv('CRM_FILE','leads_crm.csv')).read_verified(limit)
    for lead in leads:
        existing=store.get_lead(lead.lead_id)
        store.upsert_lead(lead)
        if not existing and not store.is_suppressed(lead.email): store.set_lead_status(lead.lead_id,'ELIGIBLE')
    return leads

def research_only(store,research,leads):
    done=0
    for lead in leads:
        current=store.latest_research(lead.lead_id)
        if current and current.research_status=='RESEARCHED': continue
        r=research.run_one(lead); done+=1 if r.research_status=='RESEARCHED' else 0
    return done

def personalization_only(settings,store,generator,validator,scheduler,queue,leads):
    prepared=0
    for lead in leads:
        if store.is_suppressed(lead.email) or store.get_sequence(lead.lead_id,'INITIAL',1): continue
        r=store.latest_research(lead.lead_id)
        if not r or r.research_status!='RESEARCHED': continue
        sender=scheduler.assign_sender(lead.lead_id)
        try:
            draft=generator.initial(lead,r,sender.email)
        except Exception as exc:
            store.add_event('initial_generation_failed',lead_id=lead.lead_id,sender_id=sender.sender_id,sequence_type='INITIAL',status='FAILED_RETRYABLE',reason=exc.__class__.__name__)
            continue
        valid=validator.validate(lead,r,draft,previous_bodies=[])
        if not valid.ok or not draft.eligible:
            store.add_event('initial_rejected',lead_id=lead.lead_id,sender_id=sender.sender_id,sequence_type='INITIAL',status='FAILED_TERMINAL',reason=valid.reason or 'not_eligible'); continue
        when=scheduler.next_send_time(sender.sender_id,lead.timezone); oid=queue.create(lead,draft,sender,when)
        if oid: store.set_lead_status(lead.lead_id,'SCHEDULED'); prepared+=1
    return prepared

def process_mailbox_sender(settings,store,sender_id):
    sender=next(s for s in settings.sender_configs() if s.sender_id==sender_id)
    monitor=MailboxMonitor(store,settings,lambda cfg,cred: IMAPMailboxProvider(cfg,cred))
    try:
        monitor.run_sender(sender); return True
    except Exception as exc:
        day=datetime.now(timezone.utc).astimezone(settings.timezone()).date().isoformat(); store.set_sender_health(sender.sender_id,day,'DEGRADED')
        store.add_event('mailbox_error',sender_id=sender.sender_id,status='FAILED',reason=exc.__class__.__name__)
        return False

def process_mailboxes(settings,store):
    monitor=MailboxMonitor(store,settings,lambda sender,cred: IMAPMailboxProvider(sender,cred)); total=0
    for sender in settings.sender_configs():
        try: total+=monitor.run_sender(sender)
        except Exception as exc:
            day=datetime.now(timezone.utc).astimezone(settings.timezone()).date().isoformat(); store.set_sender_health(sender.sender_id,day,'DEGRADED')
            store.add_event('mailbox_error',sender_id=sender.sender_id,status='FAILED',reason=exc.__class__.__name__)
    return total

def send_due(settings,store,controller,only_followups=False,dry_run=None):
    now=datetime.now(timezone.utc).replace(microsecond=0); ts=now.isoformat().replace('+00:00','Z')
    rows=store.db.fetchall("SELECT * FROM outreach WHERE status IN ('SCHEDULED','QUEUED','FAILED_RETRYABLE') AND (scheduled_at_utc<=? OR next_retry_at_utc<=?) ORDER BY coalesce(next_retry_at_utc,scheduled_at_utc),sequence_number LIMIT ?",[ts,ts,settings.daily_new_outreach_target*5])
    results=[]
    for row in rows:
        is_follow=row['sequence_type'].startswith('FOLLOWUP_')
        if only_followups!=is_follow: continue
        lead=store.get_lead(row['lead_id'])
        ok,reason=SenderCapacity(store,settings).can_send(row['sender_id'],is_follow,now,lead.timezone if lead else '')
        if not ok: store.add_event('send_deferred',lead_id=row['lead_id'],outreach_id=row['outreach_id'],sender_id=row['sender_id'],sequence_type=row['sequence_type'],status=row['status'],reason=reason); continue
        if is_follow and settings.require_fresh_mailbox_check_before_followup:
            if not process_mailbox_sender(settings,store,row['sender_id']): continue
            row=store.get_outreach(row['outreach_id'])
            if not row or row['status'] not in {'SCHEDULED','QUEUED','FAILED_RETRYABLE'}: continue
        results.append(controller.send_one(row['outreach_id'],dry_run=dry_run,latest_mailbox_check_ok=(not is_follow or True)))
    return results

def run(mode='all',lead_limit=100):
    settings=settings_from_env()
    if settings.send_enabled and not settings.dry_run: settings.validate_for_send()
    else: settings.validate_for_dry_run()
    store,llm,crawler,research,generator,validator,scheduler,queue,controller,followups=build_services(settings)
    try:
        controller.reconcile_inflight(); leads=[]
        if mode=='mailbox_check_only':
            print(json.dumps({'mailbox_messages':process_mailboxes(settings,store)})); return
        leads=import_verified(settings,store,lead_limit)
        if mode in {'all','research','research_only','dry_run'}: research_only(store,research,leads)
        if mode in {'all','personalization','personalization_only','dry_run'}: personalization_only(settings,store,generator,validator,scheduler,queue,leads)
        if mode in {'all','followups','followup_only','dry_run'}: followups.create_due(datetime.now(timezone.utc),lead_limit)
        if mode in {'all','send','send_only','dry_run','followup_only'}:
            if settings.sender_test_mode:
                for sender in settings.sender_configs(): SMTPEmailSender(sender).validate_connection()
                print(json.dumps({'sender_test_mode':'validated'})); return
            results=send_due(settings,store,controller,only_followups=False,dry_run=(True if mode=='dry_run' else None))
            if mode in {'all','send','send_only'}: results+=send_due(settings,store,controller,only_followups=True,dry_run=None if mode!='dry_run' else True)
            elif mode=='dry_run': results+=send_due(settings,store,controller,only_followups=True,dry_run=True)
            print(json.dumps({'send_results':results}))
        day=datetime.now(timezone.utc).astimezone(settings.timezone()).date().isoformat(); print(json.dumps(Metrics(store).snapshot(day),indent=2))
    finally: store.close()

def main():
    p=argparse.ArgumentParser(); p.add_argument('mode',choices=['all','research','research_only','personalization','personalization_only','send','send_only','followups','followup_only','mailbox_check_only','dry_run']); p.add_argument('--lead-limit',type=int,default=100); a=p.parse_args(); run(a.mode,a.lead_limit)
if __name__=='__main__':main()
