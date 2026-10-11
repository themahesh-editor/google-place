from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

LOCK_ID = 724865913087


class OperationalError(RuntimeError):
    """Fixed, credential-free coordinator diagnostics safe for user logs."""


def uid():
    return str(uuid.uuid4())


def j(value):
    return Jsonb(value)


class Store:
    """One PostgreSQL coordinator connection; network workers never share it."""

    def __init__(self, url):
        self.conn = psycopg.connect(url, autocommit=True, row_factory=dict_row, prepare_threshold=None)
        self.conn.execute("SET timezone TO 'UTC'")
        self.locked = False

    def close(self):
        self.conn.close()  # session close releases advisory lock even after a crash

    def acquire(self):
        if not self.one('SELECT pg_try_advisory_lock(%s) AS ok', [LOCK_ID])['ok']:
            raise OperationalError('Another AttachAI execution owns the database lock')
        self.locked = True

    def migrate(self):
        if not self.locked:
            raise OperationalError('Database lock required before migration')
        # This rewrite cannot silently discard legacy contact history. A populated
        # old deployment needs an explicit audited data migration, not a fresh queue.
        for table in ('outreach','suppression'):
            if self.one('SELECT to_regclass(%s) AS name',['public.'+table])['name']:
                from psycopg import sql
                if self.one(sql.SQL('SELECT 1 FROM public.{} LIMIT 1').format(sql.Identifier(table))):
                    raise OperationalError('Populated legacy AttachAI tables detected. Back up and perform an audited history migration before real operation; this replacement does not silently restart old contacts.')
        exists = self.one("SELECT to_regclass('attachai.schema_version') AS name")['name']
        if not exists:
            sql = (Path(__file__).resolve().parent.parent / 'migrations/001_initial.sql').read_text()
            with self.conn.transaction():
                self.conn.execute(sql, prepare=False)
        self.conn.execute('SET search_path TO attachai, public')
        version = self.one('SELECT max(version) AS version FROM schema_version')['version']
        if version != 1:
            raise OperationalError('Unsupported database schema version')

    def execute(self, sql, args=None):
        return self.conn.execute(sql, args)

    def one(self, sql, args=None):
        return self.execute(sql, args).fetchone()

    def all(self, sql, args=None):
        return self.execute(sql, args).fetchall()

    @contextmanager
    def tx(self):
        with self.conn.transaction():
            yield

    def reset(self):
        if not self.locked:
            raise RuntimeError('Database lock required before reset')
        # Explicit schema-qualified application tables; no public/user schema or credentials.
        self.execute('TRUNCATE attachai.event, attachai.schedule_slot, attachai.inbound, attachai.mailbox_cursor, '
                     'attachai.suppression, attachai.attempt, attachai.message, attachai.batch, attachai.draft, '
                     'attachai.lead, attachai.research_cache, attachai.candidate, attachai.invocation, '
                     'attachai.campaign, attachai.sender, attachai.discovery_cursor RESTART IDENTITY')

    def reconcile(self):
        with self.tx():
            # Holding the global lock proves the previous worker is no longer a coordinator.
            # Any SENDING is unknown even if its lease has not elapsed; never auto-retry.
            ambiguous = self.execute("UPDATE message SET status='review', error_kind='ambiguous',last_error='Interrupted SMTP acceptance; verify provider delivery before resolution',lease_until=NULL WHERE status='sending'").rowcount
            self.execute("UPDATE attempt SET status='review',finished_at=now(),error_kind='ambiguous' WHERE status='sending'")
            self.execute("UPDATE message SET next_retry=now(),lease_until=NULL WHERE status IN ('queued','retry') AND lease_until IS NOT NULL")
            self.execute("UPDATE candidate SET status='retry',next_retry=now(),lease_until=NULL WHERE status='working'")
            self.execute("UPDATE lead SET status='retry',next_retry=now(),lease_until=NULL WHERE status='working'")
            self.execute("UPDATE invocation SET status='interrupted',finished_at=now() WHERE status='running'")
            self.execute("UPDATE batch SET status='interrupted',finished_at=now() WHERE status='planned'")
        return {'ambiguous_messages': ambiguous}

    def register_senders(self, senders):
        for s in senders:
            old = self.one('SELECT email FROM sender WHERE id=%s', [s.id])
            if old and old['email'] != s.email:
                raise RuntimeError('Sender IDs are immutable; assign a new ID when changing an account')
            self.execute('INSERT INTO sender(id,email) VALUES(%s,%s) ON CONFLICT(id) DO NOTHING', [s.id, s.email])

    def start(self, target, real, mode, new_outreach):
        with self.tx():
            campaign = None
            if new_outreach and real:
                campaign = self.one("SELECT * FROM campaign WHERE kind='real' AND status IN ('active','blocked') ORDER BY created_at LIMIT 1 FOR UPDATE")
                if campaign and campaign['target'] != target:
                    raise OperationalError(f"Recovery target is immutable ({campaign['target']}); finish the campaign with the same target. Reset erases history and is not normal recovery.")
            resumed = bool(campaign)
            if new_outreach and not campaign:
                cid = uid()
                self.execute('INSERT INTO campaign(id,target,kind,status) VALUES(%s,%s,%s,%s)', [cid,target,'real' if real else 'dry','active'])
                campaign = self.one('SELECT * FROM campaign WHERE id=%s', [cid])
            iid = uid()
            self.execute('INSERT INTO invocation(id,campaign_id,mode) VALUES(%s,%s,%s)', [iid,campaign['id'] if campaign else None,mode])
            if campaign and new_outreach:
                # Reuse unsent preparation inventory from completed/dry campaigns, never successes.
                self.execute("UPDATE message SET campaign_id=%s WHERE sequence=0 AND status IN ('queued','retry') AND campaign_id IN (SELECT id FROM campaign WHERE status IN ('complete','dry_run') OR kind='dry')", [campaign['id']])
            return iid, campaign, resumed

    def count_sent(self, cid):
        return self.one("SELECT count(*) AS n FROM message WHERE campaign_id=%s AND sequence=0 AND status='sent'", [cid])['n']

    def event(self, iid, kind, payload):
        self.execute('INSERT INTO event(invocation_id,kind,payload) VALUES(%s,%s,%s)', [iid,kind,j(payload)])

    def suppress(self, email, kind):
        self.execute('INSERT INTO suppression(email,kind) VALUES(%s,%s) ON CONFLICT(email) DO UPDATE SET kind=EXCLUDED.kind', [email,kind])
        self.execute("UPDATE message SET status='cancelled',last_error=%s WHERE lead_id IN (SELECT id FROM lead WHERE email=%s) AND status IN ('queued','retry')", [kind,email])

    def review(self, mid, resolution, delays, sent_at=None, evidence='operator verification'):
        row = self.one("SELECT * FROM message WHERE id=%s AND status='review'", [mid])
        if not row:
            raise RuntimeError('Message is not in review')
        if resolution == 'not-sent':
            self.execute("UPDATE message SET status='retry',next_retry=now(),last_error='Operator verified non-delivery',error_kind=NULL,draft_attempts=CASE WHEN body IS NULL THEN 0 ELSE draft_attempts END WHERE id=%s", [mid])
        else:
            self.accept(mid, delays, sent_at)
        self.event(None, 'operator_delivery_resolution', {'message':mid,'resolution':resolution,'evidence':evidence})

    def accept(self, mid, delays, sent_at=None):
        with self.tx():
            row = self.one("UPDATE message SET status='sent',sent_at=COALESCE(%s,now()),lease_until=NULL,next_retry=NULL,last_error=NULL,error_kind=NULL,updated_at=now() WHERE id=%s AND status IN ('sending','review') RETURNING *", [sent_at,mid])
            if not row:
                return
            self.execute("UPDATE attempt SET status='sent',finished_at=now() WHERE message_id=%s AND number=%s", [mid,row['attempts']])
            self.ensure_next(row, delays)

    def ensure_next(self, row, delays):
        from .providers import stable_id
        if row['sequence'] == 3:
            return
        if self.one('SELECT 1 FROM suppression s JOIN lead l ON l.email=s.email WHERE l.id=%s', [row['lead_id']]):
            return
        seq = row['sequence']+1
        refs = row['refs']+[row['message_id']]
        self.execute('INSERT INTO message(id,lead_id,campaign_id,sequence,predecessor_id,sender_id,in_reply_to,refs,due_at) '
                     "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s + (%s * interval '1 second')) ON CONFLICT(lead_id,sequence) DO NOTHING",
                     [stable_id('message',row['lead_id'],seq),row['lead_id'],row['campaign_id'],seq,row['id'],row['sender_id'],row['message_id'],j(refs),row['sent_at'],delays[seq-1]])

    def metrics(self, cid):
        states = self.all('SELECT status,sequence,count(*) AS n FROM message WHERE campaign_id=%s GROUP BY status,sequence', [cid]) if cid else []
        return {'successful_initial_sends':self.count_sent(cid) if cid else 0,'message_states':states}
