"""Offline contract verification for optional, disabled-by-default public feeds.

No network, Google Sheets, Gemini, credentials, or production history.
"""
import unittest

import personal_discovery as d
import personal_extra_feeds as feeds


class FakeResponse:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code = status
        self.payload = payload
        self.text = text

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


def limits(**enabled):
    options = {key: 0 for key in d.DEFAULT_LIMITS}
    options.update(enabled)
    return options


REMOTE_OK_JOBS = [
    {"legal": "API terms; attribute Remote OK"},
    {
        "id": 102, "position": "Marketplace Operations Specialist", "company": "Alpha",
        "url": "https://remoteok.com/remote-jobs/102", "location": "EMEA",
        "description": "Manage catalog listings and supplier operations",
        "date": "2026-10-17T10:00:00Z", "tags": ["marketplace"],
    },
]
WWR_RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>Remote jobs</title>
<item><title>Beta: Category Manager</title>
<guid>wwr-42</guid><link>https://weworkremotely.com/remote-jobs/beta-category-manager</link>
<description><![CDATA[Manage vendor relationships and pricing.]]></description>
<pubDate>Sat, 17 Oct 2026 11:30:00 +0000</pubDate></item></channel></rss>"""
RJO_PAGE = {
    "data": [
        {
            "id": 43, "title": "Ecommerce Operations Analyst",
            "company": {"name": "Gamma"},
            "location": "Remote — Europe", "url": "https://remotejobs.org/remote-jobs/gamma-43",
            "description": "Coordinate marketplace catalog and product information workflows.",
            "posted_at": "2026-10-17T13:00:00Z", "employment_types": ["FULL_TIME"],
        }
    ],
    "pagination": {"has_more": False, "limit": 50, "offset": 0},
}


class ExtraFeedTests(unittest.TestCase):
    def test_default_and_config_ceiling(self):
        self.assertEqual(d.DEFAULT_LIMITS["Remote OK"], 0)
        self.assertEqual(d.DEFAULT_LIMITS["We Work Remotely"], 0)
        self.assertEqual(d.DEFAULT_LIMITS["RemoteJobs.org"], 0)
        self.assertEqual(d.HARD_PROVIDER_LIMITS["Remote OK"], 1)
        self.assertEqual(d.HARD_PROVIDER_LIMITS["We Work Remotely"], 1)
        self.assertEqual(d.HARD_PROVIDER_LIMITS["RemoteJobs.org"], 2)
        with self.assertRaises(ValueError):
            d.BudgetedHTTP(limits(**{"Remote OK": 2}))
        with self.assertRaises(ValueError):
            d.BudgetedHTTP(limits(**{"We Work Remotely": 2}))
        with self.assertRaises(ValueError):
            d.BudgetedHTTP(limits(**{"RemoteJobs.org": 3}))

    def test_all_three_disabled_causes_zero_http_calls(self):
        session = FakeSession([])
        http = d.BudgetedHTTP(limits(), session)
        jobs, counts, errors = d.collect(http)
        self.assertEqual(jobs, [])
        self.assertEqual(dict(http.calls), {})
        self.assertEqual(dict(counts), {})
        self.assertEqual(errors, [])
        self.assertEqual(session.calls, [])

    def test_remote_ok_notice_not_a_job(self):
        rows = feeds.normalize_remote_ok(REMOTE_OK_JOBS)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source_job_id"], "102")
        self.assertEqual(rows[0]["source_attribution"], rows[0]["job_url"])
        self.assertEqual(rows[0]["created_at"], "2026-10-17")
        self.assertEqual(rows[0]["location"], "EMEA")
        self.assertTrue(rows[0]["remote"])

    def test_wwr_rss_preserves_url_company_and_rfc_date(self):
        rows = feeds.normalize_wwr_rss(WWR_RSS)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["company_name"], "Beta")
        self.assertEqual(rows[0]["job_title"], "Category Manager")
        self.assertEqual(rows[0]["created_at"], "2026-10-17")
        self.assertEqual(rows[0]["location"], "Unknown")
        self.assertEqual(rows[0]["source_attribution"], rows[0]["job_url"])
        with self.assertRaises(ValueError):
            feeds.normalize_wwr_rss("<html></html>")

    def test_remotejobs_org_normalization(self):
        rows = feeds.normalize_remotejobs(RJO_PAGE)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["job_title"], "Ecommerce Operations Analyst")
        self.assertEqual(rows[0]["company_name"], "Gamma")
        self.assertEqual(rows[0]["job_types"], ["FULL_TIME"])
        self.assertEqual(rows[0]["source_attribution"], rows[0]["job_url"])
        self.assertEqual(rows[0]["created_at"], "2026-10-17")
        with self.assertRaises(ValueError):
            feeds.normalize_remotejobs({"data": "bad"})

    def test_three_enabled_providers_reuse_existing_screen_and_dedup(self):
        session = FakeSession([
            FakeResponse(payload=REMOTE_OK_JOBS),
            FakeResponse(text=WWR_RSS),
            FakeResponse(payload=RJO_PAGE),
        ])
        http = d.BudgetedHTTP(limits(**{
            "Remote OK": 1, "We Work Remotely": 1, "RemoteJobs.org": 1}), session)
        jobs, counts, errors = d.collect(http)
        self.assertEqual(errors, [])
        self.assertEqual(len(jobs), 3)
        self.assertEqual(http.calls["Remote OK"], 1)
        self.assertEqual(http.calls["We Work Remotely"], 1)
        self.assertEqual(http.calls["RemoteJobs.org"], 1)
        self.assertEqual(dict(counts), {
            "Remote OK": 1, "We Work Remotely": 1, "RemoteJobs.org": 1,
        })
        unique = d.deduplicate(jobs + [dict(jobs[0])])
        self.assertEqual(len(unique), 3)
        screened, _, _ = d.screen_candidates(unique)
        self.assertTrue(screened)
        self.assertTrue(all(j.get("precheck_eligibility") != "eligible" for j in screened))
        self.assertEqual(len(http.request_log), 3)

    def test_remotejobs_second_page_only_when_has_more(self):
        first = {**RJO_PAGE, "pagination": {"has_more": True}}
        second = {**RJO_PAGE, "data": [], "pagination": {"has_more": False}}
        session = FakeSession([FakeResponse(payload=first), FakeResponse(payload=second)])
        http = d.BudgetedHTTP(limits(**{"RemoteJobs.org": 2}), session)
        jobs, _, errors = d.collect(http)
        self.assertEqual(errors, [])
        self.assertEqual(len(jobs), 1)
        self.assertEqual(http.calls["RemoteJobs.org"], 2)
        self.assertEqual(session.calls[0][1]["params"]["offset"], 0)
        self.assertEqual(session.calls[1][1]["params"]["offset"], 50)
        self.assertTrue(all(c[1]["params"]["limit"] == 50 for c in session.calls))

    def test_wwr_429_blocks_provider_without_retry(self):
        session = FakeSession([FakeResponse(status=429)])
        http = d.BudgetedHTTP(limits(**{"We Work Remotely": 1}), session)
        _, _, errors = d.collect(http)
        self.assertEqual(len(session.calls), 1)
        self.assertIn("We Work Remotely", http.blocked)
        self.assertTrue(any("429" in e for e in errors))

    def test_malformed_rss_reports_provider_error(self):
        session = FakeSession([FakeResponse(text="<rss><channel><item>")])
        http = d.BudgetedHTTP(limits(**{"We Work Remotely": 1}), session)
        _, _, errors = d.collect(http)
        self.assertTrue(errors)
        self.assertEqual(len(session.calls), 1)


if __name__ == "__main__":
    unittest.main()
