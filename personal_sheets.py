"""Personal-only Google Sheets destination with one authoritative table and two views.

The original six-column RAY Jobs sheet is NEVER read/written by this module.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import re
from datetime import datetime, timezone
import os

HEADERS = ["Job Title", "Company", "Location", "Work Arrangement", "Source", "Source Job ID",
           "Job URL", "Posted", "Checked", "Eligibility", "Fit Score", "Decision",
           "Matched Evidence", "Mandatory Requirements", "Main Gap or Uncertainty", "Reason",
           "Salary (as posted)", "Review Status", "Notes"]
RUN_HEADERS = ["Run UTC", "Source", "Fetched", "HTTP Attempts", "Evaluated (all sources)",
               "Strong Matches", "Review", "Ineligible", "Low Match", "Cache Hits",
               "Gemini Calls", "Failed Batches", "Unevaluated (budget)", "Errors"]
# Managed legacy field names retained for stable input normalization and tests.
# The native Personal Ray spreadsheet uses the human-first 27-column layout.
SHEET_HEADERS = [
    "Vacancy ID", "Company Name", "Job Title", "Location", "Work Arrangement",
    "Advertised Salary", "AI Fit Score", "Application Priority", "Priority Rank",
    "Decision", "Eligibility", "Review Status", "Recommended Next Action",
    "Job URL", "Posted", "Checked", "Source", "Source Job ID", "Matched Evidence",
    "Mandatory Requirements", "Main Gap or Uncertainty", "Reason", "Notes",
    "Geographic Finding", "Verification State", "Human Review Rationale",
    "AI Reviewed At",
]
LEGACY_TO_SHEET = {
    "Company": "Company Name",
    "Salary (as posted)": "Advertised Salary",
    "Fit Score": "AI Fit Score",
}
VIEW_QUERIES = {
    "New Leads": "Col8 = 'Untriaged' and Col12 <> 'Dismissed' order by Col7 desc",
    "Apply First": "(Col8 = 'P1' or Col8 = 'P2') and Col12 <> 'Dismissed' order by Col9 asc",
    "Strong Matches": "Col10 = 'Strong Match' and Col12 <> 'Dismissed'",
    "Review Queue": "(Col10 = 'Review' or (Col10 = 'Manual Review' and Col8 = 'Untriaged')) and Col12 <> 'Dismissed'",
}
VIEW_TITLE_FORMULA = (
    '=IF(OR(A2="",N2=""),"",HYPERLINK(N2,'
    'IFERROR(VLOOKUP(A2,Evaluations!A:C,3,FALSE),"")))'
)

def _view_formulas(where):
    query = f'QUERY(Evaluations!A2:AA,"select * where {where}",0)'
    other = ",".join(str(i) for i in range(4, len(SHEET_HEADERS) + 1))
    return {
        "A2": f'=IFERROR(LET(q,{query},CHOOSECOLS(q,1,2)),"")',
        "D2": f'=IFERROR(LET(q,{query},CHOOSECOLS(q,{other})),"")',
    }

VIEW_FORMULAS = {name: _view_formulas(where) for name, where in VIEW_QUERIES.items()}
# Only exact legacy formula values may be upgraded in place; user-authored
# formulas remain protected by _setup's fail-closed check.
OLD_REVIEW_QUEUE_FORMULAS = _view_formulas("Col10 = 'Review' and Col12 <> 'Dismissed'")

# Hard safety guard for this experimental branch only. Remove deliberately at
# the separately reviewed promotion point; never write to the live master.
MASTER_PERSONAL_RAY_SHEET_ID = "160oMgKCoAVnqaBVsPL624kwkGOOZ1Lw8n2bvhRkbitQ"


def verify_spreadsheet_destination():
    personal = os.getenv("PERSONAL_GOOGLE_SHEET_ID", "").strip()
    original = os.getenv("GOOGLE_SHEET_ID", "").strip()
    if not personal:
        raise ValueError("PERSONAL_GOOGLE_SHEET_ID is required for --write-sheet")
    if original and personal == original:
        raise ValueError("Personal Sheet ID matches original RAY demonstration Sheet; refusing write")
    if personal == MASTER_PERSONAL_RAY_SHEET_ID:
        raise ValueError("Experimental run targets production Personal Ray master; refusing write")
    if len(personal) < 15:
        raise ValueError("Personal Sheet ID does not look valid")
    return personal


def read_existing_evaluations():
    """Read-only staging Sheet check BEFORE any Gemini spend.

    The staging workbook was copied from the Personal Ray master. Treat its
    existing scored jobs and terminal human decisions as protected records,
    even if the experiment's local SQLite cache/history is empty.
    """
    spreadsheet_id = verify_spreadsheet_destination()
    from personal_discovery import canonical_url
    values = _service().spreadsheets().values().get(
        spreadsheetId=spreadsheet_id, range="'Evaluations'!A2:AA"
    ).execute().get("values", [])
    url_index = SHEET_HEADERS.index("Job URL")
    score_index = SHEET_HEADERS.index("AI Fit Score")
    status_index = SHEET_HEADERS.index("Review Status")
    decided = set()
    scored = set()
    existing = set()
    for row in values:
        if len(row) <= url_index:
            continue
        url = canonical_url(row[url_index])
        if not url:
            continue
        existing.add(url)
        if len(row) > score_index and str(row[score_index]).strip():
            scored.add(url)  # Includes a genuine score of 0.
        status = str(row[status_index]).strip().casefold() if len(row) > status_index else ""
        if status in {"applied", "dismissed", "reviewed", "rejected", "interviewing",
                      "offer", "withdrawn"}:
            decided.add(url)
    return {"existing_urls": existing, "scored_urls": scored,
            "terminal_urls": decided}


def _service():
    # Reuse RAY's service-account client, but never its Sheet ID or writer.
    from sheets import get_sheets_service
    return get_sheets_service()


def _setup(service, spreadsheet_id):
    sheets_api = service.spreadsheets()
    metadata = sheets_api.get(
        spreadsheetId=spreadsheet_id,
        fields="sheets(properties(sheetId,title,gridProperties))",
    ).execute()
    existing = {item["properties"]["title"]: item["properties"]
                for item in metadata.get("sheets", [])}
    # Manual Review remains an untouched historical archive if it exists.
    # Newly created workbooks should have one authoritative vacancy table.
    required = ["Evaluations", "Run Summary", "Pending AI", *VIEW_FORMULAS]
    additions = [{"addSheet": {"properties": {
        "title": title, "gridProperties": {"rowCount": 1000, "columnCount": 27}
    }}} for title in required if title not in existing]
    if additions:
        sheets_api.batchUpdate(spreadsheetId=spreadsheet_id,
                               body={"requests": additions}).execute()
        metadata = sheets_api.get(
            spreadsheetId=spreadsheet_id,
            fields="sheets(properties(sheetId,title,gridProperties))",
        ).execute()
        existing = {item["properties"]["title"]: item["properties"]
                    for item in metadata.get("sheets", [])}
    values = sheets_api.values()
    for tab, header, last in (
        ("Evaluations", SHEET_HEADERS, "AA"),
        ("Run Summary", RUN_HEADERS, "N"),
    ):
        response = values.get(spreadsheetId=spreadsheet_id,
                              range=f"'{tab}'!A1:{last}1").execute()
        rows = response.get("values", [])
        if rows and rows[0] != header:
            raise ValueError(f"{tab} has unexpected header; refusing write")
        if not rows:
            values.update(spreadsheetId=spreadsheet_id, range=f"'{tab}'!A1",
                          valueInputOption="RAW", body={"values": [header]}).execute()
    # QUERY drops source hyperlinks. A:B and D:AA are formula-driven
    # arrays; C2:C1000 are per-row linked titles (auto relative formulas).
    for tab, formulas in VIEW_FORMULAS.items():
        header_row = values.get(spreadsheetId=spreadsheet_id,
                                range=f"'{tab}'!A1:AA1").execute().get("values", [])
        if not header_row:
            values.update(spreadsheetId=spreadsheet_id, range=f"'{tab}'!A1",
                          valueInputOption="RAW",
                          body={"values": [SHEET_HEADERS]}).execute()
        for addr, formula in formulas.items():
            got = values.get(spreadsheetId=spreadsheet_id,
                             range=f"'{tab}'!{addr}",
                             valueRenderOption="FORMULA").execute().get("values", [])
            if got and got[0] and got[0][0] != formula:
                if (tab != "Review Queue" or
                        got[0][0] != OLD_REVIEW_QUEUE_FORMULAS[addr]):
                    raise ValueError(f"{tab}!{addr} has an unexpected formula; refusing write")
            if not got or not got[0] or not got[0][0] or got[0][0] != formula:
                values.update(spreadsheetId=spreadsheet_id, range=f"'{tab}'!{addr}",
                              valueInputOption="USER_ENTERED",
                              body={"values": [[formula]]}).execute()
        got_link = values.get(spreadsheetId=spreadsheet_id,
                              range=f"'{tab}'!C2",
                              valueRenderOption="FORMULA").execute().get("values", [])
        if got_link and got_link[0] and got_link[0][0] != VIEW_TITLE_FORMULA:
            raise ValueError(f"{tab}!C2 has an unexpected hyperlink formula")
        if not got_link:
            props = existing[tab]
            sheets_api.batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={"requests": [{"repeatCell": {
                    "range": {
                        "sheetId": props["sheetId"],
                        "startRowIndex": 1,
                        "endRowIndex": props.get("gridProperties", {}).get("rowCount", 1000),
                        "startColumnIndex": 2,
                        "endColumnIndex": 3,
                    },
                    "cell": {"userEnteredValue": {"formulaValue": VIEW_TITLE_FORMULA}},
                    "fields": "userEnteredValue",
                }}]},
            ).execute()



def _row(job, existing=None):
    assessment = job["assessment"]
    old = list(existing or [])
    old += [""] * max(0, len(HEADERS) - len(old))
    # Preserve an explicit human-approved geographic exclusion after subsequent
    # AI/Sheet syncs; the original Gemini cached judgment may still say Review.
    manual_geo_exclusion = (
        str(old[18]).startswith("Manual eligibility correction:")
        and str(old[9]).lower() == "ineligible"
        and old[11] == "Ineligible"
    )
    return [
        job.get("job_title", ""), job.get("company_name", ""), job.get("location", ""),
        ("Hybrid / EU relocation" if "office-based/hybrid" in job.get("precheck_reason", "")
         else "Remote" if job.get("remote") else "On-site / hybrid / unspecified"),
        job.get("source", ""), job.get("source_job_id", ""), job.get("job_url", ""),
        job.get("created_at", ""), datetime.now(timezone.utc).date().isoformat(),
        ("ineligible" if manual_geo_exclusion else assessment["eligibility"]),
        assessment["fit_score"] if assessment["fit_score"] is not None else "",
        ("Ineligible" if manual_geo_exclusion else assessment["decision"]),
        "; ".join(assessment["matched_evidence"]),
        "; ".join(assessment["mandatory_requirements"]),
        (old[14] if manual_geo_exclusion else assessment["main_gap_or_uncertainty"]),
        (old[15] if manual_geo_exclusion else assessment["reason"]),
        job.get("salary", ""), old[17] or "New", old[18],
    ]


def _job_title_formula(row_num, title):
    """Escaped hyperlink to the posting URL stored in this same row."""
    display = str(title or "").replace('"', '""')
    return f'=IF(N{row_num}="","",HYPERLINK(N{row_num},"{display}"))'


def _vacancy_id(url):
    """Stable identity independent of worksheet row number or reordering."""
    return "RAY-" + hashlib.sha256(str(url).encode("utf-8")).hexdigest()[:10].upper()


def _sheet_row(job, existing=None):
    """Map stable legacy AI fields onto the human-first Sheet layout.

    Preserve manual status, notes, priorities and geography overrides on sync.
    """
    prior = dict(zip(SHEET_HEADERS, list(existing or [])))
    old_legacy = [prior.get(LEGACY_TO_SHEET.get(key, key), "")
                  for key in HEADERS]
    legacy_values = _row(job, old_legacy)
    out = {LEGACY_TO_SHEET.get(key, key): value
           for key, value in zip(HEADERS, legacy_values)}
    url = str(job.get("job_url") or "")
    out["Vacancy ID"] = prior.get("Vacancy ID") or _vacancy_id(url)
    for key in ("Application Priority", "Priority Rank", "Recommended Next Action",
                "Geographic Finding", "Verification State",
                "Human Review Rationale", "AI Reviewed At"):
        out[key] = prior.get(key, "")
    if not out["Application Priority"]:
        out["Application Priority"] = "Untriaged"
    if not out["Recommended Next Action"]:
        out["Recommended Next Action"] = "Verify location eligibility and review fit"
    if not out["Verification State"]:
        out["Verification State"] = "Manual verification required"
    if not out["AI Reviewed At"]:
        out["AI Reviewed At"] = datetime.now(timezone.utc).date().isoformat()
    return [out.get(key, "") for key in SHEET_HEADERS]


# Archived Manual Review schema. The old tab is read-only after migration.
# Manual-only vacancies now live in Evaluations, without fabricated AI scores.
# Review Status and Notes always belong to the user.
MANUAL_HEADERS = [
    "Vacancy ID", "Company", "Job Title", "Location", "Work Arrangement",
    "Eligibility", "Deterministic Priority", "Why Manual Review", "Geography Reason",
    "Source", "Source Query", "Job URL", "Posted", "First Seen", "Last Seen",
    "AI Status", "Review Status", "Notes",
]

def _manual_review_row(job, existing=None, *, today=None):
    """Stable, idempotent manual triage row preserving human edits."""
    if not job.get("review_only") or not job.get("job_url"):
        raise ValueError("Manual Review accepts only review-only jobs with URLs")
    now = today or datetime.now(timezone.utc).date().isoformat()
    old = dict(zip(MANUAL_HEADERS, list(existing or [])))
    reason = str(job.get("precheck_reason") or "")
    return [
        old.get("Vacancy ID") or _vacancy_id(job["job_url"]),
        job.get("company_name", ""), job.get("job_title", ""), job.get("location", ""),
        ("EU relocation review" if "relocation" in reason.lower()
         else "Remote" if job.get("remote") else "On-site/hybrid/unspecified"),
        job.get("precheck_eligibility", "uncertain"),
        job.get("priority", ""), job.get("role_evidence_reason", ""), reason,
        job.get("source", ""), job.get("source_query", ""),
        job["job_url"], job.get("created_at", ""),
        old.get("First Seen") or now, now,
        "Not AI evaluated — manual triage",
        old.get("Review Status") or "New",
        old.get("Notes") or "",
    ]


def _write_manual_review(service, spreadsheet_id, jobs):
    """Append/update a dedicated, durable manual-only queue by canonical job URL.

    Never clears stale jobs: history and human review choices survive future runs.
    Never writes to Evaluations or changes AI judgments.
    """
    values = service.spreadsheets().values()
    old_rows = values.get(
        spreadsheetId=spreadsheet_id, range="'Manual Review'!A2:R",
    ).execute().get("values", [])
    url_idx = MANUAL_HEADERS.index("Job URL")
    existing = {r[url_idx]: (n, r) for n, r in enumerate(old_rows, start=2)
                if len(r) > url_idx and r[url_idx]}
    pending_add, pending_update = [], []
    processed = set()
    for job in jobs:
        url = job.get("job_url", "")
        if not job.get("review_only") or not url or url in processed:
            continue
        processed.add(url)
        prior = existing.get(url)
        row = _manual_review_row(job, prior[1] if prior else None)
        if prior:
            padded = list(prior[1]) + [""] * max(0, len(MANUAL_HEADERS) - len(prior[1]))
            if row != padded:
                pending_update.append({
                    "range": f"'Manual Review'!A{prior[0]}:R{prior[0]}",
                    "values": [row],
                })
        else:
            pending_add.append(row)
    if pending_update:
        values.batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"valueInputOption": "RAW", "data": pending_update},
        ).execute()
    if pending_add:
        values.append(
            spreadsheetId=spreadsheet_id, range="'Manual Review'!A:R",
            valueInputOption="RAW", insertDataOption="INSERT_ROWS",
            body={"values": pending_add},
        ).execute()
    return {"manual_added": len(pending_add), "manual_updated": len(pending_update)}


def _manual_to_evaluation_row(job, *, backlog=False, today=None):
    """One unified non-AI row; no fabricated score, AI date or requirements.

    Caller must not invoke on previously AI-assessed jobs. Existing human
    records are protected by URL-level insertion-only behavior.
    """
    url = str(job.get("job_url") or "").strip()
    if not url or not job.get("review_only") or "assessment" in job:
        raise ValueError("Expected an unassessed manual-review job with URL")
    now = today or datetime.now(timezone.utc).date().isoformat()
    prior = job.get("_archive") or {}
    reason = str(job.get("precheck_reason") or prior.get("Geography Reason") or "")
    rank = job.get("priority")
    why = job.get("role_evidence_reason") or prior.get("Why Manual Review") or ""
    priority_text = (f"Deterministic screening priority {rank}; {why}"
                     if rank not in ("", None) else why)
    vals = {
        "Vacancy ID": prior.get("Vacancy ID") or _vacancy_id(url),
        "Company Name": job.get("company_name", ""),
        "Job Title": job.get("job_title", ""),
        "Location": job.get("location", ""),
        "Work Arrangement": (prior.get("Work Arrangement") or
                             ("EU relocation review" if "relocation" in reason.lower()
                              else "Remote" if job.get("remote") else "On-site/hybrid/unspecified")),
        "Advertised Salary": job.get("salary", ""),
        "AI Fit Score": "",
        "Application Priority": "Backlog" if backlog else "Untriaged",
        "Priority Rank": "",
        "Decision": "Manual Review",
        "Eligibility": job.get("precheck_eligibility") or prior.get("Eligibility") or "uncertain",
        "Review Status": prior.get("Review Status") or job.get("review_status") or "New",
        "Recommended Next Action": ("Historical lead — verify vacancy is still open"
                                    if backlog else
                                    "Verify eligibility and requirements; decide whether to apply"),
        "Job URL": url,
        "Posted": job.get("created_at", ""),
        "Checked": prior.get("Last Seen") or now,
        "Source": job.get("source", ""),
        "Source Job ID": job.get("source_job_id", ""),
        "Matched Evidence": "",
        "Mandatory Requirements": "",
        "Main Gap or Uncertainty": "",
        "Reason": priority_text,
        "Notes": prior.get("Notes") or job.get("notes") or "",
        "Geographic Finding": reason,
        "Verification State": "Not AI evaluated — manual verification required",
        "Human Review Rationale": priority_text,
        "AI Reviewed At": "",
    }
    return [vals.get(key, "") for key in SHEET_HEADERS]


def _write_evaluations_manual(service, spreadsheet_id, jobs, *, backlog=False):
    """Insert-only unified manual leads by canonical URL, preserving scored rows.

    Writes the same Evaluations table as Gemini output. Repeated runs never
    clobber scores, human changes, or notes. No Manual Review tab mutation.
    """
    from personal_discovery import canonical_url
    values = service.spreadsheets().values()
    old_rows = values.get(spreadsheetId=spreadsheet_id,
                          range="'Evaluations'!A2:AA").execute().get("values", [])
    url_idx = SHEET_HEADERS.index("Job URL")
    known = {canonical_url(row[url_idx]) for row in old_rows
             if len(row) > url_idx and canonical_url(row[url_idx])}
    new_rows = []
    for job in jobs:
        url = canonical_url(job.get("job_url"))
        if not url or url in known or not job.get("review_only"):
            continue
        known.add(url)
        new_rows.append(_manual_to_evaluation_row(job, backlog=backlog))
    if not new_rows:
        return {"manual_added": 0, "manual_updated": 0}
    result = values.append(
        spreadsheetId=spreadsheet_id, range="'Evaluations'!A:AA",
        valueInputOption="RAW", insertDataOption="INSERT_ROWS",
        body={"values": new_rows},
    ).execute()
    changed = result.get("updates", {}).get("updatedRange", "")
    match = re.search(r"!A([0-9]+)(?::|$)", changed)
    if not match:
        raise RuntimeError("Cannot verify appended manual rows for title hyperlinks")
    first = int(match.group(1))
    links = [{"range": f"'Evaluations'!C{first+i}",
              "values": [[_job_title_formula(first+i, row[2])]]}
             for i, row in enumerate(new_rows)]
    values.batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"valueInputOption": "USER_ENTERED", "data": links},
    ).execute()
    _extend_evaluations_table(service, spreadsheet_id, first - 1 + len(new_rows))
    return {"manual_added": len(new_rows), "manual_updated": 0}


def _archived_manual_job(row):
    """Convert a frozen historical manual row to a display-only backlog lead."""
    old = dict(zip(MANUAL_HEADERS, row))
    url = old.get("Job URL", "")
    return {
        "job_url": url, "review_only": True,
        "company_name": old.get("Company", ""),
        "job_title": old.get("Job Title", ""),
        "location": old.get("Location", ""),
        "precheck_eligibility": old.get("Eligibility") or "uncertain",
        "precheck_reason": old.get("Geography Reason", ""),
        "priority": old.get("Deterministic Priority", ""),
        "role_evidence_reason": old.get("Why Manual Review", ""),
        "source": old.get("Source", ""),
        "source_query": old.get("Source Query", ""),
        "created_at": old.get("Posted", ""),
        "_archive": old,
    }


def migrate_manual_archive_to_evaluations(*, apply=False):
    """Stage-only one-time consolidation; dry-run by default.

    Never alters original archived Manual Review rows, existing Evaluations
    rows, saved human decisions, Google production workbook or APIs.
    """
    spreadsheet_id = verify_spreadsheet_destination()
    service = _service()
    values = service.spreadsheets().values()
    raw = values.get(spreadsheetId=spreadsheet_id,
                     range="'Manual Review'!A1:R").execute().get("values", [])
    if not raw or raw[0] != MANUAL_HEADERS:
        raise ValueError("Manual Review header mismatch; refusing archive migration")
    existing = values.get(spreadsheetId=spreadsheet_id,
                          range="'Evaluations'!A1:AA").execute().get("values", [])
    if not existing or existing[0] != SHEET_HEADERS:
        raise ValueError("Evaluations header mismatch; refusing archive migration")
    from personal_discovery import canonical_url
    known = {canonical_url(r[SHEET_HEADERS.index("Job URL")]) for r in existing[1:]
             if len(r) > SHEET_HEADERS.index("Job URL")}
    jobs = [_archived_manual_job(r) for r in raw[1:]
            if len(r) > MANUAL_HEADERS.index("Job URL")]
    unique, candidates = set(), []
    for job in jobs:
        url = canonical_url(job["job_url"])
        if url and url not in known and url not in unique:
            unique.add(url)
            candidates.append(job)
    result = {
        "mode": "apply" if apply else "dry_run",
        "archive_count": len(jobs),
        "already_in_evaluations": len(jobs) - len(candidates),
        "backlog_to_add": len(candidates),
        "existing_evaluations": len(existing) - 1,
        "provider_calls": 0, "gemini_calls": 0,
    }
    if apply and candidates:
        _setup(service, spreadsheet_id)  # protection and view migration
        result.update(_write_evaluations_manual(service, spreadsheet_id,
                                               candidates, backlog=True))
    return result


def _extend_evaluations_table(service, spreadsheet_id, required_end):
    """Expand the native table after values.append adds new vacancies.

    The existing dataset remains the source of truth. Formula-driven view tabs
    stay outside native tables to preserve QUERY array-spill behavior.
    """
    api = service.spreadsheets()
    metadata = api.get(
        spreadsheetId=spreadsheet_id,
        fields="sheets(properties(sheetId,title),tables(tableId,name,range))",
    ).execute()
    for sheet in metadata.get("sheets", []):
        props = sheet.get("properties", {})
        if props.get("title") != "Evaluations":
            continue
        for table in sheet.get("tables", []):
            if table.get("name") != "Ray_Evaluations":
                continue
            span = table.get("range", {})
            if int(span.get("endRowIndex", 0)) >= required_end:
                return
            api.batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={"requests": [{"updateTable": {
                    "table": {
                        "tableId": table["tableId"],
                        "range": {
                            "sheetId": props["sheetId"],
                            "startRowIndex": 0,
                            "endRowIndex": required_end,
                            "startColumnIndex": 0,
                            "endColumnIndex": len(SHEET_HEADERS),
                        },
                    },
                    "fields": "range",
                }}]},
            ).execute()
            return


def publish_manual_only_from_report(report_path):
    """Publish old unassessed candidates into unified Evaluations, once per URL.

    No provider HTTP, Gemini, or local history mutation. Existing scored rows
    and human statuses are never overwritten.
    """
    import json
    from pathlib import Path
    data = json.loads(Path(report_path).read_text(encoding="utf-8"))
    jobs = data.get("evaluated_jobs")
    if not isinstance(jobs, list) or not isinstance(data.get("evaluation"), dict):
        raise ValueError("Not a Personal RAY collection report")
    if any("assessment" in job for job in jobs):
        raise ValueError("Refusing AI-assessment report for manual-only publication")
    # Avoid duplicating entries already present in copied master Evaluations.
    # Read-only reference; if unavailable, fail before any Sheet mutation.
    spreadsheet_id = verify_spreadsheet_destination()
    existing = read_existing_evaluations()["existing_urls"]
    from personal_discovery import canonical_url, deduplicate, screen_candidates
    # Frozen reports predate today's screening policies. Do not publish an old
    # unsupported-language lead simply because it was once marked manual-only.
    current, _, _ = screen_candidates(deduplicate([dict(item) for item in jobs]))
    # Use CURRENT decisions only as a gate; preserve original human-facing
    # fields, notes, ordering and metadata when publishing historical rows.
    allowed_manual_urls = {item["job_url"] for item in current
                           if item.get("review_only")}
    manual_jobs = [
        item for item in jobs if item.get("review_only")
        and canonical_url(item.get("job_url")) in allowed_manual_urls
        and canonical_url(item.get("job_url")) not in existing
    ]
    service = _service()
    _setup(service, spreadsheet_id)
    return _write_evaluations_manual(service, spreadsheet_id, manual_jobs)


def write_personal_results(jobs, provider_stats, http_calls, errors, eval_stats, *, manual_jobs=None):
    spreadsheet_id = verify_spreadsheet_destination()
    service = _service()
    _setup(service, spreadsheet_id)
    values = service.spreadsheets().values()
    current = values.get(spreadsheetId=spreadsheet_id, range="'Evaluations'!A2:AA").execute().get("values", [])
    url_col = SHEET_HEADERS.index("Job URL")
    by_url = {r[url_col]: (i + 2, r) for i, r in enumerate(current)
              if len(r) > url_col and r[url_col]}
    pending_add = []
    pending_update = []
    title_links = []
    for job in jobs:
        url = job.get("job_url")
        if not url or "assessment" not in job:
            continue
        old = by_url.get(url)
        row = _sheet_row(job, old[1] if old else None)
        if old:
            if row != (list(old[1]) + [""] * max(0, len(SHEET_HEADERS) - len(old[1]))):
                pending_update.append({"range": f"'Evaluations'!A{old[0]}:AA{old[0]}",
                                       "values": [row]})
            title_links.append({
                "range": f"'Evaluations'!C{old[0]}",
                "values": [[_job_title_formula(old[0], row[2])]],
            })
        else:
            pending_add.append(row)
            by_url[url] = (-1, row)
    if pending_update:
        values.batchUpdate(spreadsheetId=spreadsheet_id,
                           body={"valueInputOption": "RAW",
                                 "data": pending_update}).execute()
    if pending_add:
        appended = values.append(
            spreadsheetId=spreadsheet_id, range="'Evaluations'!A:AA",
            valueInputOption="RAW", insertDataOption="INSERT_ROWS",
            body={"values": pending_add},
        ).execute()
        changed_range = appended.get("updates", {}).get("updatedRange", "")
        found = re.search(r"!A([0-9]+)(?::|$)", changed_range)
        if not found:
            raise RuntimeError("Unable to verify appended row positions for title links")
        first_row = int(found.group(1))
        for offset, row in enumerate(pending_add):
            index = first_row + offset
            title_links.append({
                "range": f"'Evaluations'!C{index}",
                "values": [[_job_title_formula(index, row[2])]],
            })
        _extend_evaluations_table(service, spreadsheet_id,
                                  first_row - 1 + len(pending_add))
    if title_links:
        # Job content always uses RAW. Only validated title formulas are parsed
        # with USER_ENTERED; quoted titles can't inject additional formulas.
        values.batchUpdate(spreadsheetId=spreadsheet_id,
                           body={"valueInputOption": "USER_ENTERED",
                                 "data": title_links}).execute()
    # The five pilot jobs remain in Pending AI until successfully assessed.
    # Update the status, not the source posting details or user's history.
    scored_urls = {str(job.get("job_url") or "") for job in jobs if "assessment" in job}
    pending = values.get(spreadsheetId=spreadsheet_id,
                         range="'Pending AI'!A2:F").execute().get("values", [])
    completed_pending = []
    for row_idx, old_row in enumerate(pending, start=2):
        if len(old_row) > 3 and old_row[3] in scored_urls:
            old_status = old_row[4] if len(old_row) > 4 else ""
            if old_status.startswith("Not scored"):
                completed_pending.append({
                    "range": f"'Pending AI'!E{row_idx}:F{row_idx}",
                    "values": [["Scored", "See Evaluations by Vacancy URL"]],
                })
    if completed_pending:
        values.batchUpdate(spreadsheetId=spreadsheet_id,
                           body={"valueInputOption": "RAW",
                                 "data": completed_pending}).execute()
    decisions = Counter(j["assessment"]["decision"] for j in jobs if "assessment" in j)
    source_names = sorted(set(provider_stats) | set(http_calls))
    now = datetime.now(timezone.utc).isoformat()
    summary_rows = [[now, source, provider_stats.get(source, 0), http_calls.get(source, 0),
                     len(jobs), decisions["Strong Match"], decisions["Review"],
                     decisions["Ineligible"], decisions["Low Match"],
                     eval_stats.get("cache_hits", 0), eval_stats.get("gemini_calls", 0),
                     eval_stats.get("failed_batches", 0),
                     eval_stats.get("unprocessed_budget", 0), " | ".join(errors)[:2000]]
                    for source in source_names] or [[now, "none", 0, 0, len(jobs), 0, 0, 0, 0, 0, 0, 0, 0, ""]]
    values.append(spreadsheetId=spreadsheet_id, range="'Run Summary'!A:N",
                  valueInputOption="RAW", insertDataOption="INSERT_ROWS",
                  body={"values": summary_rows}).execute()
    manual_stats = _write_evaluations_manual(service, spreadsheet_id, manual_jobs or [])
    return {"added": len(pending_add), "updated": len(pending_update), **manual_stats}
