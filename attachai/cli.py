"""Safe command entry points; credentials never appear in exception output."""
from __future__ import annotations

import argparse
import os
import re
from datetime import datetime, timezone
from urllib.parse import quote, unquote

from .config import load_config, load_secrets, parse_bool
from .db import OperationalError, Store
from .engine import Engine, log
from .providers import Discovery, LLM, Mailbox, Research, SMTP
from .scheduling import due_slots


class ControlError(ValueError):
    pass


def controls(path,overrides):
    try:
        return load_config(path,overrides)
    except ValueError as exc:
        raise ControlError(str(exc)) from None


def credentials(config):
    try:
        return load_secrets(config)
    except ValueError as exc:
        raise ControlError(str(exc)) from None


def safe_exception(exc, secrets=None):
    """Return useful failure detail after removing secrets and personal data."""
    value = str(exc) or type(exc).__name__
    possible_secrets = [os.environ.get(name, '') for name in (
        'DATABASE_URL', 'GOOGLE_PLACES_API_KEY', 'LLM_API_KEY', 'SENDER_ACCOUNTS_JSON'
    )]
    database_url = os.environ.get('DATABASE_URL', '')
    if secrets is not None:
        database_url = secrets.database_url
    if database_url:
        try:
            from urllib.parse import unquote, urlsplit
            parsed = urlsplit(database_url)
            possible_secrets.extend(unquote(value) for value in (parsed.username, parsed.password) if value)
            possible_secrets.extend(value for value in (parsed.username, parsed.password) if value)
        except ValueError:
            pass
    if secrets is not None:
        possible_secrets.extend((secrets.database_url, secrets.places_key, secrets.llm_key))
        for sender in secrets.senders:
            possible_secrets.extend((sender.password, sender.imap_password or '', sender.email))
    for item in sorted((s for s in possible_secrets if s), key=len, reverse=True):
        for variant in {item, quote(item, safe=''), unquote(item)}:
            if variant:
                value = value.replace(variant, '[REDACTED]')
    # Also mask URLs/credential-like fields that were not exact environment values.
    value = re.sub(r'(?i)postgres(?:ql)?://[^\s\"\']+', '[DATABASE_URL]', value)
    value = re.sub(r'(?i)\b(password|passwd|token|api[_-]?key|authorization)\b\s*[:=]\s*[^,\s;]+', r'\1=[REDACTED]', value)
    value = re.sub(r'(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b', '[EMAIL]', value)
    value = ''.join(ch if ch in '\n\t' or ord(ch) >= 32 else ' ' for ch in value)
    return value[:800]


def parser():
    p = argparse.ArgumentParser(description='AttachAI durable outreach coordinator')
    p.add_argument('--config', default='monitor.yaml')
    commands = p.add_subparsers(dest='command', required=True)
    commands.add_parser('migrate')
    commands.add_parser('scheduled')
    commands.add_parser('diagnose', aliases=['diagnostic'], help='Read-only configuration and database connectivity checks')
    run = commands.add_parser('run')
    run.add_argument('--reset-state', type=parse_bool, default=False)
    run.add_argument('--target-new-initials', type=int)
    for name in ('send-enabled','dry-run','process-followups','process-new-outreach'):
        run.add_argument('--'+name, type=parse_bool, default=None)
    review = commands.add_parser('review')
    review.add_argument('--message-id', required=True, help='Internal message ID from the review queue')
    review.add_argument('--resolution', choices=('sent','not-sent'), required=True)
    review.add_argument('--confirm', action='store_true')
    review.add_argument('--evidence', required=True, help='Operator reference for verified delivery/non-delivery; do not include secrets')
    review.add_argument('--sent-at', help='Verified SMTP acceptance time in ISO-8601 with timezone (required for sent)')
    return p


def main(argv=None):
    stage = 'argument parsing'
    store = None
    secrets = None
    try:
        args = parser().parse_args(argv)
        stage = 'configuration validation'
        overrides = {key:getattr(args,key,None) for key in ('target_new_initials','send_enabled','dry_run','process_followups','process_new_outreach')} if args.command=='run' else {}
        if args.command in ('migrate','review','diagnose','diagnostic'):
            overrides.update(process_followups=False,process_new_outreach=False,send_enabled=False,dry_run=True)
        config = controls(args.config,overrides)
        if config.data['safety']['emergency_stop'] and args.command in ('run','scheduled'):
            log('SKIPPED',reason='Emergency stop is enabled; no campaign state changed')
            return 0
        slots = None
        if args.command=='scheduled':
            if not config.data['automation']['enabled']:
                log('SKIPPED',reason='Automatic execution is disabled')
                return 0
            slots = due_slots(config.data,datetime.now(timezone.utc))
            if not slots:
                log('SKIPPED',reason='No schedule is due')
                return 0
            config = controls(args.config,{'process_new_outreach':'outreach' in slots,'process_followups':'followups' in slots})
        stage = 'secret validation'
        if args.command in ('diagnose','diagnostic'):
            try:
                secrets = load_secrets(config, validate_all=True)
            except ValueError as exc:
                raise ControlError(str(exc)) from None
        else:
            secrets = credentials(config)
        stage = 'database connection'
        store = Store(secrets.database_url, read_only=True) if args.command in ('diagnose','diagnostic') else Store(secrets.database_url)
        if args.command in ('diagnose','diagnostic'):
            stage = 'read-only database diagnostic'
            result = store.diagnose()
            if result.get('migration_blocked'):
                log('DIAGNOSTIC_BLOCKED', configuration='valid', secrets='format_valid',
                    reason='Read-only checks found an unsafe schema state; inspect block_reasons and legacy_tables before migrating', **result)
                return 2
            log('DIAGNOSTIC_OK',configuration='valid',secrets='format_valid',**result)
            return 0
        stage = 'database advisory lock acquisition'
        store.acquire()
        stage = 'database migration'
        store.migrate()
        if args.command=='migrate':
            applied = store.all('SELECT version FROM schema_version ORDER BY version')
            log('MIGRATED',schema='attachai',versions=[r['version'] for r in applied])
            return 0
        if args.command=='review':
            stage = 'operator review validation'
            if not args.confirm or not args.evidence.strip() or len(args.evidence)>500:
                raise ControlError('Review requires explicit confirmation and a short operator evidence reference')
            sent_at = None
            if args.resolution=='sent':
                if not args.sent_at:
                    raise ControlError('Verified sent resolution requires --sent-at')
                try:
                    sent_at = datetime.fromisoformat(args.sent_at.replace('Z','+00:00'))
                except ValueError:
                    raise ControlError('Verified acceptance time must be valid ISO-8601') from None
                if sent_at.tzinfo is None or sent_at > datetime.now(timezone.utc):
                    raise ControlError('Verified acceptance time must be timezone-aware and not in the future')
            stage = 'operator review persistence'
            store.reconcile()
            store.review(args.message_id,args.resolution,config.data['followups']['delays_seconds'],sent_at,args.evidence.strip())
            log('REVIEW_RESOLVED',message=args.message_id,resolution=args.resolution)
            return 0
        if slots is not None:
            slots = {kind:slot for kind,slot in slots.items() if not store.one('SELECT 1 FROM schedule_slot WHERE kind=%s AND slot=%s',[kind,slot])}
            if not slots:
                log('SKIPPED',reason='Due schedule slots were already claimed')
                return 0
            config = controls(args.config,{'process_new_outreach':'outreach' in slots,'process_followups':'followups' in slots})
        stage = 'campaign execution'
        engine = Engine(config,store,secrets,Discovery(config,secrets),Research(config),LLM(config,secrets),SMTP(config),Mailbox(config))
        code,_ = engine.run(reset=getattr(args,'reset_state',False),slots=slots)
        return code
    except (ControlError,OperationalError) as exc:
        log('CONFIGURATION_OR_STATE_ERROR',stage=stage,reason=safe_exception(exc,secrets))
        return 1
    except Exception as exc:
        log('ERROR',stage=stage,error_type=type(exc).__name__,reason=safe_exception(exc,secrets))
        return 1
    finally:
        if store is not None:
            try:
                store.close()
            except Exception as exc:
                log('CLOSE_WARNING',stage='database connection close',reason=safe_exception(exc,secrets))


if __name__=='__main__':
    raise SystemExit(main())
