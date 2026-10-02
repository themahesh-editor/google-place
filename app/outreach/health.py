from __future__ import annotations
from datetime import datetime,timezone
class SenderHealth:
    def __init__(self,store,settings):self.store=store;self.settings=settings
    def available(self,sender_id:str)->bool:
        day=datetime.now(timezone.utc).astimezone(self.settings.timezone()).date().isoformat()
        r=self.store.sender_daily_state(sender_id,day)
        if r['health_state']=='STOPPED':return False
        cooldown=r['cooldown_until_utc']
        if cooldown:
            try:
                if datetime.fromisoformat(cooldown.replace('Z','+00:00'))>datetime.now(timezone.utc):return False
            except Exception: return False
        return int(r.get('total',0))<self.settings.daily_total_limit_per_sender
