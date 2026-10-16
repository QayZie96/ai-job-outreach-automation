"""Manual, capped personal job discovery. Preserves the original RAY case study.

Usage: python personal_discovery.py --live [--collect-only] [--write-sheet]
The default does not execute a live job search. --write-sheet is explicit and
requires a NEW personal spreadsheet ID distinct from the original RAY ID.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit, urljoin

import requests
from dotenv import load_dotenv

from personal_evaluation import Evaluator, PersonalCache, profile_text

BASE = Path(__file__).resolve().parent
ARBEITNOW = "https://www.arbeitnow.com/api/job-board-api"
REMOTIVE = "https://remotive.com/api/remote-jobs"
HIMALAYAS = "https://himalayas.app/jobs/api/search"
JOBICY = "https://jobicy.com/api/v2/remote-jobs"
ADZUNA = "https://api.adzuna.com/v1/api/jobs/gb/search/1"
HIMALAYAS_QUERIES = ("ecommerce operations", "marketplace operations",
                     "business operations", "catalog operations")
JOBICY_FILTERS = (("operations", "europe"), ("ecommerce", "anywhere"))
DEFAULT_LIMITS = {"Arbeitnow": 2, "Remotive": 1, "Adzuna": 0,
                  "Himalayas": 4, "Jobicy": 2}
TARGET_TERMS = (
    "operation", "e-commerce", "ecommerce", "marketplace", "catalog",
    "merchandis", "category", "product data", "product information",
    "pricing", "procurement", "purchas", "supplier", "vendor", "inventory",
    "order management", "order processing", "sales ops", "sales support",
    "commercial", "revenue ops", "implementation", "business analyst",
    "business systems", "process improvement", "process excellence",
    "workflow", "automation", "supply chain", "seller support", "seller success",
    "partner operations", "merchant",
)


def env_int(name, default, minimum=0, maximum=50):
    value = int(os.getenv(name, str(default)))
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


class ProviderError(RuntimeError):
    pass


class BudgetedHTTP:
    def __init__(self, limits=None, session=None):
        self.limits = dict(limits if limits is not None else DEFAULT_LIMITS)
        self.calls = Counter()
        self.session = session or requests.Session()

    def get_json(self, source, url, params=None):
        # At most two attempts; failed attempts count against source budget.
        for attempt in range(2):
            if self.calls[source] >= self.limits.get(source, 0):
                raise ProviderError(f"{source} API request budget exhausted")
            self.calls[source] += 1
            try:
                response = self.session.get(url, params=params, timeout=20,
                                            headers={"Accept": "application/json"})
                if response.status_code == 200:
                    payload = response.json()
                    if not isinstance(payload, dict):
                        raise ProviderError(f"{source}: invalid response schema")
                    return payload
                if response.status_code == 429:
                    raise ProviderError(f"{source} rate limited (429); no retry")
                if response.status_code not in {500, 502, 503, 504}:
                    raise ProviderError(f"{source}: HTTP {response.status_code}")
                error = f"HTTP {response.status_code}"
            except (requests.RequestException, ValueError) as exc:
                error = f"{type(exc).__name__}: {exc}"
            if attempt == 0 and self.calls[source] < self.limits.get(source, 0):
                time.sleep(1)
                continue
            raise ProviderError(f"{source}: {error}")
        raise ProviderError(f"{source}: no valid response")


def canonical_url(value):
    value = str(value or "").strip()
    if not value:
        return ""
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    query = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}]
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(),
                       parsed.path.rstrip("/") or "/", urlencode(query), ""))


def iso_date(value):
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000 if value > 1e11 else value,
                                      tz=timezone.utc).date().isoformat()
    return str(value or "")[:10]


def normalize_himalayas(raw):
    result = []
    for item in raw:
        restrictions = item.get("locationRestrictions") or []
        codes = [r.get("alpha2") or r.get("name") for r in restrictions
                 if isinstance(r, dict) and (r.get("alpha2") or r.get("name"))]
        sal = item.get("minSalary"), item.get("maxSalary")
        sal_text = (f"{item.get('currency') or ''} {sal[0] or '?'}–{sal[1] or '?'} "
                    f"{item.get('salaryPeriod') or ''}") if any(s is not None for s in sal) else ""
        result.append({
            "source": "Himalayas", "source_job_id": str(item.get("guid") or ""),
            "job_title": item.get("title") or "", "company_name": item.get("companyName") or "",
            "location": "Worldwide" if not restrictions else ", ".join(
                r.get("name", "") for r in restrictions if isinstance(r, dict)),
            "location_restrictions": codes, "timezone_restrictions": item.get("timezoneRestrictions") or [],
            "remote": True, "job_description": item.get("description") or item.get("excerpt") or "",
            "job_url": item.get("applicationLink") or "", "created_at": iso_date(item.get("pubDate")),
            "job_types": [item.get("employmentType")] if item.get("employmentType") else [],
            "seniority": item.get("seniority"), "salary": sal_text,
            "source_attribution": "https://himalayas.app",
        })
    return result


def normalize_jobicy(raw):
    result = []
    for item in raw:
        types = item.get("jobType") or []
        result.append({
            "source": "Jobicy", "source_job_id": str(item.get("id") or ""),
            "job_title": item.get("jobTitle") or "", "company_name": item.get("companyName") or "",
            "location": item.get("jobGeo") or "Unknown", "remote": True,
            "location_restrictions": [], "timezone_restrictions": [],
            "job_description": item.get("jobDescription") or item.get("jobExcerpt") or "",
            "job_url": item.get("url") or "", "created_at": iso_date(item.get("pubDate")),
            "job_types": types if isinstance(types, list) else [types],
            "seniority": item.get("jobLevel"),
            "salary": (f"{item.get('salaryCurrency') or ''} {item.get('salaryMin') or '?'}–"
                       f"{item.get('salaryMax') or '?'} {item.get('salaryPeriod') or ''}")
                       if item.get("salaryMin") is not None or item.get("salaryMax") is not None else "",
            "source_attribution": "https://jobicy.com",
        })
    return result


def normalize_original(source, raw):
    # Reuse the RAY project's existing normalization functions, not a duplicate
    # implementation. Import lazily to avoid loading the RAY runtime in tests.
    from main import (normalize_arbeitnow_jobs, normalize_remotive_jobs,
                      normalize_adzuna_jobs)
    func = {"Arbeitnow": normalize_arbeitnow_jobs,
            "Remotive": normalize_remotive_jobs,
            "Adzuna": normalize_adzuna_jobs}[source]
    items = func(raw)
    for item, original in zip(items, raw):
        item["source_job_id"] = str(original.get("id") or "")
        item["location_restrictions"] = []
        item["timezone_restrictions"] = []
        item["seniority"] = None
        item["salary"] = ""
        item["source_attribution"] = item.get("job_url") or ""
    return items


def collect(http):
    jobs, stats, errors = [], Counter(), []

    def add(source, raw, convert):
        data = convert(raw)
        stats[source] += len(data)
        jobs.extend(data)

    # Keep the original feeds with much smaller per-run page budgets.
    try:
        url = ARBEITNOW
        visited = set()
        while url and url not in visited and http.calls["Arbeitnow"] < http.limits.get("Arbeitnow", 0):
            parsed = urlsplit(url)
            if parsed.hostname not in {"arbeitnow.com", "www.arbeitnow.com"}:
                raise ProviderError("Arbeitnow next page leaves approved provider host")
            visited.add(url)
            payload = http.get_json("Arbeitnow", url)
            add("Arbeitnow", payload.get("data") or [], lambda raw: normalize_original("Arbeitnow", raw))
            next_link = (payload.get("links") or {}).get("next")
            url = urljoin(url, next_link) if next_link else ""
    except (ProviderError, KeyError, TypeError) as exc:
        errors.append(str(exc))

    try:
        if http.limits.get("Remotive", 0):
            payload = http.get_json("Remotive", REMOTIVE)
            add("Remotive", payload.get("jobs") or [], lambda raw: normalize_original("Remotive", raw))
    except (ProviderError, KeyError, TypeError) as exc:
        errors.append(str(exc))

    # The original RAY Adzuna connector is UK-only, so disable it for a
    # Greece/EU personal search unless the operator deliberately opts in.
    try:
        if http.limits.get("Adzuna", 0):
            app_id, key = os.getenv("ADZUNA_APP_ID"), os.getenv("ADZUNA_APP_KEY")
            if not app_id or not key:
                raise ProviderError("Adzuna enabled but credentials missing")
            params = {"app_id": app_id, "app_key": key,
                      "results_per_page": 20, "what": "business operations"}
            payload = http.get_json("Adzuna", ADZUNA, params)
            add("Adzuna", payload.get("results") or [], lambda raw: normalize_original("Adzuna", raw))
    except (ProviderError, KeyError, TypeError) as exc:
        errors.append(str(exc))

    for query in HIMALAYAS_QUERIES:
        if http.calls["Himalayas"] >= http.limits.get("Himalayas", 0):
            break
        try:
            payload = http.get_json("Himalayas", HIMALAYAS,
                                    {"q": query, "country": "GR", "sort": "recent", "page": 1})
            if payload.get("success") is False:
                raise ProviderError("Himalayas response indicates failure")
            add("Himalayas", payload.get("jobs") or [], normalize_himalayas)
        except (ProviderError, KeyError, TypeError) as exc:
            errors.append(str(exc))

    for tag, geo in JOBICY_FILTERS:
        if http.calls["Jobicy"] >= http.limits.get("Jobicy", 0):
            break
        try:
            payload = http.get_json("Jobicy", JOBICY, {"count": 100, "tag": tag, "geo": geo})
            if payload.get("success") is False:
                raise ProviderError(f"Jobicy: {payload.get('error', 'API failed')}")
            add("Jobicy", payload.get("jobs") or [], normalize_jobicy)
        except (ProviderError, KeyError, TypeError) as exc:
            errors.append(str(exc))
    return jobs, stats, errors


def target_role(job):
    title = re.sub(r"\s+", " ", str(job.get("job_title") or "").lower())
    if not title:
        return False
    if any(term in title for term in TARGET_TERMS):
        return True
    # A generic title can still hide a genuine operational role. Require two
    # distinct signals from the description to avoid flooding Gemini.
    description = re.sub(r"<[^>]+>", " ", str(job.get("job_description") or "").lower())[:10000]
    signals = {term for term in TARGET_TERMS if term in description}
    return len(signals) >= 2


def deduplicate(jobs):
    unique, seen_urls, seen_source_ids, seen_fallbacks = [], set(), set(), set()
    for job in jobs:
        url = canonical_url(job.get("job_url"))
        if not url:
            continue  # cannot link the user to a vacancy; no AI call
        sid = (job.get("source"), str(job.get("source_job_id") or ""))
        if url in seen_urls or (sid[1] and sid in seen_source_ids):
            continue
        # Do NOT dedupe solely by (company,title): distinct requisitions and cities exist.
        job["job_url"] = url
        unique.append(job)
        seen_urls.add(url)
        if sid[1]:
            seen_source_ids.add(sid)
    return unique


def write_report(path, jobs, raw_stats, calls, errors, evaluation_stats):
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    data = {"run_utc": datetime.now(timezone.utc).isoformat(),
            "source_fetched": dict(raw_stats), "source_http_attempts": dict(calls),
            "errors": errors, "evaluation": evaluation_stats,
            "decisions": dict(Counter(j["assessment"]["decision"] for j in jobs if "assessment" in j)),
            "evaluated_jobs": jobs}
    dest.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return dest


def run(*, collect_only=False, write_sheet=False, report_path="personal_run.json", session=None):
    load_dotenv(BASE / ".env")
    limits = {"Arbeitnow": env_int("PERSONAL_MAX_ARBEITNOW_CALLS", 2),
              "Remotive": env_int("PERSONAL_MAX_REMOTIVE_CALLS", 1),
              "Adzuna": env_int("PERSONAL_MAX_ADZUNA_CALLS", 0),
              "Himalayas": env_int("PERSONAL_MAX_HIMALAYAS_CALLS", 4),
              "Jobicy": env_int("PERSONAL_MAX_JOBICY_CALLS", 2)}
    max_ai = env_int("PERSONAL_MAX_GEMINI_CALLS", 5, maximum=10)
    if write_sheet and collect_only:
        raise ValueError("Cannot write unevaluated jobs to Sheets")
    if write_sheet:
        from personal_sheets import verify_spreadsheet_destination
        verify_spreadsheet_destination()  # verify before any provider/LLM request
    candidate_profile = None if collect_only else profile_text()  # fail before paid calls
    if not collect_only and os.getenv("PERSONAL_GEMINI_FREE_TIER_CONFIRMED") != "YES":
        raise RuntimeError("Confirm your Gemini API project will not bill you, then set "
                           "PERSONAL_GEMINI_FREE_TIER_CONFIRMED=YES; ChatGPT plan usage "
                           "does not cover Google Gemini API charges")
    http = BudgetedHTTP(limits, session)
    raw, stats, errors = collect(http)
    unique = deduplicate(raw)
    candidates = [j for j in unique if target_role(j)]
    eval_stats = {"unique": len(unique), "prefiltered_candidates": len(candidates)}
    if collect_only:
        completed = candidates
    else:
        completed, ai = Evaluator(candidate_profile, PersonalCache(), max_calls=max_ai).evaluate(candidates)
        eval_stats.update(ai)
    path = write_report(report_path, completed, stats, http.calls, errors, eval_stats)
    if write_sheet:
        from personal_sheets import write_personal_results
        write_personal_results(completed, stats, http.calls, errors, eval_stats)
    print(f"Personal run complete: {len(raw)} fetched, {len(unique)} unique, "
          f"{len(candidates)} candidates, {len(completed)} evaluated/collected. "
          f"Calls: {dict(http.calls)}. Report: {path}")
    return completed, eval_stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Explicitly allow live provider/API calls")
    parser.add_argument("--collect-only", action="store_true", help="Skip Gemini and Sheets")
    parser.add_argument("--write-sheet", action="store_true", help="Append to NEW personal Sheet")
    parser.add_argument("--report", default="personal_run.json")
    args = parser.parse_args()
    if not args.live:
        parser.error("Pass --live to authorize bounded API calls (no scheduling)")
    run(collect_only=args.collect_only, write_sheet=args.write_sheet, report_path=args.report)
