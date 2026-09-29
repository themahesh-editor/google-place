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


if __name__ == "__main__":
    unittest.main(verbosity=2)
