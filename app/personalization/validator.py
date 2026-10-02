from __future__ import annotations
import hashlib,re
from dataclasses import dataclass
from urllib.parse import urlparse

PLACEHOLDER_RE=re.compile(r'(\{\{.*?\}\}|\[(?:NAME|COMPANY|FIRST_NAME|LAST_NAME)\]|\bTODO\b)',re.I)
URL_RE=re.compile(r'https?://[^\s)\]>"\']+')
RISK_TERMS=("you're losing leads","you are losing leads","you need ai","your conversion is poor","customers are waiting","opportunities are being missed","your competitors are using ai")
@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    reason: str
    body_hash: str

class PersonalizationValidator:
    def __init__(self,prompt_version='1.0'):self.prompt_version=prompt_version
    def validate(self,lead,research,draft,previous_bodies=None,store=None,**kwargs):
        reasons=[]; body_hash=hashlib.sha256(re.sub(r'\s+',' ',(draft.body or '').strip().lower()).encode()).hexdigest()
        if not draft.eligible:reasons.append('llm_marked_ineligible')
        if not draft.subject.strip():reasons.append('empty_subject')
        if not draft.body.strip():reasons.append('empty_body')
        if len(draft.subject)>160:reasons.append('subject_too_long')
        if len(draft.body)>5000:reasons.append('body_too_long')
        if PLACEHOLDER_RE.search(draft.subject+'\n'+draft.body):reasons.append('placeholder')
        allowed={e.url for e in research.evidence}
        if len(set(draft.evidence_urls))!=len(draft.evidence_urls):reasons.append('duplicate_evidence_urls')
        if any(u not in allowed for u in draft.evidence_urls):reasons.append('evidence_url_not_in_current_research')
        if draft.eligible and not draft.evidence_urls:reasons.append('missing_evidence')
        if draft.confidence<0.75:reasons.append('low_confidence')
        prior=[(x or '').strip().lower() for x in (previous_bodies or [])]
        normalized=re.sub(r'\s+',' ',(draft.body or '').strip().lower())
        if normalized and any(normalized==p for p in prior):reasons.append('duplicate_body')
        if store is not None and getattr(store,'body_hash_exists',lambda _:False)(body_hash):reasons.append('duplicate_body')
        if lead.company and lead.company.lower() not in draft.body.lower():reasons.append('company_not_personalized')
        site=(urlparse(lead.website).hostname or '').lower().removeprefix('www.')
        for url in URL_RE.findall(draft.body):
            host=(urlparse(url).hostname or '').lower().removeprefix('www.')
            if host and host not in {site,'attachaiassistant.oneapp.dev'}:reasons.append('unsupported_body_url')
        low=draft.body.lower()
        if any(x in low for x in RISK_TERMS):reasons.append('unsupported_claim')
        if re.search(r'\b(?:system|developer|assistant)\s+prompt\b',low):reasons.append('prompt_leakage')
        if '```json' in low or '"eligible":' in low or '"confidence":' in low:reasons.append('json_leakage')
        return ValidationResult(not reasons,';'.join(dict.fromkeys(reasons)),body_hash)

def normalized_body_hash(body:str)->str:return hashlib.sha256(re.sub(r'\s+',' ',(body or '').strip().lower()).encode()).hexdigest()
def validate_draft(*args,**kwargs):
    return PersonalizationValidator().validate(*args,**kwargs)
