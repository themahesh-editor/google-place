from __future__ import annotations

import csv
from pathlib import Path

from app.models import Lead
from app.storage.repository import deterministic_lead_id

REQUIRED_HEADERS = {
    "Email","Company","Website","City","State","Timezone","LeadSource","Verified","PlaceId",
    "EmailSourceURL","WebsiteFacts","ScaleClass","QualificationConfidence","Status","FirstSeenDate","Notes"
}


class LeadEngineCSV:
    """Read-only compatibility adapter for the existing verified Lead CRM."""
    def __init__(self, path: str = "leads_crm.csv"):
        self.path = Path(path)

    def read_verified(self, limit: int = 100) -> list[Lead]:
        if not self.path.exists():
            return []
        with self.path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            missing = REQUIRED_HEADERS - set(reader.fieldnames or [])
            if missing:
                raise ValueError(f"Lead CRM missing required headers: {sorted(missing)}")
            result: list[Lead] = []
            for row in reader:
                if (row.get("Verified") or "").upper() != "PASS":
                    continue
                if (row.get("Status") or "").strip().lower() != "verified":
                    continue
                email = (row.get("Email") or "").strip().lower()
                website = (row.get("Website") or "").strip()
                if not email or not website:
                    continue
                try:
                    confidence = float(row.get("QualificationConfidence") or 0)
                except ValueError:
                    confidence = 0.0
                result.append(Lead(
                    lead_id=deterministic_lead_id(email, website), email=email,
                    company=(row.get("Company") or "").strip(), website=website,
                    city=(row.get("City") or "").strip(), state=(row.get("State") or "").strip(),
                    timezone=(row.get("Timezone") or "").strip() or "Asia/Kolkata",
                    lead_source=(row.get("LeadSource") or "").strip(), verified=(row.get("Verified") or "").strip(),
                    place_id=(row.get("PlaceId") or "").strip(), email_source_url=(row.get("EmailSourceURL") or "").strip(),
                    website_facts=(row.get("WebsiteFacts") or "").strip(), scale_class=(row.get("ScaleClass") or "").strip(),
                    qualification_confidence=confidence, status=(row.get("Status") or "").strip(),
                    first_seen_date=(row.get("FirstSeenDate") or "").strip(), notes=(row.get("Notes") or "").strip(),
                ))
                if len(result) >= limit:
                    break
            return result
