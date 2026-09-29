#!/usr/bin/env python3
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import os
import random
import re
import time
import urllib.parse
import urllib.robotparser
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import dns.resolver
import requests
from bs4 import BeautifulSoup

NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "").strip()
NVIDIA_BASE_URL = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1").rstrip("/")
NVIDIA_MODEL = os.getenv("NVIDIA_MODEL", "nvidia/nemotron-3-ultra-550b-a55b").strip()
NVIDIA_TIMEOUT_SECONDS = int(os.getenv("NVIDIA_TIMEOUT_SECONDS", "180"))
NVIDIA_MAX_TOKENS = int(os.getenv("NVIDIA_MAX_TOKENS", "1500"))

GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY", "").strip()
GOOGLE_PLACES_URL = "https://places.googleapis.com/v1/places:searchText"

TARGET_VERIFIED_LEADS = int(os.getenv("TARGET_VERIFIED_LEADS", "100"))
MAX_PLACES_SEARCH_REQUESTS = int(os.getenv("MAX_PLACES_SEARCH_REQUESTS", "30"))
MAX_RAW_CANDIDATES = int(os.getenv("MAX_RAW_CANDIDATES", "250"))
SEARCH_PAGE_SIZE = min(20, max(1, int(os.getenv("SEARCH_PAGE_SIZE", "20"))))
SEARCH_DELAY_SECONDS = float(os.getenv("SEARCH_DELAY_SECONDS", "2"))
MAX_PAGES_PER_WEBSITE = int(os.getenv("MAX_PAGES_PER_WEBSITE", "5"))
HTTP_TIMEOUT_SECONDS = int(os.getenv("HTTP_TIMEOUT_SECONDS", "15"))
HONOR_ROBOTS = os.getenv("HONOR_ROBOTS", "true").lower() in {"1", "true", "yes"}

CRM_FILE = Path(os.getenv("CRM_FILE", "leads_crm.csv"))
SEEN_DOMAINS_FILE = Path(os.getenv("SEEN_DOMAINS_FILE", "seen_domains.csv"))
MEMORY_FILE = Path(os.getenv("MEMORY_FILE", "candidate_memory.jsonl"))
RUN_LOG_FILE = Path(os.getenv("RUN_LOG_FILE", "run_log.jsonl"))

USER_AGENT = os.getenv("OUTREACH_USER_AGENT", "AttachAILeadDiscovery/1.0 (+https://attachaiassistant.oneapp.dev/)")

SEED_KEYWORDS = [
    "roofing contractor", "HVAC contractor", "custom home builder", "residential real estate brokerage",
    "luxury realtor", "boutique law firm", "family law firm", "personal injury law firm",
    "cosmetic dentistry practice", "orthodontist", "remodeling contractor", "kitchen remodeling company",
    "bathroom remodeling company", "landscaping company", "commercial cleaning company", "accounting firm",
    "property management company", "pest control company", "solar installation company", "home inspection company",
]

TARGET_CITIES = [
    "Dallas TX", "Fort Worth TX", "Houston TX", "Austin TX", "San Antonio TX", "Orlando FL", "Tampa FL",
    "Jacksonville FL", "Miami FL", "Atlanta GA", "Charlotte NC", "Nashville TN", "Phoenix AZ", "Denver CO",
    "Las Vegas NV", "Los Angeles CA", "San Diego CA", "Sacramento CA", "Chicago IL", "Columbus OH",
    "Indianapolis IN", "Cleveland OH", "Kansas City MO", "Raleigh NC", "Richmond VA", "Seattle WA",
    "Portland OR", "Salt Lake City UT", "Minneapolis MN", "Boston MA",
]

CRM_HEADERS = [
    "Email", "Company", "Website", "City", "State", "Timezone", "LeadSource", "Verified", "PlaceId",
    "EmailSourceURL", "WebsiteFacts", "ScaleClass", "QualificationConfidence", "Status", "FirstSeenDate", "Notes",
]

EMAIL_RE = re.compile(r"(?<![\w.+-])[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,63}(?![\w.-])", re.I)
FREE_EMAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "yahoo.com", "hotmail.com", "outlook.com", "live.com", "msn.com",
    "icloud.com", "me.com", "aol.com", "protonmail.com", "proton.me", "gmx.com", "mail.com", "yandex.com", "zoho.com",
}
DISPOSABLE_DOMAINS = {
    "10minutemail.com", "10minutemail.net", "guerrillamail.com", "mailinator.com", "yopmail.com",
    "getnada.com", "tempmail.com", "temp-mail.org", "discard.email", "fakeinbox.com", "throwawaymail.com",
}
BLOCKED_LOCAL_PARTS = {"noreply", "no-reply", "donotreply", "do-not-reply", "mailer-daemon", "abuse"}
CONTACT_WORDS = ("contact", "about", "team", "staff", "leadership", "services", "company")

session = requests.Session()
session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.8"})


@dataclass
class Candidate:
    place_id: str
    company: str
    website: str
    address: str
    types: list[str]
    query: str


@dataclass
class EmailFinding:
    email: str
    source_url: str
    snippet: str


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso_now() -> str:
    return utc_now().replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_domain(value: str) -> str:
    value = (value or "").strip().lower()
    if "@" in value:
        value = value.rsplit("@", 1)[-1]
    if "://" in value:
        value = urllib.parse.urlparse(value).hostname or ""
    value = value.split(":", 1)[0].strip(".")
    return value[4:] if value.startswith("www.") else value


def canonical_url(url: str) -> str:
    try:
        parsed = urllib.parse.urlparse(url if "://" in url else f"https://{url}")
        scheme = parsed.scheme or "https"
        host = normalize_domain(parsed.hostname or "")
        return f"{scheme}://{host}/" if host else ""
    except Exception:
        return ""


def normalize_company(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()
    noise = {"llc", "inc", "incorporated", "corp", "corporation", "co", "company", "ltd", "limited"}
    return " ".join(t for t in value.split() if t not in noise)


def state_from_address(address: str) -> str:
    m = re.search(r",\s*([A-Z]{2})(?:\s+\d{5}(?:-\d{4})?)?\b", address or "")
    return m.group(1).upper() if m else ""


def city_from_address(address: str, state: str) -> str:
    s = re.sub(r"\s+", " ", address or "").strip()
    if not s:
        return ""
    if state:
        m = re.search(r",\s*([^,]+),\s*" + re.escape(state) + r"\b", s, re.I)
        if m:
            return m.group(1).strip()
    parts = [p.strip() for p in s.split(",") if p.strip()]
    return parts[-2] if len(parts) >= 2 else ""


def state_timezone(state: str) -> str:
    return {
        "AL":"America/Chicago","AK":"America/Anchorage","AZ":"America/Phoenix","AR":"America/Chicago",
        "CA":"America/Los_Angeles","CO":"America/Denver","CT":"America/New_York","DE":"America/New_York",
        "FL":"America/New_York","GA":"America/New_York","HI":"Pacific/Honolulu","IA":"America/Chicago",
        "ID":"America/Denver","IL":"America/Chicago","IN":"America/Indiana/Indianapolis","KS":"America/Chicago",
        "KY":"America/New_York","LA":"America/Chicago","MA":"America/New_York","MD":"America/New_York",
        "ME":"America/New_York","MI":"America/Detroit","MN":"America/Chicago","MO":"America/Chicago",
        "MS":"America/Chicago","MT":"America/Denver","NC":"America/New_York","ND":"America/Chicago",
        "NE":"America/Chicago","NH":"America/New_York","NJ":"America/New_York","NM":"America/Denver",
        "NV":"America/Los_Angeles","NY":"America/New_York","OH":"America/New_York","OK":"America/Chicago",
        "OR":"America/Los_Angeles","PA":"America/New_York","RI":"America/New_York","SC":"America/New_York",
        "SD":"America/Chicago","TN":"America/Chicago","TX":"America/Chicago","UT":"America/Denver",
        "VA":"America/New_York","VT":"America/New_York","WA":"America/Los_Angeles","WI":"America/Chicago",
        "WV":"America/New_York","WY":"America/Denver"
    }.get(state, "America/New_York")


def ensure_csv(path: Path, headers: list[str]) -> None:
    if not path.exists():
        path.write_text(",".join(headers) + "\n", encoding="utf-8")


def load_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def append_csv(path: Path, headers: list[str], row: dict[str, Any]) -> None:
    exists = path.exists()
    with path.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=headers)
        if not exists:
            w.writeheader()
        w.writerow({h: row.get(h, "") for h in headers})


def seen_domains() -> set[str]:
    ensure_csv(SEEN_DOMAINS_FILE, ["Domain", "FirstSeenUTC", "Source"])
    return {normalize_domain(r.get("Domain", "")) for r in load_csv(SEEN_DOMAINS_FILE) if normalize_domain(r.get("Domain", ""))}


def remember_domain(domain: str) -> None:
    domain = normalize_domain(domain)
    if not domain or domain in seen_domains():
        return
    append_csv(SEEN_DOMAINS_FILE, ["Domain", "FirstSeenUTC", "Source"], {
        "Domain": domain, "FirstSeenUTC": iso_now(), "Source": "public_website"
    })


def append_jsonl(path: Path, event: dict[str, Any]) -> None:
    event = dict(event)
    event["timestamp_utc"] = iso_now()
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def parse_json_object(raw: str) -> dict | None:
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


def parse_json_array(raw: str) -> list[str]:
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    candidates = [text]
    m = re.search(r"\[.*\]", text, re.S)
    if m:
        candidates.insert(0, m.group(0))
    for candidate in candidates:
        try:
            obj = json.loads(candidate)
            if isinstance(obj, list):
                return [str(x).strip() for x in obj if str(x).strip()]
        except json.JSONDecodeError:
            pass
    return []


def llm_chat(system_prompt: str, user_prompt: str, max_tokens: int) -> str | None:
    if not NVIDIA_API_KEY:
        raise RuntimeError("NVIDIA_API_KEY is missing")
    payload = {
        "model": NVIDIA_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
        "top_p": 0.95,
        "max_tokens": max_tokens,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    headers = {"Authorization": f"Bearer {NVIDIA_API_KEY}", "Content-Type": "application/json"}
    for attempt in range(3):
        try:
            r = session.post(f"{NVIDIA_BASE_URL}/chat/completions", json=payload, headers=headers, timeout=NVIDIA_TIMEOUT_SECONDS)
            if r.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                delay = 4 + attempt * 6
                print(f"[NVIDIA] HTTP {r.status_code}; retrying in {delay}s")
                time.sleep(delay)
                continue
            r.raise_for_status()
            data = r.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            if isinstance(content, str) and content.strip():
                return content.strip()
            print("[NVIDIA] empty response")
        except Exception as exc:
            print(f"[NVIDIA] attempt {attempt + 1}/3 failed: {exc}")
            if attempt < 2:
                time.sleep(4 + attempt * 6)
    return None


def choose_seed() -> str:
    return SEED_KEYWORDS[dt.date.today().toordinal() % len(SEED_KEYWORDS)]


def expand_queries(seed: str, count: int = 100) -> list[str]:
    system = """
You generate lawful, non-deceptive business-discovery search queries.
Return ONLY a JSON array of strings.
Create diverse Google Places Text Search queries for the supplied business niche and city list.
Vary service, specialization, neighborhood, and business-type wording.
Prefer queries likely to find local or regional operating businesses.
Do not search for people, personal contact details, or sensitive information.
Do not invent businesses; output only search text.
""".strip()
    prompt = f"Seed niche: {seed}\nCities: {', '.join(TARGET_CITIES)}\nGenerate {count} unique concise queries."
    raw = llm_chat(system, prompt, NVIDIA_MAX_TOKENS)
    out, seen = [], set()
    for q in parse_json_array(raw or ""):
        key = re.sub(r"\s+", " ", q.lower()).strip()
        if key and key not in seen:
            seen.add(key)
            out.append(q.strip())
    return out[:count]


def places_search(query: str) -> list[dict]:
    if not GOOGLE_PLACES_API_KEY:
        raise RuntimeError("GOOGLE_PLACES_API_KEY is missing")
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_PLACES_API_KEY,
        # This field mask uses one Text Search call to obtain the data needed for
        # downstream public-website research. No Place Details call is required.
        "X-Goog-FieldMask": (
            "places.id,places.displayName,places.formattedAddress,places.websiteUri,places.types,places.businessStatus"
        ),
    }
    payload = {"textQuery": query, "pageSize": SEARCH_PAGE_SIZE, "languageCode": "en", "regionCode": "US"}
    for attempt in range(3):
        try:
            r = session.post(GOOGLE_PLACES_URL, headers=headers, json=payload, timeout=HTTP_TIMEOUT_SECONDS)
            if r.status_code == 429 and attempt < 2:
                delay = 5 + attempt * 10
                print(f"[Places] 429 rate limit; retrying in {delay}s")
                time.sleep(delay)
                continue
            r.raise_for_status()
            return r.json().get("places", []) or []
        except Exception as exc:
            print(f"[Places] query failed ({query!r}): {exc}")
            if attempt < 2:
                time.sleep(5 + attempt * 10)
    return []


def extract_visible_text(html_doc: str, limit: int = 6000) -> str:
    soup = BeautifulSoup(html_doc, "html.parser")
    for node in soup(["script", "style", "noscript", "svg", "template"]):
        node.decompose()
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True))[:limit]


def fetch_html(url: str) -> tuple[str, str] | None:
    if HONOR_ROBOTS:
        try:
            p = urllib.parse.urlparse(url)
            robots = f"{p.scheme}://{p.netloc}/robots.txt"
            rr = session.get(robots, timeout=8)
            if rr.status_code < 400:
                rp = urllib.robotparser.RobotFileParser()
                rp.set_url(robots)
                rp.parse(rr.text.splitlines())
                if not rp.can_fetch(USER_AGENT, url):
                    print(f"[robots] blocked: {url}")
                    return None
        except Exception:
            pass
    try:
        r = session.get(url, timeout=HTTP_TIMEOUT_SECONDS, allow_redirects=True)
        ctype = (r.headers.get("content-type") or "").lower()
        if r.status_code >= 400:
            return None
        if ctype and "html" not in ctype and "xhtml" not in ctype:
            return None
        return r.url, r.text
    except Exception:
        return None


def website_pages(home_url: str) -> list[str]:
    p = urllib.parse.urlparse(home_url)
    host = normalize_domain(p.hostname or "")
    pages = [home_url]
    first = fetch_html(home_url)
    if not first:
        return pages
    final_url, html_doc = first
    soup = BeautifulSoup(html_doc, "html.parser")
    for a in soup.find_all("a", href=True):
        href = urllib.parse.urljoin(final_url, a.get("href", ""))
        x = urllib.parse.urlparse(href)
        if x.scheme not in {"http", "https"} or normalize_domain(x.hostname or "") != host:
            continue
        label = f"{a.get_text(' ', strip=True)} {x.path}".lower()
        if any(w in label for w in CONTACT_WORDS):
            clean = urllib.parse.urlunparse((x.scheme, x.netloc, x.path, "", "", ""))
            if clean not in pages:
                pages.append(clean)
        if len(pages) >= MAX_PAGES_PER_WEBSITE:
            break
    return pages[:MAX_PAGES_PER_WEBSITE]


def extract_emails(url: str, html_doc: str) -> list[EmailFinding]:
    soup = BeautifulSoup(html_doc, "html.parser")
    visible = extract_visible_text(html_doc)
    result, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        if href.lower().startswith("mailto:"):
            raw = urllib.parse.unquote(href[7:]).split("?", 1)[0]
            for e in EMAIL_RE.findall(raw):
                e = e.lower()
                if e not in seen:
                    seen.add(e)
                    result.append(EmailFinding(e, url, "mailto link"))
    for e in EMAIL_RE.findall(visible):
        e = e.lower()
        if e not in seen:
            seen.add(e)
            pos = visible.lower().find(e)
            result.append(EmailFinding(e, url, visible[max(0, pos - 120):pos + 220]))
    return result


def valid_syntax(email_addr: str) -> bool:
    if len(email_addr) > 254 or not EMAIL_RE.fullmatch(email_addr):
        return False
    local = email_addr.rsplit("@", 1)[0]
    return len(local) <= 64 and not local.startswith(".") and not local.endswith(".") and ".." not in local


def has_mx(domain: str) -> bool:
    try:
        return any(getattr(x, "exchange", None) for x in dns.resolver.resolve(domain, "MX", lifetime=7))
    except Exception:
        return False


def choose_public_business_email(findings: list[EmailFinding], website: str) -> EmailFinding | None:
    site_domain = normalize_domain(website)
    ranked = sorted(findings, key=lambda x: (0 if x.email.split("@", 1)[0] in {"contact", "info", "hello", "sales", "office", "team"} else 1, len(x.email)))
    for item in ranked:
        e = item.email.lower()
        domain = normalize_domain(e)
        local = e.rsplit("@", 1)[0]
        if not valid_syntax(e) or local in BLOCKED_LOCAL_PARTS:
            continue
        if domain in FREE_EMAIL_DOMAINS or domain in DISPOSABLE_DOMAINS:
            continue
        if not (domain == site_domain or domain.endswith("." + site_domain)):
            continue
        if not has_mx(domain):
            continue
        return EmailFinding(e, item.source_url, item.snippet)
    return None


def website_research(url: str) -> tuple[list[EmailFinding], str] | None:
    texts, findings = [], []
    for page in website_pages(url):
        fetched = fetch_html(page)
        if not fetched:
            continue
        final_url, html_doc = fetched
        visible = extract_visible_text(html_doc, 4000)
        if visible:
            texts.append(f"PAGE {final_url}: {visible[:1800]}")
        findings.extend(extract_emails(final_url, html_doc))
    unique, seen = [], set()
    for finding in findings:
        if finding.email not in seen:
            seen.add(finding.email)
            unique.append(finding)
    facts = "\n".join(texts)[:12000]
    return (unique, facts) if facts else None


def llm_qualify(candidate: Candidate, facts: str, public_email: EmailFinding) -> dict | None:
    system = """
You are a conservative B2B lead qualification classifier.
Use ONLY the supplied public website evidence and candidate metadata.
Do not invent revenue, employee counts, customers, awards, services, or locations.
Return ONLY JSON: {"action":"KEEP|REJECT","company_name":"...","scale_class":"LOCAL|REGIONAL|ENTERPRISE|UNKNOWN","confidence":0.0,"reason":"..."}
KEEP only when the website clearly represents a real operating business relevant to the target query,
looks local or regional rather than a national/global enterprise, and the public business email is on the website domain.
When uncertain, REJECT.
""".strip()
    prompt = (
        f"Target query: {candidate.query}\nCandidate: {candidate.company}\nAddress: {candidate.address}\n"
        f"Types: {', '.join(candidate.types)}\nWebsite: {candidate.website}\nPublic email: {public_email.email}\n"
        f"Website evidence:\n{facts[:10000]}"
    )
    obj = parse_json_object(llm_chat(system, prompt, 900) or "")
    if not obj:
        print(f"[LLM] invalid qualification JSON for {candidate.company}")
        return None
    action = str(obj.get("action", "")).upper()
    scale = str(obj.get("scale_class", "UNKNOWN")).upper()
    try:
        confidence = float(obj.get("confidence", 0))
    except (TypeError, ValueError):
        confidence = 0.0
    if action != "KEEP" or scale not in {"LOCAL", "REGIONAL"} or confidence < 0.75:
        return None
    return {
        "company_name": str(obj.get("company_name") or candidate.company).strip()[:180],
        "scale_class": scale,
        "confidence": round(confidence, 3),
        "reason": str(obj.get("reason") or "").strip()[:500],
    }


def existing_leads() -> list[dict[str, str]]:
    ensure_csv(CRM_FILE, CRM_HEADERS)
    return load_csv(CRM_FILE)


def already_in_crm(email_addr: str, domain: str, company: str) -> bool:
    for row in existing_leads():
        if email_addr and row.get("Email", "").lower() == email_addr.lower():
            return True
        if domain and normalize_domain(row.get("Website", "")) == domain:
            return True
        if company and normalize_company(row.get("Company", "")) == normalize_company(company):
            return True
    return False


def candidate_from_place(place: dict, query: str) -> Candidate | None:
    place_id = str(place.get("id") or "").strip()
    company = str((place.get("displayName") or {}).get("text") or "").strip()
    address = str(place.get("formattedAddress") or "").strip()
    website = canonical_url(str(place.get("websiteUri") or "").strip())
    types = [str(x) for x in (place.get("types") or [])]
    status = str(place.get("businessStatus") or "").upper()
    if not place_id or not company or not website or status in {"CLOSED", "CLOSED_PERMANENTLY"}:
        return None
    return Candidate(place_id, company, website, address, types, query)


def main() -> None:
    ensure_csv(CRM_FILE, CRM_HEADERS)
    ensure_csv(SEEN_DOMAINS_FILE, ["Domain", "FirstSeenUTC", "Source"])
    if not NVIDIA_API_KEY or not GOOGLE_PLACES_API_KEY:
        raise SystemExit("Missing NVIDIA_API_KEY or GOOGLE_PLACES_API_KEY")

    start = time.time()
    seed = choose_seed()
    print("=" * 78)
    print("Google Place Lead Discovery Experiment")
    print(f"Seed: {seed}")
    print(f"Target verified leads: {TARGET_VERIFIED_LEADS}")
    print(f"Max Places search requests: {MAX_PLACES_SEARCH_REQUESTS}")
    print(f"Max raw candidates: {MAX_RAW_CANDIDATES}")
    print("=" * 78)

    queries = expand_queries(seed, 100)
    if not queries:
        raise SystemExit("LLM did not return usable search queries")
    print(f"[LLM] generated {len(queries)} search queries")

    known_domains = seen_domains()
    crm_rows = existing_leads()
    seen_place_ids = {r.get("PlaceId", "").strip() for r in crm_rows if r.get("PlaceId")}
    seen_companies = {normalize_company(r.get("Company", "")) for r in crm_rows if r.get("Company")}

    raw_seen = set()
    verified_count = search_calls = processed = rejected = 0
    query_order = list(queries)
    random.Random(dt.date.today().toordinal()).shuffle(query_order)

    for query in query_order:
        if search_calls >= MAX_PLACES_SEARCH_REQUESTS or verified_count >= TARGET_VERIFIED_LEADS or len(raw_seen) >= MAX_RAW_CANDIDATES:
            break
        print(f"[Places] search {search_calls + 1}/{MAX_PLACES_SEARCH_REQUESTS}: {query}")
        places = places_search(query)
        search_calls += 1

        for place in places:
            if verified_count >= TARGET_VERIFIED_LEADS or len(raw_seen) >= MAX_RAW_CANDIDATES:
                break
            candidate = candidate_from_place(place, query)
            if not candidate:
                continue
            raw_key = candidate.place_id
            if raw_key in raw_seen:
                continue
            raw_seen.add(raw_key)

            domain = normalize_domain(candidate.website)
            append_jsonl(MEMORY_FILE, {
                "event": "candidate_seen",
                "place_id": candidate.place_id,
                "query": query,
                "domain_sha256": hashlib.sha256(domain.encode()).hexdigest() if domain else "",
            })

            if domain in known_domains or candidate.place_id in seen_place_ids or normalize_company(candidate.company) in seen_companies:
                rejected += 1
                continue

            known_domains.add(domain)
            remember_domain(domain)
            processed += 1
            print(f"  [Research] {candidate.company} -> {candidate.website}")

            research = website_research(candidate.website)
            if not research:
                rejected += 1
                continue
            findings, facts = research
            public_email = choose_public_business_email(findings, candidate.website)
            if not public_email:
                print("    [Skip] no verified public business email")
                rejected += 1
                continue

            qualified = llm_qualify(candidate, facts, public_email)
            if not qualified:
                print("    [Skip] LLM qualification rejected/uncertain")
                rejected += 1
                continue
            state = state_from_address(candidate.address)
            city = city_from_address(candidate.address, state)
            row = {
                "Email": public_email.email,
                "Company": qualified["company_name"],
                "Website": candidate.website,
                "City": city,
                "State": state,
                "Timezone": state_timezone(state),
                "LeadSource": "Google Places Text Search -> public website",
                "Verified": "PASS",
                "PlaceId": candidate.place_id,
                "EmailSourceURL": public_email.source_url,
                "WebsiteFacts": facts[:6000],
                "ScaleClass": qualified["scale_class"],
                "QualificationConfidence": str(qualified["confidence"]),
                "Status": "Verified",
                "FirstSeenDate": iso_now(),
                "Notes": qualified["reason"],
            }
            if already_in_crm(public_email.email, domain, qualified["company_name"]):
                rejected += 1
                continue
            append_csv(CRM_FILE, CRM_HEADERS, row)
            seen_place_ids.add(candidate.place_id)
            seen_companies.add(normalize_company(qualified["company_name"]))
            verified_count += 1
            append_jsonl(MEMORY_FILE, {
                "event": "verified_lead",
                "place_id": candidate.place_id,
                "domain_sha256": hashlib.sha256(domain.encode()).hexdigest(),
                "email": public_email.email,
                "qualification": qualified,
            })
            print(f"    [VERIFIED {verified_count}/{TARGET_VERIFIED_LEADS}] {public_email.email}")
        time.sleep(max(0, SEARCH_DELAY_SECONDS))

    summary = {
        "seed": seed, "verified_leads": verified_count, "target": TARGET_VERIFIED_LEADS,
        "places_search_calls": search_calls, "unique_raw_candidates": len(raw_seen),
        "processed_candidates": processed, "rejected": rejected,
        "duration_seconds": round(time.time() - start, 2),
    }
    append_jsonl(RUN_LOG_FILE, summary)
    print("\n[SUMMARY]")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    if verified_count < TARGET_VERIFIED_LEADS:
        print(f"[INFO] Target not reached this run ({verified_count}/{TARGET_VERIFIED_LEADS}).")
    else:
        print(f"[DONE] Collected {verified_count} verified leads.")


if __name__ == "__main__":
    main()
