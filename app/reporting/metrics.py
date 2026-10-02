from __future__ import annotations
class Metrics:
    def __init__(self,store):self.store=store
    def snapshot(self,day_key:str)->dict:
        def n(sql):
            r=self.store.db.fetchone(sql,[day_key]); return int(r[0] if not isinstance(r,dict) else list(r.values())[0]) if r else 0
        return {
            'new_leads':n("SELECT count(*) FROM leads WHERE substr(created_at_utc,1,10)=?"),
            'initial_queued':n("SELECT count(*) FROM outreach WHERE sequence_type='INITIAL' AND substr(created_at_utc,1,10)=?"),
            'initial_sent':n("SELECT count(*) FROM outreach WHERE sequence_type='INITIAL' AND substr(sent_at_utc,1,10)=?"),
            'replies':n("SELECT count(*) FROM inbound_message WHERE event_type='REPLY' AND substr(processed_at_utc,1,10)=?"),
            'bounces':n("SELECT count(*) FROM inbound_message WHERE event_type IN ('HARD_BOUNCE','SOFT_BOUNCE') AND substr(processed_at_utc,1,10)=?"),
            'unsubscribes':n("SELECT count(*) FROM inbound_message WHERE event_type='UNSUBSCRIBED' AND substr(processed_at_utc,1,10)=?"),
            'mailbox_checks':n("SELECT count(*) FROM event_log WHERE event_type='mailbox_check' AND substr(event_timestamp_utc,1,10)=?"),
        }
