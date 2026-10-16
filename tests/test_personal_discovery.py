import json
import sqlite3
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import personal_discovery as d
import personal_evaluation as ev
import personal_sheets as sheet


JOB = {
    "source": "Jobicy", "source_job_id": "11", "job_title": "Marketplace Operations Specialist",
    "company_name": "Example Ltd", "location": "Anywhere", "remote": True,
    "location_restrictions": [], "timezone_restrictions": [],
    "job_description": "Manage marketplace data, supplier processes and Excel reports.",
    "job_url": "https://jobicy.com/jobs/11", "job_types": ["Full-time"],
    "seniority": "Mid", "created_at": "2026-10-16", "salary": "",
}
VALID = {
    "job_index": 0, "eligibility": "eligible", "fit_score": 83,
    "mandatory_requirements": ["Manage supplier data"],
    "matched_evidence": ["Supplier coordination -> marketplace operation"],
    "posting_evidence": ["Manage supplier data"],
    "main_gap_or_uncertainty": "", "reason": "Matches direct work",
}


class FakeResponse:
    def __init__(self, status, payload=None):
        self.status_code = status
        self.payload = payload or {}
    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


class FakeModels:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0
    def generate_content(self, **kwargs):
        self.calls += 1
        return type("Response", (), {"text": json.dumps(self.payload)})()


class Tests(unittest.TestCase):
    def test_himalayas_normalization_and_provenance(self):
        raw = [{"guid": "abc", "title": "Business Operations", "companyName": "Co",
                "locationRestrictions": [{"alpha2": "GR", "name": "Greece"}],
                "timezoneRestrictions": ["UTC+3"], "description": "Job detail",
                "applicationLink": "https://himalayas.app/jobs/123", "pubDate": 1792000000000}]
        j = d.normalize_himalayas(raw)[0]
        self.assertEqual(j["source_job_id"], "abc")
        self.assertEqual(j["location_restrictions"], ["GR"])
        self.assertEqual(j["source_attribution"], "https://himalayas.app")
        self.assertEqual(j["job_url"], "https://himalayas.app/jobs/123")

    def test_himalayas_worldwide_not_greece_restricted(self):
        j = d.normalize_himalayas([{"guid": "x", "title": "Operations", "locationRestrictions": []}])[0]
        self.assertEqual(j["location"], "Worldwide")
        self.assertEqual(j["location_restrictions"], [])

    def test_jobicy_normalization(self):
        j = d.normalize_jobicy([{"id": 100, "jobTitle": "Commercial Operations", "jobGeo": "Europe",
                              "url": "https://jobicy.com/jobs/demo", "jobType": ["Full-time"],
                              "pubDate": "2026-10-15T10:00:00+00:00"}])[0]
        self.assertEqual(j["source_job_id"], "100")
        self.assertEqual(j["location"], "Europe")
        self.assertEqual(j["created_at"], "2026-10-15")

    def test_legacy_normalizers_do_not_import_gemini_runtime(self):
        # Regression: collect-only must work without GEMINI_API_KEY.
        # Importing RAY main.py initializes the old validator's Gemini client.
        cases = {
            "Arbeitnow": ({"id": 101, "title": "Operations Specialist", "company_name": "A",
                           "location": "Athens", "description": "Orders", "url": "https://a/jobs/101",
                           "remote": False, "tags": ["operations"], "job_types": ["full_time"],
                           "created_at": "2026-10-16"},
                          {"company_name": "A", "location": "Athens", "remote": False,
                           "tags": ["operations"], "job_types": ["full_time"],
                           "source_job_id": "101", "created_at": "2026-10-16"}),
            "Remotive": ({"id": 202, "title": "Market Operations", "company_name": "B",
                          "candidate_required_location": "Europe", "description": "Vendors",
                          "url": "https://b/jobs/202", "category": "Operations", "job_type": "contract",
                          "publication_date": "2026-10-15"},
                         {"company_name": "B", "location": "Europe", "remote": True,
                          "tags": ["Operations"], "job_types": ["contract"],
                          "source_job_id": "202", "created_at": "2026-10-15"}),
            "Adzuna": ({"id": 303, "title": "Catalog Analyst",
                         "company": {"display_name": "C"},
                         "location": {"display_name": "London"},
                         "description": "Pricing", "redirect_url": "https://c/jobs/303",
                         "created": "2026-10-14"},
                        {"company_name": "C", "location": "London", "remote": None,
                         "tags": [], "job_types": [], "source_job_id": "303",
                         "created_at": "2026-10-14"}),
        }
        with patch.dict(sys.modules, {"main": None}), patch.dict("os.environ", {"GEMINI_API_KEY": ""}):
            for source, (raw, expected) in cases.items():
                with self.subTest(source=source):
                    job = d.normalize_original(source, [raw])[0]
                    self.assertEqual(job["source"], source)
                    self.assertEqual(job["job_title"], raw["title"])
                    self.assertEqual(job["job_description"], raw["description"])
                    self.assertEqual(job["source_attribution"], job["job_url"])
                    for field, value in expected.items():
                        self.assertEqual(job[field], value)

    def test_collect_only_with_legacy_sources_and_no_gemini_key(self):
        session = FakeSession([
            FakeResponse(200, {"data": [{"id": 1, "title": "Ecommerce Operations",
                                         "company_name": "A", "url": "https://a/jobs/1"}],
                               "links": {"next": None}}),
            FakeResponse(200, {"jobs": [{"id": 2, "title": "Marketplace Operations",
                                         "company_name": "B", "url": "https://b/jobs/2"}]}),
        ])
        with tempfile.TemporaryDirectory() as td:
            report = Path(td) / "run.json"
            with patch.dict(sys.modules, {"main": None}), patch.dict("os.environ", {
                "GEMINI_API_KEY": "", "PERSONAL_MAX_ARBEITNOW_CALLS": "1",
                "PERSONAL_MAX_REMOTIVE_CALLS": "1", "PERSONAL_MAX_ADZUNA_CALLS": "0",
                "PERSONAL_MAX_HIMALAYAS_CALLS": "0", "PERSONAL_MAX_JOBICY_CALLS": "0",
            }):
                out, stats = d.run(collect_only=True, session=session, report_path=str(report))
            self.assertEqual(len(out), 2)
            self.assertEqual(stats["prefiltered_candidates"], 2)
            self.assertEqual(len(session.calls), 2)
            self.assertTrue(report.is_file())
            self.assertEqual(json.loads(report.read_text())["source_http_attempts"],
                             {"Arbeitnow": 1, "Remotive": 1})

    def test_canonical_url_keeps_job_identifiers_but_strips_tracking(self):
        first = "HTTPS://EXAMPLE.COM/jobs/123/?utm_source=x&jobid=99#fragment"
        self.assertEqual(d.canonical_url(first), "https://example.com/jobs/123?jobid=99")
        self.assertEqual(d.canonical_url("javascript:alert(1)"), "")

    def test_dedupe_does_not_collapse_different_requisitions(self):
        j1 = dict(JOB)
        j2 = {**JOB, "source_job_id": "12", "job_url": "https://jobicy.com/jobs/12"}
        self.assertEqual(len(d.deduplicate([j1, j2, dict(j1)])), 2)

    def test_prefilter_target_families(self):
        self.assertTrue(d.target_role(JOB))
        self.assertTrue(d.target_role({"job_title": "Pricing and Catalog Analyst"}))
        self.assertTrue(d.target_role({"job_title": "Implementation Manager"}))
        self.assertFalse(d.target_role({"job_title": "Executive Chef"}))

    def test_budget_counts_retries_and_exhausts(self):
        session = FakeSession([FakeResponse(500), FakeResponse(200, {"jobs": []})])
        http = d.BudgetedHTTP({"Jobicy": 2}, session)
        with patch.object(d.time, "sleep"):
            self.assertEqual(http.get_json("Jobicy", d.JOBICY), {"jobs": []})
        self.assertEqual(http.calls["Jobicy"], 2)
        with self.assertRaises(d.ProviderError):
            http.get_json("Jobicy", d.JOBICY)

    def test_429_fails_immediately(self):
        http = d.BudgetedHTTP({"Jobicy": 5}, FakeSession([FakeResponse(429)]))
        with self.assertRaisesRegex(d.ProviderError, "429"):
            http.get_json("Jobicy", d.JOBICY)
        self.assertEqual(http.calls["Jobicy"], 1)

    def test_unknown_remote_europe_cannot_be_eligible(self):
        result = ev.classify(dict(VALID), {**JOB, "location": "EMEA"})
        self.assertEqual(result["eligibility"], "uncertain")
        self.assertEqual(result["decision"], "Review")

    def test_us_only_ineligible_despite_high_score(self):
        result = ev.classify(dict(VALID, fit_score=98), {**JOB, "location": "USA"})
        self.assertEqual(result["decision"], "Ineligible")

    def test_himalayas_geography_hard_gate(self):
        job = {**JOB, "source": "Himalayas", "location_restrictions": ["US", "GB"]}
        result = ev.classify(dict(VALID, fit_score=99), job)
        self.assertEqual(result["eligibility"], "ineligible")
        self.assertEqual(result["decision"], "Ineligible")

    def test_uncertain_does_not_become_strong_match(self):
        result = ev.classify(dict(VALID, eligibility="uncertain", fit_score=90), JOB)
        self.assertEqual(result["decision"], "Review")

    def test_low_score_not_strong_match(self):
        result = ev.classify(dict(VALID, fit_score=42), JOB)
        self.assertEqual(result["decision"], "Low Match")

    def test_batch_fail_closed_on_duplicate_indices(self):
        with self.assertRaises(ValueError):
            ev.parse_batch([VALID, VALID], [dict(JOB), dict(JOB)])

    def test_batch_fail_closed_on_invalid_score(self):
        with self.assertRaises(ValueError):
            ev.parse_batch([dict(VALID, fit_score=101)], [JOB])
        with self.assertRaises(ValueError):
            ev.parse_batch([dict(VALID, fit_score=True)], [JOB])

    def test_cache_closes_sqlite_connections(self):
        class TrackedConnection(sqlite3.Connection):
            closed_explicitly = False

            def close(self):
                self.closed_explicitly = True
                return super().close()

        actual_connect = sqlite3.connect
        opened = []

        def tracked_connect(*args, **kwargs):
            conn = actual_connect(*args, factory=TrackedConnection, **kwargs)
            opened.append(conn)
            return conn

        with tempfile.TemporaryDirectory() as td:
            with patch.object(ev.sqlite3, "connect", side_effect=tracked_connect):
                cache = ev.PersonalCache(Path(td) / "db.sqlite")
                fp = ev.fingerprint(JOB, "profile", "prompt")
                self.assertIsNone(cache.get(JOB, fp))
                cache.put(JOB, fp, ev.classify(dict(VALID), JOB))
                self.assertEqual(cache.get(JOB, fp)["fit_score"], 83)
                self.assertTrue(opened)
                self.assertTrue(all(conn.closed_explicitly for conn in opened))

    def test_cache_versions_job_profile_and_prompt_and_segregation(self):
        with tempfile.TemporaryDirectory() as td:
            cache = ev.PersonalCache(Path(td) / "validation_cache.db")
            fp = ev.fingerprint(JOB, "profile-v1", "prompt-v1")
            result = ev.classify(dict(VALID), JOB)
            cache.put(JOB, fp, result)
            self.assertEqual(cache.get(JOB, fp)["fit_score"], 83)
            self.assertIsNone(cache.get(JOB, ev.fingerprint(JOB, "profile-v2", "prompt-v1")))
            self.assertIsNone(cache.get(JOB, ev.fingerprint(JOB, "profile-v1", "prompt-v2")))
            self.assertIsNone(cache.get(JOB, ev.fingerprint({**JOB,"job_description":"updated"},
                                                            "profile-v1", "prompt-v1")))
            self.assertTrue(ev.cache_key(JOB).startswith("personal-fit-v1:"))

    def test_model_batch_and_cache_reuse(self):
        with tempfile.TemporaryDirectory() as td:
            fake = FakeModels([dict(VALID)])
            client = type("Client", (), {"models": fake})()
            cache = ev.PersonalCache(Path(td) / "db.sqlite")
            evaluator = ev.Evaluator("verified evidence goes here", cache, max_calls=1, client=client)
            out, stats = evaluator.evaluate([dict(JOB)])
            self.assertEqual(out[0]["assessment"]["decision"], "Strong Match")
            self.assertEqual(stats["gemini_calls"], 1)
            out2, stats2 = evaluator.evaluate([dict(JOB)])
            self.assertEqual(stats2["cache_hits"], 1)
            self.assertEqual(fake.calls, 1)

    def test_budget_zero_no_gemini_or_false_approval(self):
        with tempfile.TemporaryDirectory() as td:
            fake = FakeModels([dict(VALID)])
            client = type("Client", (), {"models": fake})()
            evaluator = ev.Evaluator("verified", ev.PersonalCache(Path(td) / "db.sqlite"),
                                     max_calls=0, client=client)
            out, stats = evaluator.evaluate([dict(JOB)])
            self.assertEqual(out, [])
            self.assertEqual(stats["unprocessed_budget"], 1)
            self.assertEqual(fake.calls, 0)

    def test_invalid_model_json_no_false_approval(self):
        with tempfile.TemporaryDirectory() as td:
            fake = FakeModels([dict(VALID, fit_score="100")])
            client = type("Client", (), {"models": fake})()
            evaluator = ev.Evaluator("verified", ev.PersonalCache(Path(td) / "db.sqlite"),
                                     max_calls=1, client=client)
            out, stats = evaluator.evaluate([dict(JOB)])
            self.assertEqual(out, [])
            self.assertEqual(stats["failed_batches"], 1)

    def test_no_evidence_prevents_strong_match(self):
        result = ev.classify(dict(VALID, matched_evidence=[]), JOB)
        self.assertEqual(result["decision"], "Review")

    def test_capped_provider_collection_with_offline_fixtures(self):
        session = FakeSession([
            FakeResponse(200, {"jobs": [{"guid": "h1", "title": "Catalog Operations",
                                         "companyName": "H", "applicationLink": "https://himalayas.app/jobs/h1"}]}),
            FakeResponse(200, {"success": True, "jobs": [{"id": 12, "jobTitle": "Marketplace Operations",
                                           "url": "https://jobicy.com/jobs/12", "jobGeo": "Anywhere"}]}),
        ])
        limits = {"Arbeitnow": 0, "Remotive": 0, "Adzuna": 0,
                  "Himalayas": 1, "Jobicy": 1}
        http = d.BudgetedHTTP(limits, session)
        jobs, stats, errors = d.collect(http)
        self.assertEqual(len(jobs), 2)
        self.assertEqual(stats["Himalayas"], 1)
        self.assertEqual(http.calls["Jobicy"], 1)
        self.assertEqual(len(session.calls), 2)
        self.assertEqual(errors, [])

    def test_collect_only_writes_local_report_without_ai(self):
        fake_jobs = [dict(JOB)]
        with tempfile.TemporaryDirectory() as td:
            outpath = Path(td) / "run.json"
            with patch.dict("os.environ", {
                    "PERSONAL_MAX_ARBEITNOW_CALLS": "0", "PERSONAL_MAX_REMOTIVE_CALLS": "0",
                    "PERSONAL_MAX_HIMALAYAS_CALLS": "0", "PERSONAL_MAX_JOBICY_CALLS": "0"}):
                with patch.object(d, "collect", return_value=(fake_jobs, {"Jobicy": 1}, [])):
                    jobs, stats = d.run(collect_only=True, report_path=str(outpath))
            self.assertEqual(len(jobs), 1)
            self.assertTrue(outpath.exists())
            data = json.loads(outpath.read_text())
            self.assertEqual(data["source_fetched"]["Jobicy"], 1)

    def test_title_filter_rejects_description_only_engineering_and_sales_noise(self):
        noise = dict(JOB, job_description=(
            "Our ecommerce marketplace improves operations, catalog management, "
            "pricing, inventory and supplier coordination through automation."
        ))
        for title in ("Staff Product Engineer", "Senior DevOps Engineer",
                      "Enterprise Account Executive - DACH", "Chief Technology Officer",
                      "Head of Product Compliance", "Senior Accounts Payable Coordinator",
                      "Teamlead People Operations"):
            with self.subTest(title=title):
                self.assertFalse(d.target_role({**noise, "job_title": title}))
        for title in ("Digital Enablement Specialist", "Marketplace Manager",
                      "Commercial Operations Project Manager", "Product Data Specialist",
                      "Pricing and Catalog Analyst", "AI Automation Specialist - Marketing & Web"):
            with self.subTest(title=title):
                self.assertTrue(d.target_role({**noise, "job_title": title}))

    def test_geo_filter_requires_greece_for_country_restricted_remote(self):
        j = {**JOB, "location": "Netherlands", "remote": True}
        self.assertEqual(d.preliminary_eligibility(j)[0], "ineligible")
        j["location"] = "Europe"
        self.assertEqual(d.preliminary_eligibility(j)[0], "uncertain")
        j["location"] = "Anywhere"
        self.assertEqual(d.preliminary_eligibility(j)[0], "uncertain")
        j["location"] = "Greece"
        self.assertEqual(d.preliminary_eligibility(j)[0], "eligible")
        j["source"] = "Himalayas"
        j["location_restrictions"] = ["US", "GB"]
        self.assertEqual(d.preliminary_eligibility(j)[0], "ineligible")
        j["location_restrictions"] = ["GR"]
        self.assertEqual(d.preliminary_eligibility(j)[0], "eligible")

    def test_greece_in_employer_hiring_allowlist_and_eu_hybrid(self):
        foxelli = {**JOB, "location": "", "job_description": (
            "This job is remote EU. Currently, we are hiring in Albania, Bosnia, "
            "Croatia, Czech Republic, Estonia, Greece, Georgia, Latvia and Portugal."
        )}
        self.assertEqual(d.preliminary_eligibility(foxelli)[0], "eligible")
        hybrid = {**JOB, "location": "Netherlands", "job_description": (
            "This role is based in our Amsterdam office in the Netherlands. "
            "Most colleagues operate in a hybrid setup with two office days per week."
        )}
        eligibility, reason = d.preliminary_eligibility(hybrid)
        self.assertEqual(eligibility, "eligible")
        self.assertIn("relocation", reason)
        self.assertEqual(d.preliminary_eligibility(
            {**JOB, "remote": False, "location": "London"})[0], "ineligible")

    def test_unknown_precheck_cannot_be_upgraded_by_model(self):
        uncertain = {**JOB, "precheck_eligibility": "uncertain"}
        result = ev.classify(dict(VALID, eligibility="eligible", fit_score=95), uncertain)
        self.assertEqual(result["eligibility"], "uncertain")
        self.assertEqual(result["decision"], "Review")
        known = {**JOB, "precheck_eligibility": "eligible"}
        result = ev.classify(dict(VALID, eligibility="eligible", fit_score=95), known)
        self.assertEqual(result["decision"], "Strong Match")

    def test_mandatory_foreign_language_but_not_preferred(self):
        self.assertEqual(d.mandatory_other_language({**JOB, "job_description": (
            "English is required. German is a plus, but is not required."
        )}), None)
        self.assertEqual(d.preliminary_eligibility({**JOB, "job_description": (
            "Fluent German and English are required to collaborate with clients."
        )})[0], "ineligible")
        self.assertEqual(d.preliminary_eligibility({**JOB,
            "job_title": "Enterprise Implementation Consultant - German Fluency"
        })[0], "ineligible")
        self.assertEqual(d.preliminary_eligibility({**JOB, "job_description": (
            "Du sprichst fließend Deutsch und bringst gute Englischkenntnisse mit."
        )})[0], "ineligible")

    def test_prioritization_caps_ai_and_prevents_source_monopoly(self):
        jobs = []
        for source, n in (("Arbeitnow", 30), ("Himalayas", 8), ("Jobicy", 8)):
            for i in range(n):
                jobs.append({**JOB, "source": source, "job_url": f"https://test/{source}/{i}",
                             "priority": 95 if source == "Arbeitnow" else 65})
        selected = d.prioritize_candidates(jobs, 20)
        self.assertEqual(len(selected), 20)
        self.assertEqual(len({x["job_url"] for x in selected}), 20)
        counts = {s: sum(j["source"] == s for j in selected)
                  for s in ("Arbeitnow", "Himalayas", "Jobicy")}
        self.assertLessEqual(counts["Arbeitnow"], 8)
        self.assertGreater(counts["Himalayas"], 0)
        self.assertGreater(counts["Jobicy"], 0)

    def test_balanced_screen_retains_customer_ops_for_review(self):
        job = {**JOB, "job_title": "Customer Service Manager (GR)",
               "job_description": "Improve marketplace processes, order management and inventory coordination; manage vendor escalations.",
               "location": "Greece"}
        self.assertGreaterEqual(d.title_relevance(job), 45)
        audit = []
        survivors, counts, rejects = d.screen_candidates([job], audit=audit)
        self.assertEqual(len(survivors), 1)
        self.assertEqual(audit[0]["screen_outcome"], "candidate")
        self.assertEqual(audit[0]["eligibility"], "eligible")
        self.assertFalse(survivors[0]["review_only"])

    def test_exploratory_lane_does_not_consume_ai_calls(self):
        strong = {**JOB, "job_title": "Marketplace Operations Coordinator",
                  "job_url": "https://example.com/job/strong"}
        adjacent = {**JOB, "job_title": "Customer Success Manager",
                    "job_description": "Engage customers.",
                    "job_url": "https://example.com/job/explore"}
        executive = {**JOB, "job_title": "Director of Operations",
                     "job_url": "https://example.com/job/director"}
        audit = []
        pool, counts, rejects = d.screen_candidates([strong, adjacent, executive], audit)
        self.assertEqual(len(pool), 3)
        self.assertEqual(counts["review_only"], 2)
        self.assertEqual({j["job_url"] for j in pool if not j["review_only"]},
                         {strong["job_url"]})
        self.assertEqual([r["screen_outcome"] for r in audit],
                         ["candidate", "review_only", "review_only"])

    def test_dutch_requirement_is_detected_but_optional_german_is_not(self):
        dutch = {**JOB, "job_title": "Manager Operations Planning & Performance",
                 "job_description": "Je spreekt vloeiend Nederlands en Engels."}
        self.assertEqual(d.mandatory_other_language(dutch), "Dutch")
        self.assertEqual(d.preliminary_eligibility(dutch)[0], "ineligible")
        optional = {**JOB, "job_description": "Fluent German is preferred, not required. English is required."}
        self.assertIsNone(d.mandatory_other_language(optional))

    def test_screening_audit_records_all_sources_and_exclusions(self):
        rows = [
            {**JOB, "job_url": "https://site/j/1", "job_title": "Marketplace Operations Manager"},
            {**JOB, "job_url": "https://site/j/2", "job_title": "Senior Software Engineer",
             "job_description": "Our ecommerce marketplace needs operations."},
            {**JOB, "job_url": "https://site/j/3", "job_title": "Pricing Specialist",
             "location": "USA"},
        ]
        with tempfile.TemporaryDirectory() as td:
            audit = []
            pool, counts, rejects = d.screen_candidates(rows, audit)
            self.assertEqual(len(pool), 1)
            dest = d.write_screening_audit(Path(td) / "personal_run.json", audit)
            self.assertTrue(dest.exists())
            import csv
            with dest.open(encoding="utf-8-sig", newline="") as handle:
                records = list(csv.DictReader(handle))
            self.assertEqual(len(records), len(rows))
            self.assertEqual([r["screen_outcome"] for r in records],
                             ["candidate", "role_out_of_scope", "geography_excluded"])
            self.assertEqual(records[1]["role_reason"], "clear non-target profession/title")

    def test_screening_audit_escapes_untrusted_spreadsheet_formulas(self):
        with tempfile.TemporaryDirectory() as td:
            record = {"job_title": '=HYPERLINK("https://bad.test", "click")',
                      "company": "+EXECUTE()", "job_url": "https://example.com/test"}
            dest = d.write_screening_audit(Path(td) / "personal_run.json", [record])
            import csv
            with dest.open(encoding="utf-8-sig", newline="") as handle:
                row = list(csv.DictReader(handle))[0]
            self.assertTrue(row["job_title"].startswith("'="))
            self.assertTrue(row["company"].startswith("'+"))
            self.assertEqual(row["job_url"], "https://example.com/test")

    def test_collection_only_produces_audit_no_remote_ai_or_sheets(self):
        fake_jobs = [{**JOB, "job_url": "https://example.com/j/4"},
                     {**JOB, "job_url": "https://example.com/j/5", "source_job_id": "55",
                      "job_title": "Staff Software Engineer"}]
        with tempfile.TemporaryDirectory() as td:
            report = Path(td) / "personal_run.json"
            with patch.dict("os.environ", {"GEMINI_API_KEY": "",
                  "PERSONAL_MAX_ARBEITNOW_CALLS": "0", "PERSONAL_MAX_REMOTIVE_CALLS": "0",
                  "PERSONAL_MAX_HIMALAYAS_CALLS": "0", "PERSONAL_MAX_JOBICY_CALLS": "0"}):
                with patch.object(d, "collect", return_value=(fake_jobs, {"Jobicy": 2}, [])):
                    jobs, stats = d.run(collect_only=True, report_path=str(report))
            self.assertEqual(len(jobs), 1)
            self.assertEqual(stats["audit_rows"], 2)
            self.assertEqual(stats["ai_shortlist_count"], 1)
            self.assertTrue((Path(td) / "personal_run_screening_audit.csv").is_file())

    def test_normalized_legacy_dates_not_unix_timestamps(self):
        row = d.normalize_original("Arbeitnow", [{"title": "Operations Manager",
                   "url": "https://example/jobs/1", "created_at": 1792151727}])[0]
        self.assertRegex(row["created_at"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertEqual(row["created_at"], d.iso_date(1792151727))

    def test_sheet_infers_eu_hybrid_from_employer_evidence(self):
        job = {**JOB, "precheck_reason": "Employer describes EU office-based/hybrid work; relocation needed",
               "assessment": ev.classify(dict(VALID), JOB)}
        self.assertEqual(sheet._row(job)[3], "Hybrid / EU relocation")

    def test_sheet_id_guards(self):
        with patch.dict("os.environ", {"PERSONAL_GOOGLE_SHEET_ID": "12345678901234567890",
                                       "GOOGLE_SHEET_ID": "12345678901234567890"}):
            with self.assertRaisesRegex(ValueError, "original"):
                sheet.verify_spreadsheet_destination()
        with patch.dict("os.environ", {"PERSONAL_GOOGLE_SHEET_ID": "NEW-SHEET-IDENTIFIER-12345",
                                       "GOOGLE_SHEET_ID": "OLD-SHEET-IDENTIFIER-12345"}):
            self.assertEqual(sheet.verify_spreadsheet_destination(), "NEW-SHEET-IDENTIFIER-12345")

    def test_sheet_row_retains_human_review_status_and_notes(self):
        old = [""] * 19
        old[17], old[18] = "Applied", "Keep manual note"
        row = sheet._row({**JOB, "assessment": ev.classify(dict(VALID), JOB)}, old)
        self.assertEqual(row[17:], ["Applied", "Keep manual note"])
        self.assertEqual(row[10], 83)


if __name__ == "__main__":
    unittest.main()
