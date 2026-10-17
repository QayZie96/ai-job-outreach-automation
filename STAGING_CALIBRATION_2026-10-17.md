# Expanded RAY — staging calibration checkpoint (2026-10-17)

**ONLY experimental branch `experiment/ray-provider-coverage-audit`. Production RAY, its 09:00 scheduler, master Sheet, Gemini quotas and JobSpy remain untouched.**

## Source observation: user's first PC collection

- 25/25 HTTP attempts successful: Arbeitnow 4, Remotive 1, Himalayas 17, Jobicy 3.
- 1,723 deduplicated job URLs; 189 deterministic survivors (42 initial Gemini candidates, 147 manual-review-only).
- 40 originally selected for Gemini, but there were zero actual Gemini calls because this was `--collect-only`.
- All three other free feeds and Adzuna remained disabled (0); no web traffic to them.
- 41/42 candidates had geographically uncertain eligibility. Do not equate provider country labels or remote flags with an employer's hireability from Greece.
- The staging workbook was copied from the production Personal Ray workbook: https://docs.google.com/spreadsheets/d/19VFagJwpHrW_d18FEGEQDGJ2noSR3vM8NqX3aAaMxYI/edit ; ID `19VFagJwpHrW_d18FEGEQDGJ2noSR3vM8NqX3aAaMxYI`. It contains 28 pre-existing assessed vacancies and their human-review state. The Google service account was verified as an Editor.

## Changes already committed in experiment

### Screening (precision, no broad threshold lowering)

- Obvious security operations analysts and advertising creative strategist titles are excluded from non-target professions.
- Explicit translation/localization titles (e.g., English to Armenian) are excluded for unsupported languages.
- "With German" titles requiring fluent/B2 German are excluded; optional German is not.
- Senior roles, sewing-specialist customer support and Amazon-specific Seller Central expertise remain available for **manual review**, not auto-selected for Gemini; they are not silently discarded.
- Added focused adversarial regression tests for these examples.

The relevant frozen-audit headline remains **42 original candidates / 147 review-only**. A new full offline replay is necessary to measure the final count; do not present the count as measured without running the updated screener.

### Protect existing assessment history (especially on staging)

- When `--write-sheet` is used, RAY first reads the destination staging `Evaluations` table **read-only**, before any Gemini expense.
- Pre-existing AI-scored URLs and terminal human decisions are excluded from the AI shortlist. A legitimate score of 0 also counts as assessed. This avoids wasting Gemini calls on historical scores already present in the copied master spreadsheet when the experiment's local cache/history is empty.
- The tool fails closed on Sheet read failure; this protects against expensive re-evaluation if staging access breaks.
- Added report metrics `staging_scored_urls`, `staging_terminal_urls`, `candidates_protected_from_repeat_ai`, `staging_known_candidate_urls`.
- No history/cache merge or production state mutation performed.

### Manual-review Sheet validation *without provider or Gemini calls*

New command:
```powershell
cd "$env:USERPROFILE\Desktop\ai-automation-case-study\ray-provider-audit"
git pull --ff-only
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_*.py'
.\.venv\Scripts\python.exe personal_discovery.py --publish-manual-report .\personal_run_stage_01.json
```

This command takes the user's already-collected report, verifies `PERSONAL_GOOGLE_SHEET_ID`, reads existing `Evaluations` URLs to prevent duplicating assessed master leads, initializes any missing required Sheet tabs, and **only upserts review-only jobs** into the separate `Manual Review` tab (retaining human notes/status by URL). It does **not** fetch new vacancies, call Gemini, or write `Evaluations` rows. A second invocation must not append duplicate Manual Review URLs.

Ensure the experimental `.env` sets `PERSONAL_GOOGLE_SHEET_ID=19VFagJwpHrW_d18FEGEQDGJ2noSR3vM8NqX3aAaMxYI` and that `credentials/google-service-account.json` is present. **Do not run full `--write-sheet` yet.**

## Pending checks before merger

1. Verify manual publication on staging: expected positive manual rows; no duplicated URLs from pre-existing Evaluations; repeat command idempotent; no changes in master workbook.
2. Run offline rescreen of the frozen 189 survivors, review high-priority *new* eligible opportunities and false positives; user-provided CSV can be replayed offline without another API call.
3. Permit at most **one Gemini batch** on isolated staging after confirming free-tier/billing and profile/credentials, and check historic-scored URL skipping.
4. Try extra feeds / Adzuna in separate collect-only tests once base validated.
5. Decide whether to unify manual and AI rows in one Evaluations table for daily review. Currently the Manual Review tab is still separate; no claim of one-screen experience until that workflow is verified.
6. Only then promote reviewed diffs, preserve production local `.env`, history, cache and user decisions, and test the scheduler with rollback.

## Test evidence

- 120 passed: https://github.com/QayZie96/ai-job-outreach-automation/actions/runs/39027452675
- 123 passed: https://github.com/QayZie96/ai-job-outreach-automation/actions/runs/39027744124
- New stage publishing dedup rerun: https://github.com/QayZie96/ai-job-outreach-automation/actions/runs/39027861827 (verify final conclusion independently).

