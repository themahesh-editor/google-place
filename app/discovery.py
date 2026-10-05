from __future__ import annotations

import datetime as dt
import os
import random
import re
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import dns.resolver
import requests

from app.db import deterministic_lead_id, normalize_domain
from app.debug import debug
from app.llm import LLMClient, LLMTemporaryError
from app.research import WebsiteCrawler, choose_public_business_email

SEED_KEYWORDS = [
    "roofing contractor", "HVAC contractor", "custom home builder", "residential real estate brokerage",
    "luxury realtor", "boutique law firm", "family law firm", "personal injury law firm",
    "cosmetic dentistry practice", "orthodontist", "remodeling contractor", "kitchen remodeling company",
    "bathroom remodeling company", "landscaping company", "commercial cleaning company", "accounting firm",
    "property management company", "pest control company", "solar installation company", "home inspection company",
]

TARGET_CITIES = [
    "Dallas TX", "Fort Worth TX", "Houston TX", "Austin TX", "San Antonio TX", "Orlando FL", "Tampa FL", "Jacksonville FL", "Miami FL", "Atlanta GA",
    "Charlotte NC", "Nashville TN", "Phoenix AZ", "Denver CO", "Las Vegas NV", "Los Angeles CA", "San Diego CA", "Sacramento CA", "Chicago IL", "Columbus OH",
    "Indianapolis IN", "Cleveland OH", "Kansas City MO", "Raleigh NC", "Richmond VA", "Seattle WA", "Portland OR", "Salt Lake City UT", "Minneapolis MN", "Boston MA",
    "Toronto Canada", "Vancouver Canada", "Montreal Canada", "Calgary Canada", "Ottawa Canada", "Edmonton Canada",
    "London UK", "Manchester UK", "Birmingham UK", "Leeds UK", "Liverpool UK", "Glasgow UK",
    "Sydney Australia", "Melbourne Australia", "Brisbane Australia", "Perth Australia", "Adelaide Australia",
]

BUSINESS_NOUNS = (
    "dentist", "dentistry", "clinic", "practice", "contractor", "company", "firm", "agency", "brokerage", "provider",
    "service", "studio", "group", "attorney", "lawyer", "real estate", "property management", "accounting", "landscaping",
    "inspection", "hvac", "roofing", "builder", "remodeling", "orthodontist",
)

FREE_EMAIL_DOMAINS = {"gmail.com", "googlemail.com", "yahoo.com", "hotmail.com", "outlook.com", "live.com", "msn.com", "icloud.com", "me.com", "aol.com", "protonmail.com", "proton.me", "gmx.com", "mail.com", "yandex.com", "zoho.com"}
DISPOSABLE_DOMAINS = {"10minutemail.com", "guerrillamail.com", "mailinator.com", "yopmail.com", "getnada.com", "tempmail.com", "temp-mail.org", "discard.email", "throwawaymail.com"}
BLOCKED_LOCAL_PARTS = {"noreply", "no-reply", "donotreply", "do-not-reply", "mailer-daemon", "abuse"}


@dataclass(frozen=True)
class Candidate:
    place_id: str
    company: str
    website: str
    address: str
    types: tuple[str, ...]
    query: str
    country_code: str


def state_or_region_from_address(address: str, country_code: str) -> str:
    if country_code == "US":
        match = re.search(r",\s*([A-Z]{2})(?:\s+\d{5}(?:-\d{4})?)?\b", address or "")
        return match.group(1).upper() if match else ""
    if country_code == "CA":
        match = re.search(r",\s*(AB|BC|MB|NB|NL|NS|NT|NU|ON|PE|QC|SK|YT)\b", address or "", flags=re.I)
        return match.group(1).upper() if match else ""
    if country_code == "AU":
        match = re.search(r",\s*(NSW|VIC|QLD|WA|SA|TAS|NT|ACT)\b", address or "", flags=re.I)
        return match.group(1).upper() if match else ""
    return ""


def city_from_address(address: str, region: str) -> str:
    text = re.sub(r"\s+", " ", address or "").strip()
    if region:
        match = re.search(r",\s*([^,]+),\s*" + re.escape(region) + r"\b", text, flags=re.I)
        if match:
            return match.group(1).strip()
    parts = [x.strip() for x in text.split(",") if x.strip()]
    return parts[-2] if len(parts) >= 2 else ""


def location_timezone(country_code: str, region: str, city: str) -> str:
    us = {
        "AL":"America/Chicago","AK":"America/Anchorage","AZ":"America/Phoenix","AR":"America/Chicago","CA":"America/Los_Angeles","CO":"America/Denver","CT":"America/New_York","DE":"America/New_York","FL":"America/New_York","GA":"America/New_York","HI":"Pacific/Honolulu","IA":"America/Chicago","ID":"America/Boise","IL":"America/Chicago","IN":"America/Indiana/Indianapolis","KS":"America/Chicago","KY":"America/New_York","LA":"America/Chicago","MA":"America/New_York","MD":"America/New_York","ME":"America/New_York","MI":"America/Detroit","MN":"America/Chicago","MO":"America/Chicago","MS":"America/Chicago","MT":"America/Denver","NC":"America/New_York","ND":"America/Chicago","NE":"America/Chicago","NH":"America/New_York","NJ":"America/New_York","NM":"America/Denver","NV":"America/Los_Angeles","NY":"America/New_York","OH":"America/New_York","OK":"America/Chicago","OR":"America/Los_Angeles","PA":"America/New_York","RI":"America/New_York","SC":"America/New_York","SD":"America/Chicago","TN":"America/Chicago","TX":"America/Chicago","UT":"America/Denver","VA":"America/New_York","VT":"America/New_York","WA":"America/Los_Angeles","WI":"America/Chicago","WV":"America/New_York","WY":"America/Denver",
    }
    ca = {"AB":"America/Edmonton", "BC":"America/Vancouver", "MB":"America/Winnipeg", "NB":"America/Moncton", "NL":"America/St_Johns", "NS":"America/Halifax", "NT":"America/Yellowknife", "NU":"America/Iqaluit", "ON":"America/Toronto", "PE":"America/Halifax", "QC":"America/Toronto", "SK":"America/Regina", "YT":"America/Whitehorse"}
    au = {"NSW":"Australia/Sydney", "VIC":"Australia/Melbourne", "QLD":"Australia/Brisbane", "WA":"Australia/Perth", "SA":"Australia/Adelaide", "TAS":"Australia/Hobart", "NT":"Australia/Darwin", "ACT":"Australia/Sydney"}
    city_key = city.strip().lower()
    if country_code == "US": return us.get(region, "America/New_York")
    if country_code == "CA": return ca.get(region, "America/Toronto")
    if country_code == "AU": return au.get(region, "Australia/Sydney")
    if country_code == "GB": return "Europe/London"
    return "America/New_York"


def canonical_url(value: str) -> str:
    parsed = urlparse(value if "://" in value else f"https://{value}")
    if not parsed.hostname:
        return ""
    return f"{parsed.scheme or 'https'}://{parsed.netloc}/"


class DiscoveryService:
    SYSTEM_PROMPT = """
Create concise Google Places text-search queries for local or regional businesses.
Return ONLY JSON array of strings.
Rules: use only supplied target cities; include a business term related to the seed; prefer independent/local businesses;
do not generate reviews, prices, discounts, or how-to queries.
""".strip()

    QUALIFY_PROMPT = """
You are a conservative business lead classifier.
Return ONLY JSON: {"action":"KEEP|REJECT","company_name":"...","scale_class":"LOCAL|REGIONAL","confidence":0.0,"reason":"..."}
KEEP only when the business matches the target query and appears to be a real local or regional business.
Use only supplied candidate and website evidence. Do not invent facts.
""".strip()

    def __init__(self, store, llm: LLMClient, crawler: WebsiteCrawler, settings):
        self.store = store
        self.llm = llm
        self.crawler = crawler
        self.settings = settings
        self.http = requests.Session()
        self.http.headers.update({"User-Agent": "AttachAI-Discovery/2.0", "Accept-Language": "en-US,en;q=0.8"})
        self.mx_cache: dict[str, bool] = {}

    def choose_seed(self) -> str:
        return SEED_KEYWORDS[dt.date.today().toordinal() % len(SEED_KEYWORDS)]

    def expand_queries(self, seed: str, count: int = 100) -> list[str]:
        started = time.monotonic()
    
        debug(
            "DISCOVERY_QUERY_EXPANSION_START",
            seed=seed,
            requested_count=count,
        )
    
        try:
            raw = self.llm.chat_json_array(
                self.SYSTEM_PROMPT,
                (
                    f"Seed: {seed}\n"
                    f"Target cities: {', '.join(TARGET_CITIES)}\n"
                    f"Allowed countries: {', '.join(self.settings.allowed_country_codes)}\n"
                    f"Generate {count} queries."
                ),
                max_tokens=1000,
                operation="discovery_query_expansion",
            )
        except Exception as exc:
            debug(
                "DISCOVERY_QUERY_EXPANSION_ERROR",
                seed=seed,
                type=exc.__class__.__name__,
                message=str(exc)[:300],
                elapsed_seconds=round(time.monotonic() - started, 2),
            )
            raw = []
    
        if not isinstance(raw, list):
            raw = []
    
        out: list[str] = []
        seen: set[str] = set()
    
        for item in raw:
            query = re.sub(r"\s+", " ", str(item)).strip()
            lower = query.lower()
    
            if not query or lower in seen:
                continue
    
            if any(
                word in lower
                for word in (
                    "review",
                    "reviews",
                    "price",
                    "cost",
                    "cheapest",
                    "discount",
                    "specials",
                )
            ):
                continue
    
            if not any(
                city.split()[0].lower() in lower
                for city in TARGET_CITIES
            ):
                continue
    
            if not any(
                noun in lower
                for noun in BUSINESS_NOUNS
            ):
                continue
    
            seen.add(lower)
            out.append(query)
    
        variants = (
            "",
            "local",
            "independent",
            "neighborhood",
            "specialist",
            "boutique",
            "community",
        )
    
        fallback = [
            f"{' '.join(x for x in (variant, seed, city) if x)}"
            for city in TARGET_CITIES
            for variant in variants
        ]
    
        for query in fallback:
            if len(out) >= count:
                break
    
            if query.lower() not in seen:
                seen.add(query.lower())
                out.append(query)
    
        random.Random(
            dt.date.today().toordinal()
        ).shuffle(out)
    
        result = out[:count]
    
        debug(
            "DISCOVERY_QUERY_EXPANSION_END",
            seed=seed,
            llm_items=len(raw),
            final_queries=len(result),
            elapsed_seconds=round(time.monotonic() - started, 2),
        )
    
        return result

    def places_search(self, query: str, remaining_budget: int) -> tuple[list[dict], int]:
        started = time.monotonic()
    
        debug(
            "DISCOVERY_PLACES_START",
            query=query,
            remaining_budget=remaining_budget,
            max_pages=self.settings.max_pages_per_search,
        )
    
        if not self.settings.allowed_country_codes:
            return [], 0
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": os.environ.get("GOOGLE_PLACES_API_KEY", "").strip(),
            "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,places.postalAddress,places.addressComponents,places.websiteUri,places.types,places.businessStatus,nextPageToken",
        }
        if not headers["X-Goog-Api-Key"]:
            raise RuntimeError("GOOGLE_PLACES_API_KEY is missing")
        results: list[dict] = []
        page_token: str | None = None
        pages = 0
        requests_used = 0
        while pages < self.settings.max_pages_per_search and requests_used < remaining_budget:
            payload = {"textQuery": query, "pageSize": self.settings.places_page_size, "languageCode": "en"}
            if page_token:
                payload["pageToken"] = page_token
            response = None
            for attempt in range(3):
                try:
                    response = self.http.post("https://places.googleapis.com/v1/places:searchText", headers=headers, json=payload, timeout=self.settings.crawler_timeout_seconds)
                    requests_used += 1
                    debug(
                        "DISCOVERY_PLACES_RESPONSE",
                        query=query,
                        attempt=f"{attempt + 1}/3",
                        status=response.status_code,
                        requests_used=requests_used,
                        elapsed_seconds=round(time.monotonic() - started, 2),
                    )
                    if response.status_code == 429 and attempt < 2:
                        time.sleep(3 + attempt * 3)
                        continue
                    if response.status_code >= 400:
                        if response.status_code in {400, 401, 403, 404}:
                            return results, requests_used
                        response.raise_for_status()
                    break
                except Exception as exc:
                    debug(
                        "DISCOVERY_PLACES_ERROR",
                        query=query,
                        attempt=f"{attempt + 1}/3",
                        type=exc.__class__.__name__,
                        message=str(exc)[:300],
                        elapsed_seconds=round(time.monotonic() - started, 2),
                    )
                
                    if attempt == 2:
                        return results, requests_used
                
                    time.sleep(2 + attempt * 3)
            if response is None:
                return results, requests_used
            payload_json = response.json()
            results.extend(payload_json.get("places", []) or [])
            pages += 1
            page_token = payload_json.get("nextPageToken")
            if not page_token:
                break
            time.sleep(2)

        debug(
            "DISCOVERY_PLACES_END",
            query=query,
            results=len(results),
            requests_used=requests_used,
            elapsed_seconds=round(time.monotonic() - started, 2),
        )

        return results, requests_used

    def candidate_from_place(self, place: dict, query: str) -> Candidate | None:
        place_id = str(place.get("id") or "").strip()
        company = str((place.get("displayName") or {}).get("text") or "").strip()
        website = canonical_url(str(place.get("websiteUri") or "").strip())
        address = str(place.get("formattedAddress") or "").strip()
        status = str(place.get("businessStatus") or "").upper()
        postal = place.get("postalAddress") or {}
        country = str(postal.get("regionCode") or "").upper().strip()
        if not country:
            for component in place.get("addressComponents") or []:
                if "country" in (component.get("types") or []):
                    country = str(component.get("shortText") or "").upper().strip()
                    break
        if not place_id or not company or not website or status in {"CLOSED", "CLOSED_PERMANENTLY"} or country not in self.settings.allowed_country_codes:
            return None
        return Candidate(place_id, company, website, address, tuple(str(x) for x in (place.get("types") or [])), query, country)

    def has_mx(self, domain: str) -> bool:
        domain = normalize_domain(domain)
        if domain in self.mx_cache:
            return self.mx_cache[domain]
        try:
            result = any(getattr(x, "exchange", None) for x in dns.resolver.resolve(domain, "MX", lifetime=5))
        except Exception:
            result = False
        self.mx_cache[domain] = result
        return result

    def qualify(self, candidate: Candidate, facts: str, email: str) -> dict | None:
        started = time.monotonic()
    
        debug(
            "DISCOVERY_QUALIFICATION_START",
            company=candidate.company,
            website=candidate.website,
            email=email,
            query=candidate.query,
            facts_chars=len(facts),
        )
    
        try:
            obj = self.llm.chat_json_object(
                self.QUALIFY_PROMPT,
                (
                    f"Target query: {candidate.query}\n"
                    f"Company: {candidate.company}\n"
                    f"Address: {candidate.address}\n"
                    f"Country: {candidate.country_code}\n"
                    f"Website: {candidate.website}\n"
                    f"Email: {email}\n"
                    f"Website evidence:\n{facts[:6000]}"
                ),
                max_tokens=700,
                operation="discovery_qualification",
            )
    
            action = str(obj.get("action", "")).upper()
            scale = str(obj.get("scale_class", "")).upper()
            confidence = float(obj.get("confidence", 0))
    
            debug(
                "DISCOVERY_QUALIFICATION_RESULT",
                company=candidate.company,
                action=action,
                scale_class=scale,
                confidence=round(confidence, 3),
                elapsed_seconds=round(time.monotonic() - started, 2),
            )
    
            if action != "KEEP" or scale not in {"LOCAL", "REGIONAL"} or confidence < 0.75:
                return {
                    "action": "REJECT",
                    "confidence": confidence,
                    "reason": str(obj.get("reason") or "")[:1000],
                }
    
            return {
                "action": "KEEP",
                "company_name": str(
                    obj.get("company_name") or candidate.company
                )[:180],
                "scale_class": scale,
                "confidence": round(confidence, 3),
                "reason": str(obj.get("reason") or "")[:1000],
            }
    
        except (
            LLMTemporaryError,
            ValueError,
            TypeError,
            KeyError,
        ) as exc:
            debug(
                "DISCOVERY_QUALIFICATION_ERROR",
                company=candidate.company,
                website=candidate.website,
                type=exc.__class__.__name__,
                message=str(exc)[:300],
                elapsed_seconds=round(time.monotonic() - started, 2),
            )
            return None

    def run(self, run_id: str, target: int) -> dict[str, int | float | str]:
        started = time.monotonic()
        seed = self.choose_seed()
    
        debug(
            "DISCOVERY_RUN_START",
            run_id=run_id,
            target=target,
            seed=seed,
        )
    
        verified = discovered = requests_used = rejected = retryable = duplicates = 0

        # Retry previously discovered candidates from durable DB state, with a hard per-run bound.
        retry_rows = self.store.fetchall(
            """SELECT * FROM discovery_candidate
               WHERE status='RETRYABLE' AND (next_retry_at_utc IS NULL OR next_retry_at_utc<=?)
                 AND attempts < ? ORDER BY next_retry_at_utc,candidate_id LIMIT ?""",
            [__import__("app.db", fromlist=["now_utc"]).now_utc(), self.settings.discovery_retry_limit, self.settings.discovery_max_retries_per_run],
        )
        for row in retry_rows:
            if verified >= target:
                break
            result = self._process_candidate(self._candidate_from_row(row), run_id, row["candidate_id"], retry=True)
            if result == "verified": verified += 1
            elif result == "retry": retryable += 1
            elif result == "rejected": rejected += 1
            else: duplicates += 1

        if verified >= target:
            return {"seed": seed, "discovered": 0, "verified": verified, "places_search_requests": 0, "rejected": rejected, "retryable": retryable, "duplicates": duplicates, "duration_seconds": round(time.monotonic() - started, 2)}

        queries = self.expand_queries(seed, 100)
        
        debug(
            "DISCOVERY_QUERIES_READY",
            run_id=run_id,
            seed=seed,
            query_count=len(queries),
        )
        
        for query in queries:
            if verified >= target or requests_used >= self.settings.max_places_search_requests or discovered >= self.settings.max_raw_candidates:
                break
            places, used = self.places_search(query, self.settings.max_places_search_requests - requests_used)
            requests_used += used
            for place in places:
                if verified >= target or discovered >= self.settings.max_raw_candidates:
                    break
                candidate = self.candidate_from_place(place, query)
                if not candidate:
                    continue
                discovered += 1
                domain = normalize_domain(candidate.website)
                duplicate = self.store.fetchone("SELECT 1 FROM discovery_candidate WHERE place_id=? OR website_domain=? LIMIT 1", [candidate.place_id, domain])
                if duplicate:
                    duplicates += 1
                    continue
                candidate_id = f"{run_id}:{candidate.place_id}"
                self.store.execute(
                    """INSERT INTO discovery_candidate(candidate_id,workflow_run_id,place_id,website_domain,company,website,address,country_code,types_json,query,status,attempts,next_retry_at_utc,last_reason,last_seen_at_utc)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    [candidate_id, run_id, candidate.place_id, domain, candidate.company, candidate.website, candidate.address, candidate.country_code,
                     __import__("json").dumps(candidate.types), candidate.query, "SEEN", 0, None, None, __import__("app.db", fromlist=["now_utc"]).now_utc()],
                )
                result = self._process_candidate(candidate, run_id, candidate_id, retry=False)
                if result == "verified": verified += 1
                elif result == "retry": retryable += 1
                elif result == "rejected": rejected += 1
                else: duplicates += 1
        result = {
            "seed": seed,
            "discovered": discovered,
            "verified": verified,
            "places_search_requests": requests_used,
            "rejected": rejected,
            "retryable": retryable,
            "duplicates": duplicates,
            "duration_seconds": round(
                time.monotonic() - started,
                2,
            ),
        }
        
        debug(
            "DISCOVERY_RUN_END",
            run_id=run_id,
            verified=verified,
            discovered=discovered,
            requests_used=requests_used,
            rejected=rejected,
            retryable=retryable,
            duplicates=duplicates,
            elapsed_seconds=result["duration_seconds"],
        )
        
        return result

    def _candidate_from_row(self, row) -> Candidate:
        try:
            import json
            types = tuple(str(x) for x in json.loads(row["types_json"] or "[]"))
        except Exception:
            types = ()
        return Candidate(str(row["place_id"]), str(row["company"]), str(row["website"]), str(row["address"]), types, str(row["query"]), str(row["country_code"]))

    def _process_candidate(
        self,
        candidate: Candidate,
        run_id: str,
        candidate_id: str,
        retry: bool,
    ) -> str:
        from app.db import now_utc
    
        started = time.monotonic()
    
        debug(
            "DISCOVERY_CANDIDATE_START",
            run_id=run_id,
            candidate_id=candidate_id,
            place_id=candidate.place_id,
            company=candidate.company,
            website=candidate.website,
            retry=retry,
        )
    
        pages = self.crawler.crawl(candidate.website)
    
        debug(
            "DISCOVERY_CANDIDATE_CRAWL_DONE",
            candidate_id=candidate_id,
            company=candidate.company,
            pages=len(pages),
            elapsed_seconds=round(
                time.monotonic() - started,
                2,
            ),
        )
    
        email_choice = choose_public_business_email(
            pages,
            candidate.website,
            self.has_mx,
        )
    
        if not email_choice:
            debug(
                "DISCOVERY_CANDIDATE_NO_EMAIL",
                candidate_id=candidate_id,
                company=candidate.company,
                elapsed_seconds=round(
                    time.monotonic() - started,
                    2,
                ),
            )
    
            self._schedule_candidate_retry(
                candidate,
                candidate_id,
                "no_public_business_email",
                self.settings.discovery_no_email_retry_days * 86400,
                run_id,
            )
            return "retry"
    
        email, source_url = email_choice
    
        debug(
            "DISCOVERY_CANDIDATE_EMAIL_FOUND",
            candidate_id=candidate_id,
            company=candidate.company,
            source_url=source_url,
            elapsed_seconds=round(
                time.monotonic() - started,
                2,
            ),
        )
    
        facts = "\n".join(
            f"PAGE {p.url}: {p.text[:1600]}"
            for p in pages
            if p.text
        )[:12000]
    
        qualification = self.qualify(
            candidate,
            facts,
            email,
        )
    
        if qualification is None:
            debug(
                "DISCOVERY_CANDIDATE_QUALIFICATION_FAILED",
                candidate_id=candidate_id,
                company=candidate.company,
                elapsed_seconds=round(
                    time.monotonic() - started,
                    2,
                ),
            )
    
            self._schedule_candidate_retry(
                candidate,
                candidate_id,
                "llm_temporary_failure",
                self.settings.discovery_transient_retry_hours * 3600,
                run_id,
            )
            return "retry"
    
        if qualification["action"] != "KEEP":
            debug(
                "DISCOVERY_CANDIDATE_REJECTED",
                candidate_id=candidate_id,
                company=candidate.company,
                confidence=qualification.get("confidence"),
                reason=qualification.get("reason"),
                elapsed_seconds=round(
                    time.monotonic() - started,
                    2,
                ),
            )
    
            self.store.execute(
                "UPDATE discovery_candidate "
                "SET status='REJECTED',last_reason=?,last_seen_at_utc=? "
                "WHERE candidate_id=?",
                [
                    qualification.get("reason") or "rejected",
                    now_utc(),
                    candidate_id,
                ],
            )
    
            self.store.add_event(
                "lead_rejected",
                run_id=run_id,
                reason=qualification.get("reason"),
                metadata={
                    "company": candidate.company,
                    "qualification_confidence": qualification.get(
                        "confidence",
                        0,
                    ),
                },
            )
            return "rejected"
    
        region = state_or_region_from_address(
            candidate.address,
            candidate.country_code,
        )
        city = city_from_address(
            candidate.address,
            region,
        )
        tz = location_timezone(
            candidate.country_code,
            region,
            city,
        )
    
        lead_id = deterministic_lead_id(
            email,
            candidate.website,
        )
    
        existing = self.store.get_lead(lead_id)
    
        lead = {
            "lead_id": lead_id,
            "email": email,
            "company": qualification["company_name"],
            "website": candidate.website,
            "website_domain": normalize_domain(candidate.website),
            "city": city,
            "region": region,
            "country_code": candidate.country_code,
            "timezone": tz,
            "lead_source": "Google Places Text Search (paged) -> public website",
            "place_id": candidate.place_id,
            "scale_class": qualification["scale_class"],
            "qualification_confidence": qualification["confidence"],
            "qualification_reason": qualification["reason"],
            "discovery_facts": facts[:7000],
            "status": existing["status"] if existing else "ELIGIBLE",
        }
    
        self.store.upsert_lead(lead)
    
        self.store.insert_qualification(
            lead_id,
            action="KEEP",
            confidence=qualification["confidence"],
            reason=qualification["reason"],
            run_id=run_id,
            evidence_urls=[source_url],
        )
    
        self.store.execute(
            "UPDATE discovery_candidate "
            "SET status='VERIFIED',last_reason='verified',"
            "last_seen_at_utc=?,next_retry_at_utc=NULL "
            "WHERE candidate_id=?",
            [
                now_utc(),
                candidate_id,
            ],
        )
    
        self.store.add_event(
            "lead_verified",
            run_id=run_id,
            lead_id=lead_id,
            status="ELIGIBLE",
            metadata={
                "email_source_url": source_url,
                "confidence": qualification["confidence"],
                "retry": retry,
            },
        )
    
        debug(
            "DISCOVERY_CANDIDATE_VERIFIED",
            run_id=run_id,
            candidate_id=candidate_id,
            lead_id=lead_id,
            company=candidate.company,
            elapsed_seconds=round(
                time.monotonic() - started,
                2,
            ),
        )
    
        return "verified"

    def _schedule_candidate_retry(
        self,
        candidate: Candidate,
        candidate_id: str,
        reason: str,
        seconds: int,
        run_id: str,
    ) -> None:
        from app.db import now_utc
    
        debug(
            "DISCOVERY_RETRY_SCHEDULE_START",
            run_id=run_id,
            candidate_id=candidate_id,
            place_id=candidate.place_id,
            reason=reason,
            retry_delay_seconds=seconds,
        )
        row = self.store.fetchone("SELECT attempts FROM discovery_candidate WHERE candidate_id=?", [candidate_id])
        attempts = int(row["attempts"] or 0) if row else 0
        next_attempt = attempts + 1
        if next_attempt >= self.settings.discovery_retry_limit:
            # Runtime bound is intentionally finite; the durable row is terminal after repeated failures.
            self.store.execute("UPDATE discovery_candidate SET status='REJECTED',attempts=?,last_reason='retry_limit_exceeded',next_retry_at_utc=NULL,last_seen_at_utc=? WHERE candidate_id=?", [next_attempt, now_utc(), candidate_id])
            self.store.add_event("discovery_retry_exhausted", run_id=run_id, reason=reason, metadata={"place_id": candidate.place_id, "attempts": next_attempt})
            debug(
                "DISCOVERY_RETRY_EXHAUSTED",
                run_id=run_id,
                candidate_id=candidate_id,
                place_id=candidate.place_id,
                reason=reason,
                attempts=next_attempt,
            )
            return
        next_retry = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=seconds)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        self.store.execute("UPDATE discovery_candidate SET status='RETRYABLE',attempts=?,next_retry_at_utc=?,last_reason=?,last_seen_at_utc=? WHERE candidate_id=?", [next_attempt, next_retry, reason, now_utc(), candidate_id])
        self.store.add_event("discovery_retry_scheduled", run_id=run_id, reason=reason, metadata={"place_id": candidate.place_id, "next_retry_at_utc": next_retry, "attempts": next_attempt})

        debug(
            "DISCOVERY_RETRY_SCHEDULED",
            run_id=run_id,
            candidate_id=candidate_id,
            place_id=candidate.place_id,
            reason=reason,
            attempts=next_attempt,
            next_retry_at_utc=next_retry,
        )
