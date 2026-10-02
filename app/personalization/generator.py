from __future__ import annotations

from app.models import PersonalizationDraft
from app.personalization.prompts import OUTREACH_SYSTEM_PROMPT, FOLLOWUP_SYSTEM_PROMPT


class PersonalizationGenerator:
    def __init__(self,llm): self.llm=llm

    def _parse(self,obj):
        try: confidence=float(obj.get("confidence") or 0)
        except (TypeError,ValueError): confidence=0
        body=str(obj.get("body") or "").strip()[:5000]
        cta=str(obj.get("cta") or "").strip()[:500]
        signature=str(obj.get("signature") or "").strip()[:500]
        parts=[body]
        if cta and cta not in body: parts += [cta]
        if signature and signature not in body: parts += [signature]
        return PersonalizationDraft(
            eligible=bool(obj.get("eligible")),
            personalization_summary=str(obj.get("personalization_summary") or "").strip()[:1000],
            observations=[str(x).strip()[:500] for x in obj.get("observations",[]) if str(x).strip()][:6],
            opportunity=str(obj.get("opportunity") or "").strip()[:1000],
            subject=str(obj.get("subject") or "").strip()[:160],
            body="\n\n".join(parts).strip()[:5000],
            cta=cta, signature=signature, confidence=max(0,min(1,confidence)),
            evidence_urls=[str(x).strip() for x in obj.get("evidence_urls",[]) if str(x).strip()],
            risk_flags=[str(x).strip() for x in obj.get("risk_flags",[]) if str(x).strip()][:10],
        )

    def _prompt(self,lead,research,history,sequence,sender_signature):
        evidence="\n".join(f"URL: {e.url}\nTEXT: {e.snippet}" for e in research.evidence)[:14000]
        prior="\n\n".join(f"{m.get('sequence_type')}: {m.get('subject')}\n{str(m.get('body') or '')[:1200]}" for m in history[-3:]) or "(none)"
        return (f"CURRENT LEAD ONLY\nLeadID: {lead.lead_id}\nCompany: {lead.company}\nEmail: {lead.email}\nWebsite: {lead.website}\n"
          f"Location: {lead.city}, {lead.state}\nTimezone: {lead.timezone}\n\nCURRENT RESEARCH ONLY\n"
          f"Summary: {research.business_summary}\nServices: {research.services}\nTarget customers: {research.target_customers}\n"
          f"Locations: {research.locations}\nSpecialties: {research.specialties}\nWebsite signals: {research.website_signals}\n"
          f"Customer journey signals: {research.customer_journey_signals}\nAI opportunity signals: {research.ai_opportunity_signals}\n"
          f"Evidence:\n{evidence}\n\nCURRENT OUTREACH HISTORY ONLY\n{prior}\n\nSequence: {sequence}\nSender signature: {sender_signature}\nReturn JSON only.")

    def initial(self,lead,research,sender_signature):
        return self._parse(self.llm.chat_json(OUTREACH_SYSTEM_PROMPT,self._prompt(lead,research,[],"INITIAL",sender_signature),max_tokens=1400))

    def followup(self,lead,research,prior_messages,sequence_number,sender_signature):
        return self._parse(self.llm.chat_json(FOLLOWUP_SYSTEM_PROMPT,self._prompt(lead,research,prior_messages,f"FOLLOWUP_{sequence_number}",sender_signature),max_tokens=1400))
