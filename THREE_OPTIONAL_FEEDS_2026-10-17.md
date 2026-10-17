# Three opt-in public feeds — experimental RAY implementation

**Branch:** `experiment/ray-provider-coverage-audit`. No production merge, Windows Task Scheduler update, Google Sheet mutation, Gemini call or JobSpy change.

## Default configuration: strictly disabled

Set in `.env.personal.example`, and all **default to zero** inside `personal_discovery.py`:

| New provider | Environment setting (default) | Hard limit per full run | Public endpoint |
|---|---|---:|---|
| Remote OK | `PERSONAL_MAX_REMOTE_OK_CALLS=0` | 1 | `https://remoteok.com/api` |
| We Work Remotely | `PERSONAL_MAX_WWR_CALLS=0` | 1 | `https://weworkremotely.com/remote-jobs.rss` |
| RemoteJobs.org | `PERSONAL_MAX_REMOTEJOBS_ORG_CALLS=0` | 2 | `https://remotejobs.org/api/v1/jobs` |

Zero means **no HTTP request at all**, even when running the experimental full collector. The experimental existing-provider budget remains Arbeitnow 4, Himalayas 17, Jobicy 3, Remotive 1, Adzuna 0 — **25 maximum requests in the default experiment**.

Later, to enable a source independently, change only its respective `PERSONAL_MAX_..._CALLS` value (within the hard limit) **after** explicit authorization and offline/live verification. Never merge these experimental defaults into the scheduled production checkout without a separate approval.

## Integration

- Normalizers in `personal_extra_feeds.py` map the provider JSON/RSS into RAY's existing job contract: source name, provider ID, title, company, location, remote status, description, original source URL, date, salary and job types when provided.
- Collector budget and request provenance reuse `BudgetedHTTP`. HTTPS, timeout, 429 stop/no retries for WWR RSS, and hard per-source request maxima remain enforced. Remote OK's initial API legal notice is skipped.
- We Work Remotely is the official public **RSS**, not the partner-specific job-posting API. Keep WWR source URLs for application and attribution.
- RemoteJobs.org starts with the exact tested query `q=operations&limit=50&offset=0`. If the service explicitly returns `pagination.has_more=true` and a second call is authorized, continue once with `offset=50`; never page blindly.
- Source names and original URLs remain in data and the Personal Ray spreadsheet, supporting provider attribution and human verification. Remote-focused sources do **not** establish that employers hire from Greece; missing geography remains uncertain.
- All listings reuse `deduplicate`, `screen_candidates`, history and existing Gemini evaluator when subsequently enabled. No separate AI scoring system or databases were added.
- The manual-review-only Sheet feature is also in this branch; future authorized Sheet runs would display those leads in a separate **Manual Review** tab without AI scores.

## Adzuna remains at zero

Current code points only at `https://api.adzuna.com/v1/api/jobs/gb/search/1` (UK), uses one `what=business operations` search, and requires both `ADZUNA_APP_ID` and `ADZUNA_APP_KEY`. Hard ceiling and default are both zero, so its `.env` value alone cannot enable it. Although Adzuna offers other country markets, no supported Greece/EU configuration or remote-hiring compatibility has been verified, and its API snippets are truncated. Revisiting Adzuna requires separately scoped code and credential review, not quietly enabling a UK-only source.

Official references:
- Remote OK public JSON: https://remoteok.com/faq
- We Work Remotely official RSS: https://weworkremotely.com/remote-job-rss-feed
- RemoteJobs.org official API: https://remotejobs.org/developers/api
- Adzuna API overview: https://developer.adzuna.com/overview

## Offline checks

Run `python -m unittest discover -s tests -p 'test_*.py' -v`. The new fixtures cover no requests at zero, three independent opt-ins, normalization, WWR RSS dates/malformed responses, Remote OK legal row, bounded RemoteJobs.org pagination, hard request ceilings, and rate-limit handling. No live API, Google credentials or Gemini are needed.

**Verification:** 101 tests passed on GitHub Actions: https://github.com/QayZie96/ai-job-outreach-automation/actions/runs/38991554637. All three new sources are zero-default, and simulated enabled collection was verified using fixtures. The new integrated collectors have not been invoked against the live APIs (previous independent public-feed probes were successful), by design. No production changes were made.
