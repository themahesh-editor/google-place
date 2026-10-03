from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.db import now_utc


TERMINAL_LEAD_STATES = {"REPLIED", "BOUNCED", "UNSUBSCRIBED", "COMPLETED", "MANUAL_STOP"}


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class Orchestrator:
    def __init__(self, settings, store, discovery, research, personalization, mailer):
        self.settings = settings
        self.store = store
        self.discovery = discovery
        self.research = research
        self.personalization = personalization
        self.mailer = mailer
        self.stage_times: dict[str, float] = {}
        self.stage_starts: dict[str, str] = {}
        self.stage_ends: dict[str, str] = {}

    def _stage(self, name: str):
        class Stage:
            def __init__(self, outer, stage_name):
                self.outer = outer; self.stage_name = stage_name
            def __enter__(self):
                self.started = time.monotonic()
                self.outer.stage_starts[self.stage_name] = now_utc()
                print(f"{self.stage_name}_START={self.outer.stage_starts[self.stage_name]}")
            def __exit__(self, exc_type, exc, tb):
                self.outer.stage_ends[self.stage_name] = now_utc()
                self.outer.stage_times[self.stage_name] = round(time.monotonic() - self.started, 2)
                print(f"{self.stage_name}_END={self.outer.stage_ends[self.stage_name]}")
                print(f"{self.stage_name}_DURATION_SECONDS={self.outer.stage_times[self.stage_name]}")
        return Stage(self, name)

    def run(self, reset_state: bool, target: int, send_enabled: bool, dry_run: bool) -> dict:
        start_monotonic = time.monotonic()
        run_id: str | None = None
        try:
            self.store.migrate("migrations")
            if reset_state:
                print("RESET_STATE=true: clearing application runtime tables only")
                self.store.reset_runtime_state()
            run_id = self.store.start_workflow("MANUAL", reset_state)
            print(f"START_TIME={now_utc()}")
            self.reconcile_stale_state()

            with self._stage("DISCOVERY"):
                discovery_metrics = self.discovery.run(run_id, self.settings.discovery_target)

            with self._stage("PREPARE"):
                prep = self.prepare_initial_messages(run_id, target)

            with self._stage("SEND"):
                initial_send = self.send_initial_until_target(run_id, target, send_enabled and not dry_run)

            with self._stage("MAILBOX"):
                mailbox = self.sync_mailboxes(run_id, dry_run)

            with self._stage("FOLLOWUP"):
                followup = self.prepare_and_send_followups(run_id, send_enabled and not dry_run, dry_run)

            metrics = self.build_metrics(run_id, discovery_metrics, prep, initial_send, mailbox, followup, time.monotonic() - start_monotonic)
            success = metrics["successful_initial_sends"] >= target
            if metrics["successful_initial_sends"] < target:
                metrics["target_status"] = "TARGET NOT REACHED"
                metrics["target_reason"] = self.target_not_reached_reason(metrics)
                success = False if target > 0 and send_enabled and not dry_run else success
            else:
                metrics["target_status"] = "TARGET REACHED"
                metrics["target_reason"] = "100 successful initial sends reached" if target == 100 else "target reached"
            metrics["stage_durations_seconds"] = self.stage_times
            metrics["stage_timestamps"] = {k: {"start": self.stage_starts.get(k), "end": self.stage_ends.get(k)} for k in self.stage_starts}
            self.store.finish_workflow(run_id, "SUCCESS" if success else "TARGET_NOT_REACHED", metrics)
            print(json.dumps(metrics, indent=2, ensure_ascii=False))
            return metrics
        except Exception as exc:
            metrics = {"status": "FAILED", "error": exc.__class__.__name__, "message": str(exc), "stage_durations_seconds": self.stage_times}
            if run_id is not None:
                try:
                    self.store.finish_workflow(run_id, "FAILED", metrics)
                except Exception:
                    pass
            raise
        finally:
            print(f"FINAL_END={now_utc()}")
            print(f"TOTAL_RUNTIME_SECONDS={round(time.monotonic() - start_monotonic, 2)}")

    def reconcile_stale_state(self) -> None:
        cutoff = iso(datetime.now(timezone.utc) - timedelta(hours=2))
        self.store.execute("UPDATE leads SET status='ELIGIBLE',updated_at_utc=? WHERE status='RESEARCHING' AND updated_at_utc<?", [now_utc(), cutoff])
        self.store.execute("UPDATE outreach SET status='REVIEW_NEEDED',updated_at_utc=?,last_error='runner_interrupted_while_sending' WHERE status='SENDING' AND updated_at_utc<?", [now_utc(), cutoff])
        self.store.reconcile_stale_batches(cutoff)

    def prepare_initial_messages(self, run_id: str, target: int) -> dict[str, int]:
        prepared = researched = personalized = validated = rejected = 0
        blocked_this_run: set[str] = set()
        max_rounds = max(1, target * 2)
        for _ in range(max_rounds):
            if self.store.count_successful_initials() >= target:
                break
            if self.store.count_initial_progress() >= target:
                break
            leads = self.store.claim_untouched_leads(min(25, max(10, target - prepared)), exclude_ids=tuple(blocked_this_run))
            if not leads:
                break
            for lead in leads:
                lead_dict = dict(lead)
                self.store.add_event("lead_selected", run_id=run_id, lead_id=lead_dict["lead_id"], status="RESEARCHING")
                record = self.research.run(lead_dict, run_id)
                if record["research_status"] != "RESEARCHED":
                    blocked_this_run.add(lead_dict["lead_id"])
                    rejected += 1
                    self.store.add_event("research_failed", run_id=run_id, lead_id=lead_dict["lead_id"], status=record["research_status"], reason=record.get("error"))
                    self.store.update_lead_status(lead_dict["lead_id"], "ELIGIBLE")
                    continue
                researched += 1
                sender_signature = "Best,\nAttachAI"
                try:
                    draft = self.personalization.initial(lead_dict, record, sender_signature)
                except Exception as exc:
                    blocked_this_run.add(lead_dict["lead_id"])
                    self.store.update_lead_status(lead_dict["lead_id"], "ELIGIBLE")
                    self.store.add_event("personalization_failed", run_id=run_id, lead_id=lead_dict["lead_id"], status="FAILED_RETRYABLE", reason=exc.__class__.__name__)
                    continue
                personalized += 1
                self.store.add_event("personalization_generated", run_id=run_id, lead_id=lead_dict["lead_id"], status="GENERATED", metadata={"confidence": draft.confidence})
                previous = []
                from app.personalization import PersonalizationValidator
                validation = PersonalizationValidator(self.settings.min_personalization_confidence).validate(lead_dict, record, draft, previous, self.store)
                if not validation.ok:
                    blocked_this_run.add(lead_dict["lead_id"])
                    rejected += 1
                    self.store.update_lead_status(lead_dict["lead_id"], "ELIGIBLE")
                    self.store.add_event("personalization_rejected", run_id=run_id, lead_id=lead_dict["lead_id"], status="FAILED_TERMINAL", reason=validation.reason)
                    continue
                validated += 1
                self.store.add_event("personalization_validated", run_id=run_id, lead_id=lead_dict["lead_id"], status="VALIDATED")
                oid = self.store.queue_initial(run_id=run_id, lead_id=lead_dict["lead_id"], sender_id="UNASSIGNED", sender_email="", subject=draft.subject, body=draft.body, evidence_urls=draft.evidence_urls, confidence=draft.confidence)
                if oid:
                    prepared += 1
                    self.store.add_event("outreach_queued", run_id=run_id, lead_id=lead_dict["lead_id"], outreach_id=oid, sequence_type="INITIAL", status="QUEUED", metadata={"confidence": draft.confidence})
                else:
                    blocked_this_run.add(lead_dict["lead_id"])
                    self.store.update_lead_status(lead_dict["lead_id"], "ELIGIBLE")
        return {"prepared": prepared, "researched": researched, "personalized": personalized, "validated": validated, "rejected": rejected}

    def _within_window(self, when_utc: datetime, lead_timezone: str) -> bool:
        tz = self.settings.timezone()
        if self.settings.sending_window_mode == "recipient":
            try:
                tz = ZoneInfo(lead_timezone)
            except Exception:
                tz = self.settings.timezone()
        local = when_utc.astimezone(tz)
        current = local.timetz().replace(tzinfo=None)
        return self.settings.sending_window_start <= current < self.settings.sending_window_end

    def _next_window_start(self, when_utc: datetime, lead_timezone: str = "") -> datetime:
        tz = self.settings.timezone()
        if self.settings.sending_window_mode == "recipient" and lead_timezone:
            try: tz = ZoneInfo(lead_timezone)
            except Exception: pass
        local = when_utc.astimezone(tz)
        start = self.settings.sending_window_start
        end = self.settings.sending_window_end
        candidate = local.replace(hour=start.hour, minute=start.minute, second=0, microsecond=0)
        if local.timetz().replace(tzinfo=None) >= end:
            candidate = (local + timedelta(days=1)).replace(hour=start.hour, minute=start.minute, second=0, microsecond=0)
        elif local.timetz().replace(tzinfo=None) < start:
            candidate = local.replace(hour=start.hour, minute=start.minute, second=0, microsecond=0)
        return candidate.astimezone(timezone.utc)

    def _next_batch_slot(self, after: datetime, lead_timezone: str = "") -> datetime:
        tz_name = lead_timezone if self.settings.sending_window_mode == "recipient" else ""
        candidate = self._next_window_start(after, tz_name)
        try:
            tz = ZoneInfo(lead_timezone) if self.settings.sending_window_mode == "recipient" and lead_timezone else self.settings.timezone()
        except Exception:
            tz = self.settings.timezone()
        local_after = after.astimezone(tz)
        local_candidate = candidate.astimezone(tz)
        start = self.settings.sending_window_start
        end = self.settings.sending_window_end
        base = max(1, self.settings.batch_interval_minutes)
        if self._within_window(after, lead_timezone):
            local_candidate = local_after.replace(second=0, microsecond=0)
            minute = local_candidate.minute
            needs_step = (minute % base) != 0 or local_after.second != 0 or local_after.microsecond != 0
            if needs_step:
                minute = ((minute // base) + 1) * base
            if minute >= 60:
                local_candidate = (local_candidate + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
            else:
                local_candidate = local_candidate.replace(minute=minute, second=0, microsecond=0)
            if local_candidate < local_after:
                local_candidate = local_after + timedelta(minutes=base)
                local_candidate = local_candidate.replace(second=0, microsecond=0)
        if local_candidate.timetz().replace(tzinfo=None) >= end:
            local_candidate = (local_candidate + timedelta(days=1)).replace(hour=start.hour, minute=start.minute, second=0, microsecond=0)
        return local_candidate.astimezone(timezone.utc)

    def _wait_until(self, when_utc: datetime) -> None:
        seconds = (when_utc - datetime.now(timezone.utc)).total_seconds()
        if seconds > 0:
            time.sleep(seconds)

    def _available_senders(self, at_utc: datetime, is_followup: bool) -> list:
        date_key = at_utc.astimezone(self.settings.timezone()).date().isoformat()
        out = []
        for sender in self.settings.sender_configs():
            state = self.store.sender_day(sender.sender_id, date_key)
            if state["health_state"] == "STOPPED" or state["health_state"] == "DEGRADED":
                continue
            cooldown = state["cooldown_until_utc"]
            if cooldown:
                cooldown_at = parse_utc(cooldown)
                if cooldown_at > at_utc:
                    continue
                if state["health_state"] == "COOLDOWN":
                    self.store.set_sender_health(sender.sender_id, date_key, "HEALTHY", None)
                    state = self.store.sender_day(sender.sender_id, date_key)
            if int(state["total"]) >= self.settings.daily_total_limit:
                continue
            last = state["last_successful_send_utc"]
            if last and (at_utc - parse_utc(last)).total_seconds() < self.settings.batch_interval_minutes * 60:
                continue
            if is_followup and int(state["followups"]) >= self.settings.daily_followup_limit:
                continue
            if not is_followup and int(state["initials"]) >= self.settings.daily_initial_limit:
                continue
            out.append(sender)
        return out

    def _create_next_batch(self, run_id: str, batch_number: int, batch_type: str, target_remaining: int) -> tuple[str, list] | tuple[None, list]:
        now = datetime.now(timezone.utc)
        candidates = self.store.list_ready_initials(min(50, target_remaining)) if batch_type == "INITIAL" else self.store.list_due_followups(min(50, target_remaining))
        if not candidates:
            return None, []
        slot_by_id = {row["outreach_id"]: self._next_batch_slot(now, row["timezone"]) for row in candidates}
        earliest_slot = min(slot_by_id.values())
        candidates = [row for row in candidates if slot_by_id[row["outreach_id"]] == earliest_slot]
        senders = self._available_senders(earliest_slot, batch_type != "INITIAL")
        if not senders:
            return None, []
        selected = []
        capacity = min(self.settings.batch_size, len(senders), target_remaining)
        for row in candidates:
            if len(selected) >= capacity:
                break
            selected.append(row)
        if not selected:
            return None, []
        scheduled = earliest_slot
        batch_id = self.store.create_batch(run_id, batch_number, batch_type, iso(scheduled), len(selected))
        assignments = []
        for sender, row in zip(senders, selected):
            assignments.append((row["outreach_id"], row["lead_id"], sender.sender_id, sender.email))
        self.store.assign_batch(batch_id, assignments, iso(scheduled))
        for outreach_id, lead_id, sender_id, _ in assignments:
            self.store.add_event("outreach_scheduled", run_id=run_id, lead_id=lead_id, outreach_id=outreach_id, sender_id=sender_id, batch_id=batch_id, status="SCHEDULED", metadata={"scheduled_at_utc": iso(scheduled), "batch_number": batch_number})
        return batch_id, [r for r in self.store.fetchall("SELECT o.*,l.timezone,l.status AS lead_status FROM outreach o JOIN leads l ON l.lead_id=o.lead_id WHERE o.batch_id=? ORDER BY o.sequence_number,o.created_at_utc", [batch_id])]

    def send_initial_until_target(self, run_id: str, target: int, allow_real_send: bool) -> dict[str, int]:
        initial_success_total_at_start = self.store.count_successful_initials()
        successful = initial_success_total_at_start
        batches = attempted = failed = 0
        next_slot = datetime.now(timezone.utc)
        if not allow_real_send:
            remaining = max(0, target - successful)
            candidates = self.store.list_ready_initials(min(self.settings.batch_size, remaining))
            if candidates:
                batch_id = self.store.create_batch(run_id, 1, "INITIAL", iso(datetime.now(timezone.utc)), len(candidates))
                sender_ids = [s.sender_id for s in self.settings.sender_configs()]
                assignments = [(row["outreach_id"], row["lead_id"], sender_ids[i], self.settings.sender_configs()[i].email) for i, row in enumerate(candidates)]
                self.store.assign_batch(batch_id, assignments, iso(datetime.now(timezone.utc)))
                print(f"DRY_RUN_BATCH_PLANNED={batch_id} planned={len(assignments)}")
                self.store.requeue_batch_pending(batch_id)
            return {"batches": 1 if candidates else 0, "attempted": 0, "failed": 0, "successful": successful}
        for batch_number in range(1, self.settings.max_batches_per_run + 1):
            if successful >= target:
                break
            need = target - successful
            batch_id, rows = self._create_next_batch(run_id, batch_number, "INITIAL", need)
            if not rows:
                if self.store.count_initial_progress() >= target or self.store.count_eligible_untouched() == 0:
                    break
                self._wait_until(datetime.now(timezone.utc) + timedelta(seconds=1))
                continue
            scheduled = parse_utc(rows[0]["scheduled_at_utc"])
            if scheduled > datetime.now(timezone.utc):
                self._wait_until(scheduled)
            start = time.monotonic()
            result_rows = self.mailer.send_batch(batch_id, rows, {s.sender_id: s for s in self.settings.sender_configs()}, allow_real_send)
            batch_success = sum(1 for x in result_rows if x.status == "SENT")
            batch_attempted = len([x for x in result_rows if x.status != "DRY_RUN"])
            batch_failed = len([x for x in result_rows if x.status.startswith("FAILED")])
            attempted += batch_attempted; failed += batch_failed; successful = self.store.count_successful_initials(); batches += 1
            batch_status = "COMPLETED" if not any(x.status == "REVIEW_NEEDED" for x in result_rows) else "PARTIAL"
            self.store.update_batch_counts(batch_id, status=batch_status, attempted=batch_attempted, successful=batch_success, failed=batch_failed)
            self.store.requeue_batch_pending(batch_id)
            self.store.add_event("batch_completed", run_id=run_id, batch_id=batch_id, status=batch_status, metadata={"batch_number": batch_number, "scheduled_at_utc": rows[0]["scheduled_at_utc"], "planned": len(rows), "attempted": batch_attempted, "successful": batch_success, "failed": batch_failed, "duration_seconds": round(time.monotonic()-start,2), "senders": [r["sender_id"] for r in rows]})
            next_slot = scheduled + timedelta(minutes=self.settings.batch_interval_minutes)
            if successful < target:
                self._wait_until(next_slot)
        return {"batches": batches, "attempted": attempted, "failed": failed, "successful": successful, "successful_in_run": max(0, successful - initial_success_total_at_start)}

    def sync_mailboxes(self, run_id: str, dry_run: bool) -> dict[str, int]:
        if dry_run:
            print("MAILBOX_MODE=SKIPPED_DRY_RUN")
            return {"mailbox_checks": 0, "inbound_processed": 0, "replies": 0, "bounces": 0, "unsubscribes": 0}
        from app.mailbox import MailboxMonitor
        monitor = MailboxMonitor(self.store, self.settings, run_id)
        return monitor.run_all()

    def prepare_and_send_followups(self, run_id: str, allow_real_send: bool, dry_run: bool) -> dict[str, int]:
        generated = 0
        from app.personalization import PersonalizationValidator
        for sequence in ("FOLLOWUP_1", "FOLLOWUP_2", "FOLLOWUP_3"):
            number = int(sequence.split("_")[-1])
            delay = {1: timedelta(hours=self.settings.followup_1_delay_hours), 2: timedelta(days=self.settings.followup_2_delay_days), 3: timedelta(days=self.settings.followup_3_delay_days)}[number]
            for previous in self.store.list_followup_candidates(sequence, 100):
                lead = self.store.get_lead(previous["lead_id"])
                if not lead or lead["status"] in TERMINAL_LEAD_STATES or self.store.is_suppressed(lead["email"]):
                    continue
                due_at = parse_utc(previous["sent_at_utc"]) + delay
                if due_at > datetime.now(timezone.utc):
                    continue
                research = self.store.latest_research(previous["lead_id"])
                if not research or research["research_status"] != "RESEARCHED":
                    continue
                history = self.store.previous_sent_history(previous["lead_id"])
                sender = next(s for s in self.settings.sender_configs() if s.sender_id == previous["sender_id"])
                try:
                    draft = self.personalization.followup(dict(lead), dict(research), history, sequence, sender.email)
                    validation = PersonalizationValidator(self.settings.min_personalization_confidence).validate(dict(lead), dict(research), draft, [x["body"] for x in history], self.store)
                    if not validation.ok:
                        self.store.add_event("followup_rejected", run_id=run_id, lead_id=lead["lead_id"], sender_id=sender.sender_id, sequence_type=sequence, status="FAILED_TERMINAL", reason=validation.reason)
                        continue
                except Exception as exc:
                    self.store.add_event("followup_generation_failed", run_id=run_id, lead_id=lead["lead_id"], sender_id=sender.sender_id, sequence_type=sequence, status="FAILED_RETRYABLE", reason=exc.__class__.__name__)
                    continue
                oid = self.store.insert_followup(run_id=run_id, lead_id=lead["lead_id"], sequence_type=sequence, sequence_number=number, sender_id=sender.sender_id, sender_email=sender.email, subject=draft.subject, body=draft.body, evidence_urls=draft.evidence_urls, confidence=draft.confidence, in_reply_to=previous["message_id"], references_text=previous["message_id"], scheduled_at_utc=iso(due_at))
                if oid:
                    generated += 1
                    self.store.add_event("followup_generated", run_id=run_id, lead_id=lead["lead_id"], outreach_id=oid, sender_id=sender.sender_id, sequence_type=sequence, status="QUEUED", metadata={"scheduled_at_utc": iso(due_at)})
        if not allow_real_send:
            return {"generated": generated, "sent": 0, "batches": 0}
        sent = 0
        batches = 0
        for batch_number in range(1, self.settings.max_batches_per_run + 1):
            rows = self.store.list_due_followups(min(self.settings.batch_size, self.settings.daily_followup_limit))
            if not rows:
                break
            # Each follow-up batch also uses one message per sender, while preserving the sender identity from the prior stage.
            selected = []
            used_senders = set()
            now = datetime.now(timezone.utc)
            available_sender_ids = {s.sender_id for s in self._available_senders(now, True)}
            for row in rows:
                if row["sender_id"] in used_senders or row["sender_id"] not in available_sender_ids:
                    continue
                if row["lead_status"] in TERMINAL_LEAD_STATES:
                    continue
                if not self._within_window(now, row["timezone"]):
                    continue
                selected.append(row); used_senders.add(row["sender_id"])
                if len(selected) >= self.settings.batch_size:
                    break
            if not selected:
                break
            scheduled = max(parse_utc(x["scheduled_at_utc"]) for x in selected if x["scheduled_at_utc"])
            if scheduled > now:
                self._wait_until(scheduled)
            batch_id = self.store.create_batch(run_id, batch_number, "FOLLOWUP", iso(scheduled), len(selected))
            self.store.assign_batch(batch_id, [(r["outreach_id"], r["lead_id"], r["sender_id"], r["sender_email"]) for r in selected], iso(scheduled))
            result_rows = self.mailer.send_batch(batch_id, [dict(r) for r in self.store.fetchall("SELECT o.*,l.timezone,l.status AS lead_status FROM outreach o JOIN leads l ON l.lead_id=o.lead_id WHERE o.batch_id=?", [batch_id])], {s.sender_id: s for s in self.settings.sender_configs()}, allow_real_send)
            success = sum(1 for r in result_rows if r.status == "SENT")
            failed = sum(1 for r in result_rows if r.status.startswith("FAILED"))
            attempted = sum(1 for r in result_rows if r.status != "DRY_RUN")
            self.store.update_batch_counts(batch_id, status="COMPLETED", attempted=attempted, successful=success, failed=failed)
            self.store.requeue_batch_pending(batch_id)
            sent += success; batches += 1
        return {"generated": generated, "sent": sent, "batches": batches}

    def build_metrics(self, run_id: str, discovery: dict, prep: dict, initial: dict, mailbox: dict, followup: dict, runtime: float) -> dict:
        return {
            "run_id": run_id,
            "runtime_seconds": round(runtime, 2),
            "discovered": discovery.get("discovered", 0),
            "verified": discovery.get("verified", 0),
            "eligible": self.store.count_eligible_untouched() + self.store.scalar("SELECT count(*) FROM leads WHERE status IN ('RESEARCHED','QUEUED','ACTIVE')"),
            "selected": prep.get("prepared", 0),
            "researched": prep.get("researched", 0),
            "personalized": prep.get("personalized", 0),
            "validated": prep.get("validated", 0),
            "queued": self.store.scalar("SELECT count(*) FROM outreach WHERE workflow_run_id=? AND status IN ('QUEUED','SCHEDULED','SENDING','SENT')", [run_id]),
            "scheduled": self.store.scalar("SELECT count(*) FROM outreach WHERE workflow_run_id=? AND status='SCHEDULED'", [run_id]),
            "attempted": initial.get("attempted", 0),
            "successful_initial_sends": self.store.count_successful_initials(),
            "successful_initial_sends_in_run": initial.get("successful_in_run", 0),
            "retryable_failures": self.store.scalar("SELECT count(*) FROM outreach WHERE workflow_run_id=? AND status='FAILED_RETRYABLE'", [run_id]),
            "terminal_failures": self.store.scalar("SELECT count(*) FROM outreach WHERE workflow_run_id=? AND status='FAILED_TERMINAL'", [run_id]),
            "suppressed": self.store.scalar("SELECT count(*) FROM suppression"),
            "replies": mailbox.get("replies", 0),
            "bounces": mailbox.get("bounces", 0),
            "unsubscribes": mailbox.get("unsubscribes", 0),
            "followups_generated": followup.get("generated", 0),
            "followups_sent": self.store.scalar("SELECT count(*) FROM outreach WHERE workflow_run_id=? AND sequence_type LIKE 'FOLLOWUP_%%' AND status='SENT'", [run_id]),
            "eligible_untouched_after_run": self.store.count_eligible_untouched(),
            "batch_count": initial.get("batches", 0),
        }

    @staticmethod
    def target_not_reached_reason(metrics: dict) -> str:
        if metrics["successful_initial_sends"] == 0 and metrics["eligible_untouched_after_run"] == 0:
            return "no eligible untouched leads remain"
        if metrics["eligible_untouched_after_run"] > 0:
            return "remaining leads are not currently valid/sendable, or batch/sender limits were exhausted"
        return "some selected messages failed and the bounded batch/retry policy ended before target"
