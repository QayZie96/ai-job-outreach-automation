"""Offline contract tests for international opt-in Adzuna.

No live API requests, Gemini, Google Sheets or production task changes.
"""
import unittest
from unittest.mock import patch

import requests
import personal_discovery as d


class Response:
    def __init__(self, code=200, data=None):
        self.status_code = code
        self.data = data if data is not None else {"count": 0, "results": []}

    def json(self):
        return self.data


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        outcome = self.responses.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


SAMPLE = {
    "count": 1,
    "results": [{
        "id": "hire-100", "title": "E-commerce Operations Coordinator",
        "company": {"display_name": "Test Merchant"},
        "location": {"display_name": "Amsterdam, Netherlands"},
        "description": "Coordinate marketplace catalogue and supplier operations.",
        "redirect_url": "https://www.adzuna.nl/details/100",
        "created": "2026-10-17T08:00:00Z",
    }],
}


def controlled():
    return {
        "ADZUNA_APP_ID": "APP_TEST_ID",
        "ADZUNA_APP_KEY": "secret++not_for_git",
        "PERSONAL_ADZUNA_MARKETS": "de,nl,fr,es",
        "PERSONAL_ADZUNA_TERMS": "ecommerce,operations",
        "PERSONAL_ADZUNA_PAGES_PER_QUERY": "1",
    }


class InternationalAdzunaTests(unittest.TestCase):
    def test_zero_default_and_capped_opt_in(self):
        self.assertEqual(d.DEFAULT_LIMITS["Adzuna"], 0)
        self.assertEqual(d.HARD_PROVIDER_LIMITS["Adzuna"], 12)
        with self.assertRaises(ValueError):
            d.BudgetedHTTP({"Adzuna": 13})
        session = Session([])
        http = d.BudgetedHTTP({"Adzuna": 0}, session)
        with patch.dict("os.environ", controlled()):
            jobs, stats, errors = d.collect(http)
        self.assertEqual(session.calls, [])
        self.assertEqual(jobs, [])
        self.assertFalse(stats)
        self.assertEqual(errors, [])

    def test_country_market_and_query_validation(self):
        self.assertEqual(
            d.adzuna_search_plan(("de", "nl"), ("ecommerce", "operations"), 1),
            [("de", "ecommerce", 1), ("de", "operations", 1),
             ("nl", "ecommerce", 1), ("nl", "operations", 1)],
        )
        self.assertEqual(len(d.adzuna_search_plan(
            ("de", "nl", "fr", "es"), ("ecommerce", "operations"), 2)), 16)
        for config, allowed, label in [
            ("de,evil/../", d.ADZUNA_MARKET_ALLOWLIST, "markets"),
            ("de,de", d.ADZUNA_MARKET_ALLOWLIST, "markets"),
            ("", d.ADZUNA_MARKET_ALLOWLIST, "markets"),
            ("ecommerce,unsupported", d.ADZUNA_QUERY_ALLOWLIST, "terms"),
        ]:
            with self.subTest(config=config):
                with self.assertRaises(ValueError):
                    d._csv_allowlist(config, allowed, label)
        with self.assertRaises(ValueError):
            d.adzuna_search_plan(("de",), ("operations",), 3)

    def test_eight_calls_across_four_eu_markets(self):
        session = Session([Response(data=SAMPLE) for _ in range(8)])
        http = d.BudgetedHTTP({"Adzuna": 8}, session)
        with patch.dict("os.environ", controlled()):
            jobs, stats, errors = d.collect(http)
        self.assertEqual(errors, [])
        self.assertEqual(len(jobs), 8)
        self.assertEqual(stats["Adzuna"], 8)
        self.assertEqual(http.calls["Adzuna"], 8)
        self.assertEqual([url.rsplit("/jobs/", 1)[-1].split("/")[0]
                          for url, _ in session.calls],
                         ["de", "de", "nl", "nl", "fr", "fr", "es", "es"])
        self.assertTrue(all(kwargs["params"]["results_per_page"] == 50
                            for _, kwargs in session.calls))
        self.assertEqual(jobs[0]["source_query"], "market:de:what:ecommerce:p1")
        self.assertEqual(jobs[-1]["source_query"], "market:es:what:operations:p1")
        self.assertTrue(all("app_id" not in row["parameters"]
                            and "app_key" not in row["parameters"]
                            for row in http.request_log))
        self.assertTrue(all(row["parameters"]["what"] in {"ecommerce", "operations"}
                            for row in http.request_log))
        self.assertEqual(len(d.deduplicate(jobs)), 1)  # Same vacancy across markets.
        survivor, _, _ = d.screen_candidates(d.deduplicate(jobs))
        self.assertEqual(len(survivor), 1)
        self.assertEqual(survivor[0]["precheck_eligibility"], "uncertain")

    def test_missing_credentials_never_sends_request(self):
        session = Session([])
        http = d.BudgetedHTTP({"Adzuna": 8}, session)
        env = {**controlled(), "ADZUNA_APP_ID": "", "ADZUNA_APP_KEY": ""}
        with patch.dict("os.environ", env):
            _, _, errors = d.collect(http)
        self.assertTrue(any("credentials missing" in error for error in errors))
        self.assertEqual(session.calls, [])

    def test_invalid_enabled_configuration_fails_before_http(self):
        session = Session([])
        http = d.BudgetedHTTP({"Adzuna": 8}, session)
        env = {**controlled(), "PERSONAL_ADZUNA_MARKETS": "de,not-real"}
        with patch.dict("os.environ", env):
            _, _, errors = d.collect(http)
        self.assertTrue(errors)
        self.assertEqual(session.calls, [])

    def test_429_and_forbidden_stops_entire_adzuna_batch(self):
        for status in (401, 403, 429):
            with self.subTest(status=status):
                session = Session([Response(code=status)])
                http = d.BudgetedHTTP({"Adzuna": 8}, session)
                with patch.dict("os.environ", controlled()):
                    _, _, errors = d.collect(http)
                self.assertEqual(http.calls["Adzuna"], 1)
                self.assertEqual(len(session.calls), 1)
                self.assertIn("Adzuna", http.blocked)
                self.assertTrue(errors)

    def test_network_exception_does_not_leak_credentials(self):
        error = requests.ConnectionError(
            "URL: https://api.adzuna.com/v1/api/jobs/de/search/1?"
            "app_id=APP_TEST_ID&app_key=secret%2B%2Bnot_for_git"
        )
        session = Session([error, error])
        http = d.BudgetedHTTP({"Adzuna": 2}, session)
        with patch.dict("os.environ", controlled()):
            _, _, errors = d.collect(http)
        self.assertTrue(errors)
        self.assertNotIn("APP_TEST_ID", " ".join(errors))
        self.assertNotIn("secret", " ".join(errors))
        self.assertNotIn("APP_TEST_ID", repr(http.request_log))
        self.assertNotIn("secret", repr(http.request_log))

    def test_second_page_only_with_explicit_config(self):
        session = Session([Response(data=SAMPLE) for _ in range(12)])
        http = d.BudgetedHTTP({"Adzuna": 12}, session)
        env = {**controlled(), "PERSONAL_ADZUNA_PAGES_PER_QUERY": "2"}
        with patch.dict("os.environ", env):
            _, _, errors = d.collect(http)
        self.assertEqual(errors, [])
        self.assertEqual(len(session.calls), 12)
        self.assertTrue(all("/search/1" in url for url, _ in session.calls[:8]))
        self.assertTrue(all("/search/2" in url for url, _ in session.calls[8:]))

    def test_empty_page_one_skips_extra_page(self):
        session = Session([Response() for _ in range(8)])
        http = d.BudgetedHTTP({"Adzuna": 12}, session)
        env = {**controlled(), "PERSONAL_ADZUNA_PAGES_PER_QUERY": "2"}
        with patch.dict("os.environ", env):
            _, _, errors = d.collect(http)
        self.assertEqual(errors, [])
        self.assertEqual(http.calls["Adzuna"], 8)
        self.assertEqual(len(session.calls), 8)


if __name__ == "__main__":
    unittest.main()
