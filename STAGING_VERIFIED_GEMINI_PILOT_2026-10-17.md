# Expanded RAY — local staging verified, optional one-batch Gemini pilot

Date: 2026-10-17. Experimental branch: `experiment/ray-provider-coverage-audit`. Production master and scheduled RAY untouched. JobSpy parked.

## Verified user's PC and staging results

User ran `python -m unittest discover ...`: **125/125 passed**.

User ran `personal_discovery.py --publish-manual-report .\personal_run_stage_01.json`:
`{'manual_added': 134, 'manual_updated': 0}`.

Independent connected Google Sheet read confirmed in [Expanded RAY Staging](https://docs.google.com/spreadsheets/d/19VFagJwpHrW_d18FEGEQDGJ2noSR3vM8NqX3aAaMxYI/edit):

- `Manual Review`: 134 data rows, 134 distinct URLs, all with `Review Status=New` and `AI Status=Not AI evaluated — manual triage`.
- `Evaluations`: 28 existing master-copy records preserved; 0 URL overlap with Manual Review.
- New tab 18-column header correct, all original eight tabs still present.
- No Gemini or provider calls were used for this publication.

## Extra code committed after this verification

New controlled CLI:
```powershell
cd "$env:USERPROFILE\Desktop\ai-automation-case-study\ray-provider-audit"
git pull --ff-only
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
.\.venv\Scripts\python.exe personal_discovery.py --evaluate-report .\personal_run_stage_01.json
```

**This last command is not yet executed on user PC.** It is deliberately separate from regular `--live` and `--write-sheet`.

- No job API GETs or new collection.
- Re-screens frozen collect-only jobs using updated calibration, keeping original manual-only designations out of Gemini.
- Reads staging `Evaluations` first, prevents previously scored or terminal-review URLs from being sent to Gemini.
- Requires explicit `PERSONAL_GEMINI_FREE_TIER_CONFIRMED=YES`, valid `GEMINI_API_KEY` and local private profile.
- Hardcoded **1 Gemini request maximum** (up to 5 jobs), even when local `PERSONAL_MAX_GEMINI_CALLS` is higher.
- Only successful scored jobs are published to isolated staging's `Evaluations`; leaves `Manual Review` untouched.
- Results report: `personal_run_stage_01_gemini_pilot.json`. No local provider-history changes.
- On Gemini failure, no results published; error details captured and output report still created.
- Production Personal Ray Sheet ID `160oMgKCoAVnqaBVsPL624kwkGOOZ1Lw8n2bvhRkbitQ` remains an explicit write-denied target on this branch.

Final test suite for this new command: **127 tests passed**, GitHub Actions:
https://github.com/QayZie96/ai-job-outreach-automation/actions/runs/39028624172

## Decision gates before production promotion

1. One-batch pilot must complete on PC, review assessment suitability, compare already-assessed URL exclusions; no repeated/Gemini waste.
2. Validate optional new feeds and international Adzuna in bounded collect-only configurations, only where needed.
3. Agree final single `Evaluations` daily-view integration for manual-only leads without losing human statuses.
4. Review diff against original, preserve original local history/cache/production `.env` and scheduler, and keep rollback. Never merge automatically based solely on offline tests.

