import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import lead_collector as m


class LeadCollectorTests(unittest.TestCase):

    def test_parse_json_array(self):
        raw = '```json\n["roofing contractor Dallas TX", "roof repair Plano TX"]\n```'
        self.assertEqual(
            m.parse_json_array(raw),
            ["roofing contractor Dallas TX", "roof repair Plano TX"],
        )

    def test_parse_json_object(self):
        obj = m.parse_json_object(
            '{"action":"KEEP","scale_class":"LOCAL","confidence":0.9}'
        )
        self.assertEqual(obj["action"], "KEEP")
        self.assertEqual(obj["scale_class"], "LOCAL")

    def test_normalize_domain(self):
        self.assertEqual(
            m.normalize_domain("https://www.Example.com/path"),
            "example.com",
        )
        self.assertEqual(
            m.normalize_domain("Info@Example.com"),
            "example.com",
        )

    def test_email_selection_rejects_free_email(self):
        finding = m.EmailFinding(
            "person@gmail.com",
            "https://example.com/contact",
            "x",
        )
        self.assertIsNone(
            m.choose_public_business_email(
                [finding],
                "https://example.com",
            )
        )

    def test_email_selection_requires_mx(self):
        finding = m.EmailFinding(
            "info@example.com",
            "https://example.com/contact",
            "x",
        )
        with patch.object(m, "has_mx", return_value=False):
            self.assertIsNone(
                m.choose_public_business_email(
                    [finding],
                    "https://example.com",
                )
            )

    def test_email_selection_accepts_verified_domain(self):
        finding = m.EmailFinding(
            "info@example.com",
            "https://example.com/contact",
            "x",
        )
        with patch.object(m, "has_mx", return_value=True):
            chosen = m.choose_public_business_email(
                [finding],
                "https://example.com",
            )

        self.assertIsNotNone(chosen)
        self.assertEqual(chosen.email, "info@example.com")

    def test_candidate_from_place_accepts_allowed_country(self):
        place = {
            "id": "place123",
            "displayName": {"text": "Example Roofing"},
            "formattedAddress": "123 Main St, Dallas, TX 75001",
            "postalAddress": {"regionCode": "US"},
            "addressComponents": [],
            "websiteUri": "https://www.example.com/",
            "types": ["roofing_contractor"],
            "businessStatus": "OPERATIONAL",
        }

        candidate = m.candidate_from_place(
            place,
            "roofing contractor Dallas TX",
        )

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.place_id, "place123")
        self.assertEqual(candidate.company, "Example Roofing")
        self.assertEqual(candidate.country_code, "US")

    def test_candidate_from_place_accepts_canada(self):
        place = {
            "id": "place456",
            "displayName": {"text": "Toronto Roofing"},
            "formattedAddress": "123 Main St, Toronto, ON",
            "postalAddress": {"regionCode": "CA"},
            "addressComponents": [],
            "websiteUri": "https://www.example.ca/",
            "types": ["roofing_contractor"],
            "businessStatus": "OPERATIONAL",
        }

        candidate = m.candidate_from_place(
            place,
            "roofing contractor Toronto Canada",
        )

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.country_code, "CA")

    def test_candidate_from_place_rejects_india(self):
        place = {
            "id": "place789",
            "displayName": {"text": "India Roofing"},
            "formattedAddress": "123 Main St, Lucknow, Uttar Pradesh, India",
            "postalAddress": {"regionCode": "IN"},
            "addressComponents": [],
            "websiteUri": "https://www.example.in/",
            "types": ["roofing_contractor"],
            "businessStatus": "OPERATIONAL",
        }

        candidate = m.candidate_from_place(
            place,
            "roofing contractor Lucknow India",
        )

        self.assertIsNone(candidate)

    def test_candidate_from_place_rejects_unknown_country(self):
        place = {
            "id": "place999",
            "displayName": {"text": "Unknown Roofing"},
            "formattedAddress": "Unknown address",
            "postalAddress": {},
            "addressComponents": [],
            "websiteUri": "https://www.example.com/",
            "types": ["roofing_contractor"],
            "businessStatus": "OPERATIONAL",
        }

        candidate = m.candidate_from_place(
            place,
            "roofing contractor unknown",
        )

        self.assertIsNone(candidate)

    def test_candidate_from_retry_preserves_country(self):
        row = {
            "PlaceId": "retry123",
            "Company": "Retry Roofing",
            "Website": "https://example.com/",
            "Address": "123 Main St, Toronto, ON",
            "CountryCode": "CA",
            "Types": '["roofing_contractor"]',
            "Query": "roofing contractor Toronto Canada",
        }

        candidate = m.candidate_from_retry(row)

        self.assertEqual(candidate.country_code, "CA")
        self.assertEqual(candidate.company, "Retry Roofing")

    def test_memory_is_jsonl(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "memory.jsonl"

            with patch.object(m, "MEMORY_FILE", path):
                m.append_jsonl(
                    path,
                    {
                        "event": "candidate_seen",
                        "place_id": "x",
                    },
                )

                obj = json.loads(
                    path.read_text(encoding="utf-8").strip()
                )

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

        emails = {
            x.email
            for x in m.extract_emails(
                "https://example.com/contact",
                html,
            )
        }

        self.assertIn("info@example.com", emails)
        self.assertIn("support@example.com", emails)
        self.assertIn("sales@example.com", emails)

    def test_cloudflare_email_decode(self):
        email = "info@example.com"
        key = 0x12
        encoded = f"{key:02x}" + "".join(
            f"{ord(ch) ^ key:02x}"
            for ch in email
        )

        self.assertEqual(
            m.decode_cloudflare_email(encoded),
            email,
        )

    def test_seen_domains_only_permanently_blocks_verified(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "seen_domains.csv"

            path.write_text(
                "Domain,FirstSeenUTC,Source\nold-example.com,x,test\n",
                encoding="utf-8",
            )

            with patch.object(m, "SEEN_DOMAINS_FILE", path):
                self.assertNotIn(
                    "old-example.com",
                    m.seen_domains(),
                )

                path.write_text(
                    "Domain,FirstSeenUTC,Source,Status\n"
                    "old-example.com,x,test,VERIFIED\n",
                    encoding="utf-8",
                )

                self.assertIn(
                    "old-example.com",
                    m.seen_domains(),
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
