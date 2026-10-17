# RAY four-provider coverage experiment — measured results

**Run:** 2026-10-17 00:52 UTC  
**GitHub live workflow:** https://github.com/QayZie96/ai-job-outreach-automation/actions/runs/38988272403  
**Offline regression after prototype fixes:** https://github.com/QayZie96/ai-job-outreach-automation/actions/runs/38988615676  
**Branch:** `experiment/ray-provider-coverage-audit`

## Scope and safety

One GitHub-hosted comparison of existing RAY provider requests against bounded extra inventory. No Gemini, Sheets, local production history/cache, Task Scheduler or JobSpy access. No API keys; no authenticated scraping or proxy. Exactly **28 public HTTP requests** completed with **no blocked providers**. Tests: 7 initial (1 expected failure exposing an existing bug); **86 full offline regression tests passed** after fixes.

The live run used the **original** screener, not the later prototype fixes. Additional URLs are incremental to a **same-run reproduction** of the existing provider collection; they are not guaranteed new versus the private production history or application spreadsheet.

## Same-run collection comparison

| Provider | Baseline unique | Extra unique | Extra initial candidates | Extra manual review |
|---|---:|---:|---:|---:|
| Arbeitnow | 600 | 575 | 6 | 30 |
| Himalayas | 96 | 179 | 8 | 30 |
| Jobicy | 204 | 187 | 0 | 3 |
| Remotive | 15 | 0 | 0 | 0 |
| **Total** | **915** | **941** | **14** | **63** |

Raw counts: **948 baseline**, **1,335 additional fetched**, with **1,856 unique URLs** in combination. The expanded run yielded **77 additional deterministic screening survivors** (14 candidates + 63 review-only), **not** 77 confirmed eligible or high-fit applications. Overlap with earlier production Sheet entries is possible; at least Gotphoto, Black Semiconductor and Yepoda examples are known there.

## Proven query-level observations

- **Arbeitnow:** Existing pages 1 and 2 returned 300 each. Newly explored pages 3 and 4 returned 300 and 275, with 575 incremental unique URLs and **36** screening survivors. Raising the page cap from two to four is a simple, high-volume option, subject to acceptable relevant-applications yield.
- **Himalayas:** Each of the six Greece-filtered first-page searches returned 20 (120 raw, 96 globally unique after overlapping search queries). Page 2 of those same six searches added **19** surviving roles after incremental deduplication. Three first-page unfiltered-by-country role searches added **12** survivors. Two cursor-based browse pages added **7** survivors. Across all Himalayas expansions, **179** unique new URLs and **38** screen survivors. The Greece-unfiltered search response reported `totalCount=3758`; pagination is therefore a real constraint, but a full crawl is not justified.
- **Jobicy:** Europe page 1 returned 200 with `hasMore=true` and a cursor; Anywhere returned 13 with no continuation. Europe page 2 returned 64 (60 incremental unique) and one screening survivor. An unfiltered first page added 127 unique URLs and two screening survivors. Additional Greece and EMEA first-page probes did not add unique URLs beyond those already collected in this particular request order. **187** extra unique overall, but only **three manual-review-only survivors**.
- **Remotive:** Unfiltered feed returned 15; no second page is needed under current endpoint semantics.

These figures are for a one-time observation, not steady-state forecasts.

## Deterministic-screening issues and prototype fix

The unchanged live screener marked **18 baseline + 5 additional** relevant vacancies as possible EU-relocation false negatives from hard geography exclusions. These are review opportunities, not verified hiring eligibility. An offline adversarial test also confirmed that `not hiring in Greece` could produce an erroneous positive eligibility result.

The experiment branch now contains **unreleased** changes in `personal_discovery.py` and `personal_evaluation.py` that:
1. Send EU-country-restricted jobs to an **uncertain relocation-review** lane rather than treating them as Greece-remote eligible or automatically excluding them.
2. Give explicit negative Greece-hiring statements priority over positive substring detection.
3. Preserve that review-only distinction through post-Gemini classification.

Full regression: **86 tests passed** on the experimental branch, without a second live scrape.

## Quality warning and recommendation

Some initial candidates are senior/staff-level and several manual-review leads require languages, experience or locations that may make them poor targets. The observed increase is inventory, not confirmed interview-worthy opportunities. The current role screener was deliberately not broadened without ground-truth false-negative evidence.

**Suggested rollout order (requires production authorization):**
1. Promote targeted geography guardrail fixes after review; preserve `uncertain` and manual state, not `eligible` or Strong Match.
2. Add Arbeitnow pages 3–4 and Himalayas page 2 to each existing query behind bounded configuration, then track useful applications.
3. Test Himalayas global role searches selectively; do not crawl 123k browse records.
4. Defer a broader Jobicy expansion unless a second sample demonstrates better incremental eligible yield.
5. Keep Remotive unchanged. Keep the daily scheduler, Gemini budget and Sheet writer unchanged until explicitly approved.

**Raw evidence:** GitHub Actions artifact `ray-provider-coverage-audit` (7-day retention) contains `summary.json`, `extra_candidates.csv` (top 60), and `extra_screening_audit.csv` (all 941 incremental screening records). The full extra candidates CSV is intentionally *not* a list of 77 confirmed applications.
