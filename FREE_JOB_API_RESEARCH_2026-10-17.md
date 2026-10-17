# RAY — Free Job Feeds and API Research (2026-10-17)

## Scope and constraints

Research target: **additional free/low-cost job-listing providers**, beyond JobSpy and the four current RAY feeds (Arbeitnow, Himalayas, Jobicy, Remotive). Work confined to `experiment/ray-provider-coverage-audit`; **no production/RAY scheduler/Gemini/Google Sheet/JobSpy changes**. Avoid duplicate work already covered by Job Funnel v2 (company-specific ATS boards).

A one-time, read-only GitHub Actions probe sent **one public HTTP GET to each of five distinct providers**, without authentication, retries or proxies. GitHub run: https://github.com/QayZie96/ai-job-outreach-automation/actions/runs/38990528232

## Live source comparison

| Source | Status | Parsed listings | Initial candidates | Manual-review-only | Description populated | Decision |
|---|---:|---:|---:|---:|---:|---|
| Remote OK | 200 | 99 | 4 | 14 | 99 | **Priority 1** |
| We Work Remotely RSS | 200 | 87 | 2 | 16 | 87 | **Priority 1** |
| RemoteJobs.org | 200 | 50 | 0 | 2 | 50 | Priority 2, selective targeted queries |
| Working Nomads | 200 | 49 | 0 | 2 | 49 | Low, no proven additional relevant yield |
| The Muse | 200 | 20 | 0 | 3 | 20 | Low, US-skewed and registration requirement |

**Aggregate:** 305 parsed listings and 43 deterministic screening survivors, **6 candidates plus 37 manual-review-only**. All 305 parsed listings had nonempty description fields. These counts are **before cross-provider and historical RAY deduplication**. No employer vacancy was manually verified, and eligibility labels do not establish Greece hiring rights.

Some apparent good matches are poor fits: Remote OK included a US-only Marketing Operations Specialist, a specialized Oracle Fusion logistics lead, and a student assistant in its manual review; RemoteJobs.org surfaced a Chinese-speaking role in Portugal and a US-based senior director. We should not count these as verified suitable applications. We Work Remotely surfaced a Category Manager at StockX and Billing Operations Analyst at Twilio, requiring location/requirements checks.

### Official access documentation

1. **Remote OK** — https://remoteok.com/faq , JSON feed `https://remoteok.com/api`, no key; optional tag filtering according to official FAQ, but do not rely on tags until probed. Source explicitly requests attribution and original job links when aggregating. Single rolling feed, not guaranteed paginated. The first JSON element contains terms, not a vacancy; parser handles it.
2. **We Work Remotely** — https://weworkremotely.com/remote-job-rss-feed , freely accessible official all-jobs RSS `https://weworkremotely.com/remote-jobs.rss` and category-specific RSS (Customer Support; Product; Sales & Marketing; Management & Finance; All Other). WWR asks for visible source attribution. Its job posting API is partnership-based, so use documented RSS only.
3. **RemoteJobs.org** — https://remotejobs.org/developers/api ; free JSON, no key, `q`, category, job type, `limit` <=50, `offset`, `pagination.has_more`; guidance below 200 requests/hour/IP, not a guaranteed quota. Attribution and original application URL required if displaying externally. Our single `q=operations` first page contained 50 and `has_more=true`, but only two manual-review roles; depth alone is not yet justified.
4. **Working Nomads** — `https://www.workingnomads.com/api/exposed_jobs/`, public JSON returned 49 rows in the live run. We did not find first-party published API limits or explicit reuse terms for this endpoint: treat it as unverified for unattended use. A third-party comparison indicates it's an unpaginated snapshot; no blind pagination.
5. **The Muse** — https://www.themuse.com/developers/api/v2 ; official `https://www.themuse.com/api/public/jobs?page=0` with 20 jobs/page, public testing allowed, app registration required for continued use beyond testing. USA-heavy sample; unattractive for Greece-focused job search without a geography suitability check.

### Other candidates researched — **not included in the five-request live run**

- **Adzuna** — https://developer.adzuna.com/docs/terms_of_service ; real official multi-country search API with API key registration. Default documented ceilings: 25/min, 250/day, 1,000/week, 2,500/month, subject to change. Personal research permitted in ToS. Existing RAY Adzuna connector is UK-only and disabled, so a separate supported-country check is needed before activating an EU configuration; no claim that Greece is supported. Useful only after identifying international hiring access and available country endpoints.
- **Greenhouse public Job Board API** — https://docs.greenhouse.io/job-board ; public GET postings, `content=true` descriptions, no authentication for public GET. Per-company board tokens, not a single job aggregator. Already broadly addressed by Job Funnel v2; avoid reproducing that work inside RAY.
- **Lever public Postings API** — https://github.com/lever/postings-api ; public company sites with paginated GET and optional filters, global/EU instances, not general cross-company full-text search. Covered by company-specific source discovery, not worth another general RAY pipeline.
- **Ashby published Job Postings API** — https://developers.ashbyhq.com/docs/public-job-posting-api ; company-level public posts with optional compensation; avoid duplication of Job Funnel v2.
- **SmartRecruiters Posting API** — https://developers.smartrecruiters.com/docs/endpoints ; public postings by company slug, search and pagination; company-specific, not a broad public job portal. Separate authenticated endpoints should not be confused with public GET.
- **Workable public account jobs endpoint** — https://workable.readme.io/reference/jobs-1 ; public `https://www.workable.com/api/accounts/{subdomain}` returns published job ads with optional details. **Different** from authenticated SPI jobs endpoint; overlaps Job Funnel v2 already investigating Workable.
- **EURES (European Job Mobility Portal)** — https://europa.eu/eures/portal/ ; *not eligible for unrestricted automated ingestion*. Official job search disclaimer prohibits screen scraping/data extraction and reserves API extraction to recognized EURES partner organizations. Exclude from RAY automation unless obtaining explicit permitted access.
- **Reed, JSearch/third-party aggregators** — no approved accessible free stable API usage or geography value established by this audit; do not claim quotas or implement without validating provider terms, requirements and Europe coverage.

## Recommended implementation order, if separately authorized

**Do not automatically register all five sources.** This would duplicate job inventory and overwhelm manual review without meaningful gain.

1. Stage **Remote OK (1 request)** and **We Work Remotely RSS (1 request)** in a distinct experimental RAY provider patch with canonical URLs, original-source attribution, deduplication, normalized locations and descriptions, and strict geographic uncertainty. Compare their unique employer-confirmed Greece/EU-relocation roles against the existing RAY history.
2. Consider **RemoteJobs.org** with targeted `q` and conditional pagination only if experiments show incremental genuine opportunities.
3. Treat Working Nomads and The Muse as low priority; honor Muse's registration requirement for repeated use. Do not add EURES or unapproved scraping.
4. Keep company-specific ATS discovery in the separately maintained Job Funnel v2, where it already belongs.
5. Require a verified review sample before increasing Gemini evaluations or automated frequency. An extra 36 screening survivors from two boards is *not* an extra 36 feasible applications.

## Manual Review Sheet implementation

On this same experiment branch, `personal_sheets.py` creates the **Manual Review** tab only when a future authorized `--write-sheet` run executes, with exact header validation and URL-keyed idempotent upserts. It writes all `review_only` candidates into a separate 18-column queue, uses RAW values, preserves user `Review Status`/`Notes`/`First Seen`, and never invents AI scores. The `Evaluations` tab remains authoritative only for Gemini-evaluated jobs. `personal_discovery.py` passes deterministic review-only candidates to this writer before history is marked judged. This feature has **92 passing offline tests** and **no live Google Sheet write**. No production change or new Sheet tab has occurred.

Offline validation: https://github.com/QayZie96/ai-job-outreach-automation/actions/runs/38990440488

## Pending promotion gates

- Human review of representative jobs (false-positive and false-negative calibration)
- Live test in a disposable Sheet with service account permissions, verifying row formatting and human-state preservation (do not write to production without approval)
- Provider-specific reuse/attribution obligations (especially Remote OK and WWR), and no source additions until incremental eligibility is measured
- Explicit approval for production branch merge, scheduler changes, Google Sheet mutation, or provider expansion
