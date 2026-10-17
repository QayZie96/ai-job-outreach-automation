# Adzuna one-call evidence audit — 2026-10-17

Scope: user's authenticated `adzuna_probe/run_auth.json` and corresponding 50-row `run_auth_screening_audit.csv`. **Experimental only.** Production Personal RAY + scheduler + primary Sheet unchanged; JobSpy parked.

## Result and quality decision

- One successful authenticated `de` + `ecommerce` page-1 call, 50 normalized rows, zero provider errors.
- 20 deterministic survivors: 9 listed as AI candidates, 11 manual only; all 20 geographically `uncertain`. No second market tested.
- All 20 saved survivor descriptions are **snippets**: 19 exactly 500 characters and one 451 characters. `normalize_original('Adzuna')` passes through the upstream description and does not crop it.
- Official Adzuna documentation confirms API returns only a job-description snippet: https://developer.adzuna.com/docs/search
- Multiple duplicated results for the same company/title: 20 survivors represent **13 exact normalized company/title groupings**, or approximately **12** after also combining the Sony Music/The Orchard alias based on identical description.
- Initial 9 AI rows represent ~5 underlying roles: two `The Orchard/Sony Music` eCommerce Manager variants, two Deichmann three-year `Ausbildung` apprentice entries, one Melitta Data Analyst, three Hearts & Science Group Head eCommerce variants, one Melitta Platform Manager.
- No grounded evidence from snippets proves German-language requirements or Greece/EEA work eligibility; neither German advert nor EU location alone is sufficient to auto-exclude. No individual job should be AI-assessed on a snippet without obtaining the employer's complete requirements.
- Original 30 rejections include four Faber-Castell `Senior Manager Marketplaces` listings and one ADBAKER `Junior TikTok Shop Manager`, previously lost due narrowly singular `marketplace` title detection. Both are legitimate possible manual-review subjects; not proof of hireability.

**Decision: Keep Adzuna collector at 0 in eventual automated daily configuration for now; do not scale to 8 market/keyword calls.** It can remain a manually enabled source experiment. Other feeds have fuller descriptions and are preferable for paid Gemini matching. A future Adzuna enrichment design would require approved, rights-compliant source retrieval and validation rather than assuming the 500-character snippets are full text. Adzuna does **not** offer a full-detail endpoint in its public search API. Do not automate third-party publisher crawling from Adzuna API results without clearance: https://developer.adzuna.com/docs/terms_of_service prohibits API users from contacting third-party content providers on the basis of listings. A small subset of Adzuna-hosted `/details/...` pages may have full JobPosting data, but automated site access, robots and contractual permission have not been verified; `/land/ad/...` is not an assured programmatic full-text endpoint. Commercial/licensed full detail is advertised separately: https://developer.adzuna.com/.

## Experimental code fixes

- Adzuna normalizer explicitly marks `description_truncated=True`.
- Adzuna excerpt-only rows are **manual only**, including legacy reports without the field, and carry `adzuna_excerpt_requirements_unverified` fit flag.
- German apprentice title markers (`Ausbildung`, `Azubi`, etc.) are out of the active job target.
- `Group Head` correctly receives senior executive review handling instead of paid AI shortlist priority.
- `Marketplaces` plural and `TikTok Shop` can reach manual screening rather than false role-out-of-scope exclusions.
- No blanket rejection of German-description jobs. No universal dedup by company/title: different cities/requisitions can be distinct; review provider duplicates cautiously.

**144 offline regression tests passed:** https://github.com/QayZie96/ai-job-outreach-automation/actions/runs/39031466480

## Next merge milestones

1. Single `Evaluations` entry point: scored + human-only jobs in the same daily review with preserved status and no fake AI score; filters should hide low-confidence/ineligible/multiplied duplicates by default.
2. Reconcile full original Personal RAY history/cache/human decisions and staging changes. Preserve production cron, `.env`, private profile, credentials, and snapshot before merge.
3. Targeted offline/live post-merge smoke test with rollback. **User explicitly chooses to keep RemoteJobs.org=1** as a low-cost option even if one initial 50-row sample had no suitable candidate. Proposed daily budgets: Arbeitnow 4, Remotive 1, Himalayas 17, Jobicy 3, Remote OK 1, We Work Remotely 1, RemoteJobs.org 1, Adzuna 0 = 28 requests maximum. Do not alter production `.env`/schedule before release approval.
4. The local legacy-collector test previously broke when optional providers were enabled in the user's `.env`. The fixture now explicitly zeroes all optional budgets; it is independent of local `.env` and needs only 2 canned HTTP responses. 62 environment-stressed regression tests and 144 complete offline tests passed: https://github.com/QayZie96/ai-job-outreach-automation/actions/runs/39032037325.


## Adzuna-hosted saved-HTML PoC result (user-provided, 2026-10-17)

Local user probe:
`python adzuna_saved_page_probe.py --report adzuna_probe/run_auth.json --job-id 5930905647 --html adzuna_probe/5930905647.html`

For The Orchard, `eCommerce Manager - GSA`:
- API excerpt 500 characters.
- Manually saved Adzuna `/details/5930905647` HTML 197,921 bytes.
- Embedded `JobPosting` JSON-LD description 2,790 characters (~5.6x excerpt), title similarity 1.0; canonical identity checked.
- No programmatic provider network calls, redirects, Gemini, or Sheet writes. This is **evidence of available text on that one page**, not proof the posting has a complete description and not authorization for automated harvesting.
- Among the original 20 retained `de:ecommerce` results, 4 URLs used Adzuna `/details/...` format; the others used `/land/ad/...` and must not be presumed Adzuna-hosted pages after redirect.
- **Second independent manually saved `/details` PoC PASSED:** CBR eCommerce, `AI Campaign Specialist (m/w/d)`, job ID `5931419701`. Saved Adzuna HTML 144,930 bytes; API snippet 500 characters; matching `JobPosting` JSON-LD 3,071 characters (~6.1x); title similarity 1.0; canonical identity checked; zero programmatic network, Gemini or Sheet calls. Combined direct-page sample: 2/2 longer structured descriptions, but neither completeness nor automated access permission is established.
- Next evidence gate is not another manual example: inspect and establish Adzuna-hosted automated-access permissions, confirm content quality and test coverage of `/land/ad` redirect-style URLs without contacting unapproved third-party hosts. Do not enable automated enrichment or daily Adzuna budget until these gates are satisfied.
- **Automated fetching remains disabled** unless Adzuna permissions and access policy for HTML detail retrieval are established. Its [API Terms](https://developer.adzuna.com/docs/terms_of_service) expressly forbid contacting third-party content sources from API results; don't follow redirects to publishers. Public API's separate page HTML access permission remains unverified. The Adzuna Intelligence offering advertises licensed full job detail.
- No production changes or increase in Adzuna daily budget are approved from this single success.
