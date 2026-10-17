# Personal RAY — posting language hard exclusion (2026-10-17)

## Approved rule
User confirmed: job vacancies published **predominantly in a language other than English or Greek** are not suitable for their job search, even without proof of an explicit language requirement. Do not spend Gemini calls or daily manual-review attention on them.

## Implementation (experimental branch only)
- `personal_posting_language.py`: no external model/dependency/network. Conservative natural-language cue scoring for multiple European languages; unsupported non-Latin writing-system detection. Only job description body is tested; never use geography, employer identity, URLs, country, or title to infer posting language.
- `personal_discovery.py`: when there is sufficient confidence and the role would otherwise be in scope, hard exclude as `posting_language_excluded` with rationale `Posting language not supported: <language> ...`; report `precheck.posting_language_excluded` and per-provider rejections. Do not describe this as proof of the employer's mandatory working language. Remove obsolete German-only ranking penalty.
- Short excerpts, mixed-language adverts, and low-confidence text stay eligible for usual screening and are never assumed unsupported. Specifically exclude only when unsupported natural language clearly dominates supported English/Greek. Explicit English-only working language may preserve a non-English-language advert, barring independent hard requirements.
- `personal_sheets.publish_manual_only_from_report`: re-screen historical frozen job reports before a *new* manual publication, but preserve the original row metadata, status and notes if still selected. Does not purge previous manually published staging rows.
- `personal_screening_v41.replay_audit`: replay historical audit CSVs with the new posting-language rule and record transitions; no provider HTTP/AI/Sheet mutations.
- Full offline `--evaluate-report` path already re-screened the frozen inventory, so it also respects current exclusions.
- All actions confined to `experiment/ray-provider-coverage-audit`; production schedule, production workbook, experimental `.env`, API budgets, Gemini calls and staging sheet unchanged. RemoteJobs.org remains in the proposed opt-in daily mix.

## Verification
- 62 local-configuration-stressed existing tests passed, then 164 total tests passed:
  https://github.com/QayZie96/ai-job-outreach-automation/actions/runs/39061099378
- Cases include German, Dutch, French, Spanish, English, Greek, mixed text, short text, explicit English-only working-language exception, and non-Latin script.
- Cases exercise live collection screening, audit outcomes, frozen audit replay and saved manual-publication safeguard.
- No live provider requests, Gemini calls or Sheet writes required for verification.
- Historical production or staging decisions are not deleted or reclassified retroactively.

## Optional local replay on preserved October 17 Adzuna audit
```powershell
cd "$env:USERPROFILE\Desktop\ai-automation-case-study\ray-provider-audit"
git pull --ff-only
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
.\.venv\Scripts\python.exe personal_screening_v41.py --audit .\adzuna_probe\run_auth_screening_audit.csv --report .\adzuna_probe\run_auth.json --output .\adzuna_probe\language_replay.csv
```
The replay uses original screening outcomes, complete descriptions for only the previously retained jobs, and shorter audit excerpts for prior rejects. Report changes are **diagnostic**, not a perfect rerun of the original 50 rows with full descriptions.

## Known limitations
Deterministic cue detection does not recognize every world language, and a sufficiently mixed posting may be left uncertain. It prioritizes avoiding false exclusions from thin snippets. A later manual language override can be added if evidence justifies it, but no further broad provider crawls are needed.
