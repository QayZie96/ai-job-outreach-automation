# Expanded Personal RAY — Controlled Cutover Checklist

Release candidate branch: `release/expanded-ray-unified-evaluations`.
Base runtime: `feature/ray-personal-job-discovery`.
**Do not merge, deploy, run Gemini, switch the scheduler or overwrite the existing production workbook without a separately authorized cutover.**

## 1. Canonical destination decision

The user explicitly wants one daily job-review workbook. At cutover the intended canonical workbook is the existing **Personal Ray — Expanded RAY Staging**, spreadsheet ID `19VFagJwpHrW_d18FEGEQDGJ2noSR3vM8NqX3aAaMxYI`; once activated it may be renamed to "Personal Ray — Expanded" with user confirmation.

The original production Personal Ray, spreadsheet ID `160oMgKCoAVnqaBVsPL624kwkGOOZ1Lw8n2bvhRkbitQ`, remains an unchanged backup, **not a second daily destination**. GitHub code has an explicit fail-closed guard against writing to that original ID.

Do not confuse the user's uploaded XLSX snapshot with the live native Google Sheet. Native sheet connector metadata and reads were used to verify current values.

## 2. Data reconciliation completed 2026-10-17

- Original `Evaluations`: 28 postings; staging: 167 postings.
- **All 28 original postings present in staging, with identical values in all 27 columns.**
- Additional 5 scored Gemini pilot postings in staging (not duplicated).
- Additional 134 archived manual-only postings, each marked `Backlog`, `Decision=Manual Review`, blank `AI Fit Score` / `AI Reviewed At`; these do not crowd fresh `Review Queue`.
- `Manual Review` archive tab preserved in staging; **do not delete**.
- The native view `Review Queue` includes new `Manual Review`/`Untriaged` leads alongside AI `Review` results; legacy `Backlog` excluded from the normal daily view.
- Some historical scores and backlog posts predate the language hard gate. Preserve, but do not assume they were revalidated under new criteria.

**At cutover repeat a quick live 28-row equality check and resolve any newer human edits in the original before switching sources.** Do not blindly overwrite staging notes/status.

## 3. Runtime and provider configuration for eventual approved daily run

| Provider | Maximum HTTP requests/run |
|---|---:|
| Arbeitnow | 4 |
| Remotive | 1 |
| Himalayas | 17 |
| Jobicy | 3 |
| Remote OK | 1 |
| We Work Remotely | 1 |
| RemoteJobs.org | 1 |
| Adzuna | 0 |
| **Total** | **28** |

Retain RemoteJobs.org even if some days have zero viable leads, per user's explicit request. Adzuna remains a manually opted-in experiment because public API descriptions are excerpts. JobSpy remains separately parked.

Language: confidently non-English/non-Greek posting is **hard-excluded** as `posting_language_excluded`; mixed, short or low-confidence text retained for conventional screening. Source location is not a language proxy.

Gemini remains budgeted (default 5 calls/run and capped candidate pool) and must not run until `PERSONAL_GEMINI_FREE_TIER_CONFIRMED=YES` **after confirming there is no billing**.

## 4. Local-only items that are NOT in GitHub

Before cutover, reconcile/copy these from the current production and experimental PC worktrees to the eventual active runtime **locally and safely**, after making a backup:

- Git-ignored `.env`: set `PERSONAL_GOOGLE_SHEET_ID` to the intended expanded workbook; never to the original. Preserve credentials privately.
- `profiles/personal_profile.local.txt`: private profile required for matching (can use an absolute `PERSONAL_PROFILE_PATH`).
- `validation_cache.db`: SQLite Gemini assessment cache; preserve original with backup and do not overwrite a newer store.
- `personal_discovery_history.local.json` (where present, including report-path-specific copies): retain review and already-judged decisions; avoid overwriting a newer version with older history.
- Windows 09:00 local scheduled task command/working directory: **not connected to GitHub**. Verify actual task invocation; activate only one daily scheduler target. Do not assume a Git branch merge alters the Windows task.
- Past local report JSON and screening audits for traceability.

The staging spreadsheet protects previously scored URLs and terminal user decisions, independently of local cache; nevertheless history/cache migration is worth checking to avoid redundant work. Never commit secrets, private profiles, reports or SQLite data.

## 5. Release checks

Only runtime files, tests and one offline CI workflow were selected from the experimental branch; broader provider research/probes and 100+ exploratory commits were deliberately excluded.

Release CI: https://github.com/QayZie96/ai-job-outreach-automation/actions/runs/39067077653 — **153 offline tests passed** with optional feeds enabled in process environment; no provider, Gemini or Sheet calls.

Do a local read-only configuration/history sanity check and final smoke test, ideally without another full collection. Keep `--live --write-sheet` and the 09:00 schedule disabled until approval. No changes to original production branch or original workbook have been made in preparing this release.

## 6. Rollback

If a first approved scheduled run fails: disable its scheduler task; do not reactivate a second task concurrently. Inspect the error and append history. Keep the original workbook intact as immutable rollback reference. Since the new writer is URL-idempotent and manual rows are insert-only, rerun only after cause is known; preserve all human statuses and existing AI scores.
