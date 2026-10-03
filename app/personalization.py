from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from urllib.parse import urlparse

from app.llm import LLMClient, LLMTemporaryError
from app.models import PersonalizationDraft, ValidationResult

PLACEHOLDER_RE = re.compile(r"(\{\{.*?\}\}|\[(?:NAME|COMPANY|FIRST_NAME|LAST_NAME)\]|\bTODO\b)", re.I)
URL_RE = re.compile(r"https?://[^\s)\]>\"']+")
RISK_TERMS = (
    "you're losing leads", "you are losing leads", "you need ai", "your conversion is poor",
    "customers are waiting", "opportunities are being missed", "your competitors are using ai",
)


class PersonalizationValidator:
    def __init__(self, confidence_threshold: float):
        self.confidence_threshold = confidence_threshold

    def validate(self, lead, research: dict, draft: PersonalizationDraft, previous_bodies: list[str], store) -> ValidationResult:
        reasons: list[str] = []
        normalized = re.sub(r"\s+", " ", draft.body.strip().lower())
        body_hash = hashlib.sha256(normalized.encode()).hexdigest()
        if not draft.eligible:
            reasons.append("llm_marked_ineligible")
        if not draft.subject.strip():
            reasons.append("empty_subject")
        if not draft.body.strip():
            reasons.append("empty_body")
        if len(draft.subject) > 160:
            reasons.append("subject_too_long")
        if len(draft.body) > 5000:
            reasons.append("body_too_long")
        if PLACEHOLDER_RE.search(draft.subject + "\n" + draft.body):
            reasons.append("placeholder")
        evidence_json = research["evidence_json"] if "evidence_json" in research.keys() else "[]"
        allowed = {json_item["url"] for json_item in json_items(evidence_json)}
        if len(set(draft.evidence_urls)) != len(draft.evidence_urls):
            reasons.append("duplicate_evidence_urls")
        if any(url not in allowed for url in draft.evidence_urls):
            reasons.append("evidence_url_not_in_current_research")
        if draft.eligible and not draft.evidence_urls:
            reasons.append("missing_evidence")
        if draft.confidence < self.confidence_threshold:
            reasons.append("low_confidence")
        if normalized and any(normalized == re.sub(r"\s+", " ", body.strip().lower()) for body in previous_bodies):
            reasons.append("duplicate_body")
        if store.body_hash_exists(body_hash):
            reasons.append("duplicate_body")
        if lead["company"] and lead["company"].lower() not in draft.body.lower():
            reasons.append("company_not_personalized")
        host = (urlparse(lead["website"]).hostname or "").lower().removeprefix("www.")
        for url in URL_RE.findall(draft.body):
            url_host = (urlparse(url).hostname or "").lower().removeprefix("www.")
            if url_host and url_host not in {host, "attachaiassistant.oneapp.dev"}:
                reasons.append("unsupported_body_url")
        lower = draft.body.lower()
        if any(term in lower for term in RISK_TERMS):
            reasons.append("unsupported_claim")
        if re.search(r"\b(?:system|developer|assistant)\s+prompt\b", lower):
            reasons.append("prompt_leakage")
        if "```json" in lower or '"eligible":' in lower or '"confidence":' in lower:
            reasons.append("json_leakage")
        return ValidationResult(not reasons, ";".join(dict.fromkeys(reasons)), body_hash)


def json_items(raw: str) -> list[dict]:
    try:
        import json
        value = json.loads(raw or "[]")
        return value if isinstance(value, list) and all(isinstance(x, dict) for x in value) else []
    except Exception:
        return []


class PersonalizationGenerator:
    SYSTEM_PROMPT = """
You write concise, factual B2B outreach for AttachAI.
Return ONLY JSON with: eligible, personalization_summary, observations, opportunity, subject, body, cta, signature, confidence, evidence_urls, risk_flags.
Use only the current lead, current research, and current outreach history supplied.
Never invent names, testimonials, technologies, integrations, customer pain, performance claims, or competitor behavior.
Never claim the company is losing leads, needs AI, has poor conversion, missed opportunities, or that competitors use AI without direct evidence.
Keep the email concise and professional. No fake urgency, fake identity, fake reply appearance, or deceptive clickbait.
Evidence URLs must come from current research. If evidence is insufficient for a truthful opportunity, set eligible=false.
Possible use cases only when directly supported: answering common questions; handling repetitive website inquiries; helping visitors before booking; directing visitors to services; explaining services; assisting appointment/request flows; collecting basic inquiry information; helping visitors outside business hours.
""".strip()

    FOLLOWUP_SYSTEM_PROMPT = SYSTEM_PROMPT + "\nFor follow-ups, add new useful context, do not repeat the previous message verbatim, and honor the exact sequence."

    def __init__(self, llm: LLMClient, confidence_threshold: float):
        self.llm = llm
        self.confidence_threshold = confidence_threshold

    def _build_prompt(self, lead, research: dict, history: list[dict], sequence: str, sender_signature: str) -> str:
        import json
        evidence = "\n".join(f"URL: {x['url']}\nTEXT: {x.get('snippet','')}" for x in json_items(research.get("evidence_json", "[]")))[:14000]
        prior = "\n\n".join(f"{x['sequence_type']}: {x['subject']}\n{str(x.get('body') or '')[:1500]}" for x in history[-5:]) or "(none)"
        return (
            f"CURRENT LEAD ONLY\nLeadID: {lead['lead_id']}\nCompany: {lead['company']}\nEmail: {lead['email']}\nWebsite: {lead['website']}\n"
            f"Location: {lead['city']}, {lead['region']} {lead['country_code']}\nTimezone: {lead['timezone']}\n\n"
            f"CURRENT RESEARCH ONLY\nSummary: {research.get('business_summary','')}\nServices: {research.get('services_json','')}\n"
            f"Business facts: {research.get('business_facts_json','')}\nCustomer journey: {research.get('customer_journey_signals_json','')}\n"
            f"AI opportunity signals: {research.get('ai_opportunity_signals_json','')}\nEvidence:\n{evidence}\n\n"
            f"CURRENT OUTREACH HISTORY ONLY\n{prior}\n\nSequence: {sequence}\nSender signature: {sender_signature}\nReturn JSON only."
        )

    @staticmethod
    def _draft(obj: dict) -> PersonalizationDraft:
        try:
            confidence = max(0.0, min(1.0, float(obj.get("confidence") or 0)))
        except (TypeError, ValueError):
            confidence = 0.0
        body = str(obj.get("body") or "").strip()[:5000]
        cta = str(obj.get("cta") or "").strip()[:500]
        signature = str(obj.get("signature") or "").strip()[:500]
        if cta and cta not in body:
            body += "\n\n" + cta
        if signature and signature not in body:
            body += "\n\n" + signature
        return PersonalizationDraft(
            bool(obj.get("eligible")), str(obj.get("personalization_summary") or "").strip()[:1000],
            [str(x).strip()[:500] for x in obj.get("observations", []) if str(x).strip()][:6],
            str(obj.get("opportunity") or "").strip()[:1000], str(obj.get("subject") or "").strip()[:160], body[:5000],
            cta, signature, confidence, [str(x).strip() for x in obj.get("evidence_urls", []) if str(x).strip()],
            [str(x).strip() for x in obj.get("risk_flags", []) if str(x).strip()][:10],
        )

    def initial(self, lead, research: dict, sender_signature: str) -> PersonalizationDraft:
        return self._draft(self.llm.chat_json_object(self.SYSTEM_PROMPT, self._build_prompt(lead, research, [], "INITIAL", sender_signature), max_tokens=1400))

    def followup(self, lead, research: dict, history: list[dict], sequence: str, sender_signature: str) -> PersonalizationDraft:
        return self._draft(self.llm.chat_json_object(self.FOLLOWUP_SYSTEM_PROMPT, self._build_prompt(lead, research, history, sequence, sender_signature), max_tokens=1400))
