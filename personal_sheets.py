"""Personal-only Google Sheets destination with one authoritative table and two views.

The original six-column RAY Jobs sheet is NEVER read/written by this module.
"""
from __future__ import annotations

from collections import Counter
import hashlib
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
VIEWS = {"Strong Matches": "Strong Match", "Review Queue": "Review"}
VIEW_FORMULAS = {
    "Apply First": '=IFERROR(QUERY(Evaluations!A2:AA,"select * where (Col8 = \'P1\' or Col8 = \'P2\') and Col12 <> \'Dismissed\' order by Col9 asc",0),"")',
    "Strong Matches": '=IFERROR(QUERY(Evaluations!A2:AA,"select * where Col10 = \'Strong Match\' and Col12 <> \'Dismissed\'",0),"")',
    "Review Queue": '=IFERROR(QUERY(Evaluations!A2:AA,"select * where Col10 = \'Review\' and Col12 <> \'Dismissed\'",0),"")',
}


def verify_spreadsheet_destination():
    personal = os.getenv("PERSONAL_GOOGLE_SHEET_ID", "").strip()
    original = os.getenv("GOOGLE_SHEET_ID", "").strip()
    if not personal:
        raise ValueError("PERSONAL_GOOGLE_SHEET_ID is required for --write-sheet")
    if original and personal == original:
        raise ValueError("Personal Sheet ID matches original RAY demonstration Sheet; refusing write")
    if len(personal) < 15:
        raise ValueError("Personal Sheet ID does not look valid")
    return personal


def _service():
    # Reuse RAY's service-account client, but never its Sheet ID or writer.
    from sheets import get_sheets_service
    return get_sheets_service()


def _setup(service, spreadsheet_id):
    sheets_api = service.spreadsheets()
    metadata = sheets_api.get(spreadsheetId=spreadsheet_id, fields="sheets.properties.title").execute()
    existing = {s["properties"]["title"] for s in metadata.get("sheets", [])}
    required = ["Evaluations", "Run Summary", "Apply First", "Pending AI", *VIEWS]
    additions = [{"addSheet": {"properties": {"title": title}}}
                 for title in required if title not in existing]
    if additions:
        sheets_api.batchUpdate(spreadsheetId=spreadsheet_id,
                               body={"requests": additions}).execute()
    values = sheets_api.values()
    for tab, header in (("Evaluations", SHEET_HEADERS), ("Run Summary", RUN_HEADERS)):
        last = "AA" if tab == "Evaluations" else "N"
        response = values.get(spreadsheetId=spreadsheet_id,
                              range=f"'{tab}'!A1:{last}1").execute()
        rows = response.get("values", [])
        if rows and rows[0] != header:
            raise ValueError(f"{tab} has unexpected header; refusing write")
        if not rows:
            values.update(spreadsheetId=spreadsheet_id, range=f"'{tab}'!A1",
                          valueInputOption="RAW", body={"values": [header]}).execute()
    # Existing live views have headers on row 1 and formulas in A2.
    # Never overwrite user-edited formulas or replace the original RAY Sheet.
    for tab, formula in VIEW_FORMULAS.items():
        first = values.get(spreadsheetId=spreadsheet_id, range=f"'{tab}'!A2",
                           valueRenderOption="FORMULA").execute().get("values", [])
        if first and first[0] and first[0][0] != formula:
            raise ValueError(f"{tab} has an unexpected formula in A2; refusing write")
        if not first:
            values.update(spreadsheetId=spreadsheet_id, range=f"'{tab}'!A2",
                          valueInputOption="USER_ENTERED", body={"values": [[formula]]}).execute()

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


def write_personal_results(jobs, provider_stats, http_calls, errors, eval_stats):
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
    for job in jobs:
        url = job.get("job_url")
        if not url or "assessment" not in job:
            continue
        old = by_url.get(url)
        row = _sheet_row(job, old[1] if old else None)
        if old:
            if row != (list(old[1]) + [""] * max(0, len(SHEET_HEADERS) - len(old[1]))):
                pending_update.append({"range": f"'Evaluations'!A{old[0]}:AA{old[0]}", "values": [row]})
        else:
            pending_add.append(row)
            by_url[url] = (-1, row)
    if pending_update:
        values.batchUpdate(spreadsheetId=spreadsheet_id,
                           body={"valueInputOption": "RAW", "data": pending_update}).execute()
    if pending_add:
        values.append(spreadsheetId=spreadsheet_id, range="'Evaluations'!A:AA",
                      valueInputOption="RAW", insertDataOption="INSERT_ROWS",
                      body={"values": pending_add}).execute()
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
    return {"added": len(pending_add), "updated": len(pending_update)}
