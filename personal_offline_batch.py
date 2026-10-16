"""Offline-first Gemini scoring for an EXISTING personal RAY collection report.

Default: local preview, zero network. --evaluate: at most one Gemini
request, zero job-board calls, no Google Sheet writes. --sync-sheet:
separate, explicit publication of saved AI results to the personal Sheet.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
DEFAULT_HISTORY = ROOT / "personal_discovery_history.local.json"
DEFAULT_REPORT = ROOT / "personal_run_v4.json"
DEFAULT_OUTPUT = ROOT / "personal_offline_ai_v1.json"
MAX_BATCH = 20
ADJACENT = re.compile(
    r"\b(?:assistant|coordinator|administrator|admin|analyst|associate|junior|"
    r"campaign|crm|lifecycle|marketing specialist|marketing assistant|"
    r"customer success|project manager|business support|sales support|"
    r"gtm systems|implementation|office support|e-commerce|ecommerce|marketplace)\b",
    re.I,
)
SENIOR = re.compile(r"\b(?:senior|sr\.?|lead|head of|director|vice president|vp|chief|principal|staff)\b", re.I)
MANDATORY_TITLE_LANGUAGE = re.compile(
    r"\b(?:german|spanish|dutch|french|portuguese|polish|swedish|italian|"
    r"russian|ukrainian|arabic|japanese)\s+(?:and\s+english\s+)?(?:speaking|fluency|required)\b",
    re.I,
)


def _read(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return data


def _atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    try:
        temp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def select_jobs(report, history, limit=20, include_review=8):
    """Reapply v4.1 rules and skip previously reviewed or AI-judged URLs."""
    from personal_screening_v41 import calibrated_factors, pending_for_review

    if not 1 <= limit <= MAX_BATCH or not 0 <= include_review <= limit:
        raise ValueError("Require 1..20 total and 0..limit manual-review jobs")
    core, manual, seen = [], [], set()
    counts = dict(in_report=0, duplicates=0, already_judged_or_reviewed=0,
                  hard_excluded=0, manual_deferred=0)
    for original in report.get("evaluated_jobs", []):
        counts["in_report"] += 1
        url = str(original.get("job_url") or "").strip()
        if not url or url in seen:
            counts["duplicates"] += 1
            continue
        seen.add(url)
        if original.get("assessment") or not pending_for_review(history, original):
            counts["already_judged_or_reviewed"] += 1
            continue
        if original.get("precheck_eligibility") == "ineligible":
            counts["hard_excluded"] += 1
            continue
        title = str(original.get("job_title") or "")
        if MANDATORY_TITLE_LANGUAGE.search(title):
            counts["hard_excluded"] += 1
            continue
        factors = calibrated_factors(title, original.get("job_description", ""))
        if factors["hard_exclusion"]:
            counts["hard_excluded"] += 1
            continue
        job = dict(original)
        job["calibration_flags"] = factors["flags"]
        job["offline_priority"] = int(job.get("priority") or 0) + factors["priority_delta"]
        job["offline_lane"] = "manual_review" if (job.get("review_only") or factors["force_review"]) else "candidate"
        if job["offline_lane"] == "candidate":
            core.append(job)
        else:
            if factors["flags"] or SENIOR.search(title) or not ADJACENT.search(title):
                counts["manual_deferred"] += 1
                continue
            t = title.lower()
            job["offline_priority"] += (
                20 if "junior" in t else
                16 if "assistant" in t else
                9 if "coordinator" in t or "analyst" in t else
                6 if "campaign" in t or "crm" in t or "lifecycle" in t else 0
            )
            manual.append(job)
    core.sort(key=lambda j: (-j["offline_priority"], j["job_url"]))
    manual.sort(key=lambda j: (-j["offline_priority"], j["job_url"]))
    selected = core[:limit]
    selected.extend(manual[:min(include_review, limit - len(selected))])
    counts.update(candidate_available=len(core), manual_available=len(manual),
                  selected_core=sum(j["offline_lane"] == "candidate" for j in selected),
                  selected_adjacent=sum(j["offline_lane"] == "manual_review" for j in selected),
                  selected_total=len(selected))
    return selected, counts


def mark_ai_judged_only(history_path, jobs, at):
    """An offline evaluation is NOT a provider observation: don't change last_seen."""
    from personal_screening_v41 import load_history
    history = load_history(history_path)
    newly_judged = 0
    for job in jobs:
        if "assessment" not in job:
            continue
        url = job["job_url"]
        prior = history.get(url, {})
        newly_judged += not bool(prior.get("ai_judged", False))
        history[url] = {
            **prior,
            "url": url,
            "source": prior.get("source") or job.get("source", ""),
            "company": prior.get("company") or job.get("company_name", ""),
            "title": prior.get("title") or job.get("job_title", ""),
            "review_status": prior.get("review_status", "pending"),
            "ai_judged": True,
            "ai_judged_at": prior.get("ai_judged_at") or at,
            "last_ai_assessment": job["assessment"].get("decision", "Review"),
        }
    if jobs:
        _atomic_json(history_path, history)
    return newly_judged


def run(input_path, history_path, output_path, limit=20, include_review=8, evaluate=False):
    from personal_screening_v41 import load_history
    input_path, history_path, output_path = map(Path, (input_path, history_path, output_path))
    if input_path.resolve() == output_path.resolve():
        raise ValueError("Refusing to overwrite original collection report")
    report = _read(input_path)
    selected, stats = select_jobs(report, load_history(history_path), limit, include_review)
    print(json.dumps({
        "mode": "gemini" if evaluate else "offline_preview",
        "selection": stats,
        "jobs": [{"company": j.get("company_name"), "title": j.get("job_title"),
                  "lane": j["offline_lane"], "eligibility": j.get("precheck_eligibility"),
                  "url": j.get("job_url")} for j in selected],
    }, ensure_ascii=False, indent=2))
    if not evaluate:
        return {"preview": True, "selection": stats}

    if os.getenv("PERSONAL_GEMINI_FREE_TIER_CONFIRMED", "").upper() != "YES":
        raise RuntimeError("Free-tier acknowledgement missing in .env")
    if not os.getenv("GEMINI_API_KEY"):
        raise RuntimeError("GEMINI_API_KEY missing in .env")
    from personal_evaluation import Evaluator, PersonalCache, profile_text
    profile = profile_text()  # fail before any API calls if CV evidence is missing
    old_output = _read(output_path) if output_path.exists() else {}
    if old_output and not old_output.get("evaluation", {}).get("offline_from_saved_report"):
        raise ValueError("Existing output is not an offline AI report; refusing overwrite")
    previous_scored = {j["job_url"]: j for j in old_output.get("evaluated_jobs", [])
                       if j.get("job_url") and "assessment" in j}
    if not selected:
        print(f"No new evaluations; Gemini not called. Preserved {len(previous_scored)} prior scores.")
        return {"preview": False, "gemini_calls": 0, "existing_scored": len(previous_scored)}
    scored, ai_stats = Evaluator(profile, PersonalCache(), max_calls=1).evaluate(selected)
    for job in scored:
        previous_scored[job["job_url"]] = job
    timestamp = datetime.now(timezone.utc).isoformat()
    data = {
        "run_utc": timestamp, "input_report": str(input_path),
        "collection_run_utc": report.get("run_utc"),
        "source_fetched": report.get("source_fetched", {}),
        "source_http_attempts": {"Arbeitnow": 0, "Remotive": 0, "Himalayas": 0, "Jobicy": 0},
        "errors": [] if not ai_stats.get("failed_batches") else ["Gemini batch failed; check console"],
        "evaluation": {**ai_stats, "selection": stats, "offline_from_saved_report": True},
        "evaluated_jobs": list(previous_scored.values()),
    }
    _atomic_json(output_path, data)
    marked = mark_ai_judged_only(history_path, scored, timestamp)
    print(json.dumps({
        "report": str(output_path), "new_scored": len(scored),
        "total_saved": len(previous_scored), "marked_judged": marked,
        "gemini_calls": ai_stats["gemini_calls"], "cache_hits": ai_stats["cache_hits"],
        "failed_batches": ai_stats["failed_batches"],
    }, indent=2))
    return data


def sync_sheet(output_path):
    """Explicit step; neither discovery nor Gemini is called."""
    from personal_sheets import verify_spreadsheet_destination, write_personal_results
    from sheets import CREDENTIALS_PATH
    verify_spreadsheet_destination()
    if not CREDENTIALS_PATH.is_file():
        raise FileNotFoundError(
            f"Google service account credentials missing: {CREDENTIALS_PATH}. "
            "Share the new Sheet with the service account client_email as Editor."
        )
    saved = _read(output_path)
    if not saved.get("evaluation", {}).get("offline_from_saved_report"):
        raise ValueError("Expected saved results from this offline AI runner")
    jobs = saved.get("evaluated_jobs", [])
    if not jobs:
        print("No evaluated jobs to publish")
        return {"added": 0, "updated": 0}
    return write_personal_results(jobs, {}, {}, saved.get("errors", []), saved["evaluation"])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--history", type=Path, default=DEFAULT_HISTORY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--include-review", type=int, default=8)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--evaluate", action="store_true", help="At most ONE Gemini call; no job-board/Sheet calls")
    modes.add_argument("--sync-sheet", action="store_true", help="Publish the saved AI report to the personal Google Sheet")
    args = parser.parse_args(argv)
    load_dotenv(ROOT / ".env")
    if args.sync_sheet:
        print(json.dumps(sync_sheet(args.output), indent=2))
    else:
        run(args.input, args.history, args.output, args.limit, args.include_review, args.evaluate)


if __name__ == "__main__":
    main()
