from __future__ import annotations
from datetime import datetime, timedelta, timezone, time

class SenderScheduler:
    def __init__(self,store,settings): self.store=store; self.settings=settings
    def assign_sender(self,lead_id:str)->object:
        existing=self.store.sender_for(lead_id)
        configs=self.settings.sender_configs()
        if existing:return next(s for s in configs if s.sender_id==existing)
        day=datetime.now(timezone.utc).astimezone(self.settings.timezone()).date().isoformat()
        scored=[]
        for s in configs:
            r=self.store.sender_daily_state(s.sender_id,day); scored.append((int(r['total']),int(r['new_outreach']),s.sender_id,s))
        for _,__,sid,s in sorted(scored):
            day_state=self.store.sender_daily_state(sid,day)
            if day_state['health_state']=='STOPPED': continue
            if self.store.assign_sender(lead_id,sid): return s
        existing=self.store.sender_for(lead_id)
        if existing:return next(s for s in configs if s.sender_id==existing)
        raise RuntimeError(f'Unable to persist sender assignment for {lead_id}')

    def next_window(self,lead_timezone:str,*,after:datetime|None=None,offset_minutes:int=0)->datetime:
        after=after or datetime.now(timezone.utc)
        try:
            from zoneinfo import ZoneInfo
            tz=ZoneInfo(lead_timezone or self.settings.app_timezone)
        except Exception: tz=self.settings.timezone()
        local=after.astimezone(tz)
        start=self.settings.sending_window_start; end=self.settings.sending_window_end
        candidate=local.replace(hour=start.hour,minute=start.minute,second=0,microsecond=0)
        if local.timetz().replace(tzinfo=None)<start: pass
        elif local.timetz().replace(tzinfo=None)<end: candidate=local.replace(second=0,microsecond=0)
        else: candidate=(local+timedelta(days=1)).replace(hour=start.hour,minute=start.minute,second=0,microsecond=0)
        candidate = candidate + timedelta(minutes=offset_minutes)
        if candidate.timetz().replace(tzinfo=None) > end:
            candidate = (candidate + timedelta(days=1)).replace(hour=start.hour,minute=start.minute,second=0,microsecond=0)
        return candidate.astimezone(timezone.utc)

    def next_send_time(self,sender_id:str,lead_timezone:str,after:datetime|None=None)->datetime:
        after=after or datetime.now(timezone.utc)
        candidate=self.next_window(lead_timezone,after=after)
        last=self.store.last_planned_send_at(sender_id)
        if last:
            last_dt=datetime.fromisoformat(last.replace('Z','+00:00'))
            min_after=max(after,last_dt+timedelta(minutes=self.settings.send_interval_minutes))
            if candidate < min_after:
                candidate=self.next_window(lead_timezone,after=min_after)
        return candidate

class SenderCapacity:
    def __init__(self,store,settings):self.store=store;self.settings=settings
    def can_send(self,sender_id:str,is_followup:bool,now:datetime,recipient_timezone:str='')->tuple[bool,str]:
        day=now.astimezone(self.settings.timezone()).date().isoformat(); r=self.store.sender_daily_state(sender_id,day)
        if r['health_state'] in {'STOPPED'}:return False,'sender_stopped'
        cooldown=r['cooldown_until_utc']
        if cooldown:
            try:
                if datetime.fromisoformat(cooldown.replace('Z','+00:00'))>now:return False,'sender_cooldown'
            except ValueError:return False,'invalid_cooldown'
        if int(r['total'])>=self.settings.daily_total_limit_per_sender:return False,'daily_total_limit'
        try:
            from zoneinfo import ZoneInfo
            local=now.astimezone(ZoneInfo(recipient_timezone or self.settings.app_timezone))
        except Exception: local=now.astimezone(self.settings.timezone())
        lt=local.timetz().replace(tzinfo=None); start=self.settings.sending_window_start; end=self.settings.sending_window_end
        if not (start <= lt < end): return False,'outside_sending_window'
        if is_followup and int(r['followups'])>=self.settings.daily_followup_limit_per_sender:return False,'daily_followup_limit'
        if not is_followup and int(r['new_outreach'])>=self.settings.daily_new_outreach_limit_per_sender:return False,'daily_new_limit'
        last=r['last_successful_send_utc']
        if last:
            dt=datetime.fromisoformat(last.replace('Z','+00:00'))
            if (now-dt).total_seconds()<self.settings.send_interval_minutes*60:return False,'send_spacing'
        return True,''
