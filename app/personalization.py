from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from .db import normalize_url
from .llm import LLMClient, LLMInvalidResponse, LLMTemporaryError, LLMPermanentError
from .models import Evidence, ValidationResult

STOPWORDS = {
    "about", "after", "also", "been", "business", "company", "could", "from", "have", "into", "just", "more",
    "page", "that", "their", "there", "this", "through", "using", "very", "what", "when", "with", "your", "they",
}


def normalize_evidence_url(value: str) -> str:
    return normalize_url(value).rstrip("/")


def _normalize_text(value: str) -> str:
    value = re.sub(r"\s+", " ", str(value or "")).strip().lower()
    return re.sub(r"[^a-z0-9 ]+", "", value)


def _meaningful_tokens(value: str) -> set[str]:
    tokens = []
    for token in re.findall(r"[a-zA-Z]{4,}", _normalize_text(value)):
        if token in STOPWORDS:
            continue
        if token.endswith("ies") and len(token) > 5:
            token = token[:-3] + "y"
        elif token.endswith("s") and len(token) > 5:
            token = token[:-1]
        tokens.append(token)
    return set(tokens)


def _claim_supported(claim: str, evidence_text: str) -> bool:
    claim_tokens = _meaningful_tokens(claim)
    if not claim_tokens:
        return False
    evidence_tokens = _meaningful_tokens(evidence_text)
    overlap = claim_tokens & evidence_tokens
    needed = 1 if len(claim_tokens) <= 4 else 2
    return len(overlap) >= needed


@dataclass(frozen=True)
class PersonalizationDraft:
    eligible: bool
    confidence: float
    subject: str
    body: str
    cta: str
    observations: tuple[str, ...]
    opportunity: str
    evidence: tuple[Evidence, ...]

    def payload(self) -> dict[str, Any]:
        return {
            "eligible": self.eligible,
            "confidence": self.confidence,
            "subject": self.subject,
            "body": self.body,
            "cta": self.cta,
            "observations": list(self.observations),
            "opportunity": self.opportunity,
            "evidence": [e.__dict__ for e in self.evidence],
        }


class PersonalizationValidator:
    def __init__(self, confidence_threshold: float):
        self.confidence_threshold = confidence_threshold

    def validate(self, draft: dict[str, Any], research_pages: list[dict[str, Any]], lead: dict[str, Any]) -> ValidationResult:
        reasons: list[str] = []
        if draft.get("eligible") is not True:
            reasons.append("eligible must be true")
        try:
            confidence = float(draft.get("confidence"))
        except (TypeError, ValueError):
            confidence = 0
        if confidence < self.confidence_threshold:
            reasons.append(f"confidence below {self.confidence_threshold}")
        subject = str(draft.get("subject") or "").strip()
        body = str(draft.get("body") or "").strip()
        cta = str(draft.get("cta") or "").strip()
        if not subject:
            reasons.append("subject is empty")
        if not body:
            reasons.append("body is empty")
        if not cta:
            reasons.append("cta is empty")
        if cta and not _claim_supported(cta, body):
            reasons.append("CTA is not grounded in the generated body")

        raw_evidence = draft.get("evidence")
        if not isinstance(raw_evidence, list) or not raw_evidence:
            reasons.append("evidence_count=0")
            raw_evidence = []

        page_by_url: dict[str, dict[str, Any]] = {}
        for page in research_pages:
            normalized = normalize_evidence_url(str(page.get("url") or ""))
            if normalized:
                page_by_url[normalized] = page

        normalized_evidence: list[Evidence] = []
        for item in raw_evidence[:10]:
            if not isinstance(item, dict):
                reasons.append("evidence item is not an object")
                continue
            url = normalize_evidence_url(str(item.get("url") or ""))
            snippet = re.sub(r"\s+", " ", str(item.get("snippet") or "")).strip()
            title = str(item.get("title") or "").strip()
            if not url or not snippet:
                reasons.append("evidence url/snippet missing")
                continue
            page = page_by_url.get(url)
            if page is None:
                reasons.append(f"evidence URL not recognized: {url}")
                continue
            page_text = str(page.get("text") or "")
            if _normalize_text(snippet) not in _normalize_text(page_text):
                reasons.append(f"evidence snippet not found on page: {url}")
                continue
            normalized_evidence.append(Evidence(url, snippet, title))

        evidence_text = " ".join(e.snippet for e in normalized_evidence)
        claims = [str(x).strip() for x in (draft.get("observations") or []) if str(x).strip()][:6]
        opportunity = str(draft.get("opportunity") or "").strip()
        if not claims:
            reasons.append("at least one observation is required")
        for claim in claims:
            if not _claim_supported(claim, evidence_text):
                reasons.append(f"unsupported observation: {claim[:120]}")
        if not opportunity or not _claim_supported(opportunity, evidence_text):
            reasons.append("opportunity is unsupported by evidence")
        if evidence_text and _meaningful_tokens(str(lead.get("company") or "")) and not _claim_supported(str(lead.get("company")), body + " " + evidence_text):
            reasons.append("company identity is absent from grounded message context")

        return ValidationResult(valid=not reasons, reasons=tuple(reasons), normalized_evidence=tuple(normalized_evidence))


class PersonalizationGenerator:
    SYSTEM_PROMPT = """
You write conservative, evidence-grounded outreach for a real business.
Return ONLY JSON object:
{
  "eligible": true,
  "confidence": 0.0,
  "subject": "...",
  "body": "...",
  "cta": "...",
  "observations": ["..."],
  "opportunity": "...",
  "evidence": [{"url":"...","title":"...","snippet":"..."}]
}
Every factual observation or opportunity must be supported by an exact snippet from the supplied research pages.
Do not invent capabilities, clients, services, growth, metrics, technology, pain points, locations, or claims about the recipient.
Use a specific but respectful CTA. Avoid hype. Never mention that an AI generated the message.
""".strip()

    def __init__(self, llm: LLMClient, confidence_threshold: float, repair_attempts: int = 1):
        self.llm = llm
        self.validator = PersonalizationValidator(confidence_threshold)
        self.repair_attempts = repair_attempts

    def _prompt(self, lead: dict[str, Any], research: dict[str, Any], pages: list[dict[str, Any]], previous: list[dict[str, Any]], sequence_type: str, sender_signature: str) -> str:
        page_text = "\n\n".join(f"URL={p['url']}\nTEXT={str(p.get('text') or '')[:4500]}" for p in pages)[:24000]
        history = "\n".join(f"{x.get('sequence_type')}: {x.get('subject')}" for x in previous[-3:])
        return (
            f"Sequence: {sequence_type}\nCompany: {lead['company']}\nWebsite: {lead['website']}\n"
            f"Email: {lead['email']}\nSender signature: {sender_signature}\n"
            f"Research: {json.dumps(research, ensure_ascii=False)}\n"
            f"Previous outreach history:\n{history or '(none)'}\n"
            f"Research pages:\n{page_text}"
        )

    @staticmethod
    def _parse(obj: dict[str, Any]) -> PersonalizationDraft:
        evidence: list[Evidence] = []
        for item in obj.get("evidence") or []:
            if isinstance(item, dict):
                evidence.append(Evidence(str(item.get("url") or ""), str(item.get("snippet") or ""), str(item.get("title") or "")))
        return PersonalizationDraft(
            eligible=bool(obj.get("eligible")),
            confidence=float(obj.get("confidence") or 0),
            subject=str(obj.get("subject") or "").strip(),
            body=str(obj.get("body") or "").strip(),
            cta=str(obj.get("cta") or "").strip(),
            observations=tuple(str(x).strip() for x in (obj.get("observations") or []) if str(x).strip()),
            opportunity=str(obj.get("opportunity") or "").strip(),
            evidence=tuple(evidence),
        )

    def generate(self, lead: dict[str, Any], research: dict[str, Any], pages: list[dict[str, Any]], previous: list[dict[str, Any]], sequence_type: str, sender_signature: str) -> tuple[PersonalizationDraft, ValidationResult, int]:
        raw = self.llm.chat_json_object(
            self.SYSTEM_PROMPT,
            self._prompt(lead, research, pages, previous, sequence_type, sender_signature),
            max_tokens=1100,
            operation=f"personalization_{sequence_type.lower()}",
        )
        draft = self._parse(raw)
        result = self.validator.validate(raw, pages, lead)
        attempts = 0
        while not result.valid and attempts < self.repair_attempts:
            attempts += 1
            repair_prompt = (
                f"Original JSON:\n{json.dumps(raw, ensure_ascii=False)}\n\n"
                f"Deterministic validator errors:\n- " + "\n- ".join(result.reasons) +
                "\n\nRewrite the JSON so every observation/opportunity/evidence entry is grounded in supplied page text."
            )
            raw = self.llm.chat_json_object(self.SYSTEM_PROMPT, repair_prompt, max_tokens=1100, operation=f"personalization_repair_{sequence_type.lower()}")
            draft = self._parse(raw)
            result = self.validator.validate(raw, pages, lead)
        return draft, result, attempts
