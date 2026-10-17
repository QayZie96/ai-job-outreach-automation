"""Second-stage measured RAY coverage probe; standalone, one-off, read-only.

Runs the original baseline and first expansion again, then tests a moderate
additional pagination and targeted-keyword budget. No Gemini, Sheets, state,
scheduler, or API keys. Stops providers on rate limits.
"""
from __future__ import annotations

from collections import Counter
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import re

import personal_discovery as ray
import provider_coverage_audit as prior

OUT = Path(__file__).resolve().parent / "provider_depth_results"

# Below the available documented daily API allowance; cautious for shared unauthenticated pool.
HIMALAYAS_DEPTH = 44  # 17 first pilot + up to 26 extra probes, 1 reserve
LIMITS = {"Arbeitnow": 5, "Remotive": 1, "Himalayas": HIMALAYAS_DEPTH, "Jobicy": 7}
TARGETED_GR = ("catalogue", "product data", "pricing", "procurement",
               "implementation", "marketplace", "business operations")
TARGETED_PAGES = (1, 2)
EXISTING_DEEP_PAGES = (3, 4)
MAX_TOTAL = sum(LIMITS.values())


def search(http, term, page, *, country="GR"):
    params = {"sort": "recent", "page": page}
    if term:
        params["q"] = term
    if country:
        params["country"] = country
    return http.get("Himalayas", ray.HIMALAYAS, params)


def grow(http, known_urls):
    additions = []
    performance = []
    seen = set(known_urls)

    def accept(provider, label, rows):
        jobs = prior.convert(provider, rows, label)
        # Normalized job URLs are the basis for incremental discovery.
        valid = ray.deduplicate(jobs)
        incremental = []
        for job in valid:
            if job["job_url"] not in seen:
                seen.add(job["job_url"])
                incremental.append(job)
        scan, survivors, counts, _, geo_flags, _ = prior.count_outcomes(incremental)
        cand = sum(r["screen_outcome"] == "candidate" for r in scan)
        review = sum(r["screen_outcome"] == "review_only" for r in scan)
        additions.extend(incremental)
        performance.append({
            "source": provider, "query": label, "fetched": len(rows),
            "incremental_unique": len(incremental), "initial_candidates": cand,
            "manual_review_only": review, "geo_review_flags": len(geo_flags),
            "out_of_scope": counts.get("role_out_of_scope", 0),
            "language_excluded": counts.get("mandatory_language_excluded", 0),
        })

    # Page 4 was short (275) in the first pilot. Check whether page 5 exists,
    # but do not fan out blindly.
    last_link = None
    # Existing prior.gather consumes Arbeitnow pages 1–4. A fifth-page endpoint
    # can only be followed from next-link metadata; we intentionally do not
    # invent a pagination URL, so Arbeitnow expansion remains pages 1–4.
    # All further requests here are to officially documented search parameters.

    for term in prior.HIMA_QUERIES:
        if "Himalayas" in http.blocked:
            break
        for page in EXISTING_DEEP_PAGES:
            if http.counts["Himalayas"] >= LIMITS["Himalayas"]:
                break
            response = search(http, term, page)
            if response is None:
                break
            rows = response.get("jobs") or []
            label = f"GR:{term or 'all'}:p{page}"
            accept("Himalayas", label, rows)
            if not rows:
                break

    for term in TARGETED_GR:
        if "Himalayas" in http.blocked:
            break
        for page in TARGETED_PAGES:
            if http.counts["Himalayas"] >= LIMITS["Himalayas"]:
                break
            response = search(http, term, page)
            if response is None:
                break
            rows = response.get("jobs") or []
            label = f"GR:{term}:p{page}"
            accept("Himalayas", label, rows)
            if not rows:
                break

    return additions, performance


def run():
    # Audit module's limits are process-local; production code remains unmodified.
    prior.LIMITS = dict(LIMITS)
    prior.MAX_TOTAL_CALLS = MAX_TOTAL
    http = prior.AuditHTTP(sleep=0.8)
    baseline, previous_extension, earlier_queries = prior.gather(http)
    base_unique = ray.deduplicate(baseline)
    mid_unique = ray.deduplicate(baseline + previous_extension)
    old_urls = {j["job_url"] for j in mid_unique}
    extra, depth_performance = grow(http, old_urls)
    deep_unique = ray.deduplicate(baseline + previous_extension + extra)

    # Run same unchanged screening on the complete same-day inventory.
    baseline_audit, base_survivors, base_counts, _, _, _ = prior.count_outcomes(base_unique)
    mid_only = [j for j in mid_unique if j["job_url"] not in {x["job_url"] for x in base_unique}]
    mid_audit, mid_survivors, mid_counts, _, _, _ = prior.count_outcomes(mid_only)
    deep_audit, deep_survivors, deep_counts, _, _, _ = prior.count_outcomes(extra)

    # Trustworthy comparison: same-run totals and absolute new URLs, not
    # guessed matches against PC-only private RAY history.
    stats = {
        "at_utc": datetime.now(timezone.utc).isoformat(),
        "method": "same-run stages: production baseline, previous moderate expansion, new depth",
        "limits": dict(LIMITS), "total_network_requests": sum(http.counts.values()),
        "calls": dict(http.counts), "blocked": sorted(http.blocked),
        "stage": {
            "original": {"raw": len(baseline), "unique": len(base_unique),
                         "screen_survivors": len(base_survivors),
                         "candidate": sum(r["screen_outcome"] == "candidate" for r in baseline_audit),
                         "review_only": sum(r["screen_outcome"] == "review_only" for r in baseline_audit)},
            "first_expansion": {"raw": len(previous_extension), "incremental_unique": len(mid_only),
                                "screen_survivors": len(mid_survivors),
                                "candidate": sum(r["screen_outcome"] == "candidate" for r in mid_audit),
                                "review_only": sum(r["screen_outcome"] == "review_only" for r in mid_audit)},
            "additional_depth": {"raw": sum(q["fetched"] for q in depth_performance),
                                 "incremental_unique": len(extra),
                                 "screen_survivors": len(deep_survivors),
                                 "candidate": sum(r["screen_outcome"] == "candidate" for r in deep_audit),
                                 "review_only": sum(r["screen_outcome"] == "review_only" for r in deep_audit)},
            "total_unique": len(deep_unique),
        },
        "previous_query_yields": earlier_queries,
        "new_query_yields": depth_performance,
        "request_logs": http.logs,
        "note": "Classification uses experimental geography adjustments; no Gemini; no employer hiring verification",
    }
    OUT.mkdir(exist_ok=True)
    (OUT / "summary.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
    # Keep the complete incremental candidate+review pool, rather than only
    # the first N, so reviewers can identify false positives/interesting leads.
    details = {r["job_url"]: r for r in deep_audit}
    fields = ["source", "title", "company", "location", "job_url",
              "source_query", "screen_outcome", "eligibility", "reason", "priority"]
    with (OUT / "incremental_shortlist.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        w = csv.DictWriter(handle, fieldnames=fields)
        w.writeheader()
        for job in sorted(deep_survivors, key=lambda x: (-x["priority"], x["source"])):
            a = details[job["job_url"]]
            w.writerow({
                "source": prior.safe_cell(job["source"]),
                "title": prior.safe_cell(job["job_title"]),
                "company": prior.safe_cell(job["company_name"]),
                "location": prior.safe_cell(job["location"]),
                "job_url": prior.safe_cell(job["job_url"]),
                "source_query": job["source_query"],
                "screen_outcome": a["screen_outcome"],
                "eligibility": a["eligibility"],
                "reason": prior.safe_cell(a["eligibility_reason"]),
                "priority": a["priority"],
            })
    print(json.dumps({
        "stage": stats["stage"], "calls": stats["calls"],
        "blocked": stats["blocked"], "new_query_yields": depth_performance,
    }, ensure_ascii=False))
    if not baseline:
        raise RuntimeError("Baseline providers did not return inventory; comparison not reliable")
    return stats


if __name__ == "__main__":
    run()
