from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class CampaignStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SUCCESS = "SUCCESS"
    BLOCKED = "BLOCKED"


class LeadStatus(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    RESEARCHING = "RESEARCHING"
    RESEARCHED = "RESEARCHED"
    QUEUED = "QUEUED"
    ACTIVE = "ACTIVE"
    REPLIED = "REPLIED"
    BOUNCED = "BOUNCED"
    UNSUBSCRIBED = "UNSUBSCRIBED"
    COMPLETED = "COMPLETED"
    MANUAL_STOP = "MANUAL_STOP"
    REVIEW_NEEDED = "REVIEW_NEEDED"


class CandidateStatus(StrEnum):
    DISCOVERED = "DISCOVERED"
    RETRYABLE = "RETRYABLE"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class MessageStatus(StrEnum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    QUEUED = "QUEUED"
    WAITING_DUE = "WAITING_DUE"
    SCHEDULED = "SCHEDULED"
    SENDING = "SENDING"
    SENT = "SENT"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_TERMINAL = "FAILED_TERMINAL"
    CANCELLED = "CANCELLED"
    REVIEW_NEEDED = "REVIEW_NEEDED"


class SequenceType(StrEnum):
    INITIAL = "INITIAL"
    FOLLOWUP_1 = "FOLLOWUP_1"
    FOLLOWUP_2 = "FOLLOWUP_2"
    FOLLOWUP_3 = "FOLLOWUP_3"

    @property
    def number(self) -> int:
        return {
            SequenceType.INITIAL: 1,
            SequenceType.FOLLOWUP_1: 1,
            SequenceType.FOLLOWUP_2: 2,
            SequenceType.FOLLOWUP_3: 3,
        }[self]


class InboundEventType(StrEnum):
    REPLY = "REPLY"
    HARD_BOUNCE = "HARD_BOUNCE"
    SOFT_BOUNCE = "SOFT_BOUNCE"
    UNSUBSCRIBED = "UNSUBSCRIBED"
    UNCLASSIFIED = "UNCLASSIFIED"
    REVIEW_NEEDED = "REVIEW_NEEDED"


class SendErrorClass(StrEnum):
    TEMPORARY = "temporary/provider/network"
    AUTHENTICATION = "authentication"
    TERMINAL_RECIPIENT = "terminal recipient/address"
    TERMINAL_UNKNOWN = "terminal unknown"
    SENDER_STOPPED = "sender stopped/degraded/cooldown"


@dataclass(frozen=True)
class Evidence:
    url: str
    snippet: str
    title: str = ""


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    reasons: tuple[str, ...] = ()
    normalized_evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True)
class SendResult:
    outreach_id: str
    status: str
    error_class: str | None = None
    error: str | None = None
    provider_message_id: str | None = None


@dataclass
class RunMetrics:
    raw_candidates: int = 0
    deduplicated_candidates: int = 0
    qualified: int = 0
    researched: int = 0
    research_failed: int = 0
    personalized: int = 0
    personalization_rejected: int = 0
    ready: int = 0
    queued: int = 0
    attempted: int = 0
    successful_initial_sends: int = 0
    retryable_failures: int = 0
    terminal_failures: int = 0
    followups_generated: int = 0
    followups_sent: int = 0
    replies: int = 0
    bounces: int = 0
    unsubscribes: int = 0
    suppressed: int = 0
    remaining_target: int = 0
    run_status: str = "RUNNING"
    duration_seconds: float = 0.0
    stage_seconds: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        data = self.__dict__.copy()
        data["stage_seconds"] = dict(self.stage_seconds)
        data["notes"] = list(self.notes)
        return data
