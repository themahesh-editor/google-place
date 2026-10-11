from __future__ import annotations

import base64
import json
import re
import time
import urllib.robotparser
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlparse, urldefrag

import requests
from bs4 import BeautifulSoup

from .db import normalize_domain, normalize_url
from .debug import debug
from .llm import LLMClient, LLMTemporaryError, LLMInvalidResponse, LLMPermanentError

EMAIL_RE = re.compile(r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b", re.I)
FREE_EMAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "yahoo.com", "hotmail.com", "outlook.com", "live.com", "msn.com",
    "icloud.com", "me.com", "aol.com", "protonmail.com", "proton.me", "gmx.com", "mail.com", "yandex.com",
}
BLOCKED_LOCAL_PARTS = {"noreply", "no-reply", "donotreply", "do-not-reply", "mailer-daemon", "abuse"}
KEYWORD_SCORES = {
    "about": 10, "contact": 10, "team": 9, "services": 8, "service": 8, "solutions": 7,
    "specialties": 7, "industries": 6, "work": 5, "products": 5, "company": 4,
}


@dataclass(frozen=True)
class Page:
    url: str
    title: str
    text: str
    links: tuple[str, ...] = ()
    emails: tuple[str, ...] = ()


def canonicalize(url: str) -> str:
    text = (url or "").strip()
    if not text:
        return ""
    if "://" not in text:
        text = "https://" + text
    parsed = urlparse(text)
    if not parsed.hostname:
        return ""
    scheme = parsed.scheme.lower() or "https"
    host = parsed.hostname.lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    port = parsed.port
    if port and not ((scheme == "https" and port == 443) or (scheme == "http" and port == 80)):
        host = f"{host}:{port}"
    path = parsed.path or "/"
    if path != "/":
        path = re.sub(r"/{2,}", "/", path).rstrip("/") or "/"
    return f"{scheme}://{host}{path}"


def extract_visible_text(html_doc: str, limit: int = 12000) -> str:
    soup = BeautifulSoup(html_doc, "html.parser")
    for tag in soup(["script", "style", "noscript", "template", "svg"]):
        tag.decompose()
    text = soup.get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text)[:limit]


def decode_cloudflare_email(encoded: str) -> str:
    try:
        key = int(encoded[:2], 16)
        return "".join(chr(int(encoded[i:i + 2], 16) ^ key) for i in range(2, len(encoded), 2))
    except Exception:
        return ""


def email_strings(text: str) -> list[str]:
    return sorted({m.group(0).lower().strip(".,;:()[]<>") for m in EMAIL_RE.finditer(text or "")})


def extract_jsonld_emails(soup: BeautifulSoup) -> list[str]:
    found: set[str] = set()
    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for k, v in value.items():
                if str(k).lower() == "email" and isinstance(v, str):
                    found.update(email_strings(v))
                walk(v)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            walk(json.loads(script.string or script.get_text()))
        except Exception:
            continue
    return sorted(found)


def extract_emails(page: Page) -> list[str]:
    return sorted(set(page.emails) | set(email_strings(page.text)))


def choose_public_business_email(pages: list[Page], website: str, has_mx) -> tuple[str, str] | None:
    domain = normalize_domain(website)
    candidates: list[tuple[int, str, str]] = []
    for page in pages:
        for email in extract_emails(page):
            local, _, edomain = email.partition("@")
            if not edomain or email in BLOCKED_LOCAL_PARTS or local in BLOCKED_LOCAL_PARTS:
                continue
            if edomain in FREE_EMAIL_DOMAINS and edomain != domain:
                continue
            if edomain != domain:
                continue
            if not has_mx(edomain):
                continue
            score = 0
            if local in {"hello", "info", "contact", "sales", "team", "office", "business", "inquiries"}:
                score += 100
            if "contact" in page.url:
                score += 20
            if "team" in page.url or "about" in page.url:
                score += 5
            candidates.append((score, email, page.url))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
    return candidates[0][1], candidates[0][2]


class WebsiteCrawler:
    """Canonical, bounded crawler. A single crawl fetches the homepage exactly once."""

    def __init__(self, timeout_seconds: int, max_bytes: int, max_pages: int, delay_seconds: float, honor_robots: bool, user_agent: str = "AttachAI-Research/3.0"):
        self.timeout_seconds = timeout_seconds
        self.max_bytes = max_bytes
        self.max_pages = max_pages
        self.delay_seconds = delay_seconds
        self.honor_robots = honor_robots
        self.user_agent = user_agent

    def _allowed(self, robots: urllib.robotparser.RobotFileParser | None, url: str) -> bool:
        if not self.honor_robots or robots is None:
            return True
        return robots.can_fetch(self.user_agent, url)

    def _load_robots(self, session: requests.Session, origin: str) -> urllib.robotparser.RobotFileParser | None:
        if not self.honor_robots:
            return None
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(urljoin(origin, "/robots.txt"))
        try:
            response = session.get(rp.url, timeout=self.timeout_seconds)
            if response.status_code < 400:
                rp.parse(response.text.splitlines())
                return rp
        except requests.RequestException:
            pass
        return None

    def fetch(self, session: requests.Session, url: str, robots: urllib.robotparser.RobotFileParser | None) -> Page | None:
        canonical = canonicalize(url)
        if not canonical or not self._allowed(robots, canonical):
            return None
        try:
            response = session.get(canonical, timeout=self.timeout_seconds, stream=True, allow_redirects=True)
            if response.status_code >= 400:
                return None
            content = bytearray()
            for chunk in response.iter_content(65536):
                content.extend(chunk)
                if len(content) > self.max_bytes:
                    break
            if len(content) > self.max_bytes:
                return None
            encoding = response.encoding or "utf-8"
            html = bytes(content).decode(encoding, errors="replace")
        except (requests.RequestException, UnicodeError):
            return None
        soup = BeautifulSoup(html, "html.parser")
        links: list[str] = []
        for a in soup.find_all("a", href=True):
            target = urldefrag(urljoin(response.url, str(a.get("href")))).url
            normalized = canonicalize(target)
            if normalized:
                links.append(normalized)
        title = (soup.title.get_text(" ", strip=True) if soup.title else "")[:300]
        email_values = set(email_strings(extract_visible_text(html)))
        email_values.update(extract_jsonld_emails(soup))
        for a in soup.select("a[href^='mailto:']"):
            email_values.update(email_strings(a.get("href", "").split(":", 1)[-1].split("?", 1)[0]))
        for el in soup.select("[data-cfemail]"):
            decoded = decode_cloudflare_email(el.get("data-cfemail", ""))
            if decoded:
                email_values.update(email_strings(decoded))
        return Page(canonicalize(response.url), title, extract_visible_text(html), tuple(sorted(set(links))), tuple(sorted(email_values)))

    def discover_urls(self, home: Page) -> list[str]:
        origin = f"{urlparse(home.url).scheme}://{urlparse(home.url).netloc}/"
        candidates: list[tuple[int, str]] = []
        for link in home.links:
            parsed = urlparse(link)
            if f"{parsed.scheme}://{parsed.netloc}/" != origin:
                continue
            lower = (parsed.path + " " + parsed.query).lower()
            score = 0
            for keyword, points in KEYWORD_SCORES.items():
                if keyword in lower:
                    score += points
            if score:
                candidates.append((score, link))
        candidates.sort(key=lambda x: (-x[0], x[1]))
        return [url for _, url in candidates[: max(0, self.max_pages - 1)]]

    def crawl(self, website: str) -> list[Page]:
        home = canonicalize(website)
        if not home:
            return []
        started = time.monotonic()
        session = requests.Session()
        session.headers.update({"User-Agent": self.user_agent, "Accept": "text/html,application/xhtml+xml"})
        origin = f"{urlparse(home).scheme}://{urlparse(home).netloc}/"
        robots = self._load_robots(session, origin)
        pages: list[Page] = []
        seen: set[str] = set()

        first = self.fetch(session, home, robots)
        if first:
            pages.append(first)
            seen.add(first.url)
            urls = self.discover_urls(first)
        else:
            urls = []

        for url in urls:
            if len(pages) >= self.max_pages:
                break
            normalized = canonicalize(url)
            if not normalized or normalized in seen:
                continue
            if self.delay_seconds:
                time.sleep(self.delay_seconds)
            page = self.fetch(session, normalized, robots)
            if page and page.url not in seen:
                pages.append(page)
                seen.add(page.url)
        debug("RESEARCH_CRAWL", website=website, pages=len(pages), elapsed_seconds=round(time.monotonic() - started, 3))
        return pages


def validate_research_schema(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LLMInvalidResponse("website_research must return an object")
    required = {"company_identity", "business_summary", "services", "business_facts", "locations", "specialties", "website_signals", "customer_journey_signals", "ai_opportunity_signals"}
    missing = sorted(required - set(value))
    if missing:
        raise LLMInvalidResponse("website_research missing fields: " + ", ".join(missing))
    scalar_fields = {"company_identity", "business_summary"}
    list_fields = required - scalar_fields
    for field in scalar_fields:
        if not isinstance(value.get(field), str) or not value[field].strip():
            raise LLMInvalidResponse(f"website_research field {field} must be a non-empty string")
    for field in list_fields:
        raw = value.get(field)
        if not isinstance(raw, list) or any(not isinstance(item, str) or not item.strip() for item in raw):
            raise LLMInvalidResponse(f"website_research field {field} must be a string array")
    return {field: value[field] for field in sorted(required)}


class ResearchService:
    SYSTEM_PROMPT = """
You are a conservative business researcher. Return ONLY JSON object:
{
  "company_identity":"...",
  "business_summary":"...",
  "services":["..."],
  "business_facts":["..."],
  "locations":["..."],
  "specialties":["..."],
  "website_signals":["..."],
  "customer_journey_signals":["..."],
  "ai_opportunity_signals":["..."]
}
Use only the supplied page evidence. Never invent facts. Keep arrays concise and evidence-grounded.
""".strip()

    def __init__(self, store, llm: LLMClient, crawler: WebsiteCrawler, version: str = "research-v3"):
        self.store = store
        self.llm = llm
        self.crawler = crawler
        self.version = version

    def run(self, lead: dict) -> tuple[dict, list[Page]]:
        canonical = canonicalize(lead["website"])
        cached = self.store.get_research_cache(canonical, self.version)
        if cached and cached["status"] == "RESEARCHED":
            evidence = [Page(x["url"], x.get("title", ""), x.get("text", ""), tuple(x.get("links", [])), tuple(x.get("emails", []))) for x in json.loads(cached["pages_json"])]
            obj = validate_research_schema(json.loads(cached["research_json"]))
            self.store.save_lead_research(lead["lead_id"], cached["cache_id"], "RESEARCHED")
            return obj, evidence

        pages = self.crawler.crawl(canonical)
        if not pages:
            cache_id = self.store.save_research_cache(canonical, self.version, [], {}, "FAILED", "no crawlable pages")
            self.store.save_lead_research(lead["lead_id"], cache_id, "FAILED_TERMINAL", "no crawlable pages")
            raise RuntimeError("website crawl returned no pages")

        evidence_lines = []
        for page in pages:
            evidence_lines.append(f"URL: {page.url}\nTITLE: {page.title}\nTEXT: {page.text[:5000]}")
        evidence_text = "\n\n".join(evidence_lines)[:30000]

        try:
            obj = self.llm.chat_json_object(
                self.SYSTEM_PROMPT,
                f"Company: {lead['company']}\nWebsite: {canonical}\n\nPAGE EVIDENCE:\n{evidence_text}",
                max_tokens=1200,
                operation="website_research",
            )
        except (LLMTemporaryError, LLMInvalidResponse):
            cache_id = self.store.save_research_cache(canonical, self.version, pages, {}, "PARTIAL_LLM_FAILURE", "temporary/invalid LLM response")
            self.store.save_lead_research(lead["lead_id"], cache_id, "FAILED_RETRYABLE", "temporary/invalid LLM response")
            raise
        except LLMPermanentError as exc:
            cache_id = self.store.save_research_cache(canonical, self.version, pages, {}, "FAILED", str(exc)[:500])
            self.store.save_lead_research(lead["lead_id"], cache_id, "FAILED_TERMINAL", str(exc)[:500])
            raise

        validated = validate_research_schema(obj)
        clean = {
            "company_identity": str(validated["company_identity"] or lead["company"]),
            "business_summary": str(obj.get("business_summary") or "").strip(),
            "services": self._arr(validated.get("services")),
            "business_facts": self._arr(validated.get("business_facts")),
            "locations": self._arr(validated.get("locations")),
            "specialties": self._arr(validated.get("specialties")),
            "website_signals": self._arr(validated.get("website_signals")),
            "customer_journey_signals": self._arr(validated.get("customer_journey_signals")),
            "ai_opportunity_signals": self._arr(validated.get("ai_opportunity_signals")),
        }
        pages_json = [page.__dict__ | {"links": list(page.links)} for page in pages]
        cache_id = self.store.save_research_cache(canonical, self.version, pages, clean, "RESEARCHED", None)
        self.store.save_lead_research(lead["lead_id"], cache_id, "RESEARCHED")
        return clean, pages

    @staticmethod
    def _arr(value: Any, limit: int = 12) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(x).strip()[:500] for x in value if str(x).strip()][:limit]
