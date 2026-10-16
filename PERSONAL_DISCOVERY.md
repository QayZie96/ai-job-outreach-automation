# RAY personal job discovery — isolated, manual first

This adds **personal job discovery** to the original RAY case-study repository. It does **not** change `main.py`, `validator.py`, `sheets.py`, `outreach.py`, the original RAY prompt, existing RAY Google Sheet, or scheduled launcher. It **never** generates outreach or sends applications. The `JobSpy` experiment is not included in this first stage and must remain a separate branch.

## Decisions and defaults

- Existing feeds: Arbeitnow (max **2** HTTP attempts), Remotive (**1**), original **UK-only** Adzuna (**0**, disabled because unsuitable for most Greece/EU targets).
- New official feeds: Himalayas targeted Greece-country searches (**4** HTTP attempts); Jobicy two bounded queries (**2** attempts). Responses are deduplicated by URL and source ID; no company/title-only collapse.
- Mandatory live flags. No automation/scheduler installed.
- Existing `validation_cache.db` table reused with namespaced personal keys, not a separate database. Fingerprint covers profile text, job details, prompt, model, and schema. Historic RAY cached values remain separate.
- Existing provider field mappings are mirrored in the isolated personal collector to avoid importing the RAY Gemini-initializing runtime. Original flow unchanged.
- **Balanced, auditable deterministic screening** retains strong target roles and plausible adjacent/generalist operational work. A low-evidence or executive-seniority role enters **manual review only** and cannot consume Gemini calls. Only clearly unrelated professions, explicit incompatible geography and evidence-backed mandatory language restrictions are rejected. The screen is for **recall**, not a fit-score substitute.
- Remote Greece eligibility and EU hybrid/on-site relocation are assessed separately; unknown jurisdiction remains **uncertain/Review**, never Strong Match merely because of an AI score. The prioritizer ranks evidence-rich candidates, diversifies sources, and selects up to **40 jobs** for Gemini (`PERSONAL_MAX_AI_CANDIDATES`, max 100). It never pads that cap with exploratory-only postings.
- Every unique job that reaches the deterministic screen gets one row in **`personal_run_screening_audit.csv`**, including title, source, URL, role evidence, geography/language result, rejection reason, manual-review-only status, priority and whether selected for AI. The CSV is local, Git-ignored, and spreadsheet-formula-safe. The report points to it. **This does not include jobs discarded earlier because they lacked a valid URL or were duplicate postings.**
- One batched Gemini pass (20 jobs per request, max **5 requests**). The output includes a 0–100 *evidence fit score*, eligible/uncertain/ineligible assessment, short requirements, matched user evidence, posting evidence, gaps and reasons. Score is **not** likelihood of interview.
- Country/location conflicts, unresolved precheck eligibility and missing supporting evidence cannot become Strong Match. `Review` retains uncertainty rather than inventing eligibility. The model receives at most 4,000 characters of each job description per call, marked truncated as needed; check full posting manually before applying.
- Only completed Gemini assessments are cached in SQLite; pre-AI exclusions are recorded in the local audit CSV (not cached as AI evaluations). Local `personal_run.json` includes the scored batch when running AI, or the whole screened-in candidate pool including review-only entries in `--collect-only`. The Google Sheet has one authoritative `Evaluations` tab and two formula-driven tabs (`Strong Matches`, `Review Queue`), plus `Run Summary`. Human status/notes survive re-evaluation.

## Before live use

1. Use the existing Python environment and install the original `requirements.txt` if needed.
2. Create `profiles/personal_profile.local.txt` locally. Use verified facts from your current CVs, portfolio, and explicitly confirmed experience. Never claim unsupported years, credentials, managerial responsibilities, or technical skills. This file is ignored by Git. The short public RAY assistant profile is not sufficient for trustworthy personal-fit scoring.
3. Copy config values from `.env.personal.example` into your **existing local** `.env`. Keep current `GEMINI_API_KEY`, `GOOGLE_SHEET_ID`, and existing credentials private. **ChatGPT plan usage does not cover Gemini API billing.** Verify the key's quota, model access and billing arrangements independently. Only after verifying no charge will occur, set `PERSONAL_GEMINI_FREE_TIER_CONFIRMED=YES`.
4. Optionally create a **brand-new private Google spreadsheet**, share it with the existing service account email, and set `PERSONAL_GOOGLE_SHEET_ID` to its ID. The writer refuses to write if it matches `GOOGLE_SHEET_ID`, which belongs to the RAY case study. `--write-sheet` is never implied by `--live`.

## Commands (manual only)

```bash
# Small initial provider experiment: calls the job APIs, NO Gemini/Sheets calls.
python personal_discovery.py --live --collect-only

# Scoring run (requires local profile, Gemini API key and free-tier confirmation).
# Outputs local personal_run.json; does NOT write to Google Sheets.
python personal_discovery.py --live

# Later, only after you've created and approved the NEW personal destination:
python personal_discovery.py --live --write-sheet

# Run offline tests without making external calls:
python -m unittest discover -s tests -p 'test_personal_discovery.py' -v
```

Review `personal_run.json` for source attempts, source failures, precheck rejection counts, shortlist URLs, exploratory/manual-review-only counts, deferred-by-cap counts, candidates, cache hits, model calls, scores and reasons. For false-negative checks, examine the adjacent `personal_run_screening_audit.csv` and sort by `screen_outcome` (including `role_out_of_scope`, `mandatory_language_excluded`, and `geography_excluded`). The audit exists in both collect-only and AI modes. It is *not* a record of jobs without valid URLs or jobs deduplicated earlier. Precheck rejections never consume Gemini calls. An API listing tagged remote may in fact be an EU hybrid office role; read the employer description, not just the feed flag. All original-provider timestamps are converted to ISO calendar dates. This file may contain job descriptions and is ignored by Git. Make sure actual remote-jurisdiction eligibility and listing availability are independently confirmed before applying; original feed membership does **not** prove a vacancy is still open.

## Acceptance gates before scheduling or JobSpy

- Spot-check at least 10–20 records from the full-screen audit (especially `role_out_of_scope`, languages, eligibility uncertainty and `review_only`) **before** Gemini. For subsequent actual evaluations, review locations, mandatory requirements, experience evidence and possible false approvals.
- Compare new *eligible, unique Strong Matches* against your existing job alerts and Job Funnel v2. No automatic cross-project writes.
- Confirm real free-tier quota and actual token usage from the run report. The request caps do not guarantee a zero charge if Gemini API billing is enabled.
- Run original RAY fixture/smoke tests in its real environment (not available in the remote GitHub snapshot alone); confirm no original Sheets writes.
- Only then decide whether the isolated `JobSpy` test adds incremental value. Do not merge experiments automatically.

### Known limitations

The role screen is intentionally broad and can still miss suitable unconventional titles or admit weak matches for human review. A job labelled `review_only` is **not** evaluated by Gemini in the initial budgeted shortlist. Ambiguous remote locations remain in Review. The 40-job cap is a budget guard, not a guarantee of 40 suitable vacancies; do not fill the shortlist with unrelated jobs. The regional rules and language screening are heuristics, not replacements for independently verifying the employer's posting.

This patch was built from the **GitHub `main` snapshot at commit `1a80483a90cddab8d25411e51a9b2f7302ea10b1`**. It has been validated offline with mocked HTTP and Gemini responses, **not** exercised with your Gemini key or live Google Sheets. The local checkout could contain unpushed differences. Applying the patch should be done in a clean checkout based on that snapshot or reviewed for conflicts. The country rules, job board feeds, and model outputs need real-posting verification before this should be treated as a reliable job-finding service.

## 16 October 2026: retrospective filter audit (offline, partial)

The original `personal_run.json` stored **only 364** description/title-prefiltered candidates from 722 unique listings, not the full raw source inventory. Replaying that 364-job subset through the balanced screen produced **27 visible postings**: 16 prioritized AI-eligible and 11 exploratory/manual-review-only. That is a retrospective **subset**, *not a measurement over all 722 unique jobs*. The previous strict screen returned 15 on the original full run. A fresh collect-only run will write one auditable row for each unique posting (e.g. all 722 if providers again return the same cohort), letting us properly measure false negatives and confirm which missed jobs are genuinely actionable. No AI, outreach, or Sheet write is required for this audit.

## v4.1: Offline screening calibration and local observation history

- Provider query plans and maximum HTTP attempts are unchanged (**Arbeitnow 2, Remotive 1, Himalayas 6, Jobicy 2, Adzuna 0**).
- `personal_screening_v41.py` checks evidenced mandatory languages (including English+Spanish and Ukrainian/Russian requirements), flags degrees without demonstrated experience alternatives, substantial leadership tenure, named specialist platforms and explicit AI-model annotation roles. Hard exclusions are conservative; nonlanguage degree/tenure gaps go to manual review rather than being presented as fit.
- Broad marketing/CRM, administrative and adjacent operational work remains reviewable, with stronger category-sensitive manual-review ordering.
- Each manual collect run updates **`personal_discovery_history.local.json`** in the report directory. It is Git-ignored. Previously found jobs absent from a later feed are marked `not_seen_in_latest_run_status_unknown`, **not closed**. Feed presence is also **not proof the employer is accepting applications**.
- Seed prior observations once using existing local reports, oldest first, before your first v4.1 run:

```powershell
.\.venv\Scripts\python.exe personal_screening_v41.py --seed-reports personal_run_v3.json personal_run_v4.json
```

- Replay a frozen v4 audit offline, using the 85 retained jobs' full descriptions where possible:

```powershell
.\.venv\Scripts\python.exe personal_screening_v41.py --audit personal_run_v4_screening_audit.csv --report personal_run_v4.json --output personal_run_v41_replay.csv
```

- Replay does **not** contact providers or invoke AI/Sheets. Of the 908 screened URLs in the 16 Oct 2026 v4 sample, 85 had full text and 823 have only 2,500-character audit excerpts. Its output is a conservative, same-inventory comparison, not a completeness or current-opening guarantee.
- Offline tests: `python -m unittest discover -s tests -p 'test_personal*.py' -v` (tests use local fixtures, no API). For a full run the existing manual `--live --collect-only` command is unchanged and must be separately approved against providers' rolling quotas.

## v4.2 — local seen-state and repeat-judgment suppression

Every URL-deduplicated posting from a manual provider run is now tracked in the Git-ignored `personal_discovery_history.local.json`, including excluded jobs. Its `last_seen` is an observation, not proof a vacancy is active. Missing from the latest fetch means status unknown, never automatically closed.

Backfill all v4 observations without any provider or AI requests:

```powershell
.\.venv\Scripts\python.exe personal_screening_v41.py --seed-audit personal_run_v4_screening_audit.csv --report personal_run_v4.json
```

To record an explicit human review decision:

```powershell
.\.venv\Scripts\python.exe personal_screening_v41.py --mark-url "https://example.com/job/123" --status dismissed
```

Choose `reviewed`, `dismissed`, `applied` or `pending` (to reopen). The exact URL must already exist in the private history; replace the example URL with the canonical URL from the report.

**Seen is not judged:** Previously discovered but unreviewed opportunities remain in the pending review queue. Successful AI evaluations are automatically marked `ai_judged`. The collector excludes human-reviewed and AI-judged jobs from future pending/AI queues and preserves them in its all-jobs audit. If a judged posting changes, it is flagged as `content_updated_since_review` for manual rechecking without automatically reopening it.

The report includes `new_postings`, `new_candidates`, `pending_for_review`, and `already_judged_skipped`. The screening audit adds `seen_before`, `review_status`, and `ai_judged`. This uses no additional provider requests, no Gemini calls, no Google Sheet writes, no scheduler, and no outreach. Never commit the private history file.


## Offline Gemini pilot (no repeat provider collection)

Use a saved collect-only report with full retained descriptions, not another job-board run:

```powershell
python personal_offline_batch.py
```

The default is an **offline preview**, reapplying v4.1 flags and skipping every
URL marked `reviewed`, `dismissed`, `applied` or already AI-judged in
`personal_discovery_history.local.json`. It selects up to 20 jobs (at most
12 original core candidates plus selected adjacent roles on the v4 baseline).
Geography uncertainty is preserved. Explicit specialist/leadership gaps remain
in manual review; they do not become automatic fits.

Before evaluating, place your verified private CV evidence at
`profiles/personal_profile.local.txt` (or set `PERSONAL_PROFILE_PATH` in
the local `.env`). Do not commit your profile or API key.
The project's `GEMINI_API_KEY`, `PERSONAL_GEMINI_MODEL` and
`PERSONAL_GEMINI_FREE_TIER_CONFIRMED=YES` must be configured. The last flag
is an acknowledgement, **not** proof of a zero-cost Google billing tier.

```powershell
python personal_offline_batch.py --evaluate
```

This calls Gemini **at most once** for up to 20 previously collected jobs,
saves `personal_offline_ai_v1.json`, and marks **only successfully
evaluated/cached** jobs as AI-judged. Re-running skips judged URLs and
preserves already saved AI results. It never calls Arbeitnow, Himalayas,
Jobicy or Remotive; it does not write Google Sheets or send applications.
The existing SQLite evaluation cache remains usable.

After examining the saved AI results, publish to the **separate personal**
Google Sheet only with this explicit command:

```powershell
python personal_offline_batch.py --sync-sheet
```

Sheet publication requires `PERSONAL_GOOGLE_SHEET_ID` in `.env`, the
existing `credentials/google-service-account.json`, and Editor access for
the service account's `client_email` on that blank personal spreadsheet.
An ID alone does not confer write access. Never point this at the original
RAY demonstration sheet. If the credential file does not exist, the separate
sync command fails without writing.

Tests: `python -m unittest discover -s tests -p "test_personal*.py" -v`.


## Daily operations (personal-only Windows Task Scheduler)

Use the dedicated script `run_personal_ray.ps1` on Windows 10 after a one-time
manual preflight. The original RAY outreach case study and its Google Sheet
are never scheduled, modified or used as a destination.

**One-time setup:**

1. From the personal branch checkout, `git pull --ff-only origin feature/ray-personal-job-discovery`
   and run `.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_personal*.py" -q`.
2. Keep `.env`, `profiles/personal_profile.local.txt`, and
   `credentials/google-service-account.json` local and gitignored.
   `PERSONAL_GOOGLE_SHEET_ID` must point to the dedicated *Personal Ray* Sheet;
   `PERSONAL_GEMINI_FREE_TIER_CONFIRMED=YES` must reflect actual Google billing settings.
   Share that Sheet as **Editor** with the service account `client_email`
   from the local JSON credential. Never disclose its private key.
3. Run `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run_personal_ray.ps1 -PreviewOnly`
   to inspect the pending shortlist without requests or Sheet writes.
4. Once, while at the console, run
   `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run_personal_ray.ps1`
   to verify the live Sheet permission, provider calls and Gemini. This is a live
   manual run and consumes permitted API quota.

**Daily scheduler:** In Task Scheduler → Create Task, run only when the
user is logged on (simplest credential behavior), trigger Daily at **09:00**
using local Windows time, and set Action → Program to
`powershell.exe`; arguments:
`-NoProfile -ExecutionPolicy Bypass -File "C:\Users\kwstas\Desktop\ai-automation-case-study\ray-personal-job-discovery\run_personal_ray.ps1"`.
Set **Start in** to the personal checkout folder without quotation marks.
Under Settings, use "If the task is already running, do not start a new
instance", and cap execution at 20 minutes. Windows must be powered on; the
task does not run on the GitHub servers or inside ChatGPT. To stop, disable
the task in Task Scheduler.

Full daily workflow: bounded job-provider fetch (max 11 requests per invocation),
normalization, URL/source-ID dedupe, deterministic screening, persistent
history skip for reviewed/AI-judged items, at most five Gemini API calls with
five jobs each, then append/update the *dedicated* Google Sheet. The writer
preserves human review status, notes, priority and explicit location overrides.
Each run produces `personal_run.json`, an audit CSV, and dated log files
under `personal_logs/`; files in `personal_logs` older than 14 days are removed.
No application or outreach is submitted automatically.

**Frequency:** Initially once daily. Himalayas publicly refreshes its API
about every 24 hours and Remotive advises at most four polls a day, so
hourly full scans offer limited discovery benefit. A six-hour Task Scheduler
repeat is an optional later adjustment after confirming stable runs, quota,
and incremental discovery; that equates to up to 44 provider calls daily.
No rapid retry loops are configured on Gemini errors.

**Pending AI (manual queue, without a new provider fetch):**

```powershell
.\.venv\Scripts\python.exe personal_offline_batch.py --evaluate --limit 5 --include-review 5
.\.venv\Scripts\python.exe personal_offline_batch.py --sync-sheet
```

The first command selects up to five still-pending adjacent roles from the
saved `personal_run_v4.json` and makes at most one Gemini call. If Gemini
returns 503, the failed roles remain pending. Run `--sync-sheet` only after
successful scoring; it writes the accumulated saved assessments and marks
successfully scored rows in the "Pending AI" tab. It never fetches job boards.

**Review loop:** Open *New Leads* for untriaged arrivals; read the AI evidence
and employer location/requirements; assign priorities in *Evaluations*
(P1/P2 for Apply First), update Review Status (New → In Review/Applied/etc.)
and Notes; work from *Apply First*. Other views update through formulas.
"Strong Match" is withheld when remote Greek employment eligibility remains
unconfirmed. The stable Vacancy ID in column A is derived from the canonical
job URL. A batch can fail partially without falsely marking the remaining
vacancies AI-judged.
