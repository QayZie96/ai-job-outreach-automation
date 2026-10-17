"""One-off, read-only smoke test of five additional published job feeds.

No Gemini, credentials, Sheets, RAY history or production side effects.
At most ONE HTTP GET to each of five separate hosts. No retries, proxies,
login, anti-bot tactics or automatic integration. Records aggregate yields.
"""
from __future__ import annotations
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

import requests

from personal_discovery import canonical_url, deduplicate, screen_candidates

OUT = Path(__file__).resolve().parent / "free_source_probe_results"
SOURCES = {
    "RemoteJobs.org": ("https://remotejobs.org/api/v1/jobs", {"q": "operations", "limit": 50, "offset": 0}),
    "Remote OK": ("https://remoteok.com/api", {}),
    "We Work Remotely": ("https://weworkremotely.com/remote-jobs.rss", {}),
    "Working Nomads": ("https://www.workingnomads.com/api/exposed_jobs/", {}),
    "The Muse": ("https://www.themuse.com/api/public/jobs", {"page": 0}),
}
LIMIT_PER_SOURCE = 120


def as_string(value):
    if value is None:
        return ""
    return str(value).strip()


def job(source, *, title, company, location, url, description="", source_id="", posted="", remote=True):
    url = canonical_url(url)
    if not all((title, company, url)):
        return None
    return {
        "source": source, "source_job_id": as_string(source_id or url),
        "job_title": as_string(title), "company_name": as_string(company),
        "location": as_string(location) or "Unknown",
        "remote": remote, "location_restrictions": [], "timezone_restrictions": [],
        "job_description": as_string(description), "job_url": url,
        "created_at": as_string(posted)[:10], "job_types": [], "seniority": None,
        "salary": "", "source_attribution": url, "source_query": "public-feed-first-page",
    }


def normalize(source, payload):
    items = []
    if source == "RemoteJobs.org":
        rows = payload.get("data") or []
        for x in rows[:LIMIT_PER_SOURCE]:
            company = x.get("company") or {}
            items.append(job(source, title=x.get("title"), company=(company.get("name") if isinstance(company, dict) else company),
                             location=x.get("location"), url=x.get("url") or x.get("job_url"),
                             description=x.get("description"), source_id=x.get("id"),
                             posted=x.get("posted_at") or x.get("created_at")))
    elif source == "Remote OK":
        for x in payload[:LIMIT_PER_SOURCE + 1]:
            if not isinstance(x, dict) or not x.get("position"):
                continue  # the API's first element is a legal notice, not a job
            items.append(job(source, title=x.get("position"), company=x.get("company"),
                             location=x.get("location"), url=x.get("url"),
                             description=x.get("description"), source_id=x.get("id"), posted=x.get("date")))
    elif source == "Working Nomads":
        for x in payload[:LIMIT_PER_SOURCE]:
            if not isinstance(x, dict):
                continue
            items.append(job(source, title=x.get("title"), company=x.get("company_name"),
                             location=x.get("location"), url=x.get("url"),
                             description=x.get("description"), posted=x.get("pub_date")))
    elif source == "The Muse":
        for x in (payload.get("results") or [])[:LIMIT_PER_SOURCE]:
            company = x.get("company") or {}
            locations = x.get("locations") or []
            refs = x.get("refs") or {}
            items.append(job(source, title=x.get("name"), company=company.get("name"),
                             location=", ".join(a.get("name", "") for a in locations if isinstance(a, dict)),
                             url=refs.get("landing_page") or x.get("url"),
                             description=x.get("contents"), source_id=x.get("id"),
                             posted=x.get("publication_date"), remote=None))
    elif source == "We Work Remotely":
        root = ET.fromstring(payload)
        for item in root.findall(".//item")[:LIMIT_PER_SOURCE]:
            title = as_string(item.findtext("title"))
            company = title.split(":", 1)[0] if ":" in title else ""
            role = title.split(":", 1)[1].strip() if ":" in title else title
            items.append(job(source, title=role, company=company, location="Remote — region unknown",
                             url=item.findtext("link"), description=item.findtext("description"),
                             source_id=item.findtext("guid"), posted=item.findtext("pubDate")))
    return [x for x in items if x]


def probe(session=None):
    session = session or requests.Session()
    results = []
    examples = []
    for name, (url, params) in SOURCES.items():
        stat = {"source": name, "endpoint": url, "status": None, "raw": 0,
                "normalized": 0, "unique": 0, "candidate": 0,
                "review_only": 0, "hard_excluded": 0,
                "has_description": 0, "error": None}
        try:
            if urlsplit(url).scheme != "https":
                raise ValueError("Non-HTTPS provider URL blocked")
            response = session.get(
                url, params=params, timeout=20,
                headers={"User-Agent": "RAY-public-feed-audit/1.0", "Accept": "application/json, application/rss+xml, application/xml"},
            )
            stat["status"] = response.status_code
            if response.status_code != 200:
                stat["error"] = "HTTP " + str(response.status_code)
                results.append(stat)
                continue
            if name == "We Work Remotely":
                payload = response.content
                stat["raw"] = payload.count(b"<item>")  # approximate, informational only
            else:
                payload = response.json()
                if name == "RemoteJobs.org":
                    stat["raw"] = len(payload.get("data") or [])
                    stat["has_more"] = (payload.get("pagination") or {}).get("has_more")
                elif name == "The Muse":
                    stat["raw"] = len(payload.get("results") or [])
                else:
                    stat["raw"] = len(payload) if isinstance(payload, list) else 0
            normalized = normalize(name, payload)
            unique = deduplicate(normalized)
            audit = []
            survivors, _, _ = screen_candidates(unique, audit)
            stat["normalized"] = len(normalized)
            stat["unique"] = len(unique)
            stat["candidate"] = sum(not j["review_only"] for j in survivors)
            stat["review_only"] = sum(bool(j["review_only"]) for j in survivors)
            stat["hard_excluded"] = len(unique) - len(survivors)
            stat["has_description"] = sum(bool(j["job_description"]) for j in unique)
            for j in sorted(survivors, key=lambda j: -j["priority"])[:12]:
                examples.append({
                    "source": name, "title": j["job_title"],
                    "company": j["company_name"], "location": j["location"],
                    "url": j["job_url"], "screen": "review_only" if j["review_only"] else "candidate",
                    "eligibility": j.get("precheck_eligibility", ""),
                })
        except (requests.RequestException, ValueError, TypeError, KeyError, ET.ParseError) as exc:
            stat["error"] = type(exc).__name__ + ": " + str(exc)[:200]
        results.append(stat)
    return results, examples


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--live", action="store_true", help="One bounded real GET per source")
    args = p.parse_args()
    if not args.live:
        p.error("Pass --live for five independent one-time public requests")
    results, examples = probe()
    OUT.mkdir(exist_ok=True)
    result = {
        "run_utc": datetime.now(timezone.utc).isoformat(),
        "source_statistics": results,
        "sample_survivors": examples[:25],
        "limitations": [
            "Different providers publish overlapping jobs; this is not net-new yield against RAY history",
            "Remote or EU metadata is not proof of Greece hiring eligibility",
            "No full employer-posting verification or calibrated human precision metrics",
            "Single first-page/snapshot test, not daily stability or completeness",
        ],
    }
    (OUT / "summary.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return result


if __name__ == "__main__":
    main()
