from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class LeadStatus(str, Enum):
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


class MessageStatus(str, Enum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    QUEUED = "QUEUED"
    SCHEDULED = "SCHEDULED"
    SENDING = "SENDING"
    SENT = "SENT"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_TERMINAL = "FAILED_TERMINAL"
    CANCELLED = "CANCELLED"
    REVIEW_NEEDED = "REVIEW_NEEDED"


class SequenceType(str, Enum):
    INITIAL = "INITIAL"
    FOLLOWUP_1 = "FOLLOWUP_1"
    FOLLOWUP_2 = "FOLLOWUP_2"
    FOLLOWUP_3 = "FOLLOWUP_3"


class InboundEventType(str, Enum):
    REPLY = "REPLY"
    HARD_BOUNCE = "HARD_BOUNCE"
    SOFT_BOUNCE = "SOFT_BOUNCE"
    UNSUBSCRIBED = "UNSUBSCRIBED"
    UNCLASSIFIED = "UNCLASSIFIED"
    REVIEW_NEEDED = "REVIEW_NEEDED"


@dataclass(frozen=True)
class Lead:
    lead_id: str
    email: str
    company: str
    website: str
    website_domain: str
    city: str
    region: str
    country_code: str
    timezone: str
    lead_source: str
    place_id: str
    scale_class: str
    qualification_confidence: float
    qualification_reason: str
    discovery_facts: str = ""
    status: str = LeadStatus.ELIGIBLE.value
    sender_id: str | None = None


@dataclass(frozen=True)
class Evidence:
    url: str
    snippet: str


@dataclass(frozen=True)
class ResearchRecord:
    research_id: str
    lead_id: str
    website_domain: str
    canonical_url: str
    company_identity: str
    business_summary: str
    services: list[str]
    business_facts: list[str]
    locations: list[str]
    specialties: list[str]
    website_signals: list[str]
    customer_journey_signals: list[str]
    ai_opportunity_signals: list[str]
    important_public_text: str
    evidence: list[Evidence]
    research_timestamp_utc: str
    research_status: str
    research_version: str
    error: str | None = None
    retry_count: int = 0
    next_retry_at_utc: str | None = None


@dataclass(frozen=True)
class PersonalizationDraft:
    eligible: bool
    personalization_summary: str
    observations: list[str]
    opportunity: str
    subject: str
    body: str
    cta: str
    signature: str
    confidence: float
    evidence_urls: list[str]
    risk_flags: list[str] = field(default_factory=list)
    personalization_anchors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    reason: str
    body_hash: str
    retryable: bool = False


@dataclass(frozen=True)
class SendResult:
    outreach_id: str
    sender_id: str
    status: str
    message_id: str
    error_kind: str | None = None
    error_text: str | None = None


@dataclass(frozen=True)
class BatchResult:
    batch_id: str
    batch_number: int
    batch_type: str
    scheduled_at_utc: str
    attempted_count: int
    successful_count: int
    failed_count: int
    duration_seconds: float
