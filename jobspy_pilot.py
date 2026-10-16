"""Isolated JobSpy pilot; no scheduler, no production state or Sheets.

Try offline first:
  python jobspy_pilot.py --fixture tests/fixtures/jobspy_sample.json
Then run bounded public searches:
  python jobspy_pilot.py --live
Add --sheet to publish deterministic pilot leads to the separate pilot Sheet.
Add --evaluate to use the existing Gemini evaluation (requires explicit free-tier gate).
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from urllib.parse import parse_qs, urlsplit

from dotenv import load_dotenv

from personal_discovery import (
    canonical_url, deduplicate, prioritize_candidates, screen_candidates,
)
from personal_screening_v41 import load_history, pending_for_review, update_history

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "jobspy_state"
PILOT_SHEET_ID = "1pgfchhc27VaGLy3Z4DjYou1lHQ0j4VH6JQ7lwGSURr8"
PRODUCTION_PERSONAL_SHEET_ID = "160oMgKCoAVnqaBVsPL624kwkGOOZ1Lw8n2bvhRkbitQ"
SEARCHES = (
    # Each invocation is one board and one query, not a page-walking loop.
    ("indeed", "ecommerce operations", "Greece", False),
    ("indeed", "catalog coordinator", "Greece", False),
    ("linkedin", "marketplace operations", "European Union", True),
    ("linkedin", "implementation coordinator", "European Union", True),
)
PER_SEARCH = 12
MAX_RAW = 4 * PER_SEARCH
HEADERS = (
    "Job Title", "Company", "Location", "Remote", "Board", "Source Job ID",
    "Job URL", "Employer URL", "Posted", "Eligibility", "Priority",
    "Screen Outcome", "Geographic Reason", "Role Reason", "Description Present",
    "Previously Seen in JobSpy", "Known in RAY", "Possible Cross-board Duplicate",
    "Review Status", "Notes",
)


def text_value(value):
    if value is None:
        return ""
    val = str(value).strip()
    if val.lower() in {"nan", "nat", "<na>", "none"}:
        return ""
    return val


def truth_value(value):
    return value is True or str(value).strip().lower() in {"true", "1", "yes"}


def source_id(site, url, original):
    stable = text_value(original)
    if stable:
        return stable
    parts = urlsplit(url)
    if site == "indeed":
        return parse_qs(parts.query).get("jk", [""])[0]
    if site == "linkedin":
        found = re.search(r"/(?:view|jobs/view)/(\d+)", parts.path)
        return found.group(1) if found else ""
    return ""


def normalize(row, *, query="fixture"):
    """Map JobSpy DataFrame rows into the existing personal RAY job contract."""
    board = text_value(row.get("site")).lower()
    if board not in {"indeed", "linkedin"}:
        return None
    url = canonical_url(row.get("job_url"))
    if not url:
        return None
    place = ", ".join(dict.fromkeys(
        x for x in (text_value(row.get("city")), text_value(row.get("state")),
                    text_value(row.get("country"))) if x
    )) or "Unknown"
    employer_url = canonical_url(row.get("job_url_direct"))
    lower = text_value(row.get("min_amount"))
    upper = text_value(row.get("max_amount"))
    salary = ""
    if lower or upper:
        salary = " ".join(x for x in (
            text_value(row.get("currency")),
            (lower + "–" + upper).strip("–"),
            text_value(row.get("interval")),
        ) if x)
    date = text_value(row.get("date_posted"))[:10]
    return {
        "source": "JobSpy:" + board,
        "underlying_board": board,
        "source_job_id": source_id(board, url, row.get("id")),
        "job_title": text_value(row.get("title")),
        "company_name": text_value(row.get("company")),
        "location": place,
        "remote": truth_value(row.get("is_remote")),
        "location_restrictions": [],
        "timezone_restrictions": [],
        "job_description": text_value(row.get("description")),
        "job_url": url,
        "employer_url": employer_url,
        "created_at": date,
        "job_types": [text_value(row.get("job_type"))] if text_value(row.get("job_type")) else [],
        "seniority": None,
        "salary": salary,
        "source_attribution": url,
        "source_query": query,
    }


def collect_live(scraper=None):
    """Hard cap: four invocations, 12 results requested each; no bypass or retries."""
    if scraper is None:
        from jobspy import scrape_jobs
        scraper = scrape_jobs
    raw, errors, counts = [], [], Counter()
    blocked = set()
    for site, phrase, location, remote in SEARCHES:
        if site in blocked:
            continue
        label = f"{site}:{phrase}:{location}:{'remote' if remote else 'all'}"
        try:
            result = scraper(
                site_name=[site], search_term=phrase, location=location,
                is_remote=remote, results_wanted=PER_SEARCH, hours_old=168,
                country_indeed="Greece", fetch_description=False, verbose=0,
            )
            rows = result.to_dict(orient="records")
            # Defensive output cap even if the upstream library ignores a limit.
            counts[site] += 1
            for row in rows[:PER_SEARCH]:
                row["source_query"] = label
                raw.append(row)
        except Exception as exc:
            counts[site] += 1
            # Stop this provider after its first failure, never rotate proxies.
            blocked.add(site)
            errors.append(f"{site}: {type(exc).__name__}: {str(exc)[:250]}")
    return raw[:MAX_RAW], dict(counts), errors


def _safe_csv(value):
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def save_csv(path, rows, headers):
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({name: _safe_csv(row.get(name, "")) for name in headers})


def clean_token(value):
    return " ".join(re.sub(r"[^\w ]", " ", text_value(value).casefold()).split())


def possible_crossboard_duplicates(jobs):
    by_signature = defaultdict(list)
    for job in jobs:
        key = (clean_token(job.get("company_name")),
               clean_token(job.get("job_title")),
               clean_token(job.get("location")))
        if all(key):
            by_signature[key].append(job)
    duplicate_urls = set()
    for members in by_signature.values():
        if len({j["underlying_board"] for j in members}) > 1:
            duplicate_urls.update(j["job_url"] for j in members)
    return duplicate_urls


def eligible_sheet():
    configured = os.getenv("JOBSPY_SHEET_ID", "").strip()
    # The pilot is deliberately restricted to its newly created destination.
    if configured != PILOT_SHEET_ID:
        raise ValueError("JOBSPY_SHEET_ID must match the isolated JobSpy pilot spreadsheet")
    if configured == PRODUCTION_PERSONAL_SHEET_ID or configured == os.getenv("GOOGLE_SHEET_ID", "missing"):
        raise ValueError("Refusing to write to any production or demo spreadsheet")
    return configured


def publish_pilot(jobs, details):
    """Upsert deterministic leads only. Does not label them AI evaluated."""
    sheet_id = eligible_sheet()
    from sheets import get_sheets_service
    service = get_sheets_service()
    api = service.spreadsheets()
    existing_sheets = api.get(
        spreadsheetId=sheet_id, fields="sheets(properties(title))",
    ).execute().get("sheets", [])
    if "Pilot Leads" not in {s["properties"]["title"] for s in existing_sheets}:
        api.batchUpdate(spreadsheetId=sheet_id, body={"requests": [
            {"addSheet": {"properties": {"title": "Pilot Leads"}}},
        ]}).execute()
    values = api.values()
    old_head = values.get(spreadsheetId=sheet_id, range="'Pilot Leads'!A1:T1").execute().get("values", [])
    if old_head and old_head[0] != list(HEADERS):
        raise ValueError("Pilot Leads header mismatch; refusing update")
    if not old_head:
        values.update(spreadsheetId=sheet_id, range="'Pilot Leads'!A1",
                      valueInputOption="RAW", body={"values": [list(HEADERS)]}).execute()
    old = values.get(spreadsheetId=sheet_id, range="'Pilot Leads'!A2:T").execute().get("values", [])
    index = {row[6]: (i + 2, row) for i, row in enumerate(old) if len(row) > 6 and row[6]}
    append_rows, patches = [], []
    for job in jobs:
        url = job["job_url"]
        prior = index.get(url)
        old_row = prior[1] if prior else []
        item = details[url]
        row = [
            job["job_title"], job["company_name"], job["location"],
            "Yes" if job["remote"] else "No/unknown",
            job["underlying_board"], job["source_job_id"], url,
            job["employer_url"], job["created_at"],
            job.get("precheck_eligibility", "uncertain"),
            job.get("priority", ""), "Review only" if job.get("review_only") else "Candidate",
            job.get("precheck_reason", ""), job.get("role_evidence_reason", ""),
            "Yes" if job["job_description"] else "No",
            "Yes" if item["seen_before"] else "No",
            "Yes" if item["known_in_ray"] else "No",
            "Review" if item["possible_duplicate"] else "",
            old_row[18] if len(old_row) > 18 and old_row[18] else "New",
            old_row[19] if len(old_row) > 19 else "",
        ]
        if prior:
            padded = old_row + [""] * (len(HEADERS) - len(old_row))
            if padded != row:
                patches.append({"range": f"'Pilot Leads'!A{prior[0]}:T{prior[0]}", "values": [row]})
        else:
            append_rows.append(row)
            index[url] = (-1, row)
    if patches:
        values.batchUpdate(spreadsheetId=sheet_id,
                           body={"valueInputOption": "RAW", "data": patches}).execute()
    if append_rows:
        values.append(spreadsheetId=sheet_id, range="'Pilot Leads'!A:T",
                      valueInputOption="RAW", insertDataOption="INSERT_ROWS",
                      body={"values": append_rows}).execute()
    return {"added": len(append_rows), "updated": len(patches)}


def evaluate(jobs):
    """Reuse identical RAY prompt/evaluator but keep the cache entirely local."""
    if os.getenv("PERSONAL_GEMINI_FREE_TIER_CONFIRMED") != "YES":
        raise RuntimeError("Confirm Gemini billing separately before using --evaluate")
    from personal_evaluation import Evaluator, PersonalCache, profile_text
    profile = profile_text()
    pool = [job for job in jobs if not job.get("review_only")
            and len(job.get("job_description", "")) >= 80]
    shortlist = prioritize_candidates(pool, limit=20)
    cache = PersonalCache(path=STATE / "jobspy_validation_cache.db")
    return Evaluator(profile, cache, max_calls=1).evaluate(shortlist)


def main(args):
    if bool(args.live) == bool(args.fixture):
        raise ValueError("Choose exactly one of --live or --fixture")
    if args.sheet:
        eligible_sheet()  # refuse invalid destination before a scrape or AI call
    if args.evaluate and os.getenv("PERSONAL_GEMINI_FREE_TIER_CONFIRMED") != "YES":
        raise RuntimeError("Gemini free-tier acknowledgement is required to evaluate")
    STATE.mkdir(exist_ok=True)
    if args.fixture:
        data = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError("Fixture must be a JSON array of JobSpy records")
        raw, calls, errors = data[:MAX_RAW], {}, []
    else:
        raw, calls, errors = collect_live()
    normalized = []
    for row in raw:
        job = normalize(row, query=row.get("source_query", "fixture"))
        if job:
            normalized.append(job)
    unique = deduplicate(normalized)
    audit = []
    candidates, screen_counts, rejected = screen_candidates(unique, audit=audit)
    own_history_file = STATE / "jobspy_discovery_history.local.json"
    own_before = load_history(own_history_file)
    ray_history = load_history(args.baseline_history) if args.baseline_history else {}
    known = {canonical_url(url) for url in ray_history}
    dupes = possible_crossboard_duplicates(unique)
    details = {}
    for job in unique:
        url = job["job_url"]
        details[url] = {
            "seen_before": url in own_before,
            "known_in_ray": url in known,
            "possible_duplicate": url in dupes,
        }
    for row in audit:
        row.update(details.get(row["job_url"], {}))
    candidates.sort(key=lambda j: (-j["priority"], j["job_url"]))
    pending = [j for j in candidates if pending_for_review(own_before, j)]
    completed, ai_stats = ([], {})
    if args.evaluate:
        completed, ai_stats = evaluate(pending)
    written = {}
    if args.sheet:
        written = publish_pilot(candidates, details)
        if completed:
            # Reuse exactly the existing RAY Evaluations writer, but force its
            # destination to the isolated pilot spreadsheet for this process.
            from personal_sheets import write_personal_results
            os.environ["PERSONAL_GOOGLE_SHEET_ID"] = eligible_sheet()
            write_personal_results(completed,
                                   Counter(j["source"] for j in normalized),
                                   calls, errors, ai_stats)
    judged = {j["job_url"] for j in completed if j.get("assessment")}
    history_stats = update_history(own_history_file, unique, evaluated_urls=judged)
    save_csv(STATE / "jobspy_candidates.csv", [
        {"Job Title": j["job_title"], "Company": j["company_name"],
         "Location": j["location"], "Remote": j["remote"],
         "Board": j["underlying_board"], "Source Job ID": j["source_job_id"],
         "Job URL": j["job_url"], "Employer URL": j["employer_url"],
         "Posted": j["created_at"], "Eligibility": j.get("precheck_eligibility", ""),
         "Priority": j["priority"], "Screen Outcome": "review_only" if j["review_only"] else "candidate",
         "Geographic Reason": j.get("precheck_reason", ""),
         "Role Reason": j.get("role_evidence_reason", ""),
         "Description Present": bool(j.get("job_description")),
         "Previously Seen in JobSpy": details[j["job_url"]]["seen_before"],
         "Known in RAY": details[j["job_url"]]["known_in_ray"],
         "Possible Cross-board Duplicate": details[j["job_url"]]["possible_duplicate"],
        } for j in candidates], HEADERS)
    save_csv(STATE / "jobspy_screening_audit.csv", audit,
             tuple(dict.fromkeys(k for row in audit for k in row)))
    (STATE / "jobspy_raw.json").write_text(
        json.dumps(raw, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (STATE / "jobspy_normalized.json").write_text(
        json.dumps(unique, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    summary = {
        "run_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "live" if args.live else "fixture",
        "collection_invocations_not_http_count": calls,
        "errors": errors, "raw": len(raw), "valid": len(normalized),
        "unique": len(unique), "candidate_count": len(candidates),
        "pending": len(pending), "screen": screen_counts,
        "rejections": rejected,
        "with_description": sum(bool(j["job_description"]) for j in unique),
        "known_in_ray_by_exact_url": sum(d["known_in_ray"] for d in details.values()),
        "new_by_exact_url_vs_supplied_ray_history": (
            sum(not d["known_in_ray"] for d in details.values()) if args.baseline_history else None
        ),
        "crossboard_duplicate_flags": len(dupes),
        "history": history_stats, "ai": ai_stats, "sheet": written,
    }
    (STATE / "jobspy_report.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    options = parser.add_mutually_exclusive_group(required=True)
    options.add_argument("--fixture", type=Path, help="Offline JobSpy-record JSON array")
    options.add_argument("--live", action="store_true", help="Bounded public JobSpy search")
    parser.add_argument("--baseline-history", type=Path, help="Read-only existing RAY history")
    parser.add_argument("--sheet", action="store_true", help="Upsert pilot leads to separate Sheet")
    parser.add_argument("--evaluate", action="store_true", help="At most 1 Gemini batch (5 jobs)")
    arguments = parser.parse_args()
    load_dotenv(ROOT / ".env.jobspy", override=True)
    main(arguments)
