"""No-network regression checks for the provider coverage pilot."""
import unittest

import personal_discovery as ray
import provider_coverage_audit as audit


def job(title="Ecommerce Operations Specialist", location="Germany", remote=True, url="https://example.org/job-a"):
    return {
        "source": "Himalayas", "source_job_id": url.rsplit("/", 1)[-1],
        "job_title": title, "company_name": "Example", "location": location,
        "remote": remote, "location_restrictions": [], "timezone_restrictions": [],
        "job_description": "Manage ecommerce operations, suppliers and catalogue workflows.",
        "job_url": url, "job_types": [], "seniority": "", "created_at": "",
        "salary": "", "source_attribution": "https://himalayas.app",
    }


class FakeResponse:
    def __init__(self, status, payload=None):
        self.status_code = status
        self.payload = payload or {}
    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0
    def get(self, *args, **kwargs):
        self.calls += 1
        return self.replies.pop(0)


class AuditTests(unittest.TestCase):
    def test_additional_jobs_are_incremental_only(self):
        base = [job(url="https://example.org/base")]
        extra = [job(url="https://example.org/base"),
                 job(location="Greece", url="https://example.org/new")]
        result, _, _ = audit.compare(base, extra, [], audit.AuditHTTP(sleep=0))
        self.assertEqual(result["baseline"]["unique"], 1)
        self.assertEqual(result["extended_only"]["incremental_unique"], 1)
        self.assertEqual(result["total_unique"], 2)

    def test_eu_remote_placement_is_uncertain_and_reviewable(self):
        target = job()
        rows, surviving, _, _, flags, _ = audit.count_outcomes([target])
        self.assertEqual(len(surviving), 1)
        self.assertEqual(surviving[0]["precheck_eligibility"], "uncertain")
        self.assertEqual(len(flags), 0)

    def test_himalayas_eu_country_allowlist_is_review_only_not_eligible(self):
        target = job(location="Germany")
        target["location_restrictions"] = ["DE"]
        rows, surviving, _, _, flags, _ = audit.count_outcomes([target])
        self.assertEqual(len(surviving), 1)
        self.assertEqual(surviving[0]["precheck_eligibility"], "uncertain")
        self.assertEqual(len(flags), 0)

    def test_explicit_not_hiring_in_greece_is_not_eligible(self):
        # Explicit country exclusions override accidental positive substring matches.
        target = job(location="Unknown")
        target["job_description"] = ("We are not hiring in Greece. "
                                     "Coordinate marketplace supplier and catalogue operations.")
        status, reason = ray.preliminary_eligibility(target)
        self.assertNotEqual(status, "eligible", reason)

    def test_eu_relocation_does_not_become_strong_match(self):
        from personal_evaluation import classify
        target = job(location="Germany")
        target["location_restrictions"] = ["DE"]
        target["precheck_eligibility"] = "uncertain"
        target["precheck_reason"] = "EU-country location restriction; relocation eligibility unverified"
        assessment = {
            "eligibility": "eligible", "fit_score": 93,
            "matched_evidence": ["Catalog operations"], "posting_evidence": ["Product data"],
            "mandatory_requirements": [], "main_gap_or_uncertainty": "", "reason": "Match",
        }
        classified = classify(assessment, target)
        self.assertEqual(classified["eligibility"], "uncertain")
        self.assertEqual(classified["decision"], "Review")

    def test_negative_hiring_overrides_himalayas_gr_country(self):
        target = job(location="Greece")
        target["location_restrictions"] = ["GR"]
        for text in (
            "We are currently not hiring in Greece.",
            "We do not hire candidates based in Greece.",
            "The role is open everywhere except Greece.",
        ):
            with self.subTest(text=text):
                target["job_description"] = text
                status, reason = ray.preliminary_eligibility(target)
                self.assertEqual(status, "uncertain", reason)

    def test_staff_and_principal_roles_stay_visible_as_review_only(self):
        for title in ("Staff Product Manager – E-Commerce", "Principal Marketplace Operations Specialist"):
            with self.subTest(title=title):
                target = job(title=title, location="Greece")
                rows, survivors, _, _, _, _ = audit.count_outcomes([target])
                self.assertEqual(len(survivors), 1)
                self.assertTrue(survivors[0]["review_only"])
                self.assertEqual(rows[0]["screen_outcome"], "review_only")
                self.assertIn("advanced_individual_contributor_seniority", rows[0]["fit_flags"])

    def test_invalid_host_blocks_provider_before_network(self):
        http = audit.AuditHTTP(session=FakeSession([]), sleep=0)
        self.assertIsNone(http.get("Himalayas", "https://example.com/api"))
        self.assertEqual(http.counts["Himalayas"], 0)
        self.assertIn("Himalayas", http.blocked)

    def test_429_stops_provider(self):
        session = FakeSession([FakeResponse(429)])
        http = audit.AuditHTTP(session=session, sleep=0)
        self.assertIsNone(http.get("Jobicy", ray.JOBICY))
        self.assertIsNone(http.get("Jobicy", ray.JOBICY))
        self.assertEqual(session.calls, 1)
        self.assertEqual(http.counts["Jobicy"], 1)
        self.assertIn("Jobicy", http.blocked)

    def test_request_limit_fixed(self):
        session = FakeSession([FakeResponse(200, {"jobs": []}) for _ in range(10)])
        http = audit.AuditHTTP(session=session, sleep=0)
        for _ in range(4):
            self.assertEqual(http.get("Remotive", ray.REMOTIVE), {"jobs": []} if _ == 0 else None)
        self.assertEqual(session.calls, 1)
        self.assertEqual(http.counts["Remotive"], 1)


if __name__ == "__main__":
    unittest.main()
