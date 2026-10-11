from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

from .config import Settings
from .db import Store
from .discovery import DiscoveryService
from .llm import LLMClient
from .mailer import BatchSendController
from .mailbox import MailboxMonitor
from .monitor import automatic_run_flags
from .personalization import PersonalizationGenerator
from .research import ResearchService, WebsiteCrawler
from .orchestrator import Orchestrator


def parse_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def build(settings: Settings, store: Store) -> Orchestrator:
    llm = LLMClient(os.environ.get("NVIDIA_API_KEY", ""), settings.llm_base_url, settings.llm_model, settings.llm_timeout_seconds, max_retries=settings.retry_limit, backoff_seconds=max(1, settings.retry_base_seconds))
    crawler = WebsiteCrawler(settings.crawler_timeout_seconds, settings.crawler_max_bytes, settings.crawler_max_pages, settings.crawler_request_delay_seconds, settings.honor_robots)
    discovery = DiscoveryService(store, llm, crawler, settings)
    research = ResearchService(store, llm, crawler)
    personalization = PersonalizationGenerator(llm, settings.min_personalization_confidence, settings.personalization_retry_limit)
    mailer = BatchSendController(store, settings)
    mailbox = MailboxMonitor(store, settings)
    return Orchestrator(settings, store, discovery, research, personalization, mailer, mailbox)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AttachAI durable outreach runner")
    parser.add_argument("--monitor", default="monitor.yaml")
    parser.add_argument("--automatic", action="store_true", help="Honor monitor.yaml automation schedules")
    parser.add_argument("--reset-state", default=None)
    parser.add_argument("--target-new-initials", type=int, default=None)
    parser.add_argument("--send-enabled", default=None)
    parser.add_argument("--dry-run", default=None)
    parser.add_argument("--process-followups", default=None)
    parser.add_argument("--process-new-outreach", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    overrides = {}
    if args.reset_state is not None:
        overrides["reset_state"] = parse_bool(args.reset_state)
    if args.target_new_initials is not None:
        overrides["target_new_initials"] = args.target_new_initials
    if args.send_enabled is not None:
        overrides["send_enabled"] = parse_bool(args.send_enabled)
    if args.dry_run is not None:
        overrides["dry_run"] = parse_bool(args.dry_run)

    settings = Settings.from_monitor(args.monitor, overrides)
    store = Store(os.environ["SUPABASE_DB_URL"])
    try:
        store.migrate("migrations")
        if args.automatic:
            should_run, followups_due, outreach_due = automatic_run_flags(settings, store)
            if not should_run:
                print("AUTOMATION_NOT_DUE", flush=True)
                return 0
            process_followups = followups_due
            process_new_outreach = outreach_due
            store.set_automation_last_trigger("followups", datetime.now(timezone.utc)) if followups_due else None
            store.set_automation_last_trigger("outreach", datetime.now(timezone.utc)) if outreach_due else None
        else:
            process_followups = parse_bool(args.process_followups) if args.process_followups is not None else True
            process_new_outreach = parse_bool(args.process_new_outreach) if args.process_new_outreach is not None else True

        resolved_followups = process_followups and settings.followups_enabled
        resolved_outreach = process_new_outreach and settings.outreach_enabled
        settings.validate_runtime_environment(
            process_new_outreach=resolved_outreach,
            process_followups=resolved_followups,
            send_enabled=bool(overrides.get("send_enabled", settings.send_enabled)),
        )
        orchestrator = build(settings, store)
        code, metrics = orchestrator.run(
            reset_state=bool(overrides.get("reset_state", False)),
            target=int(overrides.get("target_new_initials", settings.target_new_initials)),
            send_enabled=bool(overrides.get("send_enabled", settings.send_enabled)),
            dry_run=bool(overrides.get("dry_run", settings.dry_run)),
            process_followups=resolved_followups,
            process_new_outreach=resolved_outreach,
        )
        print(f"ATTACHAI_EXIT code={code} status={metrics.get('run_status')} successful_initial_sends={metrics.get('successful_initial_sends')} remaining_target={metrics.get('remaining_target')}", flush=True)
        return code
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
