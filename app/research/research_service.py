from __future__ import annotations

from datetime import datetime, timezone

from app.llm.client import LLMClient, LLMTemporaryError
from app.models import Evidence, Lead, WebsiteResearch
from app.storage.repository import deterministic_research_id

RESEARCH_SYSTEM_PROMPT = """
You are a website research analyst for AttachAI.
Return ONLY JSON with keys: business_summary, services, target_customers, locations, specialties, website_signals, customer_journey_signals, ai_opportunity_signals, evidence_urls.
Use only the current lead and current website evidence supplied in the request. Do not use memory from any other company. Do not infer unsupported pain points. Each signal must be grounded in supplied evidence. evidence_urls must be a subset of supplied URLs.
""".strip()


class ResearchService:
    def __init__(self,store,llm,crawler,prompt_version):
        self.store=store; self.llm=llm; self.crawler=crawler; self.prompt_version=prompt_version

    def run_one(self,lead:Lead)->WebsiteResearch:
        ts=datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z")
        self.store.set_lead_status(lead.lead_id,"RESEARCHING")
        pages=self.crawler.research(lead.website)
        evidence=[Evidence(p.url,p.text[:1800]) for p in pages if p.text]
        if not evidence:
            r=WebsiteResearch(deterministic_research_id(lead.lead_id,ts),lead.lead_id,ts,"",[],[],[],[],[],[],[],[],"FAILED",self.prompt_version)
            self.store.save_research(r); self.store.set_lead_status(lead.lead_id,"ELIGIBLE"); return r
        blob="\n\n".join(f"URL: {e.url}\nTEXT: {e.snippet}" for e in evidence)[:14000]
        prompt=(f"CURRENT LEAD ONLY\nLeadID: {lead.lead_id}\nCompany: {lead.company}\nEmail: {lead.email}\nWebsite: {lead.website}\n"
                f"City: {lead.city}\nState: {lead.state}\nExisting CRM website facts: {lead.website_facts[:2500]}\n\nCURRENT WEBSITE EVIDENCE ONLY\n{blob}")
        try:
            obj=self.llm.chat_json(RESEARCH_SYSTEM_PROMPT,prompt,max_tokens=1400)
        except LLMTemporaryError:
            r=WebsiteResearch(deterministic_research_id(lead.lead_id,ts),lead.lead_id,ts,"",[],[],[],[],[],[],[],evidence,"PARTIAL_LLM_FAILURE",self.prompt_version)
            self.store.save_research(r); self.store.set_lead_status(lead.lead_id,"ELIGIBLE"); return r
        allowed={e.url for e in evidence}
        urls=[u.strip() for u in obj.get("evidence_urls",[]) if isinstance(u,str) and u.strip() in allowed]
        if not urls:
            urls=[e.url for e in evidence[:3]]
        selected=[e for e in evidence if e.url in urls]
        def arr(k,limit=12,maxlen=220):
            return [str(x).strip()[:maxlen] for x in obj.get(k,[]) if str(x).strip()][:limit]
        r=WebsiteResearch(deterministic_research_id(lead.lead_id,ts),lead.lead_id,ts,
            str(obj.get("business_summary") or "").strip()[:1200],arr("services"),arr("target_customers"),arr("locations"),arr("specialties"),
            arr("website_signals"),arr("customer_journey_signals"),arr("ai_opportunity_signals"),selected,"RESEARCHED",self.prompt_version)
        self.store.save_research(r); self.store.set_lead_status(lead.lead_id,"RESEARCHED"); return r
