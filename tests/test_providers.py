"""Network-free regression tests for canonical provider contracts."""
import copy
import json
import smtplib
import socket
import time
from datetime import datetime, timezone
from email.message import EmailMessage
from email.parser import BytesParser
from email import policy
from types import SimpleNamespace

import pytest
import requests

from attachai import providers as p


@pytest.fixture(autouse=True)
def no_external_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Tests must never access an external service")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(requests.Session, "post", forbidden)


@pytest.fixture
def config():
    return SimpleNamespace(data={
        "safety": {"send_enabled": True, "dry_run": False, "emergency_stop": False},
        "research": {"max_pages": 5, "max_bytes": 1_000_000, "timeout_seconds": 15,
                     "robots_enabled": True, "max_evidence": 12},
        "llm": {"base_url": "https://api.example/v1", "model": "test-model", "timeout_seconds": 20,
                "offer": "AttachAI helps respond to customer inquiries.", "signature": "AttachAI team",
                "postal_address": "123 Business St, Austin, TX 78701"},
        "mailbox": {"lookback_days": 30, "max_messages_per_sender": 2, "timeout_seconds": 20},
    }, send_enabled=True, dry_run=False)


@pytest.fixture
def sender():
    return p.Sender("sender-1", "team@example.org", "TOP-SECRET", "smtp.example.org", 465,
                    "imap.example.org", 993, "ssl")


@pytest.fixture
def research():
    snippet = "We provide dental care and appointments for local families."
    url = "https://example.org/Services"
    return {"pages": [{"url": url, "text": snippet}],
            "evidence": [{"id": p.stable_id(url, snippet), "url": url, "snippet": snippet}], "emails": []}


def good_draft(research, config):
    fact = research["evidence"][0]
    draft = {"subject": p.SUBJECT, "body": "", "cta": p.CTA,
             "observations": [{"claim": fact["snippet"], "evidence_ids": [fact["id"]]}],
             "opportunity": p.OPPORTUNITY, "evidence_refs": [copy.deepcopy(fact)],
             "offer": config.data["llm"]["offer"], "signature": "AttachAI team",
             "postal_address": config.data["llm"]["postal_address"]}
    draft["body"] = p._render(draft)
    return draft


def test_ids_are_structured_stable_and_type_sensitive():
    assert p.stable_id("lead", 1) == p.stable_id("lead", 1)
    assert len(p.stable_id("lead", 1)) == 64
    assert p.stable_id("a|b", "c") != p.stable_id("a", "b|c")
    assert p.stable_id(1) != p.stable_id("1")
    assert p.stable_id({"x": 1, "y": 2}) == p.stable_id({"y": 2, "x": 1})


@pytest.mark.parametrize("value", ["a..b@example.org", ".a@example.org", "a@localhost", "a@-bad.org",
                                  "Name <a@example.org>", "a@example.org\r\nBcc:x@y.org", "a@127.0.0.1"])
def test_email_rejects_unusable_syntax(value):
    with pytest.raises(p.ProviderError):
        p.normalize_email(value)


def test_email_normalization_and_secret_repr(sender):
    assert p.normalize_email(" INFO+tag@EXAMPLE.ORG ") == "info+tag@example.org"
    assert "TOP-SECRET" not in repr(sender)


def test_url_normalization_preserves_path_case_and_query():
    assert p.normalize_url("HTTPS://WWW.Example.org:443/Services/?utm_source=x&b=2&a=1#top") == "https://example.org/Services?a=1&b=2"
    assert p.normalize_url("https://example.org/services") != p.normalize_url("https://example.org/Services")
    assert p.normalize_url("example.org") == "https://example.org/"
    assert p.normalize_url("https://example.org/?tag=z&tag=a") == "https://example.org/?tag=z&tag=a"


@pytest.mark.parametrize("value", ["file:///etc/passwd", "https://u:p@example.org", "http://example.org:bad/", "https://example.org\\@127.0.0.1/"])
def test_url_invalid_schemes_credentials_ports(value):
    with pytest.raises(p.ProviderError):
        p.normalize_url(value)


class APIResponse:
    def __init__(self, body, status=200):
        self.body, self.status_code = body, status
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def iter_content(self, size):
        yield self.body if isinstance(self.body, bytes) else json.dumps(self.body).encode()


def mock_api(monkeypatch, response=None, error=None):
    calls = []
    def post(self, url, **kwargs):
        calls.append((url, kwargs))
        if error:
            raise error
        return response
    monkeypatch.setattr(requests.Session, "post", post)
    return calls


def test_google_places_real_protocol_single_page_and_pagination(monkeypatch, config):
    calls = mock_api(monkeypatch, APIResponse({"places": [{"id": "place-1", "displayName": {"text": "Dentist"},
                                                        "websiteUri": "https://www.example.org/", "rating": 4.5, "userRatingCount": 20}],
                                               "nextPageToken": "next"}))
    result = p.Discovery(config, SimpleNamespace(places_key="PRIVATE-KEY")).search("dentist in Austin", "previous")
    assert result["next_page_token"] == "next"
    assert result["requests_used"] == len(calls) == 1
    assert result["candidates"][0]["reviews"] == 20
    assert "email" not in result["candidates"][0]
    assert calls[0][1]["json"]["pageToken"] == "previous"
    assert "places.rating" in calls[0][1]["headers"]["X-Goog-FieldMask"]
    assert calls[0][1]["allow_redirects"] is False


@pytest.mark.parametrize("status,kind", [(503, "temporary"), (429, "temporary"), (401, "auth"), (400, "terminal"), (302, "terminal")])
def test_provider_http_failures_no_internal_retries(monkeypatch, status, kind):
    calls = mock_api(monkeypatch, APIResponse(b"private response text", status))
    with pytest.raises(p.ProviderError) as exc:
        p._api_post("https://example.org/private-key", {}, {"Authorization": "SECRET"}, 1)
    assert exc.value.kind == kind
    assert "private" not in str(exc.value) and "SECRET" not in str(exc.value)
    assert len(calls) == 1


def test_provider_timeout_redacted(monkeypatch):
    mock_api(monkeypatch, error=requests.ReadTimeout("https://SECRET-key.example"))
    with pytest.raises(p.ProviderError) as exc:
        p._api_post("https://example.org", {}, {}, 1)
    assert exc.value.kind == "temporary"
    assert "SECRET" not in str(exc.value)


@pytest.mark.parametrize("raw", [b"not-json", b"[]", b"x" * 2_000_001])
def test_http_200_invalid_json_and_response_bound(monkeypatch, raw):
    mock_api(monkeypatch, APIResponse(raw))
    with pytest.raises(p.ProviderError) as exc:
        p._api_post("https://example.org", {}, {}, 1)
    assert exc.value.kind == "invalid"


def test_llm_grounded_structured_response(monkeypatch, config, research):
    draft = good_draft(research, config)
    draft["body"] = "Injected unsupported assertion about their revenue."
    calls = mock_api(monkeypatch, APIResponse({"choices": [{"message": {"content": json.dumps(draft)}}]}))
    result = p.LLM(config, SimpleNamespace(llm_key="SECRET")).draft({"name": "Dentist"}, research, 0, [])
    assert p.validate_draft(result, research) == []
    assert "revenue" not in result["body"]
    assert research["evidence"][0]["snippet"] in result["body"]
    assert p.OPT_OUT in result["body"]
    assert len(calls) == 1


@pytest.mark.parametrize("content", ["not json", "[]", "{}", '{"observations":42}'])
def test_llm_malformed_response(monkeypatch, config, research, content):
    mock_api(monkeypatch, APIResponse({"choices": [{"message": {"content": content}}]}))
    with pytest.raises(p.ProviderError) as exc:
        p.LLM(config, SimpleNamespace(llm_key="SECRET")).draft({}, research, 0, [])
    assert exc.value.kind == "invalid"


def test_evidence_url_variants_and_strict_exact_quotes(config, research):
    draft = good_draft(research, config)
    draft["evidence_refs"][0]["url"] = "https://www.example.org:443/Services/?utm_source=email#top"
    assert not p.validate_draft(draft, research)
    draft["observations"][0]["claim"] = "Your dental care revenue grew 500 percent."
    draft["body"] = p._render(draft)
    assert "Observation must be an exact grounded snippet" in p.validate_draft(draft, research)


@pytest.mark.parametrize("mutation", ["fake_reference", "fake_snippet", "invented_body", "not_hypothetical", "empty_observations"])
def test_validator_rejects_unsupported_claims(config, research, mutation):
    draft = good_draft(research, config)
    if mutation == "fake_reference":
        draft["evidence_refs"][0]["id"] = "invented"
    elif mutation == "fake_snippet":
        draft["evidence_refs"][0]["snippet"] = "fabricated evidence"
    elif mutation == "invented_body":
        draft["body"] += " You lose ten customers every day."
    elif mutation == "not_hypothetical":
        draft["opportunity"] = "You need an assistant because you cannot answer customers."
        draft["body"] = p._render(draft)
    else:
        draft["observations"] = []
        draft["body"] = p._render(draft)
    assert p.validate_draft(draft, research)


def dns(monkeypatch, ips):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443)) for ip in ips])


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.1.1.1", "169.254.169.254", "::1", "::ffff:127.0.0.1", "192.168.1.1", "0.0.0.0", "224.0.0.1", "ff02::1"])
def test_ssrf_private_dns_prohibited(monkeypatch, ip):
    dns(monkeypatch, [ip])
    with pytest.raises(p.ProviderError) as exc:
        p._public_addresses("example.org", 443)
    assert exc.value.kind == "terminal"


def test_ssrf_mixed_public_private_dns_prohibited(monkeypatch):
    dns(monkeypatch, ["8.8.8.8", "127.0.0.1"])
    with pytest.raises(p.ProviderError):
        p._public_addresses("example.org", 443)


class WebResponse:
    def __init__(self, body=b"", status=200, headers=None):
        self.body = body if isinstance(body, bytes) else body.encode()
        self.offset, self.status = 0, status
        self.headers = {"Content-Type": "text/html", **(headers or {})}
    def getheader(self, name, default=None):
        return self.headers.get(name, default)
    def read(self, n):
        chunk = self.body[self.offset:self.offset + n]
        self.offset += len(chunk)
        return chunk


def mock_web(monkeypatch, responses):
    dns(monkeypatch, ["8.8.8.8"])
    calls = []
    class Connection:
        sock = None
        def __init__(self, host, port, address, timeout):
            self.host, self.address = host, address
        def request(self, method, path, headers):
            calls.append((self.host, path, self.address))
            self.path = path
        def getresponse(self):
            value = responses[self.path]
            if isinstance(value, Exception):
                raise value
            return copy.deepcopy(value)
        def close(self):
            pass
    monkeypatch.setattr(p, "_PinnedHTTPS", Connection)
    monkeypatch.setattr(p, "_PinnedHTTP", Connection)
    return calls


def test_crawler_homepage_once_contact_priority_emails_and_evidence(monkeypatch, config):
    calls = mock_web(monkeypatch, {"/robots.txt": WebResponse("User-agent: *\nDisallow: /private\n"),
                                   "/": WebResponse('<h1>Dental care for local families.</h1><a href="/">home</a><a href="/contact">Contact</a><a href="/private">private</a>'),
                                   "/contact": WebResponse('<p>Contact our dental office today.</p><a href="mailto:Office@example.org">Email</a>')})
    result = p.Research(config).crawl("https://www.example.org/")
    assert [x[1] for x in calls].count("/") == 1
    assert result["emails"] == ["office@example.org"]
    assert len(result["pages"]) == 2
    assert calls[0][2] == "8.8.8.8"
    for fact in result["evidence"]:
        assert fact["snippet"] in next(page["text"] for page in result["pages"] if page["url"] == fact["url"])


@pytest.mark.parametrize("target", ["http://127.0.0.1/", "https://169.254.169.254/", "https://other.example.org/", "file:///etc/passwd"])
def test_redirect_ssrf_and_tls_downgrade_prohibited(monkeypatch, config, target):
    config.data["research"]["robots_enabled"] = False
    calls = mock_web(monkeypatch, {"/": WebResponse(status=302, headers={"Location": target})})
    with pytest.raises(p.ProviderError):
        p.Research(config).crawl("https://example.org/")
    assert len(calls) == 1


def test_redirect_to_robots_disallowed_not_fetched(monkeypatch, config):
    calls = mock_web(monkeypatch, {"/robots.txt": WebResponse("User-agent: *\nDisallow: /private\n"),
                                   "/": WebResponse(status=302, headers={"Location": "/private"})})
    with pytest.raises(p.ProviderError):
        p.Research(config).crawl("https://example.org/")
    assert "/private" not in [x[1] for x in calls]


def test_dns_rebinding_socket_is_pinned(monkeypatch):
    connected = []
    fake_socket = SimpleNamespace(shutdown=lambda *a: None, close=lambda: None)
    monkeypatch.setattr(socket, "create_connection", lambda destination, timeout: connected.append(destination) or fake_socket)
    connection = p._PinnedHTTP("example.org", 80, "8.8.8.8", 1)
    connection.connect()
    assert connected == [("8.8.8.8", 80)]
    connection._deadline_timer.cancel()
    connection.close()


@pytest.mark.parametrize("response,kind", [(WebResponse("x" * 200), "terminal"),
                                           (WebResponse(status=503), "temporary"),
                                           (socket.timeout("SECRET URL"), "temporary")])
def test_research_bounds_503_and_timeout(monkeypatch, config, response, kind):
    config.data["research"].update(robots_enabled=False, max_bytes=100)
    mock_web(monkeypatch, {"/": response})
    with pytest.raises(p.ProviderError) as exc:
        p.Research(config).crawl("https://example.org/")
    assert exc.value.kind == kind and "SECRET" not in str(exc.value)


@pytest.fixture
def outgoing():
    return {"id": "message-1", "message_id": "<stable-id@example.org>", "email": "contact@recipient.org",
            "subject": "Hello", "body": "A question.", "in_reply_to": "<previous@example.org>",
            "references": ["<initial@example.org>", "<previous@example.org>"], "attempt": 1}


def smtp_mock(monkeypatch, data_result=(250, b"OK"), rcpt_result=(250, b"OK"), login_error=None, quit_error=None,
              mail_result=(250, b"OK")):
    calls = []
    class Client:
        def __init__(self, *args, **kwargs):
            calls.append(("connect", kwargs))
        def login(self, *args):
            if login_error:
                raise login_error
        def ehlo(self):
            calls.append(("ehlo", None))
        def starttls(self, **kwargs):
            calls.append(("starttls", None))
        def mail(self, address):
            calls.append(("mail", address))
            if isinstance(mail_result, Exception):
                raise mail_result
            return mail_result
        def rcpt(self, address):
            if isinstance(rcpt_result, Exception):
                raise rcpt_result
            return rcpt_result
        def data(self, raw):
            calls.append(("data", raw))
            if isinstance(data_result, Exception):
                raise data_result
            return data_result
        def quit(self):
            if quit_error:
                raise quit_error
        def close(self):
            pass
    monkeypatch.setattr(p.smtplib, "SMTP_SSL", Client)
    monkeypatch.setattr(p.smtplib, "SMTP", Client)
    return calls


def test_smtp_acceptance_threading_footer_and_quit_disconnect(monkeypatch, config, sender, outgoing):
    calls = smtp_mock(monkeypatch, quit_error=smtplib.SMTPServerDisconnected("private secret"))
    result = p.SMTP(config).send(outgoing, sender)
    assert result["status"] == "sent"
    raw = next(value for method, value in calls if method == "data")
    parsed = BytesParser(policy=policy.default).parsebytes(raw)
    assert parsed["Message-ID"] == outgoing["message_id"]
    assert parsed["In-Reply-To"] == outgoing["in_reply_to"]
    assert str(parsed["References"]) == " ".join(outgoing["references"])
    assert p.OPT_OUT in parsed.get_content()
    assert config.data["llm"]["postal_address"] in parsed.get_content()


@pytest.mark.parametrize("failure,status,kind", [(smtplib.SMTPServerDisconnected("SECRET"), "review", "ambiguous"),
                                                (socket.timeout("SECRET"), "review", "ambiguous"),
                                                ((451, b"SECRET"), "failed", "temporary"),
                                                ((550, b"SECRET"), "failed", "terminal"),
                                                (smtplib.SMTPDataError(450, b"SECRET"), "failed", "temporary")])
def test_smtp_data_classification(monkeypatch, config, sender, outgoing, failure, status, kind):
    smtp_mock(monkeypatch, data_result=failure)
    result = p.SMTP(config).send(outgoing, sender)
    assert result["status"] == status and result["kind"] == kind
    assert "SECRET" not in json.dumps(result)


def test_smtp_auth_failure_is_safe_and_stops_sender(monkeypatch, config, sender, outgoing):
    calls = smtp_mock(monkeypatch, login_error=smtplib.SMTPAuthenticationError(535, b"TOP-SECRET"))
    result = p.SMTP(config).send(outgoing, sender)
    assert result["kind"] == "auth"
    assert not any(method == "data" for method, _ in calls)
    assert "TOP-SECRET" not in json.dumps(result)


def test_smtp_pre_data_disconnect_retryable(monkeypatch, config, sender, outgoing):
    smtp_mock(monkeypatch, login_error=smtplib.SMTPServerDisconnected("SECRET"))
    assert p.SMTP(config).send(outgoing, sender)["kind"] == "temporary"


def test_smtp_recipient_rejection_no_data(monkeypatch, config, sender, outgoing):
    calls = smtp_mock(monkeypatch, rcpt_result=(550, b"bad"))
    assert p.SMTP(config).send(outgoing, sender)["kind"] == "recipient"
    assert not any(method == "data" for method, _ in calls)


@pytest.mark.parametrize("stage,code,diagnostic,kind", [
    ("mail", 550, b"5.1.1 SECRET sender rejected", "terminal"),
    ("mail", 530, b"5.7.0 SECRET authentication required", "auth"),
    ("mail", 451, b"4.7.0 SECRET retry later", "temporary"),
    ("rcpt", 550, b"5.1.1 SECRET no such mailbox", "recipient"),
    ("rcpt", 550, b"5.7.1 SECRET policy rejection", "terminal"),
    ("rcpt", 450, b"4.1.1 SECRET retry later", "temporary"),
    ("data", 554, b"5.7.1 SECRET policy rejection", "terminal"),
    ("data", 550, b"5.1.1 SECRET invalid recipient", "recipient"),
    ("data", 554, b"SECRET no enhanced status", "terminal"),
    ("data", 451, b"4.7.1 SECRET policy rejection", "temporary"),
])
@pytest.mark.parametrize("as_exception", [False, True])
def test_smtp_stage_aware_rejections(monkeypatch, config, sender, outgoing, stage, code, diagnostic, kind,
                                    as_exception):
    response = smtplib.SMTPResponseException(code, diagnostic) if as_exception else (code, diagnostic)
    calls = smtp_mock(monkeypatch, **{stage + "_result": response})
    result = p.SMTP(config).send(outgoing, sender)
    assert result["status"] == "failed" and result["kind"] == kind
    assert "SECRET" not in json.dumps(result)
    if stage != "data":
        assert not any(method == "data" for method, _ in calls)


def test_smtp_temporary_auth_response_is_retryable(monkeypatch, config, sender, outgoing):
    smtp_mock(monkeypatch, login_error=smtplib.SMTPAuthenticationError(454, b"4.7.0 SECRET retry later"))
    result = p.SMTP(config).send(outgoing, sender)
    assert result["kind"] == "temporary"
    assert "SECRET" not in json.dumps(result)


@pytest.mark.parametrize("control", ["dry", "disabled", "emergency", "no_postal"])
def test_smtp_safety_enforced_in_adapter(config, sender, outgoing, control):
    if control == "dry":
        config.dry_run = True
    elif control == "disabled":
        config.send_enabled = False
    elif control == "emergency":
        config.data["safety"]["emergency_stop"] = True
    else:
        config.data["llm"]["postal_address"] = ""
    assert p.SMTP(config).send(outgoing, sender)["status"] == "failed"


def raw_reply(body="Thanks for reaching out.", **headers):
    message = EmailMessage()
    message["From"] = "Contact <contact@recipient.org>"
    message["To"] = "team@example.org"
    message["In-Reply-To"] = "<previous@example.org>"
    message["References"] = "<initial@example.org> <previous@example.org>"
    for name, value in headers.items():
        message[name.replace("_", "-")] = value
    message.set_content(body)
    return message.as_bytes()


@pytest.mark.parametrize("body,headers,expected", [("Unsubscribe", {}, "unsubscribe"),
                                                   ("Please remove me from your mailing list.", {}, "unsubscribe"),
                                                   ("FYI forwarded message\n> unsubscribe", {}, "reply"),
                                                   ("Your list has an unsubscribe link", {}, "reply"),
                                                   ("normal response", {"List_Unsubscribe": "<https://example.org>"}, "reply"),
                                                   ("Unsubscribe", {"Auto_Submitted": "auto-replied"}, "unknown")])
def test_inbound_does_not_suppress_forwarded_unsubscribe_mentions(body, headers, expected):
    event = p._inbound(raw_reply(body, **headers), datetime.now(timezone.utc), "key", 1)
    assert event["kind"] == expected
    assert event["message_ids"] == ["<previous@example.org>", "<initial@example.org>"]
    assert "body" not in event


def test_machine_readable_dsn_hard_bounce_and_original_message_correlation():
    raw = (b"From: mailer-daemon@example.org\r\nMIME-Version: 1.0\r\n"
           b'Content-Type: multipart/report; boundary="dsn"; report-type=delivery-status\r\n\r\n'
           b"--dsn\r\nContent-Type: message/delivery-status\r\n\r\nReporting-MTA: dns; example.org\r\n\r\n"
           b"Final-Recipient: rfc822; bad@recipient.org\r\nAction: failed\r\nStatus: 5.1.1\r\n\r\n"
           b"--dsn\r\nContent-Type: text/rfc822-headers\r\n\r\nMessage-ID: <sent@example.org>\r\n\r\n--dsn--\r\n")
    event = p._inbound(raw, datetime.now(timezone.utc), "key", 1)
    assert event["kind"] == "hard_bounce"
    assert event["email"] == "bad@recipient.org"
    assert "<sent@example.org>" in event["message_ids"]


def imap_mock(monkeypatch, messages, validity="22", fail_uid=None):
    calls = []
    class Client:
        def __init__(self, *a, **k):
            pass
        def login(self, *a):
            pass
        def select(self, *a, **k):
            return "OK", [b"3"]
        def response(self, *a):
            return "UIDVALIDITY", [validity.encode()]
        def uid(self, command, *args):
            calls.append((command, args))
            if command == "SEARCH":
                return "OK", [b" ".join(str(uid).encode() for uid in sorted(messages))]
            uid = int(args[0])
            if uid == fail_uid:
                return "NO", []
            raw, when = messages[uid]
            metadata = f'{uid} (UID {uid} INTERNALDATE "{when}" RFC822.SIZE {len(raw)} BODY[]'.encode()
            return "OK", [(metadata, raw), b")"]
        def logout(self):
            pass
    monkeypatch.setattr(p.imaplib, "IMAP4_SSL", Client)
    return calls


def test_mailbox_oldest_first_limit_cursor_reset_and_no_uid_skips(monkeypatch, config, sender):
    when = datetime.now(timezone.utc).strftime("%d-%b-%Y %H:%M:%S %z")
    calls = imap_mock(monkeypatch, {uid: (raw_reply(), when) for uid in (1, 2, 3)})
    result = p.Mailbox(config).sync(sender, {"uidvalidity": "old", "last_uid": 900})
    assert result["uidvalidity"] == "22" and result["last_uid"] == 2
    assert [e["uid"] for e in result["events"]] == [1, 2]
    assert "1:*" in calls[0][1]
    again = p.Mailbox(config).sync(sender, result)
    assert [e["uid"] for e in again["events"]] == [3]
    assert result["events"][0]["key"] == p._inbound_key(raw_reply(), sender.id)


@pytest.mark.parametrize("own_id", [None, "<reply-123@recipient.org>"])
def test_mailbox_event_identity_survives_uidvalidity_reset_and_copies(monkeypatch, config, sender, own_id):
    when = datetime.now(timezone.utc).strftime("%d-%b-%Y %H:%M:%S %z")
    raw = raw_reply(**({"Message_ID": own_id} if own_id else {}))
    imap_mock(monkeypatch, {1: (raw, when)}, validity="22")
    first = p.Mailbox(config).sync(sender, None)
    imap_mock(monkeypatch, {81: (raw, when), 82: (raw, when)}, validity="23")
    second = p.Mailbox(config).sync(sender, first)
    assert second["last_uid"] == 82
    assert {ev["key"] for ev in first["events"] + second["events"]} == {p._inbound_key(raw, sender.id)}
    assert all("body" not in ev and "raw" not in ev for ev in second["events"])


@pytest.mark.parametrize("with_id", [True, False])
def test_distinct_replies_in_same_thread_have_distinct_event_keys(with_id):
    first = raw_reply("First reply", **({"Message_ID": "<reply1@recipient.org>"} if with_id else {}))
    second = raw_reply("Second reply", **({"Message_ID": "<reply2@recipient.org>"} if with_id else {}))
    assert p._inbound_key(first, "sender1") != p._inbound_key(second, "sender1")
    assert p._inbound_key(first, "sender1") != p._inbound_key(first, "sender2")


def test_inbound_identity_uses_own_id_not_thread_or_attached_original():
    first = raw_reply("First content", Message_ID="<reply1@recipient.org>")
    copied = raw_reply("Changed transport content", Message_ID="<reply1@recipient.org>")
    assert p._inbound_key(first, "sender") == p._inbound_key(copied, "sender")
    assert p._inbound_key(first, "sender") == p.stable_id("inbound", "sender", "message-id", "<reply1@recipient.org>")


@pytest.mark.parametrize("own_id", ["not-a-message-id", "<bad id@recipient.org>", "<bad..id@recipient.org>", "<one@recipient.org> <two@recipient.org>"])
def test_invalid_incoming_message_id_falls_back_to_digest(own_id):
    # Bypass EmailMessage's normalization of malformed Message-ID values.
    raw = f"Message-ID: {own_id}\r\n".encode() + raw_reply()
    assert p._inbound_key(raw, "sender") == p.stable_id("inbound", "sender", "raw-sha256", p.hashlib.sha256(raw).hexdigest())


def test_duplicate_message_id_headers_fall_back_to_digest():
    raw = raw_reply(Message_ID="<one@recipient.org>")
    raw = b"Message-ID: <two@recipient.org>\r\n" + raw
    assert p._inbound_key(raw, "sender") == p.stable_id("inbound", "sender", "raw-sha256", p.hashlib.sha256(raw).hexdigest())


def test_mailbox_fetch_failure_cannot_skip_uid(monkeypatch, config, sender):
    when = datetime.now(timezone.utc).strftime("%d-%b-%Y %H:%M:%S %z")
    imap_mock(monkeypatch, {uid: (raw_reply(), when) for uid in (1, 2, 3)}, fail_uid=2)
    result = p.Mailbox(config).sync(sender, None)
    assert result["last_uid"] == 1 and len(result["events"]) == 1


def test_mailbox_lookback_uses_internaldate_not_forged_date(monkeypatch, config, sender):
    imap_mock(monkeypatch, {1: (raw_reply(Date="Sun, 11 Oct 2099 10:00:00 +0000"), "01-Jan-2020 00:00:00 +0000")})
    result = p.Mailbox(config).sync(sender, None)
    assert result["last_uid"] == 1 and result["events"] == []


def test_dns_lookup_has_a_wall_clock_bound(monkeypatch):
    def slow(*args, **kwargs):
        time.sleep(0.03)
        raise OSError("credential should not leak")
    monkeypatch.setattr(socket, "getaddrinfo", slow)
    with pytest.raises(p.ProviderError) as exc:
        p._public_addresses("example.org", 443, timeout=0.005)
    assert exc.value.kind == "temporary"
    assert "credential" not in str(exc.value)
    time.sleep(0.04)  # resolver exits before monkeypatch teardown


@pytest.mark.parametrize("observations", [[None], [42], [{"claim": 42}], "invalid"])
def test_llm_malformed_observations_are_classified_not_crashes(monkeypatch, config, research, observations):
    draft = good_draft(research, config)
    draft["observations"] = observations
    mock_api(monkeypatch, APIResponse({"choices": [{"message": {"content": json.dumps(draft)}}]}))
    with pytest.raises(p.ProviderError) as exc:
        p.LLM(config, SimpleNamespace(llm_key="SECRET")).draft({}, research, 0, [])
    assert exc.value.kind == "invalid"


def test_followups_have_distinct_safe_framing(monkeypatch, config, research):
    mock_api(monkeypatch, APIResponse({"choices": [{"message": {"content": json.dumps(good_draft(research, config))}}]}))
    bodies = []
    for sequence in range(4):
        draft = p.LLM(config, SimpleNamespace(llm_key="SECRET")).draft({}, research, sequence, [])
        assert not p.validate_draft(draft, research)
        bodies.append(draft["body"])
    assert len(set(bodies)) == 4
