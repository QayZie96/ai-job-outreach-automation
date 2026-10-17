# Optional remote feeds + Adzuna pilot audit — 2026-10-17

Experimental branch: `experiment/ray-provider-coverage-audit`. **Production Personal RAY, master Sheet, schedules, Gemini, and JobSpy unchanged.**

## User PC pilot (files `run.json`, `run_screening_audit.csv`)

- HTTP: Remote OK 1 (99 jobs), We Work Remotely RSS 1 (87 jobs), RemoteJobs.org 1 (50 jobs); HTTP outcomes all 200, error list empty.
- Unique URLs across three adapters: 236. Screen survivors: 35 (5 auto-AI candidates, 30 review-only). These counts are an isolated local history; `new_postings=236` does **not** mean all are new to prior jobs/searches or still actively hiring.
- By provider: Remote OK 18 (4 AI/14 manual); We Work Remotely 15 (1 AI/14 manual); RemoteJobs.org 2 (0 AI/2 manual).
- Median *posting age of survivors* as of October 17: Remote OK 25d, WWR 4d, RemoteJobs.org 1d. Freshness is not validation of open hiring status.

### Key quality findings from full descriptions

- Remote OK **MultiplyMii — Marketplace Compliance Analyst** says **Philippines (Remote)** and “work from anywhere in the Philippines.” Provider normalized location is Unknown; prior screener incorrectly classified as uncertain.
- Remote OK **Engine — Marketing Operations** has provider location Remote-US, not Greece eligible.
- Remote OK **Tessera Labs — Oracle Fusion SCM Lead** requires nearshore in Mexico or Brazil, outside scope; strong Oracle consulting specialization.
- WWR **Twilio — Billing Operations Analyst** explicitly says remote **based in Mexico City** and proficient Spanish/English, despite normalized location Unknown. Not Greece/EU eligible.
- Remote OK **Hunt St — Marketing and Sales Administrator** says looking for Philippines-based candidates, even though provider location Unknown.
- Remote OK **JumpCloud — CSM Mexico** requires location/work permit in Mexico.
- WWR **Expel — Product Manager Detection Pipeline** says remote within United States.
- RemoteJobs.org **ScaleJet — Chinese-speaking Sourcing/Production Manager** explicitly needs Chinese; user does not verify it. Similar company+title also appeared in master staging from Himalayas, a cross-provider near duplicate distinct URL.
- RemoteJobs.org **Smarsh — Sr Director Sales/CS Ops** US-Atlanta senior leadership, not user target.
- WWR **Paragon Planners — Part-time CRM specialist** includes explicit U.S. state hiring allowlist; avoid treating the WWR feed's Unknown location as global.
- WWR **Spiralyze Project Manager** and Remote OK **Spiralyze Project Manager** appear to be a cross-provider company/title near-duplicate. A more plausible transferable role with no formal PM experience required but remote-from-Greece permission not verified. WWR copy is older; board age is not proof role remains open.
- Remote OK **Omega Enterprises junior digital assets operations** is an entry-level possible lead with unconfirmed jurisdiction/employer; verify legitimacy before applying.
- WWR **Tines GTM Systems Specialist** and other manual roles often have substantial CRM/RevOps specialist requirements; headquarters must not be treated as hiring eligibility.

### Priority recommendation (not yet production enabled)

1. Retain **Remote OK=1** and **WWR=1** as *experimental* daily candidates subject to rescreened precision, incremental/new-lead quality and board terms. Do not send the raw top 5 directly to Gemini before geographic fixes.
2. Leave **RemoteJobs.org=0** (minimal incremental suitability from this first 50-row probe); revisit only if search query relevance improves.
3. Prefer one daily `Evaluations` experience with manual/AI statuses, not new separate daily triage obligations.

## Adzuna one-call report (`run(1).json`)

- No HTTP request was attempted; 0 jobs, 0 audit rows.
- Error: `Adzuna enabled but app ID/key credentials missing`.
- Client requires `ADZUNA_APP_ID` and `ADZUNA_APP_KEY` from local experiment `.env` or process environment. Existing credentials can be used across Adzuna country-specific markets; source `.env` is not loaded automatically by experiment. Do not share/commit keys.
- Do not diagnose 401/403 or unsupported EU market: neither was tested.

## Experimental code changes and verification

- Added explicit remote-role non-EU hiring restriction detection using employer description/body and metadata. Avoids treating headquarters/markets as role work locations.
- Added explicit Chinese/Mandarin/Korean/Hindi/Armenian mandatory title-language detection, to avoid spending AI calls on unverified professional languages.
- Added mocked offline regression tests for Philippines, Mexico, Brazil, Remote-US, China-language and false-exclusion control examples.
- 137 tests passed, GitHub Actions: https://github.com/QayZie96/ai-job-outreach-automation/actions/runs/39030321047

**Next:** after `git pull --ff-only`, run an *offline rescreen of the retained 35* (no API/Gemini/Sheets) to see corrected AI/manual survivors; then review lead quality and pilot Adzuna 1 call when local credentials are present. No approved production merge yet.
