from __future__ import annotations

import hashlib
from datetime import datetime, timezone, timedelta
from email.utils import make_msgid

from app.email.smtp_provider import SMTPEmailSender
from app.models import MessageStatus, SequenceType
from app.outreach.queue import OutreachQueue
from app.outreach.scheduler import SenderCapacity


def now_utc() -> datetime:
    return datetime.now(timezone.utc)

def iso(dt:datetime)->str:return dt.replace(microsecond=0).isoformat().replace('+00:00','Z')

def message_id_for(outreach_id:str, sender_email:str)->str:
    token=hashlib.sha256(f'{outreach_id}|{sender_email}'.encode()).hexdigest()[:24]
    domain=sender_email.split('@',1)[1] if '@' in sender_email else 'localhost'
    return f'<attachai-{token}@{domain}>'

class SendController:
    def __init__(self,store,settings,sender_factory=SMTPEmailSender): self.store=store; self.settings=settings; self.sender_factory=sender_factory

    def _daily_key(self,sender_id:str,when:datetime)->str:return when.astimezone(self.settings.timezone()).date().isoformat()

    def _eligible(self,row,*,latest_mailbox_check_ok:bool=False)->tuple[bool,str]:
        if row['status'] not in {MessageStatus.QUEUED.value,MessageStatus.SCHEDULED.value,MessageStatus.FAILED_RETRYABLE.value}: return False,'forbidden_state'
        if self.store.is_suppressed(row['email']): return False,'suppressed'
        lead=self.store.get_lead(row['lead_id'])
        if not lead:return False,'missing_lead'
        if lead.status in {'REPLIED','BOUNCED','UNSUBSCRIBED','COMPLETED','MANUAL_STOP'}: return False,lead.status
        if row['sequence_type'].startswith('FOLLOWUP_') and not latest_mailbox_check_ok and self.settings.require_fresh_mailbox_check_before_followup: return False,'stale_mailbox'
        return True,''

    def send_one(self,outreach_id:str,*,dry_run:bool|None=None,latest_mailbox_check_ok:bool=False)->str:
        dry=self.settings.dry_run if dry_run is None else dry_run
        row=self.store.get_outreach(outreach_id)
        if not row:return 'missing'
        ok,reason=self._eligible(row,latest_mailbox_check_ok=latest_mailbox_check_ok)
        if not ok:
            self.store.add_event('send_blocked',lead_id=row['lead_id'],outreach_id=outreach_id,sender_id=row['sender_id'],sequence_type=row['sequence_type'],status=row['status'],reason=reason)
            return 'blocked'
        mid=message_id_for(outreach_id,row['sender_email'])
        if dry or not self.settings.send_enabled:
            self.store.add_event('dry_run_send',lead_id=row['lead_id'],outreach_id=outreach_id,sender_id=row['sender_id'],sequence_type=row['sequence_type'],status='DRY_RUN')
            return 'dry_run'
        now=now_utc(); cap=SenderCapacity(self.store,self.settings); cap_ok,cap_reason=cap.can_send(row['sender_id'],row['sequence_type'].startswith('FOLLOWUP_'),now,self.store.get_lead(row['lead_id']).timezone)
        if not cap_ok:
            self.store.add_event('send_blocked',lead_id=row['lead_id'],outreach_id=outreach_id,sender_id=row['sender_id'],sequence_type=row['sequence_type'],status=row['status'],reason=cap_reason)
            return 'blocked'
        if not self.store.claim_outreach(outreach_id): return 'already_claimed'
        provider=None
        try:
            provider=self.sender_factory(next(s for s in self.settings.sender_configs() if s.sender_id==row['sender_id']))
            provider.send(to_email=row['email'],subject=row['subject'],body=row['body'],from_email=row['sender_email'],message_id=mid,in_reply_to=row['in_reply_to'])
            sent=iso(now_utc())
            self.store.mark_sent(outreach_id,sent,mid)
            self.store.record_send(row['sender_id'],self._daily_key(row['sender_id'],now_utc()),row['sequence_type'].startswith('FOLLOWUP_'),sent)
            self.store.set_lead_status(row['lead_id'],'COMPLETED' if row['sequence_type']=='FOLLOWUP_3' else 'ACTIVE')
            self.store.add_event('message_sent',lead_id=row['lead_id'],outreach_id=outreach_id,sender_id=row['sender_id'],sequence_type=row['sequence_type'],status='SENT')
            return 'sent'
        except Exception as exc:
            if provider is not None: kind=provider.classify_error(exc)
            else: kind='TERMINAL'
            next_retry=iso(now_utc()+timedelta(seconds=self.settings.retry_base_seconds*(2**min(row['attempt_count'],5)))) if kind=='TEMPORARY' and row['attempt_count']<self.settings.max_retries else None
            retry=kind=='TEMPORARY' and row['attempt_count']<self.settings.max_retries
            self.store.mark_failure(outreach_id,retry,str(exc),next_retry)
            self.store.record_failure(row['sender_id'],self._daily_key(row['sender_id'],now_utc()),kind)
            if kind=='AUTH': self.store.set_sender_health(row['sender_id'],self._daily_key(row['sender_id'],now_utc()),'STOPPED')
            self.store.add_event('send_failed',lead_id=row['lead_id'],outreach_id=outreach_id,sender_id=row['sender_id'],sequence_type=row['sequence_type'],status='FAILED_RETRYABLE' if retry else 'FAILED_TERMINAL',reason=kind,metadata={'error_class':exc.__class__.__name__})
            return 'retryable_failed' if retry else 'failed'

    def reconcile_inflight(self):
        for row in self.store.get_unfinished_sends():
            self.store.db.execute("UPDATE outreach SET status='REVIEW_NEEDED',last_error='workflow_interrupted_while_sending',updated_at_utc=? WHERE outreach_id=?",[iso(now_utc()),row['outreach_id']])
            self.store.add_event('inflight_reconciled',lead_id=row['lead_id'],outreach_id=row['outreach_id'],sender_id=row['sender_id'],sequence_type=row['sequence_type'],status='REVIEW_NEEDED',reason='crash_safe_no_resend')
