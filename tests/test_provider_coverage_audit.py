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

    def test_current_eu_remote_exclusion_flagged_for_relocation_review(self):
        target = job()
        rows, surviving, _, _, flags, _ = audit.count_outcomes([target])
        self.assertEqual(rows[0]["screen_outcome"], "geography_excluded")
        self.assertEqual(len(surviving), 0)
        self.assertEqual(len(flags), 1)

    def test_himalayas_german_country_allowlist_flagged_for_relocation(self):
        target = job(location="Germany")
        target["location_restrictions"] = ["DE"]
        rows, surviving, _, _, flags, _ = audit.count_outcomes([target])
        self.assertEqual(rows[0]["screen_outcome"], "geography_excluded")
        self.assertEqual(len(flags), 1)

    @unittest.expectedFailure
    def test_undesired_not_hiring_in_greece_positive_match(self):
        # Expected failure documents a real flaw in the unchanged screener.
        target = job(location="Unknown")
        target["job_description"] = ("We are not hiring in Greece. "
                                     "Coordinate marketplace supplier and catalogue operations.")
        status, reason = ray.preliminary_eligibility(target)
        self.assertNotEqual(status, "eligible", reason)

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
