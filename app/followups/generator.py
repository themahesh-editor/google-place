from __future__ import annotations
from datetime import datetime,timezone
from app.models import SequenceType

class FollowupService:
    def __init__(self,store,generator,validator,queue,scheduler):
        self.store=store; self.generator=generator; self.validator=validator; self.queue=queue; self.scheduler=scheduler
    def create_due(self,now_utc,limit=100):
        made=[]
        for lead in self.store.list_eligible_leads(limit):
            initial=self.store.get_sequence(lead.lead_id,'INITIAL',1)
            if not initial or initial['status']!='SENT' or not initial['sent_at_utc']: continue
            if lead.status in {'REPLIED','BOUNCED','UNSUBSCRIBED','COMPLETED','MANUAL_STOP'} or self.store.is_suppressed(lead.email): continue
            research=self.store.latest_research(lead.lead_id)
            if not research or research.research_status!='RESEARCHED': continue
            history=[dict(x) for x in self.store.get_outreach_for_lead(lead.lead_id,include_unsent=False)]
            sender_id=initial['sender_id']; sender=next(s for s in self.scheduler.settings.sender_configs() if s.sender_id==sender_id)
            for n in (1,2,3):
                seq=f'FOLLOWUP_{n}'
                if self.store.get_sequence(lead.lead_id,seq,n): continue
                due=self.scheduler.followup_due(initial['sent_at_utc'],n)
                if due>now_utc: continue
                try:
                    draft=self.generator.followup(lead,research,history,n,sender.email)
                except Exception as exc:
                    self.store.add_event('followup_generation_failed',lead_id=lead.lead_id,sender_id=sender_id,sequence_type=seq,status='FAILED_RETRYABLE',reason=exc.__class__.__name__)
                    continue
                valid=self.validator.validate(lead,research,draft,previous_bodies=[x['body'] for x in history])
                if not valid.ok:
                    self.store.add_event('followup_rejected',lead_id=lead.lead_id,sender_id=sender_id,sequence_type=seq,status='FAILED_TERMINAL',reason=valid.reason)
                    continue
                oid=self.queue.create(lead,draft,sender,due,SequenceType(seq),n)
                if oid: made.append(oid)
                if len(made)>=limit:return made
        return made
