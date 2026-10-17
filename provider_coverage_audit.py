"""Read-only four-provider coverage experiment, run ONLY on the isolated audit branch.

No Gemini, no Sheets, no production history/cache and no scheduler mutation.
All network access is explicitly gated behind --live. A 429 or access block
stops that provider immediately; no authentication, proxy or retries.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import time
from urllib.parse import urljoin, urlsplit

import requests

import personal_discovery as ray

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "provider_audit_results"
HIMA_QUERIES = (None, "operations", "ecommerce", "automation", "marketing", "analyst")
EU_CODES = frozenset(
    "AT BE BG HR CY CZ DK EE FI FR DE GR HU IE IT LV LT LU MT NL PL PT RO SK SI ES SE".split()
)
LIMITS = {"Arbeitnow": 4, "Remotive": 1, "Himalayas": 17, "Jobicy": 7}
MAX_TOTAL_CALLS = sum(LIMITS.values())


class AuditHTTP:
    def __init__(self, session=None, sleep=0.4):
        self.session = session or requests.Session()
        self.counts = Counter()
        self.logs = []
        self.blocked = set()
        self.sleep = sleep

    def get(self, provider, url, params=None):
        if provider in self.blocked or self.counts[provider] >= LIMITS[provider]:
            return None
        if sum(self.counts.values()) >= MAX_TOTAL_CALLS:
            return None
        # Allow only the intended public hosts, including Arbeitnow's next link.
        host = urlsplit(url).hostname
        expected = {
            "Arbeitnow": {"www.arbeitnow.com", "arbeitnow.com"},
            "Remotive": {"remotive.com"},
            "Himalayas": {"himalayas.app"},
            "Jobicy": {"jobicy.com"},
        }[provider]
        if host not in expected or urlsplit(url).scheme != "https":
            self.blocked.add(provider)
            self.logs.append({"provider": provider, "error": "unapproved host"})
            return None
        self.counts[provider] += 1
        entry = {
            "provider": provider, "path": urlsplit(url).path,
            "query": {k: v for k, v in (params or {}).items() if k != "cursor"},
            "has_cursor": bool((params or {}).get("cursor")),
            "status": None, "count": 0,
        }
        self.logs.append(entry)
        try:
            response = self.session.get(
                url, params=params, headers={"Accept": "application/json"},
                timeout=20,
            )
            entry["status"] = response.status_code
            if response.status_code != 200:
                entry["error"] = "HTTP " + str(response.status_code)
                if response.status_code in (401, 403, 429) or response.status_code >= 500:
                    self.blocked.add(provider)
                return None
            data = response.json()
            if not isinstance(data, dict) or data.get("success") is False:
                entry["error"] = "invalid/error JSON response"
                self.blocked.add(provider)
                return None
            entry["count"] = len(data.get("jobs") or data.get("data") or [])
            return data
        except (requests.RequestException, ValueError) as exc:
            self.blocked.add(provider)
            entry["error"] = type(exc).__name__ + ": " + str(exc)[:160]
            return None
        finally:
            if self.sleep:
                time.sleep(self.sleep)


def convert(source, rows, label):
    if source == "Himalayas":
        normalized = ray.normalize_himalayas(rows)
    elif source == "Jobicy":
        normalized = ray.normalize_jobicy(rows)
    else:
        normalized = ray.normalize_original(source, rows)
    for job in normalized:
        job["source_query"] = label
    return normalized


def gather(http):
    baseline, extra = [], []
    plans = []

    # Exact production baseline for Arbeitnow: two pages following links.next.
    url = ray.ARBEITNOW
    for page in range(1, 5):
        if not url:
            break
        response = http.get("Arbeitnow", url)
        if response is None:
            break
        data = response.get("data") or []
        (baseline if page <= 2 else extra).extend(
            convert("Arbeitnow", data, f"page:{page}")
        )
        plans.append({"provider": "Arbeitnow", "variant": "baseline" if page <= 2 else "extra",
                      "name": f"page:{page}", "fetched": len(data)})
        next_url = (response.get("links") or {}).get("next")
        url = urljoin(url, next_url) if next_url else ""

    # Exact production baseline for Remotive: one full feed request.
    response = http.get("Remotive", ray.REMOTIVE)
    if response is not None:
        data = response.get("jobs") or []
        baseline.extend(convert("Remotive", data, "unfiltered"))
        plans.append({"provider": "Remotive", "variant": "baseline",
                      "name": "unfiltered", "fetched": len(data)})

    # Exact production Himalayas: country=GR, six queries, first page only.
    first = {}
    for term in HIMA_QUERIES:
        params = {"country": "GR", "sort": "recent", "page": 1}
        if term:
            params["q"] = term
        response = http.get("Himalayas", ray.HIMALAYAS, params)
        if response is None:
            break
        data = response.get("jobs") or []
        first[term] = response
        baseline.extend(convert("Himalayas", data, f"GR:{term or 'all'}:p1"))
        plans.append({"provider": "Himalayas", "variant": "baseline",
                      "name": f"GR:{term or 'all'}:p1", "fetched": len(data),
                      "total_count": response.get("totalCount")})

    # Only first extra page per baseline query; no unlimited pagination.
    for term in HIMA_QUERIES:
        if term not in first or not first[term].get("jobs"):
            continue
        params = {"country": "GR", "sort": "recent", "page": 2}
        if term:
            params["q"] = term
        response = http.get("Himalayas", ray.HIMALAYAS, params)
        if response is None:
            break
        data = response.get("jobs") or []
        extra.extend(convert("Himalayas", data, f"GR:{term or 'all'}:p2"))
        plans.append({"provider": "Himalayas", "variant": "extra",
                      "name": f"GR:{term or 'all'}:p2", "fetched": len(data),
                      "total_count": response.get("totalCount")})

    # Test relocation/Europe coverage without Greece-only filtering.
    for term in ("operations", "ecommerce", "automation"):
        response = http.get("Himalayas", ray.HIMALAYAS,
                            {"q": term, "sort": "recent", "page": 1})
        if response is None:
            break
        data = response.get("jobs") or []
        extra.extend(convert("Himalayas", data, f"global:{term}:p1"))
        plans.append({"provider": "Himalayas", "variant": "extra",
                      "name": f"global:{term}:p1", "fetched": len(data),
                      "total_count": response.get("totalCount")})

    # Cursor-based browse sample: only two pages, not a global-feed crawl.
    response = http.get("Himalayas", "https://himalayas.app/jobs/api", {"limit": 20})
    if response is not None:
        data = response.get("jobs") or []
        extra.extend(convert("Himalayas", data, "browse:p1"))
        plans.append({"provider": "Himalayas", "variant": "extra",
                      "name": "browse:p1", "fetched": len(data),
                      "total_count": response.get("totalCount")})
        cursor = response.get("nextCursor")
        if isinstance(cursor, str) and cursor:
            follow = http.get("Himalayas", "https://himalayas.app/jobs/api",
                              {"limit": 20, "cursor": cursor})
            if follow is not None:
                data = follow.get("jobs") or []
                extra.extend(convert("Himalayas", data, "browse:p2"))
                plans.append({"provider": "Himalayas", "variant": "extra",
                              "name": "browse:p2", "fetched": len(data)})

    # Exact Jobicy production baseline: geo=europe and geo=anywhere, count=200.
    cursors = []
    for geo in ("europe", "anywhere"):
        params = {"count": 200, "geo": geo}
        response = http.get("Jobicy", ray.JOBICY, params)
        if response is None:
            break
        data = response.get("jobs") or []
        baseline.extend(convert("Jobicy", data, f"geo:{geo}:p1"))
        plans.append({"provider": "Jobicy", "variant": "baseline",
                      "name": f"geo:{geo}:p1", "fetched": len(data),
                      "has_more": response.get("hasMore"), "has_cursor": bool(response.get("nextCursor"))})
        if response.get("nextCursor"):
            cursors.append((geo, response["nextCursor"]))

    for geo, cursor in cursors:
        response = http.get("Jobicy", ray.JOBICY, {"count": 200, "geo": geo, "cursor": cursor})
        if response is None:
            break
        data = response.get("jobs") or []
        extra.extend(convert("Jobicy", data, f"geo:{geo}:p2"))
        plans.append({"provider": "Jobicy", "variant": "extra",
                      "name": f"geo:{geo}:p2", "fetched": len(data),
                      "has_more": response.get("hasMore")})

    # Avoid speculative more geography probes if provider started rejecting us.
    for geo in (None, "greece", "emea"):
        params = {"count": 200}
        if geo:
            params["geo"] = geo
        response = http.get("Jobicy", ray.JOBICY, params)
        if response is None:
            if "Jobicy" in http.blocked:
                break
            continue
        data = response.get("jobs") or []
        extra.extend(convert("Jobicy", data, f"geo:{geo or 'unfiltered'}:p1"))
        plans.append({"provider": "Jobicy", "variant": "extra",
                      "name": f"geo:{geo or 'unfiltered'}:p1", "fetched": len(data),
                      "has_more": response.get("hasMore"), "has_cursor": bool(response.get("nextCursor"))})
    return baseline, extra, plans


def possible_relocation_false_negative(job, row):
    if row.get("screen_outcome") != "geography_excluded":
        return False
    if row.get("role_score", 0) <= 0:
        return False
    if job["source"] == "Himalayas" and job.get("location_restrictions"):
        restrictions = {str(x).upper() for x in job["location_restrictions"]}
        return bool(restrictions & EU_CODES)
    if job.get("remote") and job.get("location"):
        place = str(job["location"]).lower()
        return any(ray._has_phrase(place, x) for x in ray.EU_COUNTRIES + ray.EU_CITIES)
    return False


def count_outcomes(jobs):
    audit = []
    accepted, counts, rejects = ray.screen_candidates(jobs, audit=audit)
    lookups = {job["job_url"]: job for job in jobs}
    geo_flags = [
        row for row in audit if possible_relocation_false_negative(
            lookups[row["job_url"]], row
        )
    ]
    by_source = {}
    for provider in sorted({job["source"] for job in jobs}):
        group = [a for a in audit if a["source"] == provider]
        by_source[provider] = {
            "unique": len(group),
            "candidates": sum(r["screen_outcome"] == "candidate" for r in group),
            "review_only": sum(r["screen_outcome"] == "review_only" for r in group),
            "role_excluded": sum(r["screen_outcome"] == "role_out_of_scope" for r in group),
            "geography_excluded": sum(r["screen_outcome"] == "geography_excluded" for r in group),
            "potential_eu_relocation_false_negatives": sum(r in geo_flags for r in group),
        }
    return audit, accepted, counts, rejects, geo_flags, by_source


def safe_cell(val):
    t = str(val or "")
    return "'" + t if t.lstrip().startswith(("=", "+", "-", "@")) else t


def compare(baseline, extra, plans, http):
    base_unique = ray.deduplicate(baseline)
    all_unique = ray.deduplicate(baseline + extra)
    base_urls = {j["job_url"] for j in base_unique}
    extra_unique = [j for j in all_unique if j["job_url"] not in base_urls]
    base_audit, base_accepted, base_counts, _, base_geo, base_by_source = count_outcomes(base_unique)
    extra_audit, extra_accepted, extra_counts, _, extra_geo, extra_by_source = count_outcomes(extra_unique)
    picked = sorted(extra_accepted, key=lambda j: (-j["priority"], j["source"]))[:60]
    audit_by_url = {a["job_url"]: a for a in extra_audit}
    examples = [{
        "provider": j["source"], "title": j.get("job_title", ""), "company": j.get("company_name", ""),
        "location": j.get("location", ""), "url": j.get("job_url", ""),
        "query": j.get("source_query", ""), "classification": audit_by_url[j["job_url"]]["screen_outcome"],
        "eligibility": j.get("precheck_eligibility", ""),
        "reason": j.get("precheck_reason", ""), "priority": j.get("priority", ""),
    } for j in picked]
    summary = {
        "run_utc": datetime.now(timezone.utc).isoformat(),
        "method": "same-run baseline-vs-additional inventory, not comparison with private production history",
        "baseline": {"raw": len(baseline), "unique": len(base_unique),
                     "accepted": len(base_accepted), "outcomes": base_counts,
                     "potential_eu_relocation_false_negatives": len(base_geo),
                     "by_source": base_by_source},
        "extended_only": {"raw": len(extra), "incremental_unique": len(extra_unique),
                          "accepted": len(extra_accepted), "outcomes": extra_counts,
                          "potential_eu_relocation_false_negatives": len(extra_geo),
                          "by_source": extra_by_source},
        "total_unique": len(all_unique),
        "request_budget": LIMITS,
        "calls": dict(http.counts), "blocked": sorted(http.blocked),
        "requests": http.logs, "query_yield": plans,
        "candidates_sample_count": len(examples),
        "candidate_examples": examples[:16],
        "important_limits": [
            "No Gemini evaluation or manual verification; deterministic candidates are not confirmed eligible",
            "Cloud-runner network blocking may differ from the user's Windows connection",
            "Provider feed and first pages may change between production collection and this sample",
            "Known production Sheet/history URLs were not included in the runner",
        ],
    }
    return summary, examples, extra_audit


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Explicit public provider access")
    args = parser.parse_args()
    if not args.live:
        parser.error("Pass --live. No scheduled calls or other side effects.")
    http = AuditHTTP()
    baseline, extra, plans = gather(http)
    summary, examples, extra_audit = compare(baseline, extra, plans, http)
    OUT.mkdir(exist_ok=True)
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False),
                                      encoding="utf-8")
    with (OUT / "extra_candidates.csv").open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=[
            "provider", "title", "company", "location", "url", "query",
            "classification", "eligibility", "reason", "priority"])
        writer.writeheader()
        writer.writerows([{k: safe_cell(v) for k, v in x.items()} for x in examples])
    with (OUT / "extra_screening_audit.csv").open("w", encoding="utf-8-sig", newline="") as file:
        fields = ["source", "job_title", "company", "location", "job_url", "source_query",
                  "role_score", "role_reason", "eligibility", "eligibility_reason",
                  "screen_outcome", "priority"]
        writer = csv.DictWriter(file, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows([{k: safe_cell(x.get(k)) for k in fields} for x in extra_audit])
    print(json.dumps({k: summary[k] for k in ("run_utc", "baseline", "extended_only",
                    "calls", "blocked", "candidates_sample_count")}, ensure_ascii=False))
    # Do not silently count an all-blocked remote run as successful.
    if not summary["baseline"]["raw"] and not summary["extended_only"]["raw"]:
        raise RuntimeError("All providers returned no usable public listings")


if __name__ == "__main__":
    main()
