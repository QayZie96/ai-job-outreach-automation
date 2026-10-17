# Adzuna international collector — experiment checkpoint

**Branch:** `experiment/ray-provider-coverage-audit`  
**Production:** unchanged. **JobSpy:** unchanged.

## What is implemented

Adzuna was previously UK-only (`gb/search/1`) with a hard stop of zero. This experimental branch now supports a constrained **multi-market Adzuna Jobs API**, including country-specific endpoint selection, English-language role-family queries, up to two pages per country/search, normalization into RAY's existing model and full use of RAY deduplication, screening, human review, history and Gemini pipeline.

**Crucial:** The default request count remains **zero** and no credentials were used. The HTTP hard ceiling is **12** Adzuna attempts per collector run; the configured daily defaults for every other source are unchanged.

## Gitignored local configuration (example only)

```dotenv
PERSONAL_MAX_ADZUNA_CALLS=0
PERSONAL_ADZUNA_MARKETS=de,nl,fr,es
PERSONAL_ADZUNA_TERMS=ecommerce,operations
PERSONAL_ADZUNA_PAGES_PER_QUERY=1
# Local .env only; register with Adzuna first:
ADZUNA_APP_ID=
ADZUNA_APP_KEY=
```

- With the first setting **0**, it performs no Adzuna HTTP request, irrespective of credentials.
- After separate authorization, set **8** for the default four markets × two queries × first page, *if* those markets actually accept your credentials.
- Allowed markets: `at,de,es,fr,gb,it,nl,pl`; default `de,nl,fr,es`. These are intentionally narrow candidates, not proof of live endpoint coverage or suitability. `gb` is optional and not in the default plan.
- Allowed terms: `ecommerce,operations,marketplace,catalogue,product data,pricing,implementation`. English terms may under-cover non-English local adverts. Config rejects unknown terms, invalid country values, blank items and duplicates.
- Page count permitted: **1–2**. If set to 2, RAY searches first pages across all markets before second pages, and still stops at the requested maximum of 12 attempts. Empty first-page pairs do not request page 2.
- Requests fetch up to 50 entries each. Results are snippets; actual job pages and language requirements may require human review.
- Country-indexed Adzuna postings are **not** proof of remote work or that an employer can hire in Greece. Normalizer leaves `remote=None`, and existing RAY EU-relocation logic categorizes such opportunities for review.
- Existing request provenance excludes `app_id` and `app_key`; the Adzuna exception path suppresses credential-bearing error messages.
- HTTP 401, 403 and 429 stop the provider; HTTP failures/retries consume the configured per-provider call budget.

## Verification and limitations

All code has been committed to the experimental branch with offline fixture tests: zero-attempt behavior, country and term validation, 8-market-query requests, pagination caps, duplicate normalization, forbidden/rate-limited stop, and credential-redacted errors. **No authenticated live Adzuna call has been performed** and API market availability remains unverified until tomorrow's PC test.

Official API documentation: https://developer.adzuna.com/overview and https://developer.adzuna.com/docs/search .

To test tomorrow: (1) pull experimental branch into its separate worktree, (2) register your own Adzuna credentials and store them **only** in gitignored local `.env`, (3) use collect-only mode first with an Adzuna budget of one or two and all other sources set to zero, (4) inspect per-market outcomes and candidate quality, and only then consider the eight-call international plan. Do not modify the existing 09:00 production task for this pilot.
