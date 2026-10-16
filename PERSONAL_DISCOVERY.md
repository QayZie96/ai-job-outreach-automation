# RAY personal job discovery — isolated, manual first

This adds **personal job discovery** to the original RAY case-study repository. It does **not** change `main.py`, `validator.py`, `sheets.py`, `outreach.py`, the original RAY prompt, existing RAY Google Sheet, or scheduled launcher. It **never** generates outreach or sends applications. The `JobSpy` experiment is not included in this first stage and must remain a separate branch.

## Decisions and defaults

- Existing feeds: Arbeitnow (max **2** HTTP attempts), Remotive (**1**), original **UK-only** Adzuna (**0**, disabled because unsuitable for most Greece/EU targets).
- New official feeds: Himalayas targeted Greece-country searches (**4** HTTP attempts); Jobicy two bounded queries (**2** attempts). Responses are deduplicated by URL and source ID; no company/title-only collapse.
- Mandatory live flags. No automation/scheduler installed.
- Existing `validation_cache.db` table reused with namespaced personal keys, not a separate database. Fingerprint covers profile text, job details, prompt, model, and schema. Historic RAY cached values remain separate.
- Existing provider field mappings are mirrored in the isolated personal collector to avoid importing the RAY Gemini-initializing runtime. Original flow unchanged.
- Conservative pre-AI screening checks title role family, explicit mandatory foreign languages, remote Greece eligibility and EU hybrid/on-site relocation. Unknown jurisdiction is marked for **Review**, not promoted to Strong Match. Pre-AI ordering is based on transparent relevance and eligibility evidence, with source diversification and a default **40-job AI shortlist** (`PERSONAL_MAX_AI_CANDIDATES`, max 100). Collection-only still returns the complete screened-in pool.
- One batched Gemini pass (20 jobs per request, max **5 requests**). The output includes a 0–100 *evidence fit score*, eligible/uncertain/ineligible assessment, short requirements, matched user evidence, posting evidence, gaps and reasons. Score is **not** likelihood of interview.
- Country/location conflicts, unresolved precheck eligibility and missing supporting evidence cannot become Strong Match. `Review` retains uncertainty rather than inventing eligibility. The model receives at most 4,000 characters of each job description per call, marked truncated as needed; check full posting manually before applying.
- Rejected/low-fit results remain in SQLite; local `personal_run.json` includes the evaluated batch. The Google Sheet has one authoritative `Evaluations` tab and two formula-driven tabs (`Strong Matches`, `Review Queue`), plus `Run Summary`. Human status/notes survive re-evaluation.

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

Review `personal_run.json` for source attempts, source failures, precheck rejection counts, shortlist URLs, deferred-by-cap counts, candidates, cache hits, model calls, scores and reasons. Precheck rejections never consume Gemini calls. An API listing tagged remote may in fact be an EU hybrid office role; read the employer description, not just the feed flag. All original-provider timestamps are converted to ISO calendar dates. This file may contain job descriptions and is ignored by Git. Make sure actual remote-jurisdiction eligibility and listing availability are independently confirmed before applying; original feed membership does **not** prove a vacancy is still open.

## Acceptance gates before scheduling or JobSpy

- Spot-check at least 10–20 diverse actual evaluations, including rejected/uncertain ones; specifically review location, mandatory languages, missing credentials, experience evidence, and false negatives.
- Compare new *eligible, unique Strong Matches* against your existing job alerts and Job Funnel v2. No automatic cross-project writes.
- Confirm real free-tier quota and actual token usage from the run report. The request caps do not guarantee a zero charge if Gemini API billing is enabled.
- Run original RAY fixture/smoke tests in its real environment (not available in the remote GitHub snapshot alone); confirm no original Sheets writes.
- Only then decide whether the isolated `JobSpy` test adds incremental value. Do not merge experiments automatically.

### Known limitations

These filters are deliberately conservative: they can miss some suitable jobs with unconventional titles, and ambiguous remote locations remain in Review. The 40-job cap is a budget guard, not a guarantee of 40 suitable vacancies; do not fill the shortlist with unrelated jobs. The regional rules and language screening are heuristics, not replacements for independently verifying the employer's posting.

This patch was built from the **GitHub `main` snapshot at commit `1a80483a90cddab8d25411e51a9b2f7302ea10b1`**. It has been validated offline with mocked HTTP and Gemini responses, **not** exercised with your Gemini key or live Google Sheets. The local checkout could contain unpushed differences. Applying the patch should be done in a clean checkout based on that snapshot or reviewed for conflicts. The country rules, job board feeds, and model outputs need real-posting verification before this should be treated as a reliable job-finding service.
