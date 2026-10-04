"""Unit tests for google_client date and time parsing routines."""

import unittest
from datetime import datetime, timezone
from google_client import parse_due_syntax, parse_time_component


class TestGoogleClientHelpers(unittest.TestCase):
    def test_parse_plain_text(self):
        text = "Review security report"
        title, due = parse_due_syntax(text)
        self.assertEqual(title, "Review security report")
        self.assertIsNone(due)

    def test_parse_due_today(self):
        text = "Scan network perimeter /due:today"
        title, due = parse_due_syntax(text)
        self.assertEqual(title, "Scan network perimeter")
        self.assertIsNotNone(due)
        dt = datetime.fromisoformat(due[:10])
        self.assertEqual(dt.date(), datetime.now().date())
        self.assertEqual((dt.hour, dt.minute, dt.second), (0, 0, 0))

    def test_parse_due_tomorrow(self):
        text = "/due:tomorrow Audit open ports"
        title, due = parse_due_syntax(text)
        self.assertEqual(title, "Audit open ports")
        self.assertIsNotNone(due)
        dt = datetime.fromisoformat(due[:10])
        now = datetime.now()
        self.assertEqual((dt.date() - now.date()).days, 1)
        self.assertEqual((dt.hour, dt.minute, dt.second), (0, 0, 0))

    def test_parse_due_explicit_date(self):
        text = "Renew TLS certificates /due:2026-10-15"
        title, due = parse_due_syntax(text)
        self.assertEqual(title, "Renew TLS certificates")
        self.assertIsNotNone(due)
        dt = datetime.fromisoformat(due[:10])
        self.assertEqual(dt.strftime("%Y-%m-%d"), "2026-10-15")
        self.assertEqual((dt.hour, dt.minute, dt.second), (0, 0, 0))

    def test_parse_due_day_month_year(self):
        text = "Renew TLS certificates /due:15-10-2026"
        title, due = parse_due_syntax(text)
        self.assertEqual(title, "Renew TLS certificates")
        self.assertIsNotNone(due)
        dt = datetime.fromisoformat(due[:10])
        self.assertEqual(dt.strftime("%Y-%m-%d"), "2026-10-15")
        self.assertEqual((dt.hour, dt.minute, dt.second), (0, 0, 0))

    def test_parse_due_day_month_year_with_time(self):
        text = "Check audit logs /due:15-10-2026@5pm"
        title, due = parse_due_syntax(text)
        self.assertEqual(title, "Check audit logs")
        self.assertIsNotNone(due)
        dt = datetime.fromisoformat(due[:10])
        self.assertEqual(dt.strftime("%Y-%m-%d"), "2026-10-15")
        self.assertEqual((dt.hour, dt.minute, dt.second), (0, 0, 0))

    def test_parse_due_day_month_year_ambiguous(self):
        # 05-10-2026 must parse as 5th October (DD-MM-YYYY), not 10th May
        text = "Submit report /due:05-10-2026"
        title, due = parse_due_syntax(text)
        self.assertEqual(title, "Submit report")
        self.assertIsNotNone(due)
        dt = datetime.fromisoformat(due[:10])
        self.assertEqual(dt.strftime("%Y-%m-%d"), "2026-10-05")

    def test_parse_due_time_only(self):
        text = "Check firewall logs /due:5pm"
        title, due = parse_due_syntax(text)
        self.assertEqual(title, "Check firewall logs")
        self.assertIsNotNone(due)
        dt = datetime.fromisoformat(due[:10])
        self.assertEqual((dt.hour, dt.minute, dt.second), (0, 0, 0))

    def test_parse_due_today_with_time(self):
        text = "Patch kernel /due:today@18:30"
        title, due = parse_due_syntax(text)
        self.assertEqual(title, "Patch kernel")
        self.assertIsNotNone(due)
        dt = datetime.fromisoformat(due[:10])
        self.assertEqual(dt.date(), datetime.now().date())
        self.assertEqual((dt.hour, dt.minute, dt.second), (0, 0, 0))

    def test_parse_due_tomorrow_space_time(self):
        text = "Rotate API keys /due:tomorrow 9am"
        title, due = parse_due_syntax(text)
        self.assertEqual(title, "Rotate API keys")
        self.assertIsNotNone(due)
        dt = datetime.fromisoformat(due[:10])
        now = datetime.now()
        self.assertEqual((dt.date() - now.date()).days, 1)
        self.assertEqual((dt.hour, dt.minute, dt.second), (0, 0, 0))

    def test_parse_due_explicit_date_with_time(self):
        text = "Deploy release /due:2026-10-20@14:15"
        title, due = parse_due_syntax(text)
        self.assertEqual(title, "Deploy release")
        self.assertIsNotNone(due)
        dt = datetime.fromisoformat(due[:10])
        self.assertEqual(dt.strftime("%Y-%m-%d"), "2026-10-20")
        self.assertEqual((dt.hour, dt.minute, dt.second), (0, 0, 0))

    def test_parse_due_quoted(self):
        text = 'Backup database /due:"tomorrow 6:30pm"'
        title, due = parse_due_syntax(text)
        self.assertEqual(title, "Backup database")
        self.assertIsNotNone(due)
        dt = datetime.fromisoformat(due[:10])
        now = datetime.now()
        self.assertEqual((dt.date() - now.date()).days, 1)
        self.assertEqual((dt.hour, dt.minute, dt.second), (0, 0, 0))


if __name__ == "__main__":
    unittest.main()
