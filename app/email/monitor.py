from __future__ import annotations
import hashlib
from app.email.classifier import classify_inbound
from app.email.message_parser import parse_message
from app.models import InboundEventType

class MailboxMonitor:
    def __init__(self,store,settings,provider_factory): self.store=store; self.settings=settings; self.provider_factory=provider_factory

    def _correlate(self,sender_id,parsed):
        candidates=[]
        for ref in [parsed.in_reply_to,*parsed.references]:
            if ref:
                r=self.store.get_by_message_id(ref)
                if r:candidates.append((1.0,r))
        lead=self.store.get_lead_by_email(parsed.from_email)
        if lead:
            histories=self.store.get_outreach_for_lead(lead['lead_id'],include_unsent=False)
            for r in histories:
                if r['sender_id']==sender_id:candidates.append((0.9,r)); break
        if not candidates:return None,0.0,None
        candidates.sort(key=lambda x:x[0],reverse=True)
        conf,row=candidates[0]
        # Normal subject match is only secondary evidence and never enough by itself.
        return row['lead_id'],conf,row['outreach_id']

    def run_sender(self,sender):
        cred=__import__('os').getenv(sender.credential_env,"").strip()
        provider=self.provider_factory(sender,cred); provider.connect()
        state=self.store.mailbox_state(sender.sender_id)
        last=int(state['last_processed_uid']) if state else 0
        uidvalidity=str(state['uidvalidity']) if state and state['uidvalidity'] else None
        current_uidvalidity=getattr(provider,'uidvalidity',None)
        if uidvalidity and current_uidvalidity and uidvalidity != current_uidvalidity:
            last=0
            self.store.add_event('mailbox_uidvalidity_changed',sender_id=sender.sender_id,status='REBASE',reason='bounded_lookback_resync')
        items=provider.check_new_messages(last,self.settings.mailbox_check_lookback_minutes,self.settings.mailbox_max_messages_per_run)
        max_uid=last
        for item in items:
            max_uid=max(max_uid,item.uid)
            parsed=parse_message(item.raw)
            if not parsed.message_id: continue
            if self.store.inbound_exists(sender.sender_id,parsed.message_id): continue
            event,conf=classify_inbound(parsed)
            lead_id,out_conf,outreach_id=self._correlate(sender.sender_id,parsed)
            if event==InboundEventType.REPLY and not lead_id:
                event=InboundEventType.UNCLASSIFIED; conf=0.45
            if event==InboundEventType.HARD_BOUNCE and not lead_id:
                # Unknown DSN is recorded but does not trigger a destructive state transition.
                event=InboundEventType.REVIEW_NEEDED; conf=0.45
            final_conf=min(conf,out_conf) if out_conf else conf
            inbound_id=hashlib.sha256(f'{sender.sender_id}|{parsed.message_id}'.encode()).hexdigest()
            self.store.save_inbound(inbound_message_id=inbound_id,sender_id=sender.sender_id,message_id=parsed.message_id,in_reply_to=parsed.in_reply_to,references_text=' '.join(parsed.references),received_at_utc=parsed.received_at_utc,lead_id=lead_id,outreach_id=outreach_id,event_type=event.value,classification_confidence=final_conf,processing_status='PROCESSED',subject=parsed.subject,from_email=parsed.from_email)
            if event==InboundEventType.REPLY and lead_id:
                self.store.set_lead_status(lead_id,'REPLIED'); self.store.cancel_future_followups(lead_id)
                self.store.add_event('reply_detected',lead_id=lead_id,outreach_id=outreach_id,sender_id=sender.sender_id,status='REPLIED',metadata={'received_at_utc':parsed.received_at_utc})
            elif event==InboundEventType.HARD_BOUNCE and lead_id:
                target_email=self.store.get_lead(lead_id).email if lead_id else parsed.from_email
                self.store.suppress(target_email,lead_id,'hard_bounce'); self.store.set_lead_status(lead_id,'BOUNCED'); self.store.cancel_future_followups(lead_id)
            elif event==InboundEventType.UNSUBSCRIBED:
                self.store.suppress(parsed.from_email,lead_id,'unsubscribe');
                if lead_id:self.store.set_lead_status(lead_id,'UNSUBSCRIBED'); self.store.cancel_future_followups(lead_id)
            elif event==InboundEventType.SOFT_BOUNCE:
                self.store.add_event('soft_bounce',lead_id=lead_id,outreach_id=outreach_id,sender_id=sender.sender_id,status='RECORDED',metadata={'received_at_utc':parsed.received_at_utc})
            self.store.add_event('inbound_processed',lead_id=lead_id,outreach_id=outreach_id,sender_id=sender.sender_id,status=event.value,reason='mailbox_monitor')
        self.store.save_mailbox_state(sender_id=sender.sender_id,mailbox_identifier='INBOX',provider_type='imap',uidvalidity=current_uidvalidity or uidvalidity,last_processed_uid=max_uid,last_checked_at_utc=__import__('datetime').datetime.now(__import__('datetime').timezone.utc).replace(microsecond=0).isoformat().replace('+00:00','Z'),health_state='HEALTHY')
        self.store.add_event('mailbox_check',sender_id=sender.sender_id,status='SUCCESS',metadata={'messages_seen':len(items),'last_processed_uid':max_uid})
        provider.close()
        return len(items)
