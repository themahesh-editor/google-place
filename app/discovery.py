from __future__ import annotations

import datetime as dt
import json
import os
import random
import re
import threading
import time
from dataclasses import dataclass
from typing import Any

import dns.resolver
import requests

from .db import deterministic_lead_id, normalize_domain, now_utc
from .debug import debug
from .llm import LLMClient, LLMTemporaryError, LLMInvalidResponse, LLMPermanentError
from .research import WebsiteCrawler, choose_public_business_email, canonicalize

US_REGIONS = {
    "AL":"America/Chicago","AK":"America/Anchorage","AZ":"America/Phoenix","AR":"America/Chicago","CA":"America/Los_Angeles","CO":"America/Denver","CT":"America/New_York","DE":"America/New_York","FL":"America/New_York","GA":"America/New_York","HI":"Pacific/Honolulu","IA":"America/Chicago","ID":"America/Boise","IL":"America/Chicago","IN":"America/Indiana/Indianapolis","KS":"America/Chicago","KY":"America/New_York","LA":"America/Chicago","MA":"America/New_York","MD":"America/New_York","ME":"America/New_York","MI":"America/Detroit","MN":"America/Chicago","MO":"America/Chicago","MS":"America/Chicago","MT":"America/Denver","NC":"America/New_York","ND":"America/Chicago","NE":"America/Chicago","NH":"America/New_York","NJ":"America/New_York","NM":"America/Denver","NV":"America/Los_Angeles","NY":"America/New_York","OH":"America/New_York","OK":"America/Chicago","OR":"America/Los_Angeles","PA":"America/New_York","RI":"America/New_York","SC":"America/New_York","SD":"America/Chicago","TN":"America/Chicago","TX":"America/Chicago","UT":"America/Denver","VA":"America/New_York","VT":"America/New_York","WA":"America/Los_Angeles","WI":"America/Chicago","WV":"America/New_York","WY":"America/Denver",
}
CA_REGIONS = {"AB":"America/Edmonton","BC":"America/Vancouver","MB":"America/Winnipeg","NB":"America/Moncton","NL":"America/St_Johns","NS":"America/Halifax","NT":"America/Yellowknife","NU":"America/Iqaluit","ON":"America/Toronto","PE":"America/Halifax","QC":"America/Toronto","SK":"America/Regina","YT":"America/Whitehorse"}
AU_REGIONS = {"NSW":"Australia/Sydney","VIC":"Australia/Melbourne","QLD":"Australia/Brisbane","WA":"Australia/Perth","SA":"Australia/Adelaide","TAS":"Australia/Hobart","NT":"Australia/Darwin","ACT":"Australia/Sydney"}

TARGET_CITIES = (
    "Dallas TX", "Fort Worth TX", "Houston TX", "Austin TX", "San Antonio TX", "Orlando FL", "Tampa FL", "Jacksonville FL", "Miami FL", "Atlanta GA",
    "Charlotte NC", "Nashville TN", "Phoenix AZ", "Denver CO", "Las Vegas NV", "Los Angeles CA", "San Diego CA", "Sacramento CA", "Chicago IL", "Columbus OH",
    "Indianapolis IN", "Cleveland OH", "Kansas City MO", "Raleigh NC", "Richmond VA", "Seattle WA", "Portland OR", "Salt Lake City UT", "Minneapolis MN", "Boston MA",
    "Toronto Canada", "Vancouver Canada", "Montreal Canada", "Calgary Canada", "Ottawa Canada", "Edmonton Canada", "London UK", "Manchester UK", "Birmingham UK", "Leeds UK",
    "Liverpool UK", "Glasgow UK", "Sydney Australia", "Melbourne Australia", "Brisbane Australia", "Perth Australia", "Adelaide Australia",
)

BLOCKED_QUERY_WORDS = {"reviews", "review", "price", "cost", "cheapest", "discount", "special", "jobs", "employment"}
BLOCKED_EMAIL_LOCAL_PARTS = {"noreply", "no-reply", "donotreply", "do-not-reply", "mailer-daemon", "abuse", "postmaster"}


@dataclass(frozen=True)
class Candidate:
    place_id: str
    company: str
    website: str
    address: str
    types: tuple[str, ...]
    query: str
    country_code: str


@dataclass(frozen=True)
class CandidateEvaluation:
    outcome: str
    candidate_id: str
    candidate: Candidate
    reason: str = ""
    email: str = ""
    email_source_url: str = ""
    qualification: dict[str, Any] | None = None
    facts: str = ""
    lead: dict[str, Any] | None = None
    retry_seconds: int = 0


def state_or_region_from_address(address: str, country_code: str) -> str:
    if country_code == "US":
        m = re.search(r",\s*([A-Z]{2})(?:\s+\d{5}(?:-\d{4})?)?\b", address or "")
        return m.group(1).upper() if m else ""
    if country_code == "CA":
        m = re.search(r",\s*(AB|BC|MB|NB|NL|NS|NT|NU|ON|PE|QC|SK|YT)\b", address or "", re.I)
        return m.group(1).upper() if m else ""
    if country_code == "AU":
        m = re.search(r",\s*(NSW|VIC|QLD|WA|SA|TAS|NT|ACT)\b", address or "", re.I)
        return m.group(1).upper() if m else ""
    if country_code == "GB":
        return "LND" if re.search(r"\bLondon\b", address or "", re.I) else ""
    return ""


def city_from_address(address: str, region: str) -> str:
    text = re.sub(r"\s+", " ", address or "").strip()
    if region:
        m = re.search(r",\s*([^,]+),\s*" + re.escape(region) + r"\b", text, re.I)
        if m:
            return m.group(1).strip()
    parts = [p.strip() for p in text.split(",") if p.strip()]
    return parts[-2] if len(parts) >= 2 else (parts[0] if parts else "")


def location_timezone(country_code: str, region: str, city: str) -> str:
    if country_code == "US":
        return US_REGIONS.get(region, "America/New_York")
    if country_code == "CA":
        return CA_REGIONS.get(region, "America/Toronto")
    if country_code == "AU":
        return AU_REGIONS.get(region, "Australia/Sydney")
    if country_code == "GB":
        return "Europe/London"
    return "UTC"


def validate_qualification_schema(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LLMInvalidResponse("qualification must return an object")
    required = {"action", "company_name", "scale_class", "confidence", "reason"}
    missing = sorted(required - set(value))
    if missing:
        raise LLMInvalidResponse("qualification missing fields: " + ", ".join(missing))
    action = str(value.get("action") or "").upper()
    scale_class = str(value.get("scale_class") or "").upper()
    try:
        confidence = float(value.get("confidence"))
    except (TypeError, ValueError) as exc:
        raise LLMInvalidResponse("qualification confidence must be numeric") from exc
    if action not in {"KEEP", "REJECT"}:
        raise LLMInvalidResponse("qualification action must be KEEP or REJECT")
    if scale_class not in {"LOCAL", "REGIONAL"}:
        raise LLMInvalidResponse("qualification scale_class must be LOCAL or REGIONAL")
    if not 0 <= confidence <= 1:
        raise LLMInvalidResponse("qualification confidence must be between 0 and 1")
    company_name = str(value.get("company_name") or "").strip()
    reason = str(value.get("reason") or "").strip()
    if not company_name or not reason:
        raise LLMInvalidResponse("qualification company_name/reason must be non-empty")
    return {"action": action, "company_name": company_name, "scale_class": scale_class, "confidence": confidence, "reason": reason}


class DiscoveryService:
    QUALIFY_SYSTEM = """
You are a conservative business lead classifier.
Return ONLY JSON object:
{"action":"KEEP|REJECT","company_name":"...","scale_class":"LOCAL|REGIONAL","confidence":0.0,"reason":"..."}
KEEP only when the business clearly matches the requested business query and appears to be a real local or regional business.
Use only the supplied candidate and website evidence. Do not invent facts. Reject thin, irrelevant, closed, or non-business results.
""".strip()

    def __init__(self, store, llm: LLMClient, crawler: WebsiteCrawler, settings):
        self.store = store
        self.llm = llm
        self.crawler = crawler
        self.settings = settings
        self.http = requests.Session()
        self.http.headers.update({"Content-Type": "application/json", "Accept-Language": "en-US,en;q=0.8"})
        self.mx_cache: dict[str, bool] = {}
        self.mx_lock = threading.Lock()

    def query_cycle(self) -> list[str]:
        queries: list[str] = []
        for seed in self.settings.discovery_queries:
            for city in TARGET_CITIES:
                queries.append(f"{seed} in {city}")
        # Stable shuffle avoids hammering the same city/category every run while remaining reproducible.
        random.Random(dt.date.today().toordinal()).shuffle(queries)
        return queries

    def places_search(self, query: str, remaining_budget: int) -> tuple[list[dict[str, Any]], int]:
        api_key = os.getenv("GOOGLE_PLACES_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("GOOGLE_PLACES_API_KEY is missing")
        results: list[dict[str, Any]] = []
        token: str | None = None
        used = 0
        for _ in range(self.settings.discovery_max_pages_per_query):
            if used >= remaining_budget:
                break
            payload: dict[str, Any] = {"textQuery": query, "pageSize": self.settings.places_page_size, "languageCode": "en"}
            if token:
                payload["pageToken"] = token
            response = None
            for attempt in range(3):
                try:
                    response = self.http.post(
                        "https://places.googleapis.com/v1/places:searchText",
                        headers={
                            "X-Goog-Api-Key": api_key,
                            "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,places.postalAddress,places.addressComponents,places.websiteUri,places.types,places.businessStatus,nextPageToken",
                        },
                        json=payload,
                        timeout=self.settings.crawler_timeout_seconds,
                    )
                    used += 1
                    if response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                        time.sleep(2 * (attempt + 1))
                        continue
                    if response.status_code >= 400:
                        return results, used
                    break
                except requests.RequestException:
                    if attempt == 2:
                        return results, used
                    time.sleep(2 * (attempt + 1))
            if response is None:
                break
            body = response.json()
            results.extend(body.get("places") or [])
            token = body.get("nextPageToken")
            if not token:
                break
            time.sleep(0.5)
        return results, used

    def candidate_from_place(self, place: dict[str, Any], query: str) -> Candidate | None:
        place_id = str(place.get("id") or "").strip()
        company = str((place.get("displayName") or {}).get("text") or "").strip()
        website = canonicalize(str(place.get("websiteUri") or ""))
        address = str(place.get("formattedAddress") or "").strip()
        business_status = str(place.get("businessStatus") or "").upper()
        postal = place.get("postalAddress") or {}
        country = str(postal.get("regionCode") or "").upper().strip()
        if not country:
            for component in place.get("addressComponents") or []:
                if "country" in (component.get("types") or []):
                    country = str(component.get("shortText") or component.get("longText") or "").upper().strip()
                    break
        if business_status in {"CLOSED", "CLOSED_PERMANENTLY"}:
            return None
        if not place_id or not company or not website or not address or country not in self.settings.allowed_country_codes:
            return None
        return Candidate(place_id, company, website, address, tuple(str(x) for x in (place.get("types") or [])), query, country)

    def discover_raw(self, run_id: str, minimum_new_candidates: int, request_budget: int | None = None) -> dict[str, int]:
        existing = int(self.store.scalar("SELECT count(*) FROM discovery_candidate WHERE created_at_utc >= ?", [now_utc().replace(hour=0, minute=0, second=0)], 0))
        budget = self.settings.discovery_max_places_requests if request_budget is None else max(0, int(request_budget))
        raw = 0
        inserted = 0
        duplicate = 0
        queries_used = 0
        candidates_seen_this_call: set[str] = set()
        for query in self.query_cycle():
            if budget <= 0 or inserted >= max(minimum_new_candidates, 1) or existing + inserted >= self.settings.max_candidates_per_run:
                break
            if any(word in query.lower().split() for word in BLOCKED_QUERY_WORDS):
                continue
            places, used = self.places_search(query, budget)
            budget -= used
            queries_used += 1
            raw += len(places)
            for place in places:
                candidate = self.candidate_from_place(place, query)
                if not candidate or candidate.place_id in candidates_seen_this_call:
                    if candidate:
                        duplicate += 1
                    continue
                candidates_seen_this_call.add(candidate.place_id)
                _, fresh = self.store.upsert_candidate(
                    place_id=candidate.place_id,
                    company=candidate.company,
                    website=candidate.website,
                    address=candidate.address,
                    country_code=candidate.country_code,
                    types=list(candidate.types),
                    query=candidate.query,
                )
                if fresh:
                    inserted += 1
                else:
                    duplicate += 1
            if inserted >= minimum_new_candidates:
                break
        debug("DISCOVERY_RAW", run_id=run_id, raw=raw, inserted=inserted, duplicate=duplicate, queries_used=queries_used, places_requests_used=self.settings.discovery_max_places_requests - budget)
        return {"raw_candidates": raw, "deduplicated_candidates": inserted, "queries_used": queries_used, "places_requests_used": self.settings.discovery_max_places_requests - budget}

    def _has_mx(self, domain: str) -> bool:
        domain = normalize_domain(domain)
        with self.mx_lock:
            if domain in self.mx_cache:
                return self.mx_cache[domain]
        try:
            answer = dns.resolver.resolve(domain, "MX", lifetime=5)
            value = any(getattr(x, "exchange", None) for x in answer)
        except Exception:
            value = False
        with self.mx_lock:
            self.mx_cache[domain] = value
        return value

    def _evaluate_candidate(self, row: Any, run_id: str) -> CandidateEvaluation:
        candidate = Candidate(
            str(row["place_id"]), str(row["company"]), str(row["website"]), str(row["address"]),
            tuple(json.loads(row["types_json"] or "[]")), str(row["query"]), str(row["country_code"]),
        )
        cid = str(row["candidate_id"])
        try:
            pages = self.crawler.crawl(candidate.website)
            if not pages:
                return CandidateEvaluation("retry", cid, candidate, "website_inaccessible", retry_seconds=self.settings.candidate_retry_hours * 3600)
            email_choice = choose_public_business_email(pages, candidate.website, self._has_mx)
            if not email_choice:
                return CandidateEvaluation("retry", cid, candidate, "no_public_business_email", retry_seconds=self.settings.candidate_no_email_retry_days * 86400)
            email, source_url = email_choice
            if self.store.get_lead_by_email(email) is not None:
                return CandidateEvaluation("rejected", cid, candidate, "email_already_has_lead", email=email, email_source_url=source_url)
            facts = "\n".join(f"URL: {p.url}\nTEXT: {p.text[:2200]}" for p in pages if p.text)[:14000]
            obj = self.llm.chat_json_object(
                self.QUALIFY_SYSTEM,
                f"Target query: {candidate.query}\nCompany: {candidate.company}\nAddress: {candidate.address}\nCountry: {candidate.country_code}\nWebsite: {candidate.website}\nPublic email: {email}\nWebsite evidence:\n{facts}",
                max_tokens=500,
                operation="discovery_qualification",
            )
            obj = validate_qualification_schema(obj)
            action = obj["action"]
            confidence = obj["confidence"]
            scale = obj["scale_class"]
            if action != "KEEP" or confidence < 0.60 or scale not in {"LOCAL", "REGIONAL"}:
                return CandidateEvaluation("rejected", cid, candidate, str(obj.get("reason") or "qualification_rejected"), email=email, email_source_url=source_url, qualification=obj, facts=facts)
            region = state_or_region_from_address(candidate.address, candidate.country_code)
            city = city_from_address(candidate.address, region)
            lead = {
                "lead_id": deterministic_lead_id(email, candidate.place_id),
                "email": email,
                "company": str(obj.get("company_name") or candidate.company),
                "website": candidate.website,
                "website_domain": normalize_domain(candidate.website),
                "place_id": candidate.place_id,
                "city": city,
                "region": region,
                "country_code": candidate.country_code,
                "timezone": location_timezone(candidate.country_code, region, city),
                "lead_source": "Google Places Text Search -> canonical website research",
                "scale_class": scale,
                "qualification_confidence": confidence,
                "qualification_reason": str(obj.get("reason") or "").strip(),
                "discovery_facts": facts[:8000],
                "status": "ELIGIBLE",
            }
            return CandidateEvaluation("verified", cid, candidate, "verified", email=email, email_source_url=source_url, qualification=obj, facts=facts, lead=lead)
        except (LLMTemporaryError, LLMInvalidResponse) as exc:
            return CandidateEvaluation("retry", cid, candidate, f"llm_temporary_or_invalid:{exc}", retry_seconds=self.settings.candidate_retry_hours * 3600)
        except LLMPermanentError as exc:
            return CandidateEvaluation("rejected", cid, candidate, f"llm_permanent_failure:{exc}")
        except Exception as exc:
            return CandidateEvaluation("retry", cid, candidate, f"candidate_error:{exc.__class__.__name__}:{exc}", retry_seconds=self.settings.candidate_retry_hours * 3600)

    def process_candidates(self, run_id: str, rows: list[Any], max_workers: int = 10) -> dict[str, int]:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        counts = {"qualified": 0, "rejected": 0, "retryable": 0, "verified": 0, "duplicates": 0}
        if not rows:
            return counts
        with ThreadPoolExecutor(max_workers=min(max_workers, 10)) as pool:
            futures = {pool.submit(self._evaluate_candidate, row, run_id): row for row in rows}
            for future in as_completed(futures):
                result = future.result()
                row = futures[future]
                cid = result.candidate_id
                attempts = int(row["attempts"] or 0) + 1
                if result.outcome == "verified" and result.lead:
                    try:
                        existing_email = self.store.get_lead_by_email(result.lead["email"])
                        existing_place = self.store.get_lead_by_place_id(result.lead["place_id"])
                        if existing_email or existing_place:
                            counts["duplicates"] += 1
                            self.store.set_candidate_result(cid, "VERIFIED", reason="lead_identity_already_exists")
                            continue
                        self.store.upsert_lead(result.lead)
                        q = result.qualification or {}
                        self.store.insert_qualification(result.lead["lead_id"], "KEEP", float(q.get("confidence") or 0), str(q.get("reason") or ""), run_id, [result.email_source_url])
                        self.store.set_candidate_result(cid, "VERIFIED", reason="verified")
                        self.store.add_event("candidate_verified", run_id=run_id, lead_id=result.lead["lead_id"], metadata={"place_id": result.candidate.place_id, "email_source_url": result.email_source_url})
                        counts["qualified"] += 1
                        counts["verified"] += 1
                    except Exception as exc:
                        self.store.set_candidate_result(cid, "RETRYABLE", reason=f"persist_failure:{exc}", next_retry_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=self.settings.retry_base_seconds), increment_attempt=True)
                        counts["retryable"] += 1
                elif result.outcome == "rejected":
                    self.store.set_candidate_result(cid, "REJECTED", reason=result.reason, increment_attempt=True)
                    if result.email:
                        self.store.add_event("candidate_rejected", run_id=run_id, reason=result.reason, metadata={"place_id": result.candidate.place_id, "email": result.email})
                    counts["rejected"] += 1
                else:
                    if attempts >= self.settings.candidate_retry_limit:
                        self.store.set_candidate_result(cid, "REJECTED", reason="retry_limit_exceeded", increment_attempt=True)
                        counts["rejected"] += 1
                    else:
                        next_retry = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=max(result.retry_seconds, self.settings.retry_base_seconds))
                        self.store.set_candidate_result(cid, "RETRYABLE", reason=result.reason, next_retry_at=next_retry, increment_attempt=True)
                        counts["retryable"] += 1
        return counts

    def run(self, run_id: str, required_inventory: int) -> dict[str, int]:
        before = self.discover_raw(run_id, max(required_inventory + self.settings.discovery_overage_buffer, 1))
        rows = self.store.list_pending_candidates(max(required_inventory + self.settings.discovery_overage_buffer, 1))
        processed = self.process_candidates(run_id, rows, max_workers=self.settings.max_concurrency)
        return {**before, **processed, "pending_candidates": len(self.store.list_pending_candidates(1000))}
