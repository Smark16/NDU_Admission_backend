"""Unit tests for scan-desk code parsing (no DB)."""
from django.test import SimpleTestCase

from payments.scan_desk import normalize_purpose, parse_scan_code


class ScanDeskParseTests(SimpleTestCase):
    def test_normalize_purpose(self):
        self.assertEqual(normalize_purpose("id"), "id")
        self.assertEqual(normalize_purpose("REG"), "registration")
        self.assertEqual(normalize_purpose("examination"), "exam")
        self.assertEqual(normalize_purpose("weird"), "registration")

    def test_parse_bare_paycode(self):
        p = parse_scan_code("1009889661")
        self.assertEqual(p["lookup"], "1009889661")
        self.assertIsNone(p["exam_token"])

    def test_parse_ndu_id_prefix(self):
        p = parse_scan_code("NDU|id|1009889661")
        self.assertEqual(p["lookup"], "1009889661")
        self.assertEqual(p["hint_purpose"], "id")

    def test_parse_verify_registration_url(self):
        p = parse_scan_code("https://portal.example/verify-registration/25%2F1%2F377%2FD%2F519")
        self.assertEqual(p["lookup"], "25/1/377/D/519")
        self.assertEqual(p["hint_purpose"], "registration")

    def test_parse_exam_uuid(self):
        code = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        p = parse_scan_code(code)
        self.assertEqual(p["exam_token"], code)
        self.assertEqual(p["hint_purpose"], "exam")

    def test_parse_exam_url(self):
        code = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        p = parse_scan_code(f"https://portal.example/verify-exam-card/{code}")
        self.assertEqual(p["exam_token"], code)
        self.assertEqual(p["hint_purpose"], "exam")
