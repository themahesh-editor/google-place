from __future__ import annotations
import imaplib
from datetime import datetime,timedelta,timezone
from app.email.mailbox_provider import MailboxItem

class IMAPMailboxProvider:
    def __init__(self, config, credential: str, mailbox: str = 'INBOX'):
        self.config=config; self.credential=credential; self.mailbox=mailbox; self.client=None; self.uidvalidity=None
    def connect(self)->None:
        if not self.config.email or not self.credential: raise ValueError(f'{self.config.sender_id} mailbox identity/credential missing')
        if self.config.imap_ssl:
            self.client=imaplib.IMAP4_SSL(self.config.imap_host,self.config.imap_port)
        else:
            self.client=imaplib.IMAP4(self.config.imap_host,self.config.imap_port); self.client.starttls()
        self.client.login(self.config.email,self.credential); status,_=self.client.select(self.mailbox,readonly=True)
        if status!='OK': raise RuntimeError(f'IMAP select failed for {self.mailbox}')
        try:
            _,data=self.client.response('UIDVALIDITY')
            self.uidvalidity=(data[0].decode() if data and isinstance(data[0],bytes) else str(data[0])) if data else None
        except Exception: self.uidvalidity=None
    def check_new_messages(self,last_processed_uid:int,lookback_minutes:int,max_messages:int)->list[MailboxItem]:
        if not self.client: raise RuntimeError('IMAP not connected')
        since=(datetime.now(timezone.utc)-timedelta(minutes=lookback_minutes)).strftime('%d-%b-%Y')
        criteria=f'(SINCE "{since}" UID {max(1,last_processed_uid+1)}:*)'
        status,data=self.client.uid('SEARCH',None,criteria)
        if status!='OK' or not data or not data[0]: return []
        uids=[int(x) for x in data[0].split()][-max_messages:]
        out=[]
        for uid in uids:
            status,data=self.client.uid('FETCH',str(uid),'(RFC822)')
            if status=='OK':
                for part in data:
                    if isinstance(part,tuple): out.append(MailboxItem(uid,part[1]))
        return out
    def mark_processed(self,uid:int)->None: pass
    def close(self)->None:
        try:
            if self.client:
                try:self.client.close()
                except Exception:pass
                try:self.client.logout()
                except Exception:pass
        finally:self.client=None
