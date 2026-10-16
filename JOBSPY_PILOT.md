# JobSpy isolated pilot

This branch is **experimental**. Production RAY's 09:00 Windows task, four provider collectors,
deduplication history, cache, and original Personal Ray Sheet are **not** modified.

## Windows setup (separate checkout; no scheduling)

From the existing RAY checkout:

```powershell
git fetch origin experiment/jobspy-discovery
git worktree add --track -b experiment/jobspy-discovery ..\ray-personal-jobspy origin/experiment/jobspy-discovery
cd ..\ray-personal-jobspy
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-jobspy.txt
Copy-Item .env.jobspy.example .env.jobspy
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_jobspy_pilot.py -v
.\.venv\Scripts\python.exe jobspy_pilot.py --fixture tests\fixtures\jobspy_sample.json
```

If the branch already exists locally, use `git worktree add ..\ray-personal-jobspy experiment/jobspy-discovery`
instead of the branch-creation command. Keep the production checkout on its existing branch.

## Bounded public pilot

```powershell
.\.venv\Scripts\python.exe jobspy_pilot.py --live --baseline-history "C:\Users\kwstas\Desktop\ai-automation-case-study\ray-personal-job-discovery\personal_discovery_history.local.json"
```

The baseline file is **read only**. The pilot makes four bounded board searches:
two Indeed Greece queries and two LinkedIn EU remote queries, requesting at most 12
records each (48 raw records max). It makes no requests to Gemini by default and
does not fetch individual posting descriptions as extra HTTP calls. Do not use
proxies, authentication, or anti-bot workarounds. Stop a platform after its first
failed invocation. Actual underlying HTTP request counts are not exposed by JobSpy:
`collection_invocations_not_http_count` counts **library calls**, not HTTP requests.

Fixture results have a separate local history and cannot publish to Sheets or call Gemini.
Live results stay under ignored `jobspy_state/`:
- `jobspy_raw.json`, `jobspy_normalized.json`
- `jobspy_candidates.csv`, `jobspy_screening_audit.csv`
- `jobspy_report.json`, and a **separate** local history file.

All screening is the existing RAY deterministic `screen_candidates` function.
No new AI scoring rules are applied. A missing description may still generate
a manual lead, but cannot be submitted for AI until content is present.
A site "remote" label is NOT proof of Greece hiring eligibility.
Cross-board title/company/location similarities are flags for manual review,
not silent duplicate deletion.

## Optional pilot Sheet publication

This writes **only** to [Personal Ray — JobSpy Pilot](https://docs.google.com/spreadsheets/d/1pgfchhc27VaGLy3Z4DjYou1lHQ0j4VH6JQ7lwGSURr8/edit).

The new blank Sheet is prepared with a `Pilot Leads` tab.
When you are ready for publication, separately grant your existing RAY
Google service-account email
`ea-job-outreach-writer@ea-job-outreach-automation.iam.gserviceaccount.com`
**Editor** access to the pilot sheet, then copy
the existing service-account JSON securely into this separate checkout at
`credentials/google-service-account.json`.
Do not commit credentials. **Do not share or write to the production Personal Ray Sheet.**

```powershell
.\.venv\Scripts\python.exe jobspy_pilot.py --live --sheet
```

`--sheet` upserts deterministic leads with eligibility, priority,
description status, existing-RAY exact-URL match, and duplicate review flag.
Manual review status and notes survive subsequent upserts.

## Optional reuse of the exact RAY Gemini workflow

Only if explicitly choosing to spend a Gemini call, provide a private
verified candidate-profile file and Gemini key in `.env.jobspy`,
confirm the API project's billing/free tier, and set
`PERSONAL_GEMINI_FREE_TIER_CONFIRMED=YES`.
Then run:

```powershell
.\.venv\Scripts\python.exe jobspy_pilot.py --live --sheet --evaluate
```

This uses **the existing** prompt, evaluator, and Personal Ray Evaluations writer,
but with a JobSpy-only local SQLite cache and the separately guarded pilot Sheet.
Maximum one Gemini batch (up to five jobs) in this pilot; no billing promise.
The standard Personal Ray `Evaluations` and view tabs are created
by the existing writer only when completed assessments exist.

## Promotion gate

Do not add a Task Scheduler job or make JobSpy write into the existing Personal
Ray spreadsheet yet. Compare unique, genuinely new, credible and eligible leads;
missing descriptions; real page access; duplicates; rate limits; and maintenance
burden before deciding. A future *separate* Windows task writing to the shared
sheet requires new approval, robust cross-run dedup, and coordination on writes.
