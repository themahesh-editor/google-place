from __future__ import annotations

import html
import json
import re
import time
import urllib.parse
import urllib.robotparser
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parseaddr
from typing import Any

import requests
from bs4 import BeautifulSoup

from app.db import deterministic_research_id, normalize_domain
from app.models import Evidence
from app.llm import LLMClient, LLMTemporaryError


EMAIL_RE = re.compile(r"(?<![\w.+-])[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,63}(?![\w.-])", re.I)
FREE_EMAIL_DOMAINS = {"gmail.com", "googlemail.com", "yahoo.com", "hotmail.com", "outlook.com", "live.com", "msn.com", "icloud.com", "me.com", "aol.com", "protonmail.com", "proton.me", "gmx.com", "mail.com", "yandex.com", "zoho.com"}
DISPOSABLE_DOMAINS = {"10minutemail.com", "guerrillamail.com", "mailinator.com", "yopmail.com", "getnada.com", "tempmail.com", "temp-mail.org", "discard.email", "throwawaymail.com"}
BLOCKED_LOCALS = {"noreply", "no-reply", "donotreply", "do-not-reply", "mailer-daemon", "abuse"}


@dataclass(frozen=True)
class Page:
    url: str
    text: str
    html: str


class WebsiteCrawler:
    PRIORITY_PATHS = (
        "/", "/contact", "/contact-us", "/contactus", "/get-in-touch", "/connect", "/about", "/about-us",
        "/company", "/team", "/our-team", "/staff", "/leadership", "/locations", "/location", "/services",
        "/products", "/solutions", "/industries", "/faq", "/booking", "/book", "/request", "/request-a-quote", "/pricing",
    )
    KEYWORDS = ("contact", "about", "team", "staff", "leadership", "location", "service", "faq", "book", "request", "quote")

    def __init__(self, timeout_seconds: int, max_bytes: int, max_pages: int, delay_seconds: float, honor_robots: bool, user_agent: str = "AttachAI-Research/2.0"):
        self.timeout_seconds = timeout_seconds
        self.max_bytes = max_bytes
        self.max_pages = max_pages
        self.delay_seconds = delay_seconds
        self.honor_robots = honor_robots
        self.user_agent = user_agent
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent, "Accept-Language": "en-US,en;q=0.8"})
        self.robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    def _origin(self, url: str) -> str:
        parsed = urllib.parse.urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}"

    def _allowed(self, url: str) -> bool:
        if not self.honor_robots:
            return True
        origin = self._origin(url)
        if origin not in self.robots:
            try:
                response = self.session.get(f"{origin}/robots.txt", timeout=8)
                if response.status_code >= 400:
                    self.robots[origin] = None
                else:
                    parser = urllib.robotparser.RobotFileParser()
                    parser.set_url(f"{origin}/robots.txt")
                    parser.parse(response.text.splitlines())
                    self.robots[origin] = parser
            except Exception:
                self.robots[origin] = None
        parser = self.robots.get(origin)
        return True if parser is None else parser.can_fetch(self.user_agent, url)

    def fetch(self, url: str) -> Page | None:
        if not self._allowed(url):
            return None
        try:
            response = self.session.get(url, timeout=self.timeout_seconds, allow_redirects=True)
            if response.status_code >= 400:
                return None
            ctype = (response.headers.get("content-type") or "").lower()
            if ctype and "html" not in ctype and "xhtml" not in ctype:
                return None
            raw = response.content
            if len(raw) > self.max_bytes:
                return None
            text = extract_visible_text(raw.decode(response.encoding or "utf-8", errors="ignore"), 12000)
            return Page(response.url, text, raw.decode(response.encoding or "utf-8", errors="ignore"))
        except Exception:
            return None

    def _sitemap_urls(self, home: str) -> list[str]:
        parsed = urllib.parse.urlparse(home)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        candidates = [f"{origin}/sitemap.xml", f"{origin}/sitemap_index.xml", f"{origin}/wp-sitemap.xml"]
        try:
            robots = self.session.get(f"{origin}/robots.txt", timeout=8)
            if robots.status_code < 400:
                candidates.extend(line.split(":", 1)[1].strip() for line in robots.text.splitlines() if line.lower().startswith("sitemap:"))
        except Exception:
            pass
        seen: set[str] = set()
        urls: list[str] = []
        nested: list[str] = []
        for sitemap in candidates:
            if sitemap in seen:
                continue
            seen.add(sitemap)
            try:
                response = self.session.get(sitemap, timeout=self.timeout_seconds)
                if response.status_code >= 400:
                    continue
                root = ET.fromstring(response.text)
            except Exception:
                continue
            for node in root.iter():
                if not node.tag.lower().endswith("loc") or not node.text:
                    continue
                value = node.text.strip()
                if not value.startswith(origin):
                    continue
                if value.endswith(".xml") or value.endswith(".xml.gz"):
                    nested.append(value)
                elif value not in urls:
                    urls.append(value)
                if len(urls) >= 80:
                    return urls
        for sitemap in nested[:5]:
            try:
                response = self.session.get(sitemap, timeout=self.timeout_seconds)
                root = ET.fromstring(response.text)
                for node in root.iter():
                    if node.tag.lower().endswith("loc") and node.text and node.text.strip().startswith(origin):
                        value = node.text.strip()
                        if value not in urls:
                            urls.append(value)
                        if len(urls) >= 80:
                            return urls
            except Exception:
                continue
        return urls

    def discover_urls(self, website: str) -> list[str]:
        value = website if "://" in website else f"https://{website}"
        parsed = urllib.parse.urlparse(value)
        if not parsed.hostname:
            return []
        origin = f"{parsed.scheme or 'https'}://{parsed.netloc}"
        host = normalize_domain(parsed.hostname)
        home = urllib.parse.urlunparse((parsed.scheme or "https", parsed.netloc, parsed.path or "/", "", "", ""))
        urls = [home]
        seen = {home}
        first = self.fetch(home)
        linked: list[str] = []
        if first:
            soup = BeautifulSoup(first.html, "html.parser")
            for anchor in soup.find_all("a", href=True):
                absolute = urllib.parse.urljoin(first.url, anchor.get("href", ""))
                item = urllib.parse.urlparse(absolute)
                if item.scheme not in {"http", "https"} or normalize_domain(item.hostname or "") != host:
                    continue
                label = f"{anchor.get_text(' ', strip=True)} {item.path}".lower()
                if any(word in label for word in self.KEYWORDS):
                    clean = urllib.parse.urlunparse((item.scheme, item.netloc, item.path or "/", "", "", ""))
                    if clean not in linked:
                        linked.append(clean)
        ordered = [origin + p for p in self.PRIORITY_PATHS if p != "/"] + linked
        for value in self._sitemap_urls(home):
            if any(word in value.lower() for word in self.KEYWORDS):
                ordered.append(value)
        for url in ordered:
            item = urllib.parse.urlparse(url)
            clean = urllib.parse.urlunparse((item.scheme, item.netloc, item.path or "/", "", "", ""))
            if normalize_domain(item.hostname or "") != host or clean in seen:
                continue
            seen.add(clean)
            urls.append(clean)
            if len(urls) >= self.max_pages:
                break
        return urls[:self.max_pages]

    def crawl(self, website: str) -> list[Page]:
        pages: list[Page] = []
        for index, url in enumerate(self.discover_urls(website)):
            page = self.fetch(url)
            if page and page.text:
                pages.append(page)
            if index + 1 < self.max_pages:
                time.sleep(max(0.0, self.delay_seconds))
        return pages


def extract_visible_text(html_doc: str, limit: int = 12000) -> str:
    soup = BeautifulSoup(html_doc or "", "html.parser")
    for node in soup(["script", "style", "noscript", "svg", "template", "iframe"]):
        node.decompose()
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True))[:limit]


def decode_cloudflare_email(encoded: str) -> str:
    try:
        key = int(encoded[:2], 16)
        return "".join(chr(int(encoded[i:i + 2], 16) ^ key) for i in range(2, len(encoded), 2))
    except Exception:
        return ""


def email_strings(text: str) -> list[str]:
    if not text:
        return []
    text = html.unescape(text)
    found = {x.lower() for x in EMAIL_RE.findall(text)}
    obfuscated = re.sub(r"(?<![A-Za-z0-9])(?:\[\s*at\s*\]|\(\s*at\s*\)|\{\s*at\s*\}|at|@)(?![A-Za-z0-9])", "@", text, flags=re.I)
    obfuscated = re.sub(r"(?<![A-Za-z0-9])(?:\[\s*dot\s*\]|\(\s*dot\s*\)|\{\s*dot\s*\}|dot)(?![A-Za-z0-9])", ".", obfuscated, flags=re.I)
    obfuscated = re.sub(r"\s*@\s*", "@", obfuscated)
    obfuscated = re.sub(r"\s*\.\s*", ".", obfuscated)
    found.update(x.lower() for x in EMAIL_RE.findall(obfuscated))
    return sorted(found)


def extract_jsonld_emails(soup: BeautifulSoup) -> list[str]:
    found: list[str] = []
    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key.lower() in {"email", "emailaddress"} and isinstance(child, str):
                    found.extend(email_strings(child))
                else:
                    walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    for script in soup.find_all("script", attrs={"type": re.compile(r"application/ld\+json", re.I)}):
        try:
            walk(json.loads(script.get_text(" ", strip=True)))
        except Exception:
            continue
    return found


def extract_emails(page: Page) -> list[str]:
    soup = BeautifulSoup(page.html, "html.parser")
    candidates: list[str] = []
    for anchor in soup.find_all("a", href=True):
        href = html.unescape(urllib.parse.unquote(anchor.get("href", "")))
        if href.lower().startswith("mailto:"):
            candidates.extend(email_strings(href[7:].split("?", 1)[0]))
        for value in (anchor.get("aria-label"), anchor.get("title"), anchor.get("data-email")):
            candidates.extend(email_strings(value or ""))
    for node in soup.find_all(attrs={"data-cfemail": True}):
        candidates.extend(email_strings(decode_cloudflare_email(node.get("data-cfemail", ""))))
    for encoded in re.findall(r"/cdn-cgi/l/email-protection#([0-9a-fA-F]+)", page.html):
        candidates.extend(email_strings(decode_cloudflare_email(encoded)))
    candidates.extend(email_strings(page.text))
    candidates.extend(email_strings(page.html))
    candidates.extend(extract_jsonld_emails(soup))
    result: list[str] = []
    for email in candidates:
        email = email.lower().strip()
        if email and email not in result:
            result.append(email)
    return result


def choose_public_business_email(pages: list[Page], website: str, has_mx) -> tuple[str, str] | None:
    site = normalize_domain(website)
    candidates: list[tuple[int, int, str, str]] = []
    preferred = {"contact", "info", "hello", "sales", "office", "team"}
    for page in pages:
        for email in extract_emails(page):
            local, domain = email.rsplit("@", 1)
            rank = 0 if local in preferred else 1
            candidates.append((rank, len(email), email, page.url))
    for _, _, email, source_url in sorted(candidates):
        if len(email) > 254:
            continue
        local, domain = email.rsplit("@", 1)
        if local in BLOCKED_LOCALS or domain in FREE_EMAIL_DOMAINS or domain in DISPOSABLE_DOMAINS:
            continue
        if not (domain == site or domain.endswith("." + site)):
            continue
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email) or len(local) > 64 or ".." in local:
            continue
        if not has_mx(domain):
            continue
        return email, source_url
    return None


class ResearchService:
    SYSTEM_PROMPT = """
You are an evidence-bound website research analyst for AttachAI.
Return ONLY JSON with keys: business_summary, services, business_facts, locations, specialties,
website_signals, customer_journey_signals, ai_opportunity_signals, important_public_text, evidence_urls.
Use ONLY the current lead and current website evidence supplied. Do not use memory from any other lead.
Do not infer unsupported pain points. Every signal and claim must be grounded in supplied evidence.
evidence_urls must be a subset of supplied URLs.
""".strip()

    def __init__(self, store, llm: LLMClient, crawler: WebsiteCrawler, version: str):
        self.store = store
        self.llm = llm
        self.crawler = crawler
        self.version = version

    def run(self, lead, run_id: str):
        timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        pages = self.crawler.crawl(lead["website"])
        evidence = [Evidence(p.url, p.text[:2000]) for p in pages if p.text]
        if not evidence:
            record = self._record(lead, timestamp, [], "FAILED", self.version, error="no_website_evidence")
            self.store.save_research(record)
            self.store.update_lead_status(lead["lead_id"], "ELIGIBLE")
            return record
        blob = "\n\n".join(f"URL: {e.url}\nTEXT: {e.snippet}" for e in evidence)[:16000]
        prompt = (
            f"CURRENT LEAD ONLY\nLeadID: {lead['lead_id']}\nCompany: {lead['company']}\nWebsite: {lead['website']}\n"
            f"Email: {lead['email']}\nLocation: {lead['city']}, {lead['region']} {lead['country_code']}\n"
            f"Current discovery facts: {lead.get('discovery_facts','')[:3000]}\n\nWEBSITE EVIDENCE ONLY\n{blob}"
        )
        try:
            obj = self.llm.chat_json_object(self.SYSTEM_PROMPT, prompt, max_tokens=1400)
        except LLMTemporaryError as exc:
            record = self._record(lead, timestamp, evidence, "PARTIAL_LLM_FAILURE", self.version, error=str(exc))
            self.store.save_research(record)
            self.store.update_lead_status(lead["lead_id"], "ELIGIBLE")
            return record
        allowed = {e.url for e in evidence}
        urls = [u for u in obj.get("evidence_urls", []) if isinstance(u, str) and u in allowed]
        if not urls:
            urls = [e.url for e in evidence[:3]]
        selected = [e for e in evidence if e.url in urls]
        record = {
            "research_id": deterministic_research_id(lead["lead_id"], timestamp),
            "lead_id": lead["lead_id"], "website_domain": lead["website_domain"], "canonical_url": lead["website"],
            "company_identity": lead["company"], "business_summary": str(obj.get("business_summary") or "")[:1500],
            "services": self._arr(obj, "services"), "business_facts": self._arr(obj, "business_facts"),
            "locations": self._arr(obj, "locations"), "specialties": self._arr(obj, "specialties"),
            "website_signals": self._arr(obj, "website_signals"), "customer_journey_signals": self._arr(obj, "customer_journey_signals"),
            "ai_opportunity_signals": self._arr(obj, "ai_opportunity_signals"), "important_public_text": str(obj.get("important_public_text") or "")[:5000],
            "evidence": [e.__dict__ for e in selected], "research_timestamp_utc": timestamp, "research_status": "RESEARCHED",
            "research_version": self.version, "error": None, "retry_count": 0, "next_retry_at_utc": None,
        }
        self.store.save_research(record)
        self.store.update_lead_status(lead["lead_id"], "RESEARCHED")
        self.store.add_event("research_succeeded", run_id=run_id, lead_id=lead["lead_id"], status="RESEARCHED", metadata={"research_id": record["research_id"]})
        return record

    @staticmethod
    def _arr(obj: dict[str, Any], key: str, limit: int = 12) -> list[str]:
        return [str(x).strip()[:500] for x in obj.get(key, []) if str(x).strip()][:limit]

    @staticmethod
    def _record(lead, timestamp, evidence, status, version, error=None):
        return {
            "research_id": deterministic_research_id(lead["lead_id"], timestamp),
            "lead_id": lead["lead_id"], "website_domain": lead["website_domain"], "canonical_url": lead["website"],
            "company_identity": lead["company"], "business_summary": "", "services": [], "business_facts": [], "locations": [], "specialties": [],
            "website_signals": [], "customer_journey_signals": [], "ai_opportunity_signals": [], "important_public_text": "",
            "evidence": [e.__dict__ for e in evidence], "research_timestamp_utc": timestamp, "research_status": status,
            "research_version": version, "error": error, "retry_count": 1, "next_retry_at_utc": None,
        }
