from __future__ import annotations

import argparse

from app.config import Settings
from app.db import Store
from app.discovery import DiscoveryService
from app.llm import LLMClient
from app.mailer import BatchSendController
from app.orchestrator import Orchestrator
from app.personalization import PersonalizationGenerator
from app.research import ResearchService, WebsiteCrawler


def build(settings: Settings, store: Store):
    llm = LLMClient(settings.llm_base_url, settings.llm_model, settings.llm_timeout_seconds, settings.llm_max_tokens)
    crawler = WebsiteCrawler(settings.crawler_timeout_seconds, settings.crawler_max_bytes, settings.crawler_max_pages, settings.crawler_request_delay_seconds, settings.honor_robots)
    discovery = DiscoveryService(store, llm, crawler, settings)
    research = ResearchService(store, llm, crawler, "2.0")
    personalization = PersonalizationGenerator(llm)
    mailer = BatchSendController(store, settings)
    return Orchestrator(settings, store, discovery, research, personalization, mailer)


def parse_bool(value: str) -> bool:
    value = str(value).strip().lower()
    if value in {"1", "true", "yes", "on"}: return True
    if value in {"0", "false", "no", "off"}: return False
    raise argparse.ArgumentTypeError("expected true or false")


def main() -> int:
    parser = argparse.ArgumentParser(description="AttachAI single-runner production orchestrator")
    parser.add_argument("--reset-state", type=parse_bool, default=None)
    parser.add_argument("--initial-target", type=int, default=None)
    parser.add_argument("--send-enabled", type=parse_bool, default=None)
    parser.add_argument("--dry-run", type=parse_bool, default=None)
    args = parser.parse_args()

    settings = Settings.from_env()
    reset = settings.reset_state if args.reset_state is None else args.reset_state
    target = settings.initial_outreach_target if args.initial_target is None else args.initial_target
    send_enabled = settings.send_enabled if args.send_enabled is None else args.send_enabled
    dry_run = settings.dry_run if args.dry_run is None else args.dry_run

    store = Store(settings.supabase_db_url)
    try:
        orchestrator = build(settings, store)
        metrics = orchestrator.run(reset_state=reset, target=target, send_enabled=send_enabled, dry_run=dry_run)
        return 0 if metrics["target_status"] == "TARGET REACHED" or dry_run else 1
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
