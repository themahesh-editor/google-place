from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class LeadState(str, Enum):
    NEW="NEW"; ELIGIBLE="ELIGIBLE"; RESEARCHING="RESEARCHING"; RESEARCHED="RESEARCHED"
    OUTREACH_PREPARED="OUTREACH_PREPARED"; SCHEDULED="SCHEDULED"; ACTIVE="ACTIVE"; MANUAL_STOP="MANUAL_STOP"
    REPLIED="REPLIED"; BOUNCED="BOUNCED"; UNSUBSCRIBED="UNSUBSCRIBED"; COMPLETED="COMPLETED"


class MessageStatus(str, Enum):
    DRAFT="DRAFT"; VALIDATED="VALIDATED"; QUEUED="QUEUED"; SCHEDULED="SCHEDULED"
    SENDING="SENDING"; SENT="SENT"; FAILED_RETRYABLE="FAILED_RETRYABLE"; FAILED_TERMINAL="FAILED_TERMINAL"
    CANCELLED="CANCELLED"; REVIEW_NEEDED="REVIEW_NEEDED"


class SequenceType(str, Enum):
    INITIAL="INITIAL"; FOLLOWUP_1="FOLLOWUP_1"; FOLLOWUP_2="FOLLOWUP_2"; FOLLOWUP_3="FOLLOWUP_3"


class InboundEventType(str, Enum):
    REPLY="REPLY"; HARD_BOUNCE="HARD_BOUNCE"; SOFT_BOUNCE="SOFT_BOUNCE"
    UNSUBSCRIBED="UNSUBSCRIBED"; UNCLASSIFIED="UNCLASSIFIED"; REVIEW_NEEDED="REVIEW_NEEDED"


@dataclass(frozen=True)
class Lead:
    lead_id: str
    email: str
    company: str
    website: str
    city: str=""
    state: str=""
    timezone: str="Asia/Kolkata"
    lead_source: str=""
    verified: str=""
    place_id: str=""
    email_source_url: str=""
    website_facts: str=""
    scale_class: str=""
    qualification_confidence: float=0.0
    status: str="Verified"
    first_seen_date: str=""
    notes: str=""


@dataclass(frozen=True)
class Evidence:
    url: str
    snippet: str


@dataclass(frozen=True)
class WebsiteResearch:
    research_id: str
    lead_id: str
    research_timestamp: str
    business_summary: str
    services: list[str]
    target_customers: list[str]
    locations: list[str]
    specialties: list[str]
    website_signals: list[str]
    customer_journey_signals: list[str]
    ai_opportunity_signals: list[str]
    evidence: list[Evidence]
    research_status: str
    research_version: str


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
    risk_flags: list[str]=field(default_factory=list)
