from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Any

from .db import deterministic_outreach_id, now_utc, iso_utc
from .debug import debug, log
from .models import RunMetrics


class Orchestrator:
    """Coordinates durable phases without making any phase's in-memory queue authoritative."""

    def __init__(self, settings, store, discovery, research, personalization, mailer, mailbox):
        self.settings = settings
        self.store = store
        self.discovery = discovery
        self.research = research
        self.personalization = personalization
        self.mailer = mailer
        self.mailbox = mailbox

    def run(self, *, reset_state: bool, target: int, send_enabled: bool, dry_run: bool, process_followups: bool, process_new_outreach: bool) -> tuple[int, dict[str, Any]]:
        if target < 1:
            raise ValueError("target_new_initials must be >= 1")
        started = time.monotonic()
        if reset_state:
            self.store.reset_runtime_state()
        if not self.store.try_acquire_run_lock():
            raise RuntimeError("Another production AttachAI run is already active")

        mode = self._mode(process_followups, process_new_outreach)
        workflow_id = campaign_id = None
        metrics = RunMetrics()
        try:
            recovery = self.store.reconcile_startup(
                sending_stale_minutes=self.settings.smtp_sending_lease_minutes,
                research_stale_minutes=self.settings.research_lease_minutes,
                personalization_stale_minutes=self.settings.research_lease_minutes,
            )
            workflow_id, campaign_id, resumed = self.store.start_workflow(mode, reset_state, target)
            self.store.add_event("workflow_start", run_id=workflow_id, campaign_id=campaign_id, metadata={"target_new_initials": target, "resumed_campaign": resumed, "send_enabled": send_enabled, "dry_run": dry_run})
            log("START", workflow_run_id=workflow_id, campaign_run_id=campaign_id, mode=mode, target_new_initials=target, resumed_campaign=resumed, recovery=recovery)

            if process_followups:
                self._run_followups(workflow_id, campaign_id, metrics)

            if process_new_outreach:
                blocked_reason = self._run_new_outreach(workflow_id, campaign_id, target, send_enabled=send_enabled, dry_run=dry_run, metrics=metrics)
                if blocked_reason:
                    metrics.notes.append(blocked_reason)

            successful = self.store.successful_initial_count(campaign_id)
            metrics.successful_initial_sends = successful
            metrics.remaining_target = max(0, target - successful if target else 0)
            metrics.run_status = self._result_status(target, successful, send_enabled, dry_run, process_new_outreach)
            if successful >= target:
                self.store.finish_campaign(campaign_id, blocked=False)
                exit_code = 0
                workflow_status = "SUCCESS"
            elif dry_run:
                self.store.finish_campaign(campaign_id, blocked=False, reason="dry_run_does_not_count_as_sent")
                exit_code = 0
                workflow_status = "DRY_RUN"
            elif not process_new_outreach:
                self.store.finish_campaign(campaign_id, blocked=False, reason="new_outreach_disabled_for_this_run")
                exit_code = 0
                workflow_status = "PREP_ONLY"
            else:
                reason = metrics.notes[-1] if metrics.notes else "new initial target not reached"
                self.store.finish_campaign(campaign_id, blocked=True, reason=reason)
                exit_code = 2
                workflow_status = "TARGET_NOT_REACHED"

            self._finalize_metrics(metrics, workflow_id, campaign_id, started, workflow_status)
            self.store.finish_workflow(workflow_id, workflow_status, metrics.as_dict())
            self.store.add_event("workflow_finish", run_id=workflow_id, campaign_id=campaign_id, status=workflow_status, metadata=metrics.as_dict())
            log("FINAL_SUMMARY", workflow_run_id=workflow_id, campaign_run_id=campaign_id, **metrics.as_dict())
            return exit_code, metrics.as_dict()
        except Exception as exc:
            if workflow_id:
                self.store.finish_workflow(workflow_id, "FAILED", {"error": str(exc)[:1000], **metrics.as_dict()})
            raise
        finally:
            self.store.release_run_lock()

    @staticmethod
    def _mode(followups: bool, new_outreach: bool) -> str:
        if followups and new_outreach:
            return "FULL"
        if followups:
            return "FOLLOWUPS_ONLY"
        if new_outreach:
            return "NEW_OUTREACH_ONLY"
        return "RESUME_RECOVERY"

    @staticmethod
    def _result_status(target: int, successful: int, send_enabled: bool, dry_run: bool, process_new_outreach: bool) -> str:
        if successful >= target:
            return "SUCCESS"
        if dry_run:
            return "DRY_RUN"
        if not process_new_outreach:
            return "PREP_ONLY"
        return "TARGET_NOT_REACHED"

    def _run_followups(self, workflow_id: str, campaign_id: str, metrics: RunMetrics) -> None:
        stage_started = time.monotonic()
        totals = self.mailbox.run_all(self.settings.sender_configs())
        metrics.replies += totals.get("replies", 0)
        metrics.bounces += totals.get("bounces", 0)
        metrics.unsubscribes += totals.get("unsubscribes", 0)
        log("MAILBOX_SYNC", workflow_run_id=workflow_id, **totals)
        due = self.store.list_queued_followups(limit=100)
        if not due:
            metrics.stage_seconds["followups"] = round(time.monotonic() - stage_started, 3)
            return

        rows: list[Any] = []
        sender_by_id = {s.sender_id: s for s in self.settings.sender_configs()}
        for row in due:
            lead = self.store.get_lead(row["lead_id"])
            if not lead or self.store.is_suppressed(lead["email"]):
                self.store.mark_review_needed(row["outreach_id"], "lead suppressed before follow-up generation")
                continue
            previous = self.store.previous_successful(lead["lead_id"])
            if not previous or previous["outreach_id"] == row["outreach_id"]:
                continue
            # Strict chain guard: previous successful sequence must be exactly the immediately preceding stage.
            required_previous = {"FOLLOWUP_1": "INITIAL", "FOLLOWUP_2": "FOLLOWUP_1", "FOLLOWUP_3": "FOLLOWUP_2"}.get(row["sequence_type"])
            if required_previous and previous["sequence_type"] != required_previous:
                continue
            research = self.store.latest_research(lead["lead_id"])
            if not research:
                continue
            research_obj, pages = self._research_payload(research)
            history = self.store.fetchall("SELECT sequence_type,subject,body,smtp_message_id,sent_at_utc FROM outreach WHERE lead_id=? AND status='SENT' ORDER BY sent_at_utc", [lead["lead_id"]])
            sender = sender_by_id.get(row["sender_id"])
            if not sender:
                self.store.mark_review_needed(row["outreach_id"], "previous sender is no longer configured")
                continue
            try:
                draft, validation, repairs = self.personalization.generate(dict(lead), research_obj, pages, [dict(x) for x in history], row["sequence_type"], sender.email)
                self.store.save_personalization(lead_id=lead["lead_id"], campaign_id=campaign_id, outreach_id=row["outreach_id"], sequence_type=row["sequence_type"], payload=draft.payload(), validation_valid=validation.valid, validation_error="; ".join(validation.reasons), attempts=repairs)
                if not validation.valid:
                    self.store.mark_review_needed(row["outreach_id"], "personalization validation: " + "; ".join(validation.reasons))
                    continue
                evidence_urls = [e.url for e in validation.normalized_evidence]
                refs = ((previous["references_text"] or "").strip() + " " + (previous["smtp_message_id"] or "")).strip()
                self.store.queue_followup_draft(row["outreach_id"], draft.subject, draft.body, evidence_urls, draft.confidence, previous["smtp_message_id"], refs)
                metrics.followups_generated += 1
                metrics.ready += 1
                rows.append(self.store.get_outreach(row["outreach_id"]))
            except Exception as exc:
                self.store.mark_review_needed(row["outreach_id"], f"follow-up generation failed: {exc}")
                self.store.add_event("followup_generation_failed", run_id=workflow_id, campaign_id=campaign_id, lead_id=lead["lead_id"], outreach_id=row["outreach_id"], reason=str(exc)[:500])

        self._send_rows(workflow_id, campaign_id, rows, batch_type="FOLLOWUP", send_enabled=self.settings.send_enabled and not self.settings.emergency_stop and not self.settings.dry_run, dry_run=self.settings.dry_run, metrics=metrics)
        metrics.stage_seconds["followups"] = round(time.monotonic() - stage_started, 3)

    @staticmethod
    def _research_payload(research_row: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        obj = json.loads(research_row["research_json"] or "{}")
        pages = json.loads(research_row["pages_json"] or "[]")
        return obj, pages

    def _run_new_outreach(self, workflow_id: str, campaign_id: str, target: int, *, send_enabled: bool, dry_run: bool, metrics: RunMetrics) -> str | None:
        stage_started = time.monotonic()
        allow_real_send = bool(send_enabled and not dry_run and not self.settings.emergency_stop)
        blocked_reason: str | None = None
        loop_guard = 0
        discovery_requests_used_total = 0
        replenishment_rounds = 0
        max_replenishment_rounds = max(1, min(100, self.settings.max_candidates_per_run))
        while True:
            loop_guard += 1
            successful = self.store.successful_initial_count(campaign_id)
            remaining = max(0, target - successful)
            metrics.successful_initial_sends = successful
            metrics.remaining_target = remaining
            if remaining == 0:
                break
            if loop_guard > 1000:
                blocked_reason = "orchestrator loop guard reached; durable queue state was unchanged"
                break
            if replenishment_rounds >= max_replenishment_rounds and not self.store.list_ready_initials(campaign_id, limit=1):
                blocked_reason = "replenishment round budget exhausted before the new-initial target was reached"
                break

            ready = self.store.list_ready_initials(campaign_id, limit=10)
            if ready:
                if dry_run or not allow_real_send:
                    metrics.queued += len(ready)
                    metrics.notes.append("dry/disabled send mode: prepared messages remain QUEUED")
                    break
                batch_result = self._send_rows(workflow_id, campaign_id, ready, batch_type="INITIAL", send_enabled=True, dry_run=False, metrics=metrics)
                if batch_result == 0:
                    # A batch can have zero successes when all senders fail. Replenish/retry instead of cycling the same rows.
                    ready_after = self.store.list_ready_initials(campaign_id, 10)
                    if ready_after and len(ready_after) == len(ready):
                        blocked_reason = "send batch produced no progress; failures were isolated and queued/retryable state is durable"
                        if not any(r["status"] == "FAILED_RETRYABLE" for r in ready_after):
                            break
                    time.sleep(min(max(self.settings.retry_base_seconds, 1), 5))
                if self.settings.batch_gap_seconds:
                    time.sleep(self.settings.batch_gap_seconds)
                continue

            # Low inventory: discover replacements. This is the key anti-stall mechanism.
            pending = self.store.pending_initial_count(campaign_id)
            needed_inventory = max(remaining + self.settings.discovery_overage_buffer - pending, self.settings.batch_size)
            needed_inventory = min(needed_inventory, self.settings.max_candidates_per_run)
            if needed_inventory <= 0:
                blocked_reason = "no additional discovery inventory is required"
                break

            remaining_request_budget = max(0, self.settings.discovery_max_places_requests - discovery_requests_used_total)
            if remaining_request_budget <= 0:
                blocked_reason = "configured discovery provider request budget exhausted before the new-initial target was reached"
                break
            replenishment_rounds += 1
            discovery_result = self.discovery.discover_raw(workflow_id, needed_inventory, remaining_request_budget)
            discovery_requests_used_total += int(discovery_result.get("places_requests_used", 0))
            metrics.raw_candidates += int(discovery_result.get("raw_candidates", 0))
            metrics.deduplicated_candidates += int(discovery_result.get("deduplicated_candidates", 0))
            log("DISCOVERY_PROGRESS", workflow_run_id=workflow_id, remaining_target=remaining, **discovery_result)
            candidates = self.store.list_pending_candidates(min(needed_inventory, self.settings.max_candidates_per_run))
            if not candidates:
                if int(discovery_result.get("places_requests_used", 0)) <= 0 or discovery_requests_used_total >= self.settings.discovery_max_places_requests:
                    blocked_reason = "discovery/provider limits produced no new processable candidates"
                    break
                continue
            process_result = self.discovery.process_candidates(workflow_id, candidates, max_workers=self.settings.max_concurrency)
            metrics.qualified += process_result.get("qualified", 0)
            metrics.research_failed += process_result.get("retryable", 0)
            log("QUALIFICATION_PROGRESS", workflow_run_id=workflow_id, candidates=len(candidates), **process_result)
            lead_rows = self.store.fetchall(
                """SELECT l.* FROM lead l WHERE l.status='ELIGIBLE' AND NOT EXISTS (SELECT 1 FROM outreach o WHERE o.lead_id=l.lead_id AND o.sequence_type='INITIAL') AND NOT EXISTS (SELECT 1 FROM suppression s WHERE s.email=l.email) ORDER BY l.created_at_utc LIMIT ?""",
                [needed_inventory],
            )
            if not lead_rows:
                # Continue discovery, unless no provider budget remains.
                if discovery_requests_used_total >= self.settings.discovery_max_places_requests:
                    blocked_reason = "provider request budget exhausted before any lead became processable"
                    break
                continue
            prepared = self._prepare_leads(workflow_id, campaign_id, lead_rows, metrics)
            if prepared == 0:
                blocked_reason = "candidate inventory was consumed by research/personalization failures and discovery must replenish"
                continue
            log("QUEUE_PROGRESS", workflow_run_id=workflow_id, prepared=prepared, successful_initials=self.store.successful_initial_count(campaign_id), remaining_target=remaining)

        metrics.stage_seconds["new_outreach"] = round(time.monotonic() - stage_started, 3)
        return blocked_reason

    def _prepare_leads(self, workflow_id: str, campaign_id: str, leads: list[Any], metrics: RunMetrics) -> int:
        prepared = 0
        eligible = [dict(row) for row in leads]
        # Research is concurrent, DB writes remain in the coordinator thread for deterministic transitions.
        for lead in eligible:
            self.store.set_lead_status(lead["lead_id"], "RESEARCHING")
        def worker(lead: dict[str, Any]):
            try:
                research_obj, pages = self.research.run(lead)
                return lead, research_obj, pages, None
            except Exception as exc:
                return lead, None, None, exc
        with ThreadPoolExecutor(max_workers=self.settings.max_concurrency) as pool:
            futures = {pool.submit(worker, lead): lead for lead in eligible}
            for future in as_completed(futures):
                lead, research_obj, pages, error = future.result()
                if error:
                    self.store.mark_research_retry(lead["lead_id"], delay_seconds=max(self.settings.retry_base_seconds, 5), terminal_after=self.settings.retry_limit + 1, reason=str(error)[:500])
                    metrics.research_failed += 1
                    self.store.add_event("research_failed", run_id=workflow_id, campaign_id=campaign_id, lead_id=lead["lead_id"], reason=str(error)[:500])
                    continue
                self.store.set_lead_status(lead["lead_id"], "RESEARCHED")
                metrics.researched += 1
                research_row = self.store.latest_research(lead["lead_id"])
                if not research_row:
                    continue
                try:
                    research_data, pages_data = self._research_payload(research_row)
                    # Sender is assigned only at batch creation. Use a stable neutral signature here.
                    draft, validation, repairs = self.personalization.generate(lead, research_data, pages_data, [], "INITIAL", "AttachAI")
                    outreach_id = deterministic_outreach_id(lead["lead_id"], "INITIAL", 1)
                    self.store.save_personalization(lead_id=lead["lead_id"], campaign_id=campaign_id, outreach_id=outreach_id, sequence_type="INITIAL", payload=draft.payload(), validation_valid=validation.valid, validation_error="; ".join(validation.reasons), attempts=repairs)
                    if not validation.valid:
                        self.store.set_lead_status(lead["lead_id"], "REVIEW_NEEDED")
                        metrics.personalization_rejected += 1
                        self.store.add_event("personalization_rejected", run_id=workflow_id, campaign_id=campaign_id, lead_id=lead["lead_id"], reason="; ".join(validation.reasons))
                        continue
                    ok = self.store.insert_outreach({
                        "outreach_id": outreach_id,
                        "workflow_run_id": workflow_id,
                        "campaign_id": campaign_id,
                        "lead_id": lead["lead_id"],
                        "sequence_type": "INITIAL",
                        "sequence_number": 1,
                        "sender_id": "",
                        "sender_email": "",
                        "email": lead["email"],
                        "subject": draft.subject,
                        "body": draft.body,
                        "status": "QUEUED",
                        "confidence": draft.confidence,
                        "evidence_urls": [e.url for e in validation.normalized_evidence],
                    })
                    if ok:
                        self.store.set_lead_status(lead["lead_id"], "QUEUED")
                        metrics.personalized += 1
                        metrics.ready += 1
                        prepared += 1
                except (Exception) as exc:
                    self.store.set_lead_status(lead["lead_id"], "REVIEW_NEEDED")
                    metrics.personalization_rejected += 1
                    self.store.add_event("personalization_failed", run_id=workflow_id, campaign_id=campaign_id, lead_id=lead["lead_id"], reason=str(exc)[:500])
        return prepared

    def _send_rows(self, workflow_id: str, campaign_id: str, rows: list[Any], *, batch_type: str, send_enabled: bool, dry_run: bool, metrics: RunMetrics) -> int:
        if not rows:
            return 0
        if dry_run or not send_enabled:
            metrics.queued += len(rows)
            log("SEND_SKIPPED", workflow_run_id=workflow_id, batch_type=batch_type, planned=len(rows), reason="dry_run_or_send_disabled")
            return 0
        senders = self.settings.sender_configs()
        at = datetime.now(timezone.utc)
        date_key = at.date().isoformat()
        healthy: dict[str, Any] = {}
        for sender in senders:
            day = self.store.sender_day(sender.sender_id, date_key)
            state = str(day["health_state"])
            cooldown = day["cooldown_until_utc"]
            if state == "STOPPED" or (state == "COOLDOWN" and cooldown and cooldown > at):
                continue
            if self.settings.daily_limits_enforce:
                current = int(day["total"])
                limit = self.settings.daily_followup_limit if batch_type == "FOLLOWUP" else self.settings.daily_initial_limit
                if current >= min(limit, self.settings.daily_total_limit):
                    continue
            healthy[sender.sender_id] = sender
        if batch_type == "FOLLOWUP":
            selected = [row for row in rows if str(row["sender_id"]) in healthy][:10]
            # One follow-up per sender in a batch, preserving the predecessor sender identity.
            seen_sender: set[str] = set()
            selected = [row for row in selected if not (str(row["sender_id"]) in seen_sender or seen_sender.add(str(row["sender_id"])))][:self.settings.batch_size]
            assignment_senders = [healthy[str(row["sender_id"])] for row in selected]
        else:
            available = list(healthy.values())
            if not available:
                return 0
            remaining_for_initial = max(0, int(self.store.scalar("SELECT target_new_initials FROM campaign_run WHERE campaign_run_id=?", [campaign_id], 0)) - self.store.successful_initial_count(campaign_id)) if batch_type == "INITIAL" else len(rows)
            count = min(len(rows), self.settings.batch_size, len(available), 10, remaining_for_initial)
            selected = rows[:count]
            assignment_senders = available[:count]
        if not selected:
            return 0
        batch_number = self.store.next_batch_number(workflow_id, batch_type)
        batch_id = self.store.create_batch(workflow_id, campaign_id, batch_type, batch_number, [str(r["outreach_id"]) for r in selected])
        assignments = []
        for row, sender in zip(selected, assignment_senders):
            assignments.append((str(row["outreach_id"]), str(row["lead_id"]), sender.sender_id, sender.email))
        self.store.assign_batch(batch_id, assignments)
        sender_by_id = {s.sender_id: s for s in senders}
        credentials = {s.credential_env: __import__("os").getenv(s.credential_env, "") for s in senders}
        batch_rows = [self.store.get_outreach(a[0]) for a in assignments]
        batch_started = time.monotonic()
        results = self.mailer.send_batch(batch_id, batch_rows, sender_by_id, credentials, dry_run=False)
        batch_duration_seconds = round(time.monotonic() - batch_started, 3)
        attempted = len(results)
        success = 0
        failed = 0
        for result in results:
            row = self.store.get_outreach(result.outreach_id)
            if result.status == "SENT":
                sent_at = datetime.now(timezone.utc)
                self.store.mark_sent(result.outreach_id, sent_at)
                sender = row["sender_id"]
                self.store.record_send_success(sender, sent_at.date().isoformat(), batch_type == "FOLLOWUP", sent_at)
                self.store.add_event("outreach_sent", run_id=workflow_id, campaign_id=campaign_id, lead_id=row["lead_id"], outreach_id=result.outreach_id, sender_id=sender, batch_id=batch_id, sequence_type=row["sequence_type"], status="SENT", metadata={"smtp_message_id": row["smtp_message_id"]})
                success += 1
                if row["sequence_type"] == "INITIAL":
                    lead = self.store.get_lead(row["lead_id"])
                    if lead:
                        self.store.set_lead_status(lead["lead_id"], "ACTIVE")
                    self._schedule_next_followup(workflow_id, campaign_id, self.store.get_outreach(result.outreach_id), "FOLLOWUP_1", 1, self.settings.followup_1_delay_hours * 3600)
                elif row["sequence_type"] == "FOLLOWUP_1":
                    self._schedule_next_followup(workflow_id, campaign_id, self.store.get_outreach(result.outreach_id), "FOLLOWUP_2", 2, self.settings.followup_2_delay_days * 86400)
                elif row["sequence_type"] == "FOLLOWUP_2":
                    self._schedule_next_followup(workflow_id, campaign_id, self.store.get_outreach(result.outreach_id), "FOLLOWUP_3", 3, self.settings.followup_3_delay_days * 86400)
            else:
                failed += 1
                sender_id = row["sender_id"]
                error_class = result.error_class or "terminal unknown"
                retryable = error_class == "temporary/provider/network" and int(row["retry_count"]) < self.settings.retry_limit
                next_retry = datetime.now(timezone.utc) + timedelta(seconds=self.settings.retry_base_seconds * (2 ** int(row["retry_count"]))) if retryable else None
                self.store.mark_failed(result.outreach_id, error_class=error_class, error=result.error or "send failed", retryable=retryable, next_retry_at=next_retry, sender_id=sender_id)
                cooldown = datetime.now(timezone.utc) + timedelta(seconds=max(self.settings.retry_base_seconds, 10)) if retryable else None
                self.store.record_send_failure(sender_id, datetime.now(timezone.utc).date().isoformat(), error_class, cooldown)
                if error_class == "authentication":
                    self.store.set_sender_health(sender_id, datetime.now(timezone.utc).date().isoformat(), "STOPPED")
                self.store.add_event("outreach_send_failed", run_id=workflow_id, campaign_id=campaign_id, lead_id=row["lead_id"], outreach_id=result.outreach_id, sender_id=sender_id, batch_id=batch_id, sequence_type=row["sequence_type"], status=row["status"], reason=error_class, metadata={"error": result.error})
        self.store.complete_batch(batch_id, attempted, success, failed)
        metrics.attempted += attempted
        metrics.successful_initial_sends = self.store.successful_initial_count(campaign_id)
        metrics.followups_sent += sum(1 for r in results if r.status == "SENT" and self.store.get_outreach(r.outreach_id)["sequence_type"] != "INITIAL")
        metrics.retryable_failures += sum(1 for r in results if r.status == "FAILED" and r.error_class == "temporary/provider/network")
        metrics.terminal_failures += sum(1 for r in results if r.status == "FAILED" and r.error_class != "temporary/provider/network")
        log("BATCH_RESULT", workflow_run_id=workflow_id, batch_id=batch_id, batch_number=batch_number, planned=len(selected), attempted=attempted, successful=success, failed=failed, senders_used=[a[2] for a in assignments], duration_seconds=batch_duration_seconds)
        return success

    def _schedule_next_followup(self, workflow_id: str, campaign_id: str, previous: Any, sequence_type: str, sequence_number: int, delay_seconds: int) -> None:
        lead = self.store.get_lead(previous["lead_id"])
        if not lead or self.store.is_suppressed(lead["email"]):
            return
        sent_at = previous["sent_at_utc"]
        if not isinstance(sent_at, datetime):
            sent_at = datetime.fromisoformat(str(sent_at).replace("Z", "+00:00"))
        scheduled = sent_at + timedelta(seconds=delay_seconds)
        self.store.create_followup_row(workflow_id=workflow_id, campaign_id=campaign_id, lead=lead, previous=previous, sequence_type=sequence_type, sequence_number=sequence_number, scheduled_at=scheduled)

    def _within_send_window(self, when: datetime, sender: Any, row: Any, mode: str) -> bool:
        # Recipient timezone is used for configured recipient mode. Application mode uses the runner timezone.
        if mode == "recipient":
            try:
                from zoneinfo import ZoneInfo
                tz = ZoneInfo(str(self.store.get_lead(row["lead_id"])["timezone"]))
            except Exception:
                tz = self.settings.timezone()
        else:
            tz = self.settings.timezone()
        local = when.astimezone(tz).time()
        start = self.settings.send_window_start
        end = self.settings.send_window_end
        if start < end:
            return start <= local <= end
        return local >= start or local <= end

    def _finalize_metrics(self, metrics: RunMetrics, workflow_id: str, campaign_id: str, started: float, status: str) -> None:
        metrics.successful_initial_sends = self.store.successful_initial_count(campaign_id)
        metrics.remaining_target = max(0, self.store.scalar("SELECT target_new_initials FROM campaign_run WHERE campaign_run_id=?", [campaign_id], 0) - metrics.successful_initial_sends)
        metrics.run_status = status
        metrics.replies += self.store.count_events(workflow_id).get("reply", 0)
        metrics.duration_seconds = round(time.monotonic() - started, 3)
