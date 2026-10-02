from __future__ import annotations
from datetime import datetime,timedelta,timezone

class FollowupScheduler:
    def __init__(self,settings): self.settings=settings
    def followup_due(self,initial_sent_at:str,sequence_number:int):
        base=datetime.fromisoformat(initial_sent_at.replace('Z','+00:00'))
        if sequence_number==1:return base+timedelta(hours=self.settings.followup_1_delay_hours)
        if sequence_number==2:return base+timedelta(days=self.settings.followup_2_delay_days)
        if sequence_number==3:return base+timedelta(days=self.settings.followup_3_delay_days)
        raise ValueError('sequence_number must be 1-3')
