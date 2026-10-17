# Expanded RAY — five-job Gemini pilot review
Date: 2026-10-17. Experimental branch only.

## Pilot verified

Source: user-run `personal_run_stage_01_gemini_pilot.json` (five saved jobs).

- Local regression: 127 passed before run. Pilot: 5 jobs, 1 Gemini request, 0 provider requests, 0 Gemini failures; 7,379 input / 1,448 output tokens. `Evaluations` added 5, updated 0. 26 previously assessed candidate URLs were protected.
- Independently verified staging Sheet `19VFagJwpHrW_d18FEGEQDGJ2noSR3vM8NqX3aAaMxYI`: 33 Evaluations records and 134 manual rows, all unique.
- Decisions from first pilot: 3 Review, 2 Ineligible. These are model judgments, not hiring eligibility determinations.

## Human quality review of the five

| Employer | Position | Initial model score / decision | Finding |
|---|---|---|---|
| Sleep 21 | Freelance Creative/Content Lead (DTC launch) | 75 / Review | Dutch-language posting, senior creative/art direction case requirements. Should be manual-only, not paid Gemini priority; model may have overvalued marketplace overlap. |
| Precoro | Product Manager – AI & Supplier Management | 68 / Review | Explicit 3+ years of PM experience at product company and B2B SaaS; domain transferable but major qualification gap. Manual-only pending human assessment. |
| Cision | Sales Business Analyst | 55 / Review | Plausible transferable operations/reporting work. Only Bulgaria/Hungary hiring locations are listed; EU relocation and employer conditions must be verified. |
| Commoditysupplies | Ocean Freight Customer Service Specialist | 45 / Ineligible | Switzerland on-site (outside EU relocation scope), mandatory native-level German and specialist ocean-freight experience; should never have reached Gemini. |
| Moss | IT Program Manager (Berlin) | 50 / Ineligible | Gemini treated German C1 as mandatory but the actual advert says German C1 and other certifications **are all a plus**. The model's language rationale is demonstrably wrong. The substantial IT vendor/migration specialization remains a fit concern, so review rather than assert qualification. |

## Experimental corrections (no existing Sheet edits)

- Catch mandatory "native-level German", but not when genuinely marked optional.
- Treat Wollerau/Schwyz as Swiss non-EU location for non-remote postings.
- Flag predominantly Dutch-language job descriptions for manual review (never assume automatic ineligibility solely due to job-text language).
- Flag creative/art direction lead requirements and explicit 3+ years of PM at a product company as manual-review specialisms.
- Prompt Gemini to interpret clause-wide "are all a plus" accurately.
- Add a narrow deterministic post-assessment safety guard so a false mandatory-German-C1 reading of Moss-style optional language does not cause an automatic Ineligible decision; only when no independent deterministic exclusion already exists.

**Full verification:** 134 tests passed on https://github.com/QayZie96/ai-job-outreach-automation/actions/runs/39029290600.

## Remaining next gates

1. User pulls experimental branch. No need to repeat paid pilot. Do not overwrite existing 33 staging evaluations/134 manual entries; the old 5 assessments are preserved for human review.
2. Activate Remote OK, WWR and RemoteJobs.org as **independent single-call collect-only probes**, with all other feed limits zero; use separate report directory/history.
3. Test existing Adzuna credentials using **one** call only against a selected EU market; expand to 8 only after validation.
4. Assess incremental hireable *new* vacancies, not raw fetched counts. Evaluate false positives and manual queue size before deciding daily call budgets.
5. Build one daily Evaluations entry point while retaining unscored/manual visibility and human status.
6. Merge only after isolated Sheet publication and source checks; preserve production scheduler, cache, private profile, .env, and rollback.

No new live calls or production changes made while preparing this checkpoint.
