"""Offline checks for the manually saved Adzuna hosted-page proof of concept."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from adzuna_saved_page_probe import inspect_saved_page


JOB = {"source": "Adzuna", "source_job_id": "5930905647",
       "job_title": "eCommerce Manager - GSA",
       "job_url": "https://www.adzuna.de/details/5930905647",
       "job_description": "Drive growth for ecommerce platforms. " * 12}


class SavedPageProbeTests(unittest.TestCase):
    def check_page(self, html, *, change=None):
        with TemporaryDirectory() as folder:
            report = Path(folder) / "run.json"
            html_path = Path(folder) / "job.html"
            report.write_text(
                json.dumps({"evaluated_jobs": [{**JOB, **(change or {})}]}),
                encoding="utf-8")
            html_path.write_text(html, encoding="utf-8")
            return inspect_saved_page(report, "5930905647", html_path)

    def test_long_matching_jsonld_appears_to_have_more_text_than_snippet(self):
        desc = "Ecommerce operations, pricing, merchandising and supplier management. " * 35
        html = ('<html><link rel="canonical" href="https://www.adzuna.de/details/5930905647">'
                '<script type="application/ld+json">' +
                json.dumps({"@type": "JobPosting", "title": "eCommerce Manager - GSA",
                            "description": "<p>" + desc + "</p>"}) +
                '</script></html>')
        result = self.check_page(html)
        self.assertEqual(result["status"], "longer_description_candidate")
        self.assertEqual(result["network_requests"], 0)
        self.assertEqual(result["external_redirects_followed"], 0)
        self.assertEqual(result["source"], "JobPosting JSON-LD")
        self.assertGreater(result["extracted_description_chars"], result["snippet_chars"])
        self.assertNotIn("description", {k for k in result if k == "description"})

    def test_short_text_is_not_a_full_description_candidate(self):
        html = '<script type="application/ld+json">' + json.dumps({
            "@type": "JobPosting", "title": "eCommerce Manager - GSA",
            "description": "Short job description."
        }) + '</script>'
        self.assertEqual(
            self.check_page(html)["status"], "insufficient_or_mismatched_description"
        )

    def test_unrelated_jobposting_title_is_not_considered_usable(self):
        desc = "Large full text of an entirely unrelated engineer role. " * 35
        html = '<script type="application/ld+json">' + json.dumps({
            "@type": "JobPosting", "title": "Neurosurgeon",
            "description": desc
        }) + '</script>'
        self.assertEqual(
            self.check_page(html)["status"], "insufficient_or_mismatched_description"
        )

    def test_saved_third_party_redirect_is_blocked_before_content_inspection(self):
        html = (
            '<link rel="canonical" href="https://employer.example/jobs/888">'
            '<script type="application/ld+json">' + json.dumps({
                "@type": "JobPosting", "title": "eCommerce Manager - GSA",
                "description": "Full job requirement. " * 100
            }) + '</script>'
        )
        self.assertEqual(self.check_page(html)["status"], "blocked_non_adzuna_page")

    def test_redirect_style_land_ad_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "redirect-style"):
            self.check_page(
                "<html></html>",
                change={"job_url": "https://www.adzuna.de/land/ad/5930905647"}
            )

    def test_robot_challenge_is_not_treated_as_job_posting(self):
        html = "<html><body>JavaScript is disabled. Verify that you're not a robot.</body></html>"
        self.assertEqual(self.check_page(html)["status"], "access_challenge_or_empty")

    def test_no_description_is_reported_candidly(self):
        self.assertEqual(
            self.check_page("<html><body>Job listings are available.</body></html>")["status"],
            "no_structured_job_description_found"
        )


if __name__ == "__main__":
    unittest.main()
