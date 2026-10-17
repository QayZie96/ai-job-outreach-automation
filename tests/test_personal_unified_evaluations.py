"""Unified Evaluations writer: staged-only, no provider or Gemini network tests."""
import unittest
from unittest.mock import MagicMock, patch

import personal_sheets as s


def manual(url="https://example.com/jobs/1", **changes):
    return {
        "job_url": url, "job_title": "Marketplace Operations Specialist",
        "company_name": "Shop", "location": "Worldwide",
        "remote": True, "source": "Himalayas", "source_job_id": "1",
        "created_at": "2026-10-17", "priority": 73,
        "precheck_reason": "Worldwide remote; hiring unverified",
        "precheck_eligibility": "uncertain",
        "role_evidence_reason": "target role in title",
        "review_only": True, **changes,
    }


def row_with_url(url, score=""):
    fields = [""] * len(s.SHEET_HEADERS)
    fields[s.SHEET_HEADERS.index("Job URL")] = url
    fields[s.SHEET_HEADERS.index("AI Fit Score")] = score
    return fields


class UnifiedEvaluationsTests(unittest.TestCase):
    def test_manual_row_has_no_fake_ai_score_or_date(self):
        fields = dict(zip(s.SHEET_HEADERS, s._manual_to_evaluation_row(manual(), today="2026-10-17")))
        self.assertEqual(fields["AI Fit Score"], "")
        self.assertEqual(fields["AI Reviewed At"], "")
        self.assertEqual(fields["Decision"], "Manual Review")
        self.assertEqual(fields["Application Priority"], "Untriaged")
        self.assertEqual(fields["Verification State"], "Not AI evaluated — manual verification required")
        self.assertEqual(fields["Review Status"], "New")
        self.assertEqual(fields["Priority Rank"], "")

    def test_archive_preserves_human_decision_and_notes(self):
        fields = dict(zip(s.SHEET_HEADERS, s._manual_to_evaluation_row(
            manual(_archive={
                "Vacancy ID": "RAY-EXISTING",
                "Review Status": "Applied",
                "Notes": "I submitted my CV",
                "Last Seen": "2026-10-10",
                "Work Arrangement": "EU relocation review",
            }), backlog=True, today="2026-10-17")))
        self.assertEqual(fields["Application Priority"], "Backlog")
        self.assertEqual(fields["Review Status"], "Applied")
        self.assertEqual(fields["Notes"], "I submitted my CV")
        self.assertEqual(fields["Vacancy ID"], "RAY-EXISTING")
        self.assertEqual(fields["Checked"], "2026-10-10")
        self.assertEqual(fields["AI Reviewed At"], "")

    def test_unified_manual_writer_skips_existing_scored_and_duplicate_urls(self):
        svc = MagicMock()
        values = svc.spreadsheets.return_value.values.return_value
        values.get.return_value.execute.return_value = {
            "values": [row_with_url("https://example.com/jobs/1", 93)]
        }
        values.append.return_value.execute.return_value = {
            "updates": {"updatedRange": "'Evaluations'!A35:AA35"}
        }
        with patch.object(s, "_extend_evaluations_table") as extend:
            result = s._write_evaluations_manual(svc, "STAGING", [
                manual("https://example.com/jobs/1"),
                manual("https://example.com/jobs/2"),
                manual("https://example.com/jobs/2?utm_source=feed"),
            ])
        self.assertEqual(result, {"manual_added": 1, "manual_updated": 0})
        rows = values.append.call_args.kwargs["body"]["values"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][s.SHEET_HEADERS.index("AI Fit Score")], "")
        self.assertEqual(rows[0][s.SHEET_HEADERS.index("Job URL")], "https://example.com/jobs/2")
        values.batchUpdate.assert_called_once()
        extend.assert_called_once_with(svc, "STAGING", 35)

    def test_no_manual_write_to_existing_rows(self):
        svc = MagicMock()
        values = svc.spreadsheets.return_value.values.return_value
        values.get.return_value.execute.return_value = {
            "values": [row_with_url("https://example.com/jobs/1", "0")]
        }
        result = s._write_evaluations_manual(svc, "STAGING", [manual()])
        self.assertEqual(result["manual_added"], 0)
        values.append.assert_not_called()
        values.batchUpdate.assert_not_called()

    def test_archive_migration_is_read_only_by_default(self):
        svc = MagicMock()
        values = svc.spreadsheets.return_value.values.return_value
        archive = [""] * len(s.MANUAL_HEADERS)
        archive[s.MANUAL_HEADERS.index("Job URL")] = "https://example.com/jobs/3"
        archive[s.MANUAL_HEADERS.index("Review Status")] = "New"
        values.get.return_value.execute.side_effect = [
            {"values": [s.MANUAL_HEADERS, archive]},
            {"values": [s.SHEET_HEADERS, row_with_url("https://example.com/jobs/1", "75")]},
        ]
        with (patch.object(s, "verify_spreadsheet_destination",
                           return_value="STAGING"),
              patch.object(s, "_service", return_value=svc),
              patch.object(s, "_setup") as setup,
              patch.object(s, "_write_evaluations_manual") as write):
            result = s.migrate_manual_archive_to_evaluations()
        self.assertEqual(result["backlog_to_add"], 1)
        self.assertEqual(result["existing_evaluations"], 1)
        self.assertEqual(result["mode"], "dry_run")
        setup.assert_not_called()
        write.assert_not_called()

    def test_review_queue_formula_supports_untriaged_manual_not_backlog(self):
        q = s.VIEW_QUERIES["Review Queue"]
        self.assertIn("Col10 = 'Manual Review'", q)
        self.assertIn("Col8 = 'Untriaged'", q)
        self.assertIn("Col10 = 'Review'", q)


if __name__ == "__main__":
    unittest.main()
