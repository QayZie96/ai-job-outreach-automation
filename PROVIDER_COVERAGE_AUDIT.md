# RAY four-provider coverage audit — isolated experiment

Branch: `experiment/ray-provider-coverage-audit` (branched from `feature/ray-personal-job-discovery`).

This audit does **not** modify the scheduled RAY collector, its config/history,
the Personal Ray spreadsheet, Gemini, JobSpy or production deployment.

## Purpose

Run one live, bounded comparison between exactly today's collector requests
and additional supported collection paths, using the existing deterministic
`screen_candidates` function unchanged.

- Arbeitnow: baseline pages 1–2, extension pages 3–4.
- Remotive: one baseline unfiltered feed; no extra calls.
- Himalayas: baseline six `country=GR` keyword searches, page 1;
  extension page 2 of those queries, three no-country keyword queries and
  two cursor-paginated browse pages. Total at most 17 requests.
- Jobicy: baseline Europe and Anywhere, count 200 each;
  extension one cursor page where offered and first page of no-geo,
  Greece and EMEA queries. Total at most seven requests.

Every provider call is timeout bounded, domain restricted and never retried.
A rate limit or access block stops that provider. At most **29 public calls**
in one test run, no credentials. No scheduled recurring workflow.

## Interpreting outcomes

`extended_only.incremental_unique` is the number of new URLs compared
against this **same-run** reproduction of the existing four-source collector.
It is not a comparison with the private on-PC RAY discovery history, nor a
count of verified viable applications.

`potential_eu_relocation_false_negatives` counts relevant roles the
existing code hard rejects geographically, despite EU-country placement
potentially meriting relocation review. It is an audit signal, **not proof**
of employment eligibility.

The offline tests intentionally include an expected failure showing that
the existing positive phrase matcher can interpret `not hiring in Greece`
as positive eligibility. **Production code remains untouched**.

Outputs:
- `provider_audit_results/summary.json` with request response status,
  per-query yield and source funnel.
- `provider_audit_results/extra_candidates.csv`, top 60 screened
  incremental candidates (public vacancy data only).
- `provider_audit_results/extra_screening_audit.csv`,
  reasons for deterministic acceptance/rejection of all incremental jobs.

## Reproduce locally (optional)

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install requests beautifulsoup4 python-dotenv
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_provider_coverage_audit.py -v
.\.venv\Scripts\python.exe provider_coverage_audit.py --live
```

The GitHub workflow runs only when its own workflow file is added/changed
on the audit branch, or manually dispatched; it does not run periodically.
Inspect Actions artifacts before proposing production changes.
