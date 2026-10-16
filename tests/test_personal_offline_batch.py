"""Offline pilot regressions; provider APIs, Gemini and Sheets are never called."""
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import personal_offline_batch as p


def example(index, title="Marketplace Coordinator", manual=False):
    return {"source": "Jobicy", "job_url": f"https://example.test/job/{index}",
            "job_title": title, "company_name": "Test Co", "location": "Europe",
            "remote": True, "job_description": "Catalog and inventory operations.",
            "review_only": manual, "priority": 70, "precheck_eligibility": "uncertain"}


class OfflinePilotTests(unittest.TestCase):
    def test_one_batch_limit_and_adjacent_jobs(self):
        jobs = [example(1), example(2),
                example(3, "Senior Marketing Director", True),
                example(4, "Junior Project Manager", True),
                example(5, "Remote Office Assistant", True),
                example(6, "Customer Success German and English Speaking", True)]
        selected, summary = p.select_jobs({"evaluated_jobs": jobs}, {}, 4, 2)
        self.assertEqual({j["job_url"] for j in selected},
                         {jobs[i]["job_url"] for i in (0, 1, 3, 4)})
        self.assertEqual(summary["selected_core"], 2)
        self.assertEqual(summary["selected_adjacent"], 2)
        self.assertEqual(summary["hard_excluded"], 1)
        with self.assertRaises(ValueError):
            p.select_jobs({"evaluated_jobs": []}, {}, limit=21)

    def test_reviewed_applied_ai_judged_stay_out(self):
        jobs = [example(i) for i in range(3)]
        history = {jobs[0]["job_url"]: {"ai_judged": True},
                   jobs[1]["job_url"]: {"review_status": "applied"}}
        selected, summary = p.select_jobs({"evaluated_jobs": jobs}, history)
        self.assertEqual([j["job_url"] for j in selected], [jobs[2]["job_url"]])
        self.assertEqual(summary["already_judged_or_reviewed"], 2)

    def test_offline_judgment_preserves_observation_state(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "history.json"
            job = example(1)
            previous = {
                job["job_url"]: {"status": "not_seen_in_latest_run_status_unknown",
                                 "last_seen": "2026-10-01", "first_seen": "2026-09-01"},
                "https://example.test/other": {"status": "seen_in_feed_unverified_open"},
            }
            path.write_text(json.dumps(previous), encoding="utf-8")
            assessed = {**job, "assessment": {"decision": "Review"}}
            self.assertEqual(p.mark_ai_judged_only(path, [assessed], "2026-10-16"), 1)
            current = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(current[job["job_url"]]["last_seen"], "2026-10-01")
            self.assertEqual(current[job["job_url"]]["status"], previous[job["job_url"]]["status"])
            self.assertTrue(current[job["job_url"]]["ai_judged"])
            self.assertEqual(current["https://example.test/other"], previous["https://example.test/other"])

    def test_failed_gemini_request_is_diagnostic_and_safe(self):
        from personal_evaluation import Evaluator, safe_failure_details
        class BadModels:
            def generate_content(self, **kwargs):
                raise RuntimeError("429 quota exceeded for API key AIzaTESTKEYCANARY123456")
        class BadClient:
            models = BadModels()
        class EmptyCache:
            def get(self, job, fingerprint): return None
            def put(self, job, fingerprint, result):
                self.fail("Failed batch must never write cache")
        with patch.dict("os.environ", {"GEMINI_API_KEY": "AIzaTESTKEYCANARY123456"}):
            evaluator = Evaluator("verified CV evidence", EmptyCache(),
                                  max_calls=1, client=BadClient())
            jobs, stats = evaluator.evaluate([example(1)])
        self.assertEqual(jobs, [])
        self.assertEqual(stats["gemini_calls"], 1)
        self.assertEqual(stats["failed_batches"], 1)
        self.assertEqual(stats["failure_details"][0]["stage"], "request")
        self.assertEqual(stats["failure_details"][0]["batch_size"], 1)
        self.assertNotIn("AIzaTESTKEYCANARY123456",
                         stats["failure_details"][0]["message"])
        self.assertIn("[REDACTED_API_KEY]", stats["failure_details"][0]["message"])

    def test_preview_does_not_write_or_use_gemini(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "source.json"
            src.write_text(json.dumps({"evaluated_jobs": [example(1)]}), encoding="utf-8")
            result = p.run(src, root / "missing-history.json", root / "output.json")
            self.assertTrue(result["preview"])
            self.assertFalse((root / "output.json").exists())
            self.assertFalse((root / "missing-history.json").exists())
            with self.assertRaises(ValueError):
                p.run(src, root / "history.json", src)

    def test_evaluation_only_with_explicit_flag_and_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src, hist, out = root / "v4.json", root / "history.json", root / "out.json"
            src.write_text(json.dumps({"run_utc": "2026-10-16",
                                       "evaluated_jobs": [example(1)]}), encoding="utf-8")
            fake = types.ModuleType("personal_evaluation")
            fake.profile_text = lambda: "Verified CV evidence text"
            fake.PersonalCache = lambda: object()
            requested = []
            class FakeEvaluator:
                def __init__(self, profile, cache, max_calls):
                    self.assertion = max_calls
                def evaluate(self, jobs):
                    requested.append(len(jobs))
                    return ([{**j, "assessment": {"decision": "Review"}} for j in jobs],
                            {"cache_hits": 0, "gemini_calls": 1, "failed_batches": 0})
            fake.Evaluator = FakeEvaluator
            with patch.dict(sys.modules, {"personal_evaluation": fake}), patch.dict(
                "os.environ", {"GEMINI_API_KEY": "test-only", "PERSONAL_GEMINI_FREE_TIER_CONFIRMED": "YES"}
            ):
                first = p.run(src, hist, out, evaluate=True)
                second = p.run(src, hist, out, evaluate=True)
            self.assertEqual(requested, [1])
            self.assertEqual(first["evaluation"]["gemini_calls"], 1)
            self.assertEqual(second["gemini_calls"], 0)
            self.assertEqual(len(json.loads(out.read_text())["evaluated_jobs"]), 1)
            self.assertTrue(json.loads(hist.read_text())[example(1)["job_url"]]["ai_judged"])


if __name__ == "__main__":
    unittest.main()
