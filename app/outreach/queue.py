from __future__ import annotations
from datetime import datetime, timedelta, timezone
from app.models import MessageStatus, SequenceType
from app.storage.repository import deterministic_outreach_id

def iso(dt): return dt.replace(microsecond=0).isoformat().replace('+00:00','Z')

class OutreachQueue:
    def __init__(self,store): self.store=store
    def create(self,lead,draft,sender,schedule_at,sequence_type=SequenceType.INITIAL,sequence_number=1,in_reply_to=None)->str|None:
        oid,key=deterministic_outreach_id(lead.lead_id,sequence_type,sequence_number)
        existing=self.store.get_outreach(oid)
        if existing: return oid
        body_hash=__import__('hashlib').sha256(draft.body.strip().encode()).hexdigest()
        record={'outreach_id':oid,'sequence_key':key,'lead_id':lead.lead_id,'email':lead.email,'company':lead.company,'website':lead.website,
          'sender_id':sender.sender_id,'sender_email':sender.email,'sequence_type':sequence_type.value,'sequence_number':sequence_number,
          'subject':draft.subject,'body':draft.body,'generated_at_utc':iso(datetime.now(timezone.utc)),'scheduled_at_utc':iso(schedule_at),
          'status':MessageStatus.SCHEDULED.value,'evidence_urls':draft.evidence_urls,'personalization_confidence':draft.confidence,
          'suppression_status':'SUPPRESSED' if self.store.is_suppressed(lead.email) else 'CLEAR','body_hash':body_hash,'in_reply_to':in_reply_to}
        if record['suppression_status']=='SUPPRESSED':return None
        return oid if self.store.insert_outreach(record) else None
