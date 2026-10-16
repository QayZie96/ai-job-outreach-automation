"""Offline verification only: no scrapes, Gemini, or Google Sheets writes."""
import os
import unittest
from unittest.mock import patch

import jobspy_pilot as m
from personal_discovery import deduplicate, screen_candidates


class JobSpyPilotTests(unittest.TestCase):
    def test_normalize_contract_and_provider_identity(self):
        raw = {"site": "linkedin", "title": "Catalog Operations Specialist",
               "company": "Example", "city": "Athens", "country": "Greece",
               "is_remote": True, "job_url": "https://www.linkedin.com/jobs/view/12345/?utm_source=x",
               "description": "Manage product catalog data and supplier operations.",
               "date_posted": "2026-10-16"}
        j = m.normalize(raw)
        self.assertEqual(j["job_url"], "https://www.linkedin.com/jobs/view/12345")
        self.assertEqual(j["source_job_id"], "12345")
        self.assertEqual(j["source"], "JobSpy:linkedin")
        self.assertTrue(j["remote"])
        self.assertEqual(j["location"], "Athens, Greece")
        self.assertEqual(len(deduplicate([j, dict(j)])), 1)

    def test_missing_description_does_not_become_eligibility_claim(self):
        j = m.normalize({"site": "indeed", "title": "Marketplace Operations",
                         "company": "Company", "city": "", "country": "",
                         "is_remote": True, "job_url": "https://example.org/a"})
        result, stats, _ = screen_candidates([j])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["precheck_eligibility"], "uncertain")
        self.assertFalse(result[0]["job_description"])

    def test_crossboard_signature_is_review_only_signal(self):
        a = m.normalize({"site": "linkedin", "title": "Catalog Operations",
                         "company": "Same Employer", "city": "Athens",
                         "country": "Greece", "job_url": "https://example.org/a"})
        b = m.normalize({"site": "indeed", "title": "Catalog Operations",
                         "company": "Same Employer", "city": "Athens",
                         "country": "Greece", "job_url": "https://example.org/b"})
        dupes = m.possible_crossboard_duplicates([a, b])
        self.assertEqual(dupes, {a["job_url"], b["job_url"]})
        self.assertEqual(len(deduplicate([a, b])), 2)

    def test_bounded_scraping_arguments(self):
        calls = []
        class Frame:
            def to_dict(self, orient=None):
                self_orient = orient
                if self_orient != "records":
                    raise AssertionError(orient)
                return []
        def fake_scraper(**kwargs):
            calls.append(kwargs)
            return Frame()
        result, counts, errors = m.collect_live(scraper=fake_scraper)
        self.assertEqual(result, [])
        self.assertEqual(errors, [])
        self.assertEqual(len(calls), 4)
        self.assertEqual(counts, {"indeed": 2, "linkedin": 2})
        self.assertTrue(all(c["results_wanted"] == 12 for c in calls))
        self.assertTrue(all(c["fetch_description"] is False for c in calls))
        self.assertTrue(all(c.get("proxies") is None for c in calls))

    def test_stop_failed_provider(self):
        calls = []
        def broken(**kwargs):
            calls.append(kwargs["site_name"][0])
            raise RuntimeError("rate limited")
        result, counts, errors = m.collect_live(scraper=broken)
        self.assertEqual(calls, ["indeed", "linkedin"])
        self.assertEqual(result, [])
        self.assertEqual(len(errors), 2)

    def test_production_sheet_denied(self):
        with patch.dict(os.environ, {"JOBSPY_SHEET_ID": m.PRODUCTION_PERSONAL_SHEET_ID}):
            with self.assertRaises(ValueError):
                m.eligible_sheet()
        with patch.dict(os.environ, {"JOBSPY_SHEET_ID": m.PILOT_SHEET_ID,
                                     "GOOGLE_SHEET_ID": m.PILOT_SHEET_ID}):
            with self.assertRaises(ValueError):
                m.eligible_sheet()
        with patch.dict(os.environ, {"JOBSPY_SHEET_ID": m.PILOT_SHEET_ID,
                                     "GOOGLE_SHEET_ID": "different_demo_id"}):
            self.assertEqual(m.eligible_sheet(), m.PILOT_SHEET_ID)

    def test_gemini_is_off_without_explicit_billing_gate(self):
        with patch.dict(os.environ, {"PERSONAL_GEMINI_FREE_TIER_CONFIRMED": "NO"}):
            with self.assertRaises(RuntimeError):
                m.evaluate([])


if __name__ == "__main__":
    unittest.main()
