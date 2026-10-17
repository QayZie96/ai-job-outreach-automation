# RAY coverage expansion + screening refinement — experimental checkpoint

**Date:** October 17, 2026
**Branch:** `experiment/ray-provider-coverage-audit`  
**Production branch:** `feature/ray-personal-job-discovery` — unchanged  
**JobSpy branch:** unchanged

## Empirical evidence

1. Initial controlled live comparison: **28 public API requests**, zero provider blocks. The same-run original RAY collector found **948 raw / 915 unique** URLs. Bounded extended collection found **941 additional unique** URLs, **77** initial deterministic screening survivors (14 AI-lane candidates, 63 manual review), for **1,856** combined unique URLs. Source breakdown: Arbeitnow +575, Himalayas +179, Jobicy +187.
2. Further depth probe: **31 provider requests** total (4 Arbeitnow, 1 Remotive, 20 Himalayas, 6 Jobicy). It got **22 additional unique** URLs after the first expansion, with **2 manual-review candidates**. Himalayas responded **HTTP 429 on call #20**, after 19 successful Himalayas responses; the probe stopped the provider without retry or bypass. The figure **1,878 combined unique** from this second run is not a reliable daily expectation.
3. Initial source-detail evidence: Arbeitnow pages 3–4 yielded 575 additional unique URLs and 36 screening survivors; Himalayas second pages for ecommerce, marketing, operations, and automation yielded useful incremental candidates. Jobicy's second Europe page yielded far fewer survivors.
4. There is no reliable public, unauthenticated Himalayas *daily allowance*. The shared quota can vary by connection, time and other clients; avoid interpreting 19 accepted requests as an exact user limit. Its optional free API key has documented higher limits, but this experiment did **not** use one.

GitHub hosted evidence:
- https://github.com/QayZie96/ai-job-outreach-automation/actions/runs/38988272403
- https://github.com/QayZie96/ai-job-outreach-automation/actions/runs/38989216094

## Experimental production-shaped plan: **at most 25 public attempts per run**

| Provider | Original cap | Experimental cap | Change |
|---|---:|---:|---|
| Arbeitnow | 2 | **4** | Follow two more provider-supplied next links |
| Himalayas | 6 | **17** | Six original page-1 GR searches, four high-yield GR page-2 searches, five new narrow GR keyword queries and two global keyword first pages |
| Jobicy | 2 | **3** | Original Europe and Anywhere queries plus ONE Europe cursor page if available |
| Remotive | 1 | **1** | Unfiltered feed unchanged |
| Adzuna | 0 | **0** | Still disabled |

This is a **moderate experimental ceiling, not a commitment to send every possible request daily**. Existing production local `.env` values override Python defaults even after future promotion. Do not copy larger caps into scheduled production until approved.

The eleven to twenty-five call increase is within the user's request for more coverage without pushing public services to extreme limits, but the exact 25-call plan has **not** been live validated: the deeper probe was blocked, and no further same-day attempts were made after 429.

### Himalayas priority (17 attempts at most)
1. GR: {unfiltered, operations, ecommerce, automation, marketing, analyst}, page 1 — **six requests**.
2. GR: {ecommerce, marketing, operations, automation}, page 2 — **four requests**, chosen over low-yield all/analyst page 2 using observed audit results.
3. GR: {catalogue, product data, pricing, procurement, implementation}, page 1 — **five requests**, new targeted queries; **not yet live validated**.
4. Global (no GR restriction): {operations, ecommerce}, page 1 — **two requests**, both produced useful screening survivors in the first audit.

The query order is deliberately auditable and bounded. Do not assume the global search proves Greece-based eligibility: country restrictions and employer contracts still require explicit verification.

### Gemini is unchanged
- At most 5 API requests per existing scheduled run, batch size 5 and max pre-AI shortlist 40 (subject to existing local .env).
- Existing cached AI judgments and human review decisions remain untouched.
- Large additional inventory does *not* automatically imply more AI requests, as only novel shortlist entries are scored.

## Experimental screening adjustments

- EU-country-restricted remote opportunities go to uncertain **relocation review**, not automatically ineligible merely because Greece-remote is not possible. They never become Greece-remote Strong Matches without verification.
- Explicit negative Greece hiring wording outranks broad feed labels and positive keyword detection, including contradictions in Himalayas provider metadata.
- Titles containing Staff/Principal are kept for **manual review only**, rather than automatically taking Gemini budget based on adjacent marketplace wording.
- No blanket relaxation of unrelated professions, mandatory language requirements, degree/managerial evidence flags or AI strong-match checks.
- The broader manual review set must remain accessible to reviewers. Currently scheduled production writes assessed vacancies to the Sheet; manually flagged unevaluated candidates are present in local screening audits but are **not automatically published**. Solving that visibility gap needs a separately reviewed Sheet workflow.
- Screening recall/precision cannot be called verified without labeling a representative sample of title/geography exclusions and manual review examples from complete descriptions.

## Boundaries and next decision

Everything remains on the experiment branch. The normal Task Scheduler run, real Google Sheet, JobSpy, Gemini project, production cache and production histories were never modified.

Next consequential step is a **separate approval to promote** only after reviewing tests and provider-policy suitability, and deciding whether to configure a free Himalayas API key for stable higher-volume collection. If authorized, keep a reversible migration, preserve manual decisions, and compare new eligible *applications* rather than raw URL count alone.
