from __future__ import annotations
class SuppressionService:
    def __init__(self,store): self.store=store
    def is_suppressed(self,email:str)->bool:return self.store.is_suppressed(email)
    def suppress(self,email:str,lead_id:str|None,reason:str):
        self.store.suppress(email,lead_id,reason)
        if lead_id:self.store.set_lead_status(lead_id,'UNSUBSCRIBED' if 'unsubscribe' in reason.lower() or 'opt' in reason.lower() else 'BOUNCED')
