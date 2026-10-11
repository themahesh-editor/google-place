"""Safe command entry points; credentials never appear in exception output."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

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


def parser():
    p = argparse.ArgumentParser(description='AttachAI durable outreach coordinator')
    p.add_argument('--config', default='monitor.yaml')
    commands = p.add_subparsers(dest='command', required=True)
    commands.add_parser('migrate')
    commands.add_parser('scheduled')
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
    args = parser().parse_args(argv)
    store = None
    try:
        overrides = {key:getattr(args,key,None) for key in ('target_new_initials','send_enabled','dry_run','process_followups','process_new_outreach')} if args.command=='run' else {}
        if args.command in ('migrate','review'):
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
        secrets = credentials(config)
        store = Store(secrets.database_url)
        store.acquire()
        store.migrate()
        if args.command=='migrate':
            log('MIGRATED',schema='attachai',version=1)
            return 0
        if args.command=='review':
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
        engine = Engine(config,store,secrets,Discovery(config,secrets),Research(config),LLM(config,secrets),SMTP(config),Mailbox(config))
        code,_ = engine.run(reset=getattr(args,'reset_state',False),slots=slots)
        return code
    except (ControlError,OperationalError) as exc:
        log('CONFIGURATION_OR_STATE_ERROR',reason=str(exc))
        return 1
    except Exception as exc:
        # Even driver/network/config errors may carry passwords; print only the class.
        log('ERROR',error_type=type(exc).__name__,reason='Execution failed. Check configuration, provider connectivity and durable event/review records. Credentials are intentionally not printed.')
        return 1
    finally:
        if store is not None:
            store.close()


if __name__=='__main__':
    raise SystemExit(main())
