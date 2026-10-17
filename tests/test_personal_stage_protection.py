"""Focused safeguards for expanded RAY before any Gemini/staging publication.

All tests are offline: no provider API, Gemini, or Google Sheet mutations.
"""
import unittest
from unittest.mock import MagicMock, patch

import personal_discovery as d
import personal_screening_v41 as screening
import personal_sheets as sheet


def job(title, description="", **changes):
    base = {
        "source": "Himalayas",
        "source_job_id": "sample-1",
        "job_title": title,
        "company_name": "Sample employer",
        "location": "Worldwide",
        "remote": True,
        "location_restrictions": [],
        "timezone_restrictions": [],
        "job_description": description,
        "job_url": "https://example.com/jobs/sample-1",
        "created_at": "2026-10-17",
        "seniority": [],
        "salary": "",
        "job_types": [],
    }
    return {**base, **changes}


class CalibrationTests(unittest.TestCase):
    def test_sewing_specialist_goes_manual_not_gemini(self):
        row = job(
            "Customer Support & Sales Agent (Sewing Specialist) | E-commerce | Remote",
            "Our online store requires hands-on experience with sewing. "
            "You must be able to discuss stitches and patterns. Hiring in Greece.",
        )
        kept, stats, _ = d.screen_candidates([row])
        self.assertEqual(len(kept), 1)
        self.assertTrue(kept[0]["review_only"])
        self.assertIn("sewing_specialist_experience_unverified", kept[0]["fit_flags"])
        self.assertEqual(kept[0]["precheck_eligibility"], "eligible")

    def test_specific_amazon_seller_expertise_remains_reviewable(self):
        row = job(
            "Amazon Marketplace Manager",
            "Deep understanding of Amazon Seller Central, FBA, A+ Content, "
            "Amazon Advertising and catalogue optimization. Worldwide remote.",
        )
        kept, _, _ = d.screen_candidates([row])
        self.assertEqual(len(kept), 1)
        self.assertTrue(kept[0]["review_only"])
        self.assertIn("amazon_seller_central_expertise_unverified", kept[0]["fit_flags"])

    def test_senior_pricing_lead_goes_manual(self):
        row = job(
            "Senior Product Manager, Pricing & Revenue",
            "Drive marketplace pricing operations and reporting.",
        )
        kept, _, _ = d.screen_candidates([row])
        self.assertEqual(len(kept), 1)
        self.assertTrue(kept[0]["review_only"])
        self.assertIn("advanced_role_seniority_review", kept[0]["fit_flags"])

    def test_armenian_translation_requirements_are_not_gemini_candidates(self):
        row = job(
            "English to Armenian Review Lead for UI, Marketing & Product Content",
            "A linguist fluent in Armenian must review product content and localization.",
        )
        self.assertEqual(
            screening.calibrated_factors(row["job_title"], row["job_description"])["hard_exclusion"],
            "mandatory_language",
        )
        kept, _, _ = d.screen_candidates([row])
        self.assertEqual(kept, [])

    def test_german_b2_requirement_excluded_with_evidence(self):
        row = job(
            "Customer Success Renewals Representative with German",
            "Manage marketplace renewals and customer relationships. "
            "Speak English and German fluently (B2 min.) to support our clients.",
        )
        self.assertEqual(
            screening.mandatory_language(row["job_title"], row["job_description"]), "German"
        )
        kept, stats, _ = d.screen_candidates([row])
        self.assertEqual(kept, [])
        self.assertEqual(stats["mandatory_language_excluded"], 1)

    def test_optional_german_not_excluded(self):
        self.assertIsNone(screening.mandatory_language(
            "Customer Success Specialist",
            "Handle global renewals and customer queries. German is preferred but not required."
        ))

    def test_security_or_creative_ad_roles_outside_target_search(self):
        for title in ("Security Operations Analyst- Ireland",
                      "Ads Creative Strategist - E-commerce Marketing Agency"):
            with self.subTest(title=title):
                kept, counts, _ = d.screen_candidates([
                    job(title, "Coordinate campaigns, business operations, pricing and client deliverables.")
                ])
                self.assertEqual(kept, [])
                self.assertEqual(counts["role_out_of_scope"], 1)

    def test_regular_ops_remains_candidate(self):
        kept, _, _ = d.screen_candidates([
            job("Marketplace Operations Specialist",
                "Manage product listings, supplier processes and Excel reporting.")
        ])
        self.assertEqual(len(kept), 1)
        self.assertFalse(kept[0]["review_only"])


class ExistingSheetProtectionTests(unittest.TestCase):
    def test_experiment_refuses_production_personal_ray_sheet(self):
        with patch.dict("os.environ", {
            "PERSONAL_GOOGLE_SHEET_ID": sheet.MASTER_PERSONAL_RAY_SHEET_ID,
            "GOOGLE_SHEET_ID": "SOME-OTHER-DEMO-SHEET",
        }):
            with self.assertRaisesRegex(ValueError, "production Personal Ray master"):
                sheet.verify_spreadsheet_destination()

    def test_read_only_reconcile_existing_evaluations(self):
        h = sheet.SHEET_HEADERS
        def tabrow(url, score="", status="New"):
            row = [""] * len(h)
            row[h.index("Job URL")] = url
            row[h.index("AI Fit Score")] = score
            row[h.index("Review Status")] = status
            return row
        base = "https://example.com/jobs"
        data = [
            tabrow(base + "/assessed?utm_source=jobs", 75),
            tabrow(base + "/zero-score", 0),
            tabrow(base + "/applied", "", "Applied"),
            tabrow(base + "/dismissed", "", "Dismissed"),
            tabrow(base + "/unscored", "", "New"),
        ]
        svc = MagicMock()
        svc.spreadsheets.return_value.values.return_value.get.return_value.execute.return_value = {
            "values": data
        }
        with patch.object(sheet, "verify_spreadsheet_destination", return_value="STAGING-ONLY-ID"):
            with patch.object(sheet, "_service", return_value=svc):
                result = sheet.read_existing_evaluations()
        self.assertEqual(len(result["existing_urls"]), 5)
        self.assertEqual(len(result["scored_urls"]), 2)
        self.assertIn(base + "/assessed", result["scored_urls"])
        self.assertIn(base + "/zero-score", result["scored_urls"])
        self.assertEqual(len(result["terminal_urls"]), 2)
        self.assertNotIn(base + "/unscored", result["terminal_urls"])
        kwargs = svc.spreadsheets.return_value.values.return_value.get.call_args.kwargs
        self.assertEqual(kwargs["range"], "'Evaluations'!A2:AA")
        self.assertEqual(kwargs["spreadsheetId"], "STAGING-ONLY-ID")
        svc.spreadsheets.return_value.values.return_value.batchUpdate.assert_not_called()
        svc.spreadsheets.return_value.values.return_value.append.assert_not_called()

    def test_publish_offline_manual_report_without_ai_or_network(self):
        import json
        from pathlib import Path
        from tempfile import TemporaryDirectory
        source = job(
            "Senior Marketplace Operations Manager",
            "Lead complex marketplace operations and vendor processes.",
            review_only=True, precheck_reason="EU relocation required",
            precheck_eligibility="uncertain",
            priority=40,
            role_evidence_reason="target role in title",
        )
        with TemporaryDirectory() as folder:
            report = Path(folder) / "collected.json"
            report.write_text(json.dumps({
                "evaluation": {"ai_shortlist_count": 0},
                "decisions": {},
                "evaluated_jobs": [source],
            }), encoding="utf-8")
            mock_service = MagicMock()
            with patch.object(sheet, "verify_spreadsheet_destination",
                              return_value="ISOLATED-STAGING-ID"):
                with patch.object(sheet, "read_existing_evaluations",
                                  return_value={"existing_urls": set()}):
                    with patch.object(sheet, "_service", return_value=mock_service):
                        with patch.object(sheet, "_setup") as setup:
                            with patch.object(sheet, "_write_manual_review",
                                              return_value={"manual_added": 1,
                                                            "manual_updated": 0}) as writer:
                                result = sheet.publish_manual_only_from_report(report)
            self.assertEqual(result["manual_added"], 1)
            setup.assert_called_once_with(mock_service, "ISOLATED-STAGING-ID")
            writer.assert_called_once_with(
                mock_service, "ISOLATED-STAGING-ID", [source]
            )

    def test_publishing_offline_report_does_not_duplicate_existing_evaluations(self):
        import json
        from pathlib import Path
        from tempfile import TemporaryDirectory
        source = job("Marketplace Operations Specialist", review_only=True)
        with TemporaryDirectory() as folder:
            report = Path(folder) / "collect.json"
            report.write_text(json.dumps({
                "evaluation": {}, "evaluated_jobs": [source],
            }), encoding="utf-8")
            with patch.object(sheet, "verify_spreadsheet_destination",
                              return_value="ISOLATED-STAGING-ID"):
                with patch.object(sheet, "read_existing_evaluations",
                                  return_value={"existing_urls": {source["job_url"]}}):
                    with patch.object(sheet, "_service", return_value=MagicMock()):
                        with patch.object(sheet, "_setup"):
                            with patch.object(sheet, "_write_manual_review",
                                              return_value={"manual_added": 0, "manual_updated": 0}) as writer:
                                sheet.publish_manual_only_from_report(report)
            self.assertEqual(writer.call_args.args[2], [])

    def test_manual_only_rejects_assessment_report(self):
        import json
        from pathlib import Path
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as folder:
            report = Path(folder) / "assessed.json"
            report.write_text(json.dumps({
                "evaluation": {},
                "evaluated_jobs": [dict(job("Ops"), assessment={"fit_score": 70})],
            }), encoding="utf-8")
            with patch.object(sheet, "_service") as service:
                with self.assertRaisesRegex(ValueError, "Refusing AI-assessment report"):
                    sheet.publish_manual_only_from_report(report)
                service.assert_not_called()

    def test_run_excludes_existing_staging_score_from_gemini_shortlist(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        previously_scored = job("Marketplace Operations Specialist",
                                "Manage marketplace listings and supplier processes.")
        newly_discovered = job(
            "Ecommerce Inventory Coordinator",
            "Manage online inventory data, supplier processes and Excel reporting.",
            source_job_id="sample-2",
            job_url="https://example.com/jobs/sample-2",
        )
        with TemporaryDirectory() as folder:
            with patch.dict("os.environ", {
                "PERSONAL_GEMINI_FREE_TIER_CONFIRMED": "YES",
                "PERSONAL_MAX_AI_CANDIDATES": "40",
            }):
                with patch.object(d, "profile_text", return_value="Verified profile"):
                    with patch.object(d, "collect", return_value=(
                        [previously_scored, newly_discovered], {}, []
                    )):
                        with patch.object(
                            sheet, "read_existing_evaluations", return_value={
                                "existing_urls": {previously_scored["job_url"]},
                                "scored_urls": {previously_scored["job_url"]},
                                "terminal_urls": set(),
                            }
                        ):
                            with patch.object(
                                sheet, "verify_spreadsheet_destination",
                                return_value="STAGING-SHEET-ID"
                            ):
                                with patch.object(d, "Evaluator") as evaluator:
                                    evaluator.return_value.evaluate.return_value = (
                                        [], {"gemini_calls": 0, "cache_hits": 0}
                                    )
                                    with patch.object(
                                        sheet, "write_personal_results",
                                        return_value={"added": 0, "updated": 0,
                                                      "manual_added": 0, "manual_updated": 0}
                                    ):
                                        _, metrics = d.run(
                                            write_sheet=True,
                                            report_path=str(Path(folder) / "stage.json"),
                                        )
        selected = evaluator.return_value.evaluate.call_args.args[0]
        self.assertEqual([j["job_url"] for j in selected],
                         [newly_discovered["job_url"]])
        self.assertEqual(metrics["candidates_protected_from_repeat_ai"], 1)
        self.assertEqual(metrics["staging_known_candidate_urls"], 1)

    def test_failed_sheet_read_is_not_silently_swallowed(self):
        svc = MagicMock()
        svc.spreadsheets.return_value.values.return_value.get.return_value.execute.side_effect = PermissionError(
            "staging sheet inaccessible"
        )
        with patch.object(sheet, "verify_spreadsheet_destination", return_value="STAGING-ONLY-ID"):
            with patch.object(sheet, "_service", return_value=svc):
                with self.assertRaisesRegex(PermissionError, "inaccessible"):
                    sheet.read_existing_evaluations()


if __name__ == "__main__":
    unittest.main()
