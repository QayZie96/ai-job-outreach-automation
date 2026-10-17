# Unified Evaluations — experimental milestone (2026-10-17)

## Completed and verified
- Implemented insert-only manual-review rows in authoritative 27-column `Evaluations` for future new leads, with blank `AI Fit Score`, blank `AI Reviewed At`, `Decision=Manual Review`, and `Application Priority=Untriaged`. Existing scored rows and user statuses/notes are never overwritten by this manual path.
- `Review Queue` view includes `Decision=Review` or `Decision=Manual Review and Application Priority=Untriaged`. Historical `Backlog` rows do not crowd daily `Review Queue` and `New Leads`.
- Old `Manual Review` is an unchanged historical archive, not the target for new writes.
- Added `personal_unify_sheet.py` dry-run-first staging-only migration CLI and `migrate_manual_archive_to_evaluations`. Source/target headers are checked; canonical URL matching prevents repeat insertion. The CLI default does not write; `--apply` explicitly allows staging migration.
- 62 config-stress tests and 170 full tests passed: https://github.com/QayZie96/ai-job-outreach-automation/actions/runs/39066219110.

## Staging workbook applied directly using connected Google Sheets API
Staging spreadsheet ID `19VFagJwpHrW_d18FEGEQDGJ2noSR3vM8NqX3aAaMxYI`; production ID `160oMgKCoAVnqaBVsPL624kwkGOOZ1Lw8n2bvhRkbitQ` was **not accessed for mutation**.

Before: 33 scored/AI pilot Evaluations rows + 134 separate Manual Review rows. Verified no URL overlap and stable headers.
- Copied 134 archive entries into `Evaluations!A35:AA168` using 6 atomic batch requests (four blocks + two Review Queue formulas). Recorded all 134 as `Backlog`, `Manual Review`, blank AI score/date, `Not AI evaluated — manual verification required`.
- Preserved 33 preexisting Evaluations rows, scoring, priority, notes and statuses, and the 134-row historical Manual Review tab.
- Verified first new row 35 and last row 168 with displayed values, blank scores, Backlog marker, matching URLs, and View formulas.
- No provider calls, Gemini calls, scheduler activation, production workbook writes, or source deletion.
- Original archive includes some postings screened before the new language gate. **Do not silently certify the archived backlog as currently relevant or supported-language.** It is a preserved historical set, not a fresh current shortlist. New runs respect language hard exclusions.
- Google Sheets metadata didn't expose a native table in Evaluations via the connected metadata read; routine writer has a guarded optional table extender. Verify any native table range when full production migration is separately authorized.

## Remaining before production merge
1. Verify a new manual-only posting through the experimental writer (mock tests already passed); live collection/AI call not necessary for first check.
2. Reconcile production Personal RAY scored rows/cache and terminal human decisions, preserve originals.
3. Review the proposed provider max budgets: Arbeitnow 4, Remotive 1, Himalayas 17, Jobicy 3, Remote OK 1, We Work Remotely 1, RemoteJobs.org 1, Adzuna 0; no JobSpy changes.
4. Separately authorize and verify controlled production merge and scheduling; no automatic activation from staging work.
