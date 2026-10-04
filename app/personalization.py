from __future__ import annotations

import hashlib
import json
import re
from urllib.parse import urlparse

from app.llm import LLMClient
from app.models import PersonalizationDraft, ValidationResult


PLACEHOLDER_RE = re.compile(
    r"(\{\{.*?\}\}|\[(?:NAME|COMPANY|FIRST_NAME|LAST_NAME)\]|\bTODO\b)",
    re.I,
)
URL_RE = re.compile(r"https?://[^\s)\]>\"']+")
RISK_TERMS = (
    "you're losing leads",
    "you are losing leads",
    "you need ai",
    "your conversion is poor",
    "customers are waiting",
    "opportunities are being missed",
    "your competitors are using ai",
)
RETRYABLE_REASONS = frozenset(
    {
        "llm_marked_ineligible",
        "low_confidence",
        "weak_personalization",
        "personalization_anchor_not_used",
    }
)


def normalize_evidence_url(value: str) -> str:
    try:
        parsed = urlparse((value or "").strip())
        scheme = parsed.scheme.lower()
        if scheme not in {"http", "https"} or not parsed.netloc:
            return ""
        host = (parsed.hostname or "").lower().rstrip(".")
        if not host:
            return ""
        port = parsed.port
    except (TypeError, ValueError):
        return ""
    netloc = host
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = f"{host}:{port}"
    path = parsed.path.rstrip("/") or "/"
    return f"{scheme}://{netloc}{path}"


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _singularize_token(token: str) -> str:
    if len(token) > 5 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 4 and token.endswith("es"):
        return token[:-2]
    if len(token) > 4 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _meaningful_tokens(value: str) -> list[str]:
    stop = {
        "the",
        "a",
        "an",
        "and",
        "or",
        "of",
        "to",
        "for",
        "on",
        "in",
        "with",
        "their",
        "your",
        "our",
        "this",
        "that",
        "from",
        "has",
        "have",
        "is",
        "are",
        "can",
        "be",
    }
    tokens = re.findall(r"[a-z0-9]+", (value or "").lower())
    return [_singularize_token(x) for x in tokens if x not in stop and len(x) >= 3]


def _text_supports_anchor(anchor: str, text: str) -> bool:
    normalized_anchor = _normalize_text(anchor)
    normalized_text = _normalize_text(text)
    if not normalized_anchor or not normalized_text:
        return False
    if normalized_anchor in normalized_text:
        return True

    anchor_tokens = _meaningful_tokens(normalized_anchor)
    text_tokens = _meaningful_tokens(normalized_text)
    if not anchor_tokens or not text_tokens:
        return False

    span = len(anchor_tokens)
    target = [_singularize_token(x) for x in text_tokens]
    for i in range(0, max(0, len(target) - span + 1)):
        if target[i : i + span] == anchor_tokens:
            return True
    return False


def _string_list(value, limit: int | None = None, item_limit: int = 500) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        text = str(item).strip()
        if text:
            result.append(text[:item_limit])
        if limit is not None and len(result) >= limit:
            break
    return result


def _parse_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(value, (int, float)):
        return bool(value)
    return False


class PersonalizationValidator:
    def __init__(self, confidence_threshold: float):
        self.confidence_threshold = confidence_threshold

    def validate(
        self,
        lead,
        research: dict,
        draft: PersonalizationDraft,
        previous_bodies: list[str],
        store,
    ) -> ValidationResult:
        reasons: list[str] = []
        normalized = _normalize_text(draft.body)
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

        research_map = dict(research) if not isinstance(research, dict) else research
        evidence_json = research_map.get("evidence_json", "[]")
        evidence_items = json_items(evidence_json)
        allowed = {
            normalize_evidence_url(str(item.get("url") or ""))
            for item in evidence_items
            if item.get("url")
        }
        allowed.discard("")

        research_parts = [
            research_map.get("business_summary", ""),
            research_map.get("important_public_text", ""),
            research_map.get("services_json", ""),
            research_map.get("business_facts_json", ""),
            research_map.get("customer_journey_signals_json", ""),
            research_map.get("ai_opportunity_signals_json", ""),
        ]
        research_parts.extend(
            f"{item.get('url', '')} {item.get('snippet', '')}" for item in evidence_items
        )
        research_text = " ".join(str(x or "") for x in research_parts).lower()

        anchors = [_normalize_text(x) for x in draft.personalization_anchors if str(x).strip()]
        grounded_anchors = [x for x in anchors if _text_supports_anchor(x, research_text)]
        body_lower = _normalize_text(draft.body)
        body_uses_anchor = any(_text_supports_anchor(x, body_lower) for x in grounded_anchors)

        if draft.eligible and not grounded_anchors:
            reasons.append("weak_personalization")
        elif draft.eligible and not body_uses_anchor:
            reasons.append("personalization_anchor_not_used")

        normalized_draft_urls = [normalize_evidence_url(url) for url in draft.evidence_urls]
        if len(set(normalized_draft_urls)) != len(normalized_draft_urls):
            reasons.append("duplicate_evidence_urls")
        if any(not value or value not in allowed for value in normalized_draft_urls):
            reasons.append("evidence_url_not_in_current_research")
        if draft.eligible and not normalized_draft_urls:
            reasons.append("missing_evidence")

        if draft.confidence < self.confidence_threshold:
            reasons.append("low_confidence")

        if normalized and any(normalized == _normalize_text(body) for body in previous_bodies):
            reasons.append("duplicate_body")
        if store.body_hash_exists(body_hash):
            reasons.append("duplicate_body")

        website = str(lead.get("website") or "")
        host = (urlparse(website).hostname or "").lower().removeprefix("www.")
        for url in URL_RE.findall(draft.body):
            try:
                url_host = (urlparse(url).hostname or "").lower().removeprefix("www.")
            except ValueError:
                url_host = ""
            if url_host and url_host not in {host, "attachaiassistant.oneapp.dev"}:
                reasons.append("unsupported_body_url")

        lower = draft.body.lower()
        if any(term in lower for term in RISK_TERMS):
            reasons.append("unsupported_claim")
        if re.search(r"\b(?:system|developer|assistant)\s+prompt\b", lower):
            reasons.append("prompt_leakage")
        if "```json" in lower or '"eligible":' in lower or '"confidence":' in lower:
            reasons.append("json_leakage")

        unique_reasons = list(dict.fromkeys(reasons))
        retryable = bool(unique_reasons) and all(reason in RETRYABLE_REASONS for reason in unique_reasons)
        return ValidationResult(
            not unique_reasons,
            ";".join(unique_reasons),
            body_hash,
            retryable=retryable,
        )


def json_items(raw: str) -> list[dict]:
    try:
        value = json.loads(raw or "[]")
        return value if isinstance(value, list) and all(isinstance(x, dict) for x in value) else []
    except Exception:
        return []


class PersonalizationGenerator:
    SYSTEM_PROMPT = """
You write concise, factual B2B outreach for AttachAI.
Return ONLY JSON with: eligible, personalization_summary, observations, opportunity, personalization_anchors, subject, body, cta, signature, confidence, evidence_urls, risk_flags.
Use only the current lead, current research, and current outreach history supplied.
Never invent names, testimonials, technologies, integrations, customer pain, performance claims, or competitor behavior.
Never claim the company is losing leads, needs AI, has poor conversion, missed opportunities, or that competitors use AI without direct evidence.
Keep the email concise and professional. No fake urgency, fake identity, fake reply appearance, or deceptive clickbait.
Evidence URLs must come from current research.
If current research contains at least one supported business fact, service, customer-journey signal, or website signal that supports a truthful AttachAI use case, set eligible=true.
If evidence is insufficient for a truthful opportunity, set eligible=false.
Do not require the company name to appear verbatim in the email.
Return 1-3 short personalization_anchors. Each anchor must be directly supported by the supplied current research and naturally usable in the email body.
Possible use cases only when directly supported: answering common questions; handling repetitive website inquiries; helping visitors before booking; directing visitors to services; explaining services; assisting appointment/request flows; collecting basic inquiry information; helping visitors outside business hours.
""".strip()

    FOLLOWUP_SYSTEM_PROMPT = SYSTEM_PROMPT + "\nFor follow-ups, add new useful context, do not repeat the previous message verbatim, and honor the exact sequence."

    REPAIR_SYSTEM_PROMPT = """
You repair an AttachAI outreach draft using ONLY the current lead, current research, current outreach history, the prior draft, and the validator problems supplied.
Return ONLY JSON with: eligible, personalization_summary, observations, opportunity, personalization_anchors, subject, body, cta, signature, confidence, evidence_urls, risk_flags.
Fix every validator problem that can be repaired while preserving factual accuracy.
Never invent facts, names, pain points, testimonials, technologies, integrations, performance claims, or competitor behavior.
Evidence URLs must come from current research only.
Do not require the company name to appear verbatim.
A truthful research-backed business fact or service signal is enough to support eligible=true.
Personalization anchors must be directly supported by current research and must appear naturally in the body.
Keep the email concise and professional.
""".strip()

    def __init__(self, llm: LLMClient, confidence_threshold: float):
        self.llm = llm
        self.confidence_threshold = confidence_threshold

    def _build_prompt(self, lead, research: dict, history: list[dict], sequence: str, sender_signature: str) -> str:
        research_map = dict(research) if not isinstance(research, dict) else research
        evidence = "\n".join(
            f"URL: {x['url']}\nTEXT: {x.get('snippet', '')}" for x in json_items(research_map.get("evidence_json", "[]"))
        )[:14000]
        prior = "\n\n".join(
            f"{x['sequence_type']}: {x['subject']}\n{str(x.get('body') or '')[:1500]}" for x in history[-5:]
        ) or "(none)"
        return (
            f"CURRENT LEAD ONLY\nLeadID: {lead['lead_id']}\nCompany: {lead['company']}\nEmail: {lead['email']}\nWebsite: {lead['website']}\n"
            f"Location: {lead['city']}, {lead['region']} {lead['country_code']}\nTimezone: {lead['timezone']}\n\n"
            f"CURRENT RESEARCH ONLY\nSummary: {research_map.get('business_summary', '')}\nServices: {research_map.get('services_json', '')}\n"
            f"Business facts: {research_map.get('business_facts_json', '')}\nCustomer journey: {research_map.get('customer_journey_signals_json', '')}\n"
            f"AI opportunity signals: {research_map.get('ai_opportunity_signals_json', '')}\nImportant public text: {research_map.get('important_public_text', '')}\n"
            f"Evidence:\n{evidence}\n\n"
            f"CURRENT OUTREACH HISTORY ONLY\n{prior}\n\nSequence: {sequence}\nSender signature: {sender_signature}\nReturn JSON only."
        )

    def _build_repair_prompt(
        self,
        lead,
        research: dict,
        history: list[dict],
        sequence: str,
        sender_signature: str,
        draft: PersonalizationDraft,
        validation_reason: str,
    ) -> str:
        payload = {
            "eligible": draft.eligible,
            "personalization_summary": draft.personalization_summary,
            "observations": draft.observations,
            "opportunity": draft.opportunity,
            "personalization_anchors": draft.personalization_anchors,
            "subject": draft.subject,
            "body": draft.body,
            "cta": draft.cta,
            "signature": draft.signature,
            "confidence": draft.confidence,
            "evidence_urls": draft.evidence_urls,
            "risk_flags": draft.risk_flags,
        }
        return (
            self._build_prompt(lead, research, history, sequence, sender_signature)
            + f"\n\nPREVIOUS DRAFT JSON\n{json.dumps(payload, ensure_ascii=False)}"
            + f"\n\nVALIDATOR PROBLEMS TO REPAIR\n{validation_reason}\nReturn a corrected JSON draft only."
        )

    @staticmethod
    def _draft(obj: dict) -> PersonalizationDraft:
        try:
            confidence = max(0.0, min(1.0, float(obj.get("confidence") or 0)))
        except (TypeError, ValueError):
            confidence = 0.0

        subject = str(obj.get("subject") or "").strip()
        raw_body = str(obj.get("body") or "").strip()
        cta = str(obj.get("cta") or "").strip()
        signature = str(obj.get("signature") or "").strip()
        body = raw_body
        if body and cta and cta not in body:
            body += "\n\n" + cta
        if body and signature and signature not in body:
            body += "\n\n" + signature

        return PersonalizationDraft(
            eligible=_parse_bool(obj.get("eligible")),
            personalization_summary=str(obj.get("personalization_summary") or "").strip()[:1000],
            observations=_string_list(obj.get("observations"), limit=6, item_limit=500),
            opportunity=str(obj.get("opportunity") or "").strip()[:1000],
            subject=subject,
            body=body,
            cta=cta,
            signature=signature,
            confidence=confidence,
            evidence_urls=_string_list(obj.get("evidence_urls"), limit=None, item_limit=2000),
            risk_flags=_string_list(obj.get("risk_flags"), limit=10, item_limit=500),
            personalization_anchors=_string_list(obj.get("personalization_anchors"), limit=3, item_limit=500),
        )

    def initial(self, lead, research: dict, sender_signature: str) -> PersonalizationDraft:
        return self._draft(
            self.llm.chat_json_object(
                self.SYSTEM_PROMPT,
                self._build_prompt(lead, research, [], "INITIAL", sender_signature),
                max_tokens=1400,
            )
        )

    def followup(self, lead, research: dict, history: list[dict], sequence: str, sender_signature: str) -> PersonalizationDraft:
        return self._draft(
            self.llm.chat_json_object(
                self.FOLLOWUP_SYSTEM_PROMPT,
                self._build_prompt(lead, research, history, sequence, sender_signature),
                max_tokens=1400,
            )
        )

    def repair_initial(
        self,
        lead,
        research: dict,
        draft: PersonalizationDraft,
        validation_reason: str,
        sender_signature: str,
    ) -> PersonalizationDraft:
        return self._repair(
            lead,
            research,
            [],
            "INITIAL",
            sender_signature,
            draft,
            validation_reason,
        )

    def repair_followup(
        self,
        lead,
        research: dict,
        history: list[dict],
        sequence: str,
        draft: PersonalizationDraft,
        validation_reason: str,
        sender_signature: str,
    ) -> PersonalizationDraft:
        return self._repair(
            lead,
            research,
            history,
            sequence,
            sender_signature,
            draft,
            validation_reason,
        )

    def _repair(
        self,
        lead,
        research: dict,
        history: list[dict],
        sequence: str,
        sender_signature: str,
        draft: PersonalizationDraft,
        validation_reason: str,
    ) -> PersonalizationDraft:
        return self._draft(
            self.llm.chat_json_object(
                self.REPAIR_SYSTEM_PROMPT,
                self._build_repair_prompt(
                    lead,
                    research,
                    history,
                    sequence,
                    sender_signature,
                    draft,
                    validation_reason,
                ),
                max_tokens=1400,
            )
        )
