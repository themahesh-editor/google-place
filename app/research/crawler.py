from __future__ import annotations

import html
import re
import time
import urllib.parse
import urllib.request
import urllib.robotparser
from dataclasses import dataclass
from html.parser import HTMLParser


@dataclass(frozen=True)
class PageEvidence:
    url: str
    text: str


class _Parser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text_parts: list[str] = []
        self.links: list[tuple[str, str]] = []
        self.skip_depth = 0
        self.link_href: str | None = None
        self.link_label: list[str] = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in {"script","style","noscript","svg","template","iframe"}:
            self.skip_depth += 1
        attrs = dict(attrs)
        if tag == "a" and attrs.get("href"):
            self.link_href = attrs["href"]
            self.link_label = []

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in {"script","style","noscript","svg","template","iframe"} and self.skip_depth:
            self.skip_depth -= 1
        if tag == "a" and self.link_href:
            self.links.append((self.link_href, " ".join(self.link_label).strip()))
            self.link_href = None
            self.link_label = []

    def handle_data(self, data):
        if self.skip_depth:
            return
        text = re.sub(r"\s+", " ", html.unescape(data)).strip()
        if text:
            self.text_parts.append(text)
            if self.link_href:
                self.link_label.append(text)


class WebsiteCrawler:
    PRIORITY = [
        "/","/about","/about-us","/services","/products","/solutions","/industries","/locations",
        "/team","/contact","/contact-us","/faq","/booking","/book","/request","/request-a-quote",
        "/get-started","/pricing"
    ]
    KEYWORDS = ("about","service","product","solution","industry","location","team","contact","faq","book","booking","request","quote","appointment")

    def __init__(self, timeout_seconds=15, max_bytes=2_000_000, max_pages=10, request_delay_seconds=0.25, honor_robots=True, user_agent="AttachAI-Outreach/1.0"):
        self.timeout_seconds=timeout_seconds
        self.max_bytes=max_bytes
        self.max_pages=max_pages
        self.request_delay_seconds=request_delay_seconds
        self.honor_robots=honor_robots
        self.user_agent=user_agent
        self.robots: dict[str, urllib.robotparser.RobotFileParser|None]={}

    @staticmethod
    def _origin(url):
        p=urllib.parse.urlparse(url)
        return f"{p.scheme}://{p.netloc}"

    def _allowed(self,url):
        if not self.honor_robots:
            return True
        origin=self._origin(url)
        if origin not in self.robots:
            try:
                req=urllib.request.Request(f"{origin}/robots.txt",headers={"User-Agent":self.user_agent})
                with urllib.request.urlopen(req,timeout=8) as r:
                    raw=r.read(self.max_bytes).decode("utf-8","ignore")
                rp=urllib.robotparser.RobotFileParser()
                rp.set_url(f"{origin}/robots.txt")
                rp.parse(raw.splitlines())
                self.robots[origin]=rp
            except Exception:
                self.robots[origin]=None
        rp=self.robots[origin]
        return True if rp is None else rp.can_fetch(self.user_agent,url)

    def _fetch(self,url):
        if not self._allowed(url):
            return None
        try:
            req=urllib.request.Request(url,headers={"User-Agent":self.user_agent,"Accept":"text/html,application/xhtml+xml"})
            with urllib.request.urlopen(req,timeout=self.timeout_seconds) as r:
                ctype=(r.headers.get("Content-Type") or "").lower()
                if ctype and "html" not in ctype:
                    return None
                raw=r.read(self.max_bytes+1)
            if len(raw)>self.max_bytes:
                return None
            p=_Parser(); p.feed(raw.decode("utf-8","ignore"))
            text=re.sub(r"\s+"," "," ".join(p.text_parts)).strip()
            return PageEvidence(url,text[:12000]),p.links
        except Exception:
            return None

    def discover_pages(self,home_url):
        value=home_url if "://" in home_url else f"https://{home_url}"
        p=urllib.parse.urlparse(value)
        if not p.hostname:
            return []
        home=urllib.parse.urlunparse((p.scheme or "https",p.netloc,p.path or "/","","",""))
        first=self._fetch(home)
        extra=[]
        if first:
            _,links=first
            for href,label in links:
                absolute=urllib.parse.urljoin(home,href)
                x=urllib.parse.urlparse(absolute)
                if x.scheme not in {"http","https"} or (x.hostname or "").lower()!=p.hostname.lower():
                    continue
                if any(k in f"{label} {x.path}".lower() for k in self.KEYWORDS):
                    clean=urllib.parse.urlunparse((x.scheme,x.netloc,x.path or "/","","",""))
                    if clean not in extra: extra.append(clean)
        origin=f"{p.scheme or 'https'}://{p.netloc}"
        ordered=[home]+[origin+x for x in self.PRIORITY if x!="/"]+extra
        out=[];seen=set()
        for u in ordered:
            x=urllib.parse.urlparse(u)
            clean=urllib.parse.urlunparse((x.scheme,x.netloc,x.path or "/","","",""))
            if (x.hostname or "").lower()!=p.hostname.lower() or clean in seen: continue
            seen.add(clean);out.append(clean)
            if len(out)>=self.max_pages: break
        return out

    def research(self,website):
        pages=self.discover_pages(website)
        result=[]
        for i,url in enumerate(pages):
            fetched=self._fetch(url)
            if fetched and fetched[0].text:
                result.append(fetched[0])
            if i+1<len(pages): time.sleep(max(0,self.request_delay_seconds))
        return result
