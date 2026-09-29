import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import lead_collector as m


class LeadCollectorTests(unittest.TestCase):
    def test_parse_json_array(self):
        raw = '```json\n["roofing contractor Dallas TX", "roof repair Plano TX"]\n```'
        self.assertEqual(m.parse_json_array(raw), ["roofing contractor Dallas TX", "roof repair Plano TX"])

    def test_parse_json_object(self):
        obj = m.parse_json_object('{"action":"KEEP","scale_class":"LOCAL","confidence":0.9}')
        self.assertEqual(obj["action"], "KEEP")
        self.assertEqual(obj["scale_class"], "LOCAL")

    def test_normalize_domain(self):
        self.assertEqual(m.normalize_domain("https://www.Example.com/path"), "example.com")
        self.assertEqual(m.normalize_domain("Info@Example.com"), "example.com")

    def test_email_selection_rejects_free_email(self):
        finding = m.EmailFinding("person@gmail.com", "https://example.com/contact", "x")
        self.assertIsNone(m.choose_public_business_email([finding], "https://example.com"))

    def test_email_selection_requires_mx(self):
        finding = m.EmailFinding("info@example.com", "https://example.com/contact", "x")
        with patch.object(m, "has_mx", return_value=False):
            self.assertIsNone(m.choose_public_business_email([finding], "https://example.com"))

    def test_email_selection_accepts_verified_domain(self):
        finding = m.EmailFinding("info@example.com", "https://example.com/contact", "x")
        with patch.object(m, "has_mx", return_value=True):
            chosen = m.choose_public_business_email([finding], "https://example.com")
        self.assertIsNotNone(chosen)
        self.assertEqual(chosen.email, "info@example.com")

    def test_candidate_from_place(self):
        place = {
            "id": "place123",
            "displayName": {"text": "Example Roofing"},
            "formattedAddress": "123 Main St, Dallas, TX 75001",
            "websiteUri": "https://www.example.com/",
            "types": ["roofing_contractor"],
            "businessStatus": "OPERATIONAL",
        }
        candidate = m.candidate_from_place(place, "roofing contractor Dallas TX")
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.place_id, "place123")
        self.assertEqual(candidate.company, "Example Roofing")

    def test_memory_is_jsonl(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "memory.jsonl"
            with patch.object(m, "MEMORY_FILE", path):
                m.append_jsonl(path, {"event": "candidate_seen", "place_id": "x"})
                obj = json.loads(path.read_text(encoding="utf-8").strip())
                self.assertEqual(obj["event"], "candidate_seen")
                self.assertEqual(obj["place_id"], "x")
                self.assertIn("timestamp_utc", obj)

    def test_email_extraction_finds_contact_page_patterns_and_jsonld(self):
        html = """
        <html><body>
          <a href="mailto:info@example.com">Email us</a>
          <p>Or contact us at support [at] example [dot] com</p>
          <script type="application/ld+json">
            {"@context":"https://schema.org","contactPoint":{"email":"sales@example.com"}}
          </script>
        </body></html>
        """
        emails = {x.email for x in m.extract_emails("https://example.com/contact", html)}
        self.assertIn("info@example.com", emails)
        self.assertIn("support@example.com", emails)
        self.assertIn("sales@example.com", emails)

    def test_cloudflare_email_decode(self):
        email = "info@example.com"
        key = 0x12
        encoded = f"{key:02x}" + "".join(f"{ord(ch)^key:02x}" for ch in email)
        self.assertEqual(m.decode_cloudflare_email(encoded), email)

    def test_seen_domains_only_permanently_blocks_verified(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "seen_domains.csv"
            path.write_text("Domain,FirstSeenUTC,Source\nold-example.com,x,test\n", encoding="utf-8")
            with patch.object(m, "SEEN_DOMAINS_FILE", path):
                self.assertNotIn("old-example.com", m.seen_domains())
                path.write_text("Domain,FirstSeenUTC,Source,Status\nold-example.com,x,test,VERIFIED\n", encoding="utf-8")
                self.assertIn("old-example.com", m.seen_domains())


if __name__ == "__main__":
    unittest.main(verbosity=2)
