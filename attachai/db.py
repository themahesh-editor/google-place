from __future__ import annotations

import json
import re
import uuid
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import unquote, urlsplit

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

    def __init__(self, url, *, read_only=False):
        self.url = url
        options = "-c statement_timeout=10000 -c lock_timeout=2000" if read_only else "-c lock_timeout=10000"
        if read_only:
            # The database itself enforces the diagnostic's read-only boundary.
            options += " -c default_transaction_read_only=on"
        self.conn = psycopg.connect(
            url,
            connect_timeout=10,
            application_name="attachai-diagnostic" if read_only else "attachai",
            options=options,
            autocommit=True,
            row_factory=dict_row,
            prepare_threshold=None,
        )
        self.conn.execute("SET timezone TO 'UTC'")
        self.locked = False
        self.read_only = read_only

    def close(self):
        self.conn.close()  # session close releases advisory lock even after a crash

    def acquire(self):
        if self.read_only:
            raise OperationalError('Read-only diagnostic connections cannot acquire campaign locks')
        if not self.one('SELECT pg_try_advisory_lock(%s) AS ok', [LOCK_ID])['ok']:
            raise OperationalError('Another AttachAI execution owns the database lock')
        self.locked = True

    def diagnose(self):
        """Run bounded, read-only connectivity and migration-state checks.

        This method deliberately does not acquire advisory locks, set search_path,
        run SQL files, reconcile work, or write event/audit records.
        """
        if not self.read_only:
            raise OperationalError('Read-only diagnostic requires a read-only database connection')
        self.one('SELECT 1 AS ok')

        block_reasons = []
        legacy_tables = {}
        for table in ('outreach', 'suppression'):
            exists = self.one('SELECT to_regclass(%s) AS name', ['public.' + table])['name']
            if not exists:
                legacy_tables[table] = 'absent'
                continue
            from psycopg import sql
            populated = self.one(sql.SQL('SELECT 1 FROM public.{} LIMIT 1').format(sql.Identifier(table)))
            legacy_tables[table] = 'populated' if populated else 'empty'
        if any(state == 'populated' for state in legacy_tables.values()):
            block_reasons.append('populated_legacy_tables')

        row = self.one("SELECT to_regclass('attachai.schema_version') AS name")
        schema_objects = self.one("SELECT EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='attachai') AS present")['present']
        files = sorted(
            ((int(match.group(1)), path) for path in (Path(__file__).resolve().parent.parent / 'migrations').glob('[0-9][0-9][0-9]_*.sql')
             if (match := re.match(r'^(\d{3})_', path.name))),
            key=lambda item: item[0],
        )
        versions = [version for version, _ in files]
        if not versions or versions != list(range(1, len(versions) + 1)):
            raise OperationalError('Migration files must be numbered consecutively from 001')
        if not row['name']:
            if schema_objects:
                block_reasons.append('partial_schema_without_migration_history')
                schema_status = 'partial'
            else:
                schema_status = 'not_initialized'
            return {
                'database': 'reachable',
                'schema': schema_status,
                'applied_versions': [],
                'pending_versions': versions,
                'read_only': True,
                'legacy_tables': legacy_tables,
                'migration_blocked': bool(block_reasons),
                'block_reasons': block_reasons,
            }

        applied = [r['version'] for r in self.all('SELECT version FROM attachai.schema_version ORDER BY version')]
        if not applied or applied != list(range(1, max(applied) + 1)):
            raise OperationalError('Database migration history is empty or contains a version gap')
        if max(applied) > versions[-1]:
            raise OperationalError('Database schema is newer than this application; use a compatible release')
        required_relations = ('campaign', 'invocation', 'sender', 'candidate', 'research_cache', 'lead',
                              'draft', 'batch', 'message', 'attempt', 'suppression', 'mailbox_cursor',
                              'inbound', 'schedule_slot', 'event', 'discovery_cursor')
        missing_relations = [name for name in required_relations
                             if not self.one('SELECT to_regclass(%s) AS name', ['attachai.' + name])['name']]
        if missing_relations:
            block_reasons.append('missing_schema_relations')
        return {
            'database': 'reachable',
            'schema': 'initialized',
            'applied_versions': applied,
            'pending_versions': [version for version in versions if version not in applied],
            'missing_relations': missing_relations,
            'read_only': True,
            'legacy_tables': legacy_tables,
            'migration_blocked': bool(block_reasons),
            'block_reasons': block_reasons,
        }

    def migrate(self):
        if self.read_only:
            raise OperationalError('Read-only diagnostic connections cannot run migrations')
        if not self.locked:
            raise OperationalError('Database lock required before migration')
        # This rewrite cannot silently discard legacy contact history. A populated
        # old deployment needs an explicit audited data migration, not a fresh queue.
        for table in ('outreach','suppression'):
            if self.one('SELECT to_regclass(%s) AS name',['public.'+table])['name']:
                from psycopg import sql
                if self.one(sql.SQL('SELECT 1 FROM public.{} LIMIT 1').format(sql.Identifier(table))):
                    raise OperationalError('Populated legacy AttachAI tables detected. Back up and perform an audited history migration before real operation; this replacement does not silently restart old contacts.')
        migration_dir = Path(__file__).resolve().parent.parent / 'migrations'
        files = sorted(
            ((int(match.group(1)), path) for path in migration_dir.glob('[0-9][0-9][0-9]_*.sql')
             if (match := re.match(r'^(\d{3})_', path.name))),
            key=lambda item: item[0],
        )
        versions = [version for version, _ in files]
        if not files or versions != list(range(1, len(versions) + 1)):
            raise OperationalError('Migration files must be numbered consecutively from 001')
        exists = self.one("SELECT to_regclass('attachai.schema_version') AS name")['name']
        if not exists:
            partial = self.one("SELECT EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='attachai') AS present")['present']
            if partial:
                raise OperationalError('Partial AttachAI schema detected without migration history. Back up and audit it before proceeding.')
            applied = []
        else:
            applied = [r['version'] for r in self.all('SELECT version FROM attachai.schema_version ORDER BY version')]
            if not applied or applied != list(range(1, max(applied) + 1)):
                raise OperationalError('Database migration history is empty or contains a version gap')
        if applied and max(applied) > versions[-1]:
            raise OperationalError('Database schema is newer than this application; use a compatible release')
        for version, path in files:
            if version in applied:
                continue
            expected = (max(applied) + 1) if applied else 1
            if version != expected:
                raise OperationalError(f'Migration history expects version {expected}, found {version}')
            migration = path.read_text(encoding='utf-8')
            try:
                with self.conn.transaction():
                    self.conn.execute(migration, prepare=False)
            except Exception as exc:
                # Keep the actionable database reason, but never echo the connection URL.
                detail = str(exc).replace(self.url, '[DATABASE_URL]')
                try:
                    parsed_url = urlsplit(self.url)
                    for secret in (parsed_url.username, parsed_url.password):
                        if secret:
                            for variant in {secret, unquote(secret)}:
                                detail = detail.replace(variant, '[REDACTED]')
                except ValueError:
                    detail = f'{type(exc).__name__} (details redacted)'
                detail = re.sub(r'(?i)postgres(?:ql)?://[^\s"\']+', '[DATABASE_URL]', detail)
                detail = re.sub(r'(?i)(password|passwd|token|api[_-]?key)\s*[:=]\s*[^,\s;]+', r'\1=[REDACTED]', detail)
                detail = ''.join(ch if ch in '\n\t' or ord(ch) >= 32 else ' ' for ch in detail)[:500]
                raise OperationalError(f'Migration {path.name} failed: {detail}; transaction rolled back') from None
            applied.append(version)
        self.conn.execute('SET search_path TO attachai, public')
        current = self.all('SELECT version FROM schema_version ORDER BY version')
        current_versions = [r['version'] for r in current]
        if current_versions != versions:
            raise OperationalError('Database schema version does not match the installed migration set')

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
        if self.read_only:
            raise OperationalError('Read-only diagnostic connections cannot reset state')
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
        with self.tx():
            row = self.one("SELECT * FROM message WHERE id=%s AND status='review' FOR UPDATE", [mid])
            if not row:
                raise RuntimeError('Message is not in review')
            if resolution == 'not-sent':
                self.execute("UPDATE message SET status='retry',next_retry=now(),last_error='Operator verified non-delivery',error_kind=NULL,draft_attempts=CASE WHEN body IS NULL THEN 0 ELSE draft_attempts END WHERE id=%s", [mid])
            else:
                self.accept(mid, delays, sent_at)
            self.event(None, 'operator_delivery_resolution', {'message':mid,'resolution':resolution,'evidence':evidence})

    def accept(self, mid, delays, sent_at=None, invocation_id=None):
        with self.tx():
            row = self.one("UPDATE message SET status='sent',sent_at=COALESCE(%s,now()),lease_until=NULL,next_retry=NULL,last_error=NULL,error_kind=NULL,updated_at=now() WHERE id=%s AND status IN ('sending','review') RETURNING *", [sent_at,mid])
            if not row:
                return False
            self.execute("UPDATE attempt SET status='sent',finished_at=now() WHERE message_id=%s AND number=%s", [mid,row['attempts']])
            self.ensure_next(row, delays)
            self.event(invocation_id, 'delivery_accepted', {'message':mid,'sequence':row['sequence']})
            return True

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
