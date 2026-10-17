"""Manual, capped personal job discovery. Preserves the original RAY case study.

Usage: python personal_discovery.py --live [--collect-only] [--write-sheet]
The default does not execute a live job search. --write-sheet is explicit and
requires a NEW personal spreadsheet ID distinct from the original RAY ID.
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import html
import os
from pathlib import Path
import re
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit, urljoin

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from personal_evaluation import Evaluator, PersonalCache, profile_text
from personal_extra_feeds import (
    normalize_remote_ok, normalize_remotejobs, normalize_wwr_rss,
)
from personal_screening_v41 import calibrated_factors, update_history, load_history, pending_for_review

BASE = Path(__file__).resolve().parent
ARBEITNOW = "https://www.arbeitnow.com/api/job-board-api"
REMOTIVE = "https://remotive.com/api/remote-jobs"
HIMALAYAS = "https://himalayas.app/jobs/api/search"
JOBICY = "https://jobicy.com/api/v2/remote-jobs"
ADZUNA_ROOT = "https://api.adzuna.com/v1/api/jobs"
# Intentional finite allowlist. Country codes refer to Adzuna's market index,
# NOT permission for a foreign employer to hire from Greece.
ADZUNA_MARKET_ALLOWLIST = frozenset(("at", "de", "es", "fr", "gb", "it", "nl", "pl"))
ADZUNA_DEFAULT_MARKETS = ("de", "nl", "fr", "es")
ADZUNA_QUERY_ALLOWLIST = frozenset((
    "ecommerce", "operations", "marketplace", "catalogue",
    "product data", "pricing", "implementation",
))
ADZUNA_DEFAULT_QUERIES = ("ecommerce", "operations")
ADZUNA_MAX_PAGES_PER_QUERY = 2
REMOTE_OK = "https://remoteok.com/api"
WE_WORK_REMOTELY = "https://weworkremotely.com/remote-jobs.rss"
REMOTEJOBS_ORG = "https://remotejobs.org/api/v1/jobs"
REMOTEJOBS_QUERY = "operations"
# All six Himalayas searches are intentionally broad *single-term* searches.
# This covers core and adjacent families without multiplying keyword variants.
# The unfiltered GR query is intentionally first to catch unexpected job titles.
# GR may also include worldwide postings; provider metadata is not eligibility proof.
HIMALAYAS_QUERIES = (None, "operations", "ecommerce", "automation",
                     "marketing", "analyst")
# Experimental coverage expansion: broad page 2 first, then selected
# high-signal niche queries. No unlimited crawl of Himalayas' global feed.
HIMALAYAS_SECOND_PAGE_QUERIES = ("ecommerce", "marketing", "operations", "automation")
HIMALAYAS_EXTRA_QUERIES = ("catalogue", "product data", "pricing",
                           "procurement", "implementation")
# Two international queries had higher verified incremental screening yield
# than the general GR:p2 search in the bounded October 17 comparison.
HIMALAYAS_GLOBAL_QUERIES = ("operations", "ecommerce")
# Query-by-geography instead of restrictive combinations such as
# tag=operations+geo=europe; keep titles and full employer descriptions locally.
JOBICY_FILTERS = ((None, "europe"), (None, "anywhere"))
# Fixed hard ceilings per manual run, independently of .env values.
DEFAULT_LIMITS = {"Arbeitnow": 4, "Remotive": 1, "Adzuna": 0,
                  "Himalayas": 17, "Jobicy": 3,
                  "Remote OK": 0, "We Work Remotely": 0, "RemoteJobs.org": 0}
HARD_PROVIDER_LIMITS = dict(DEFAULT_LIMITS)
# These opt-in providers have ZERO default attempts. Only their specific
# environment flags may later authorize a tiny, separately bounded pilot.
HARD_PROVIDER_LIMITS.update({
    "Adzuna": 12, "Remote OK": 1,
    "We Work Remotely": 1, "RemoteJobs.org": 2,
})
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


def _csv_allowlist(value, allowed, label):
    """Finite configuration; never interpolate arbitrary values into API paths."""
    entries = tuple(piece.strip().lower() for piece in value.split(","))
    if not entries or any(not piece or piece not in allowed for piece in entries):
        raise ValueError(f"{label} contains an unapproved or blank value")
    if len(entries) != len(set(entries)):
        raise ValueError(f"{label} contains duplicate values")
    return entries


def adzuna_search_plan(countries, terms, page_count=1):
    """Round-robin markets before following deeper pages; all pages bounded."""
    if not 1 <= page_count <= ADZUNA_MAX_PAGES_PER_QUERY:
        raise ValueError("Adzuna page count outside approved 1..2 range")
    if not countries or not terms or any(c not in ADZUNA_MARKET_ALLOWLIST for c in countries):
        raise ValueError("Unapproved or empty Adzuna country configuration")
    if any(t not in ADZUNA_QUERY_ALLOWLIST for t in terms):
        raise ValueError("Unapproved Adzuna query configuration")
    # Country-first breadth is more useful than overcollecting one country.
    return [(country, term, page)
            for page in range(1, page_count + 1)
            for country in countries
            for term in terms]


class ProviderError(RuntimeError):
    pass


class BudgetedHTTP:
    def __init__(self, limits=None, session=None):
        self.limits = dict(limits if limits is not None else DEFAULT_LIMITS)
        for provider, limit in self.limits.items():
            if provider not in HARD_PROVIDER_LIMITS or not 0 <= limit <= HARD_PROVIDER_LIMITS[provider]:
                raise ValueError(f"{provider}: manual HTTP budget exceeds fixed safe ceiling")
        self.calls = Counter()
        self.session = session or requests.Session()
        self.blocked = set()  # stop this provider on 429, including later planned queries
        self.request_log = []  # safe metadata only; never log API credentials

    def get_json(self, source, url, params=None):
        if source in self.blocked:
            raise ProviderError(f"{source} stopped after 429; no further requests")
        # Retries also spend budget. Record attempt provenance without credentials.
        # Do not repeat a query after the provider explicitly rate-limits it.
        safe_keys = {"q", "country", "sort", "page", "geo", "count", "tag", "industry", "limit", "offset",
                     "what", "sort_by", "results_per_page"}
        safe_params = {k: v for k, v in (params or {}).items() if k in safe_keys}
        for attempt in range(2):
            if self.calls[source] >= self.limits.get(source, 0):
                raise ProviderError(f"{source} API request budget exhausted")
            self.calls[source] += 1
            entry = {"source": source, "path": urlsplit(url).path,
                     "parameters": safe_params, "attempt": attempt + 1,
                     "outcome": "request_error"}
            self.request_log.append(entry)
            try:
                response = self.session.get(url, params=params, timeout=20,
                                            headers={"Accept": "application/json"})
                entry["outcome"] = response.status_code
                if response.status_code == 200:
                    payload = response.json()
                    if not isinstance(payload, dict) and not (
                        source == "Remote OK" and isinstance(payload, list)
                    ):
                        raise ProviderError(f"{source}: invalid response schema")
                    entry["returned"] = (
                        len(payload) if isinstance(payload, list) else
                        len(payload.get("jobs") or payload.get("data") or payload.get("results") or [])
                    )
                    return payload
                if response.status_code == 429:
                    self.blocked.add(source)
                    raise ProviderError(f"{source} rate limited (429); no retry")
                if response.status_code in {401, 403}:
                    self.blocked.add(source)
                    raise ProviderError(f"{source}: HTTP {response.status_code}; further requests stopped")
                if response.status_code not in {500, 502, 503, 504}:
                    raise ProviderError(f"{source}: HTTP {response.status_code}")
                error = f"HTTP {response.status_code}"
            except (requests.RequestException, ValueError) as exc:
                # A network exception can embed a URL containing Adzuna's
                # app_id/app_key. Never copy those secrets into audit logs.
                # Exception messages can contain percent-encoded query
                # credentials. Do not log their contents for Adzuna at all.
                if source == "Adzuna":
                    error = f"{type(exc).__name__}: request failed (credentials redacted)"
                else:
                    error = f"{type(exc).__name__}: {exc}"
            if attempt == 0 and self.calls[source] < self.limits.get(source, 0):
                time.sleep(1)
                continue
            raise ProviderError(f"{source}: {error}")
        raise ProviderError(f"{source}: no valid response")


    def get_text(self, source, url):
        """One bounded public RSS request; 429 stops the provider, no retries."""
        if source != "We Work Remotely" or url != WE_WORK_REMOTELY:
            raise ProviderError("Only the approved We Work Remotely RSS endpoint is allowed")
        if source in self.blocked:
            raise ProviderError(f"{source} stopped after rate limiting")
        if self.calls[source] >= self.limits.get(source, 0):
            raise ProviderError(f"{source} API request budget exhausted")
        self.calls[source] += 1
        entry = {"source": source, "path": urlsplit(url).path,
                 "parameters": {}, "attempt": 1, "outcome": "request_error"}
        self.request_log.append(entry)
        try:
            response = self.session.get(
                url, timeout=20, headers={"Accept": "application/rss+xml, application/xml"}
            )
            entry["outcome"] = response.status_code
            if response.status_code == 429:
                self.blocked.add(source)
                raise ProviderError(f"{source} rate limited (429); no retry")
            if response.status_code != 200:
                if response.status_code in {401, 403}:
                    self.blocked.add(source)
                raise ProviderError(f"{source}: HTTP {response.status_code}")
            rss = response.text
            if not isinstance(rss, str) or len(rss) > 5_000_000:
                raise ProviderError(f"{source}: invalid/oversized RSS response")
            return rss
        except requests.RequestException as exc:
            raise ProviderError(f"{source}: {type(exc).__name__}: {exc}") from exc


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
    """Normalize legacy providers without importing RAY's Gemini-initializing main.py.

    These field mappings match the original RAY normalizers, while the personal
    pipeline adds its own IDs, eligibility fields and source attribution.
    """
    items = []
    for original in raw:
        if source == "Arbeitnow":
            item = {
                "job_title": original.get("title"),
                "company_name": original.get("company_name"),
                "location": original.get("location"),
                "job_description": original.get("description"),
                "job_url": original.get("url"),
                "remote": original.get("remote"),
                "tags": original.get("tags"),
                "job_types": original.get("job_types"),
                "created_at": iso_date(original.get("created_at")),
            }
        elif source == "Remotive":
            category = original.get("category")
            job_type = original.get("job_type")
            item = {
                "job_title": original.get("title"),
                "company_name": original.get("company_name"),
                "location": original.get("candidate_required_location"),
                "job_description": original.get("description"),
                "job_url": original.get("url"),
                "remote": True,
                "tags": [category] if category else [],
                "job_types": [job_type] if job_type else [],
                "created_at": iso_date(original.get("publication_date")),
            }
        elif source == "Adzuna":
            company = original.get("company") or {}
            location = original.get("location") or {}
            item = {
                "job_title": original.get("title"),
                "company_name": company.get("display_name"),
                "location": location.get("display_name"),
                "job_description": original.get("description"),
                "job_url": original.get("redirect_url"),
                "remote": None,
                "tags": [],
                "job_types": [],
                "created_at": iso_date(original.get("created")),
            }
        else:
            raise ValueError(f"Unknown legacy job provider: {source}")
        item.update({
            "source": source,
            "source_job_id": str(original.get("id") or ""),
            "location_restrictions": [],
            "timezone_restrictions": [],
            "seniority": None,
            "salary": "",
            "source_attribution": item.get("job_url") or "",
        })
        items.append(item)
    return items


def collect(http):
    jobs, stats, errors = [], Counter(), []

    def add(source, raw, convert, query="unfiltered"):
        data = convert(raw)
        for job in data:
            job["source_query"] = query
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

    # Multi-country Adzuna stays OFF by default. Enable with an explicit
    # per-run budget, registered app credentials, and bounded market/query lists.
    # Country-market membership is not Greece-remote hiring eligibility.
    if http.limits.get("Adzuna", 0):
        try:
            app_id, key = os.getenv("ADZUNA_APP_ID"), os.getenv("ADZUNA_APP_KEY")
            if not app_id or not key:
                raise ProviderError("Adzuna enabled but app ID/key credentials missing")
            markets = _csv_allowlist(
                os.getenv("PERSONAL_ADZUNA_MARKETS", ",".join(ADZUNA_DEFAULT_MARKETS)),
                ADZUNA_MARKET_ALLOWLIST, "Adzuna markets",
            )
            terms = _csv_allowlist(
                os.getenv("PERSONAL_ADZUNA_TERMS", ",".join(ADZUNA_DEFAULT_QUERIES)),
                ADZUNA_QUERY_ALLOWLIST, "Adzuna search terms",
            )
            pages = env_int("PERSONAL_ADZUNA_PAGES_PER_QUERY", 1, minimum=1,
                            maximum=ADZUNA_MAX_PAGES_PER_QUERY)
            empty_pairs = set()
            for country, term, page in adzuna_search_plan(markets, terms, pages):
                if (country, term) in empty_pairs:
                    continue
                if (http.calls["Adzuna"] >= http.limits["Adzuna"]
                        or "Adzuna" in http.blocked):
                    break
                try:
                    url = f"{ADZUNA_ROOT}/{country}/search/{page}"
                    payload = http.get_json(
                        "Adzuna", url,
                        {"app_id": app_id, "app_key": key,
                         "results_per_page": 50, "what": term, "sort_by": "date"},
                    )
                    rows = payload.get("results")
                    if not isinstance(rows, list):
                        raise ProviderError("Adzuna: malformed results list")
                    add("Adzuna", rows,
                        lambda raw: normalize_original("Adzuna", raw),
                        query=f"market:{country}:what:{term}:p{page}")
                    if not rows:
                        # Never request page 2 of an empty page 1 query.
                        empty_pairs.add((country, term))
                except (ProviderError, KeyError, TypeError, ValueError) as exc:
                    errors.append(str(exc))
                    if "Adzuna" in http.blocked:
                        break
        except (ProviderError, ValueError) as exc:
            errors.append(str(exc))

    # Six original first pages, four high-yield second pages, then selected
    # niche Greece and international searches: exactly 17 planned requests.
    hima_plan = (
        [(q, 1, "GR") for q in HIMALAYAS_QUERIES]
        + [(q, 2, "GR") for q in HIMALAYAS_SECOND_PAGE_QUERIES]
        + [(q, 1, "GR") for q in HIMALAYAS_EXTRA_QUERIES]
        + [(q, 1, None) for q in HIMALAYAS_GLOBAL_QUERIES]
    )
    for query, page, country in hima_plan:
        if (http.calls["Himalayas"] >= http.limits.get("Himalayas", 0)
                or "Himalayas" in http.blocked):
            break
        try:
            params = {"sort": "recent", "page": page}
            if country:
                params["country"] = country
            if query:
                params["q"] = query
            payload = http.get_json("Himalayas", HIMALAYAS, params)
            if payload.get("success") is False:
                raise ProviderError("Himalayas response indicates failure")
            add("Himalayas", payload.get("jobs") or [], normalize_himalayas,
                query=f"{country or 'global'}:{query or 'all'}:p{page}")
        except (ProviderError, KeyError, TypeError) as exc:
            errors.append(str(exc))
            if "Himalayas" in http.blocked:
                break

    # Preserve the existing two Jobicy geography probes, then optionally
    # traverse ONE more Europe page only if the API supplies a cursor.
    europe_cursor = None
    for tag, geo in JOBICY_FILTERS:
        if (http.calls["Jobicy"] >= http.limits.get("Jobicy", 0)
                or "Jobicy" in http.blocked):
            break
        try:
            params = {"count": 200, "geo": geo}
            if tag:
                params["tag"] = tag
            payload = http.get_json("Jobicy", JOBICY, params)
            if payload.get("success") is False:
                raise ProviderError(f"Jobicy: {payload.get('error', 'API failed')}")
            add("Jobicy", payload.get("jobs") or [], normalize_jobicy,
                query=f"geo:{geo}:p1")
            if geo == "europe" and isinstance(payload.get("nextCursor"), str):
                europe_cursor = payload["nextCursor"] or None
        except (ProviderError, KeyError, TypeError) as exc:
            errors.append(str(exc))
            if "Jobicy" in http.blocked:
                break
    if (europe_cursor and "Jobicy" not in http.blocked
            and http.calls["Jobicy"] < http.limits.get("Jobicy", 0)):
        try:
            payload = http.get_json("Jobicy", JOBICY, {
                "count": 200, "geo": "europe", "cursor": europe_cursor})
            if payload.get("success") is False:
                raise ProviderError(f"Jobicy: {payload.get('error', 'API failed')}")
            add("Jobicy", payload.get("jobs") or [], normalize_jobicy,
                query="geo:europe:p2")
        except (ProviderError, KeyError, TypeError) as exc:
            errors.append(str(exc))
    # The following sources are deliberately opt-in, independently budgeted
    # and reuse exactly the existing deterministic screen/dedup/history pipeline.
    if http.limits.get("Remote OK", 0):
        try:
            payload = http.get_json("Remote OK", REMOTE_OK)
            add("Remote OK", payload, normalize_remote_ok, query="unfiltered")
        except (ProviderError, ValueError, KeyError, TypeError) as exc:
            errors.append(str(exc))

    if http.limits.get("We Work Remotely", 0):
        try:
            rss = http.get_text("We Work Remotely", WE_WORK_REMOTELY)
            add("We Work Remotely", rss, normalize_wwr_rss, query="rss:all")
        except (ProviderError, ValueError, KeyError, TypeError) as exc:
            errors.append(str(exc))

    if http.limits.get("RemoteJobs.org", 0):
        offset = 0
        while (http.calls["RemoteJobs.org"] < http.limits.get("RemoteJobs.org", 0)
               and "RemoteJobs.org" not in http.blocked):
            try:
                payload = http.get_json("RemoteJobs.org", REMOTEJOBS_ORG, {
                    "q": REMOTEJOBS_QUERY, "limit": 50, "offset": offset,
                })
                if not isinstance(payload.get("data"), list):
                    raise ProviderError("RemoteJobs.org: missing data list")
                add("RemoteJobs.org", payload, normalize_remotejobs,
                    query=f"q:{REMOTEJOBS_QUERY}:offset:{offset}")
                if not payload["data"] or not (payload.get("pagination") or {}).get("has_more"):
                    break
                offset += 50
            except (ProviderError, ValueError, KeyError, TypeError) as exc:
                errors.append(str(exc))
                break

    return jobs, stats, errors


# Two-stage screening: preserve plausible operational work for review, then
# prioritize evidence-rich roles for a bounded Gemini pass. Do NOT treat a
# deterministic title/description keyword match as a final fit assessment.
ROLE_TERMS = (
    "ecommerce", "e-commerce", "e commerce", "marketplace", "catalog", "catalogue",
    "merchandis", "product data", "product information", "product content",
    "pricing", "inventory", "procurement", "purchasing", "supplier", "vendor",
    "fulfilment", "fulfillment", "order management", "order processing",
    "business operations", "commercial operations", "sales operations", "revenue operations",
    "marketing operations", "partner operations", "merchant operations", "seller operations",
    "operations", "process improvement", "process excellence", "workflow",
    "automation specialist", "automation manager", "automation coordinator",
    "implementation", "digital enablement", "business analyst", "business systems",
    "category manager", "supply chain", "omnichannel", "retail trade",
    "seller success", "partner success", "customer operations", "business enablement",
    "business process", "product operations", "sales support", "commercial support",
    "client operations", "customer support operations", "retail operations",
    "logistics coordinator", "project operations", "sales enablement",
)
# These are clearly other professions irrespective of company description.
# Seniority alone is NOT an exclusion: it affects priority, while Gemini/humans
# verify whether required leadership experience is actually demonstrated.
OUT_OF_SCOPE_TITLE = re.compile(
    r"\b(?:software|backend|back-end|frontend|front-end|full[ -]?stack|devops|"
    r"site reliability|sre|cloud|platform|infrastructure|machine learning|\bml|"
    r"data|security|mechanical|electrical|robotics|firmware|embedded|"
    r"computer vision|network|systems|product|quality assurance|qa|test|"
    r"solution|solutions|salesforce|ai)\s+(?:engineer|architect|developer)\b|"
    r"\b(?:engineer|developer|architect|scientist|copywriter|videographer|"
    r"video editor|graphic designer|product designer|\bdesigner|"
    r"account executive|account development|sales representative|"
    r"sales development representative|business development representative|"
    r"clinical|medical|nurse|lawyer|legal counsel|"
    r"tax manager|payroll|accountant|underwriter|auditor|accounts payable|finance specialist|"
    r"chief technology officer|chief operating officer|chief executive|"
    r"intern|internship|werkstudent|working student|stage\b|"
    r"apprentice|praktikum)\b",
    re.IGNORECASE,
)
GENERIC_TITLE = re.compile(
    r"\b(?:specialist|analyst|coordinator|associate|project manager|program manager|"
    r"programme manager|consultant|advisor|manager|lead|officer|administrator|"
    r"assistant|executive|customer success|customer experience|customer service|"
    r"customer care|client success|client support|sales support|onboarding|"
    r"business development|digital transformation)\b", re.IGNORECASE
)
ADJACENT_TITLE = (
    "customer success", "customer service", "customer experience", "customer care",
    "client success", "client support", "merchant support", "seller support",
    "partner support", "onboarding", "sales enablement", "digital transformation",
    "business transformation", "commercial excellence", "operational excellence",
    "project manager", "program manager", "programme manager", "process manager",
    "business support", "growth operations", "service delivery", "trade support",
    # Transferable roles from verified CV experience; title alone never
    # asserts hireability and most of these should remain human-review only.
    "marketing", "crm", "retention", "lifecycle", "campaign", "seo",
    "content specialist", "content manager", "web manager", "website manager",
    "data analyst", "reporting analyst", "business intelligence", "revenue analyst",
    "office assistant", "administrative assistant", "project coordinator",
    "project assistant", "shopify specialist", "brand manager", "product manager",
    "customer solutions consultant", "customer solutions specialist",
)
# Direct experience in these domains is not proven by merely operating a
# marketplace; a plausible role stays visible without taking Gemini budget.
TRANSFERABLE_REVIEW_TITLES = (
    "marketing", "crm", "retention", "lifecycle", "campaign", "seo",
    "content specialist", "content manager", "web manager", "website manager",
    "data analyst", "reporting analyst", "business intelligence", "revenue analyst",
    "office assistant", "administrative assistant", "project coordinator",
    "project assistant", "shopify specialist", "product manager",
    "customer solutions consultant", "customer solutions specialist",
)
STRONG_DESCRIPTION_SIGNALS = (
    "ecommerce", "e-commerce", "marketplace", "product data", "product information",
    "catalog", "catalogue", "inventory", "supplier", "vendor", "merchandis",
    "pricing", "fulfillment", "fulfilment", "order management", "procurement",
    "workflow automation", "process automation", "operations management",
    "seller", "product listing", "order processing", "logistics coordination",
    "business operations", "process improvement", "supplier coordination",
    "crm", "marketing automation", "email marketing", "web analytics",
    "digital marketing", "customer retention", "data reporting", "power bi",
    "sql", "google analytics", "marketing campaign", "api integration",
)
OPERATIONAL_ACTIONS = (
    "manage", "manage and", "optimiz", "improv", "coordinat", "implement",
    "streamlin", "automat", "develop", "maintain", "monitor", "track",
    "oversee", "support", "launch", "deliver", "analy", "build",
)
NON_ENGLISH_LANGUAGE = (
    "german", "french", "dutch", "spanish", "italian", "portuguese", "polish",
    "swedish", "danish", "norwegian", "finnish", "turkish", "arabic", "japanese",
)
EU_COUNTRIES = (
    "austria", "belgium", "bulgaria", "croatia", "cyprus", "czechia", "czech republic",
    "denmark", "estonia", "finland", "france", "germany", "greece", "hungary",
    "ireland", "italy", "latvia", "lithuania", "luxembourg", "malta",
    "netherlands", "poland", "portugal", "romania", "slovakia", "slovenia",
    "spain", "sweden",
)
EU_CITIES = (
    "athens", "thessaloniki", "berlin", "munich", "münchen", "hamburg",
    "frankfurt", "cologne", "stuttgart", "bonn", "amsterdam", "rotterdam",
    "utrecht", "paris", "bordeaux", "lyon", "nantes", "madrid", "barcelona",
    "lisbon", "porto", "dublin", "warsaw", "krakow", "prague", "vienna",
    "rome", "milan", "brussels", "stockholm", "copenhagen", "helsinki",
    "budapest", "bucharest", "sofia", "tallinn", "riga", "vilnius",
)
NON_EU_LOCATIONS = (
    "united kingdom", "uk", "london", "manchester", "bristol", "leeds", "oxford",
    "cambridge", "england", "scotland", "switzerland", "zurich", "zürich",
    "lausanne", "geneva", "nyon", "zug", "usa", "united states", "canada",
    "latam", "australia", "serbia", "norway", "israel", "india", "japan",
)
EU_RELOCATION_CODES = set("AT BE BG HR CY CZ DK EE FI FR DE GR HU IE IT LV LT LU MT NL PL PT RO SK SI ES SE".split())
BROAD_REMOTE = ("worldwide", "anywhere", "global", "fully global", "work from anywhere")
BROAD_REGION = ("europe", "emea", "european union", "eu", "eea")


def _has_phrase(text, phrase):
    return bool(re.search(r"(?<![\w])" + re.escape(phrase) + r"(?![\w])", text))


def _has_any(text, phrases):
    return any(_has_phrase(text, phrase) for phrase in phrases)


def description_text(job):
    # HTML/script content is not job responsibility evidence. Limit the
    # expensive parsing and avoid scanning unrelated footer boilerplate.
    raw = str(job.get("job_description") or "")[:25000]
    return " ".join(BeautifulSoup(html.unescape(raw), "html.parser").stripped_strings)[:12000].lower()


def role_evidence(job):
    """Return (relevance points, auditable reason), never a fit/eligibility verdict."""
    title = " ".join(str(job.get("job_title") or "").lower().split())
    if not title:
        return 0, "missing title"
    if OUT_OF_SCOPE_TITLE.search(title):
        return 0, "clear non-target profession/title"
    if _has_any(title, ("people operations", "hr operations", "human resources", "data center")):
        return 0, "unrelated operations domain"
    matched = [term for term in ROLE_TERMS if _has_phrase(title, term)]
    if matched:
        major = ("ecommerce", "e-commerce", "e commerce", "marketplace", "catalog",
                 "catalogue", "product data", "product information", "pricing", "inventory")
        return (78 if _has_any(title, major) else 65), "target role in job title"
    # Adjacent titles need content corroboration. We preserve plausible roles
    # for review rather than requiring the exact words 'operations' or 'catalog'.
    desc = description_text(job)
    signals = {term for term in STRONG_DESCRIPTION_SIGNALS if _has_phrase(desc, term)}
    if _has_any(title, ADJACENT_TITLE) and len(signals) >= 2:
        return 45, "adjacent role with operational domain evidence"
    if GENERIC_TITLE.search(title) and len(signals) >= 3 and any(
            stem in desc for stem in OPERATIONAL_ACTIONS):
        return 27, "generic role with multiple operational domain signals"
    if _has_any(title, ADJACENT_TITLE):
        return 18, "adjacent title; insufficient domain evidence (manual review only)"
    return 0, "insufficient operational role evidence"


def title_relevance(job):
    return role_evidence(job)[0]


def target_role(job):
    return title_relevance(job) > 0


def mandatory_other_language(job):
    desc = description_text(job)
    title = str(job.get("job_title") or "").lower()
    for language in NON_ENGLISH_LANGUAGE:
        l = re.escape(language)
        # Require affirmative mandatory language evidence. Mentions of a
        # market, country or "German preferred" do not justify rejection.
        patterns = (
            rf"\b(?:fluent|fluency|native|business fluent|professional proficiency)\s+(?:in\s+)?{l}\b",
            rf"\b{l}\s+(?:language\s+)?(?:fluency|proficiency)\s+(?:is\s+)?(?:required|mandatory|essential)\b",
            rf"\b(?:must|need|required)\s+(?:to\s+)?(?:speak|write|understand)\s+{l}\b",
            rf"\b(?:c1|c2)\s+(?:level\s+)?{l}\b",
        )
        # Treat explicitly optional/preferred language as non-mandatory.
        # Assess the local clause, not a boilerplate preference elsewhere.
        found_required = False
        for pattern in patterns:
            for match in re.finditer(pattern, desc):
                tail = desc[match.end():match.end() + 65].split(".")[0].split(";")[0]
                optional = re.search(r"\b(?:preferred|optional|a plus|nice to have|bonus|"
                                     r"not required|desirable|advantage)\b", tail)
                required = re.search(r"\b(?:required|mandatory|must|essential)\b", tail)
                if not optional or (required and not re.search(r"\bnot required\b", tail)):
                    found_required = True
                    break
            if found_required:
                break
        if found_required or re.search(
                rf"\b{l}\s+(?:fluency|required|speaking)\b|\bfluent\s+(?:in\s+)?{l}\b|"
                rf"\b{l}[ -]speaking\b", title):
            return language
    # Country-language spellings and typical requirement constructions that
    # English-only word detection misses, e.g. Dutch "Je spreekt vloeiend
    # Nederlands en Engels". Positive requirements only, not "nice to have".
    native_patterns = (
        ("Dutch", r"\b(?:je\s+spreekt|spreek|beheers|spreekt)\s+(?:vloeiend|uitstekend|goed)\s+nederlands\b|"
                  r"\b(?:vloeiend|uitstekend)\s+nederlands\b|"
                  r"\b(?:goede|uitstekende)\s+beheersing\s+van\s+(?:de\s+)?nederlandse\s+taal\b"),
        ("German", r"\b(?:du\s+sprichst|sie\s+sprechen)\s+(?:fließend|fliessend|sehr gut)\s+deutsch\b"),
        ("French", r"\b(?:français\s+courant|maîtrise\s+du\s+français|parlez\s+couramment\s+français)\b"),
    )
    for language, pattern in native_patterns:
        if re.search(pattern, desc):
            return language
    # Explicit mandatory proficiency in German found in local-language postings.
    if re.search(
        r"\b(?:fließend|fliessend|sehr gut|hervorragend|verhandlungssicher)"
        r".{0,35}\bdeutsch(?:kenntnisse)?\b|"
        r"\b(?:fließende|fliessende|verhandlungssichere|gute)\s+deutschkenntnisse\b|"
        r"\bdeutsch[- ](?:und|oder)\s+(?:gute\s+)?englischkenntnisse\b",
        desc,
    ):
        return "German"
    return None


def preliminary_eligibility(job):
    # Only hard-reject when metadata explicitly rules out the user's location.
    # Ambiguous locations continue as Review candidates, not Strong Matches.
    language = mandatory_other_language(job)
    if language:
        return "ineligible", f"Mandatory {language} language not in verified profile"
    # The employer's explicit negative geographic statement outranks a broad
    # source label, even if provider metadata also contains GR.
    desc = description_text(job)
    if re.search(
        r"\b(?:not|never|no longer)\s+(?:currently\s+)?(?:hiring|recruiting)\s+(?:in|from)\s+greece\b|"
        r"\bcurrently\s+(?:not|no longer)\s+(?:hiring|recruiting)\s+(?:in|from)\s+greece\b|"
        r"\b(?:cannot|can't|do not|don't|unable to)\s+(?:hire|employ)\s+"
        r"(?:candidates?\s+)?(?:in|from|based in)\s+greece\b|"
        r"\bgreece\s+(?:is\s+)?not\s+(?:an?\s+)?(?:eligible|supported|approved)\s+(?:country|location)\b|"
        r"\b(?:except|excluding)\s+greece\b",
        desc,
    ):
        return "uncertain", "Explicit Greece hiring exclusion; investigate EU relocation separately"
    restrictions = job.get("location_restrictions") or []
    if job.get("source") == "Himalayas" and restrictions:
        regions = {str(x).upper() for x in restrictions}
        if {"GR", "GREECE"} & regions:
            return "eligible", "Greece present in provider country allowlist"
        if regions & EU_RELOCATION_CODES or any(
                str(r).lower() in EU_COUNTRIES for r in restrictions):
            return "uncertain", "EU-country location restriction; relocation eligibility unverified"
        return "ineligible", "Explicit country allowlist excludes Greece and EU relocation"
    place = " ".join(str(job.get("location") or "").lower().split())
    if job.get("remote"):
        # Some remote aggregators label every role remote, even when the
        # employer explicitly requires office presence. EU hybrid relocation
        # is in scope; a country-restricted fully remote role is not.
        if (_has_any(place, EU_COUNTRIES + EU_CITIES)
                and re.search(r"\bhybrid\s+(?:setup|model|work|working)|"
                              r"\bminimum\s+of\s+\w+\s+days?\s+per\s+week\s+in\s+the\s+office|"
                              r"\brole\s+is\s+based\s+in\s+our\s+\w+\s+office", desc)):
            return "uncertain", "Employer describes EU office-based/hybrid work; relocation needed"
        if _has_phrase(place, "greece") or _has_phrase(place, "athens"):
            return "eligible", "Remote listing explicitly includes Greece"
        if re.search(
            r"(?:currently\s+)?(?:we\s+are\s+)?hiring\s+in.{0,350}\bgreece\b|"
            r"(?:eligible\s+countries|locations\s+include|work\s+remotely\s+from)"
            r".{0,350}\bgreece\b", desc,
        ):
            return "eligible", "Posting explicitly lists Greece as a hiring location"
        if _has_any(place, BROAD_REMOTE):
            return "uncertain", "Worldwide remote label; contract eligibility unverified"
        if _has_any(place, BROAD_REGION):
            return "uncertain", "Europe/EMEA label does not confirm hiring from Greece"
        if _has_any(place, EU_COUNTRIES + EU_CITIES):
            return "uncertain", "EU-country remote restriction; potential relocation requires verification"
        if _has_any(place, NON_EU_LOCATIONS):
            return "ineligible", "Remote location outside Greece and EU relocation scope"
        return "uncertain", "Remote hiring location unspecified"
    if _has_any(place, NON_EU_LOCATIONS):
        return "ineligible", "On-site/hybrid location outside the EU"
    if _has_any(place, EU_COUNTRIES + EU_CITIES):
        return "uncertain", "EU location permits relocation review"
    return "uncertain", "On-site/hybrid location unclear"


def candidate_priority(job):
    score = title_relevance(job)
    eligibility = job.get("precheck_eligibility", "uncertain")
    score += 24 if eligibility == "eligible" else 8
    place = str(job.get("location") or "").lower()
    if "greece" in place or "athens" in place:
        score += 18
    if "junior" in str(job.get("job_title") or "").lower():
        score += 6
    title = str(job.get("job_title") or "").lower()
    if "senior" in title or re.search(r"\bsr\.?\b", title):
        score -= 9
    if "lead" in title:
        score -= 7
    if re.search(r"\b(?:director|head of|vice president|vp|chief of staff)\b", title):
        score -= 28  # keep visible in review; typically unlikely at this experience level
    desc = description_text(job)
    if re.search(r"\b(?:8\+|10\+|12\+)\s+years?\b", desc):
        score -= 10
    # A German-language description is not proof of a strict requirement;
    # review it, but rank it below explicit English-language opportunities.
    words = re.findall(r"[a-zäöüß]+", desc[:3000])
    if len(words) >= 40 and sum(w in {"und", "der", "die", "das", "du", "deine", "mit", "wir", "bei"}
                                 for w in words) / len(words) > 0.05:
        score -= 25
    if "intern" in title or "part-time" in title:
        score -= 10
    return score


def prioritize_candidates(jobs, limit=40):
    # A single provider's page order must not monopolize paid/limited AI.
    ordered = sorted(jobs, key=lambda j: (-j["priority"], j.get("source", ""),
                                              j.get("job_url", "")))
    per_source = max(1, (limit * 2 + 4) // 5)  # max ~40% first pass
    counts, selected, seen = Counter(), [], set()
    for job in ordered:
        if len(selected) >= limit:
            break
        if counts[job["source"]] < per_source:
            selected.append(job)
            seen.add(job["job_url"])
            counts[job["source"]] += 1
    for job in ordered:
        if len(selected) >= limit:
            break
        if job["job_url"] not in seen:
            selected.append(job)
            seen.add(job["job_url"])
    selected.sort(key=lambda j: (-j["priority"], j.get("source", ""),
                                  j.get("job_url", "")))
    return selected


def screen_candidates(jobs, audit=None):
    """Broad but accountable screen. Audit one decision for EVERY unique job."""
    survivors, counts, rejects = [], Counter(), Counter()
    for job in jobs:
        role_score, role_reason = role_evidence(job)
        factors = calibrated_factors(job.get("job_title", ""), description_text(job))
        title_text = str(job.get("job_title") or "")
        # Salvage only plausible business/marketing/admin work; never engineers,
        # architects, unrelated professions or internships via company boilerplate.
        if (role_score == 0 and role_reason == "insufficient operational role evidence"
                and factors["promote_review"]
                and not OUT_OF_SCOPE_TITLE.search(title_text)
                and not re.search(r"\b(?:engineer|architect|developer|intern|internship)\b",
                                  title_text, re.IGNORECASE)):
            role_score, role_reason = 18, "transferable role with duties evidence (review only)"
        status, reason = preliminary_eligibility(job) if role_score else ("not_checked", "role excluded before eligibility check")
        if role_score and factors["hard_exclusion"] == "mandatory_language":
            status, reason = "ineligible", factors["reason"] + " required by posting"

        senior_executive = bool(re.search(r"\b(?:director|head of|vice president|vp|chief of staff)\b",
                                          str(job.get("job_title") or ""), re.IGNORECASE))
        title = str(job.get("job_title") or "").lower()
        # Keep adjacent marketing/data/web opportunities visible; don't promote
        # them into an AI shortlist on generic company-description matches.
        transferable_only = _has_any(title, TRANSFERABLE_REVIEW_TITLES) and not _has_any(title, ROLE_TERMS)
        exploratory = bool(role_score and (role_score < 45 or senior_executive or transferable_only or factors["force_review"]))
        outcome = "review_only" if exploratory else "candidate"
        if not role_score:
            counts["role_out_of_scope"] += 1
            outcome = "role_out_of_scope"
        elif factors["hard_exclusion"] == "incompatible_role":
            counts["incompatible_role_excluded"] += 1
            outcome = "incompatible_role_excluded"
            reason = factors["reason"]
            status = "ineligible"
        elif status == "ineligible":
            key = "mandatory_language" if reason.startswith(("Mandatory", "Advanced mandatory")) else "geography"
            counts[key + "_excluded"] += 1
            rejects[(job.get("source", ""), key)] += 1
            outcome = key + "_excluded"
        else:
            job["precheck_eligibility"] = status
            job["precheck_reason"] = reason
            job["role_evidence_reason"] = role_reason
            job["review_only"] = exploratory
            job["priority"] = candidate_priority(job) + factors["priority_delta"]
            if role_reason.startswith("transferable role"):
                job["priority"] += 18
            job["fit_flags"] = list(factors["flags"])
            survivors.append(job)
            counts["eligible" if status == "eligible" else "uncertain"] += 1
            if exploratory:
                counts["review_only"] += 1
        if audit is not None:
            audit.append({
                "source": job.get("source", ""),
                "company": job.get("company_name", ""),
                "job_title": job.get("job_title", ""),
                "location": job.get("location", ""),
                "remote": job.get("remote"),
                "job_url": job.get("job_url", ""),
                "source_query": job.get("source_query", "legacy/unknown"),
                "description_excerpt": description_text(job)[:2500],
                "role_score": role_score,
                "role_reason": role_reason,
                "fit_flags": ";".join(factors["flags"]),
                "eligibility": status,
                "eligibility_reason": reason,
                "screen_outcome": outcome,
                "priority": job.get("priority", "") if outcome in ("candidate", "review_only") else "",
                "ai_selected": False,
            })
    return survivors, dict(counts), {f"{source}:{reason}": count
                                       for (source, reason), count in sorted(rejects.items())}


def write_screening_audit(report_path, audit):
    """Save a compact offline review of ALL unique jobs, not just survivors."""
    dest = Path(report_path).with_name(Path(report_path).stem + "_screening_audit.csv")
    dest.parent.mkdir(parents=True, exist_ok=True)
    fields = ("source", "company", "job_title", "location", "remote", "job_url",
              "source_query", "description_excerpt",
              "role_score", "role_reason", "fit_flags", "eligibility", "eligibility_reason",
              "screen_outcome", "priority", "ai_selected", "seen_before", "review_status", "ai_judged")
    with dest.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in audit:
            # Excel interprets leading =,+,-,@ (also when whitespace-prefixed)
            # as formulas. Job-board titles/URLs are untrusted strings.
            safe = {}
            for key, value in row.items():
                if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
                    safe[key] = "'" + value
                else:
                    safe[key] = value
            writer.writerow(safe)
    return dest


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
    limits = {"Arbeitnow": env_int("PERSONAL_MAX_ARBEITNOW_CALLS", 4, maximum=4),
              "Remotive": env_int("PERSONAL_MAX_REMOTIVE_CALLS", 1, maximum=1),
              "Adzuna": env_int("PERSONAL_MAX_ADZUNA_CALLS", 0, maximum=12),
              "Himalayas": env_int("PERSONAL_MAX_HIMALAYAS_CALLS", 17, maximum=17),
              "Jobicy": env_int("PERSONAL_MAX_JOBICY_CALLS", 3, maximum=3),
              "Remote OK": env_int("PERSONAL_MAX_REMOTE_OK_CALLS", 0, maximum=1),
              "We Work Remotely": env_int("PERSONAL_MAX_WWR_CALLS", 0, maximum=1),
              "RemoteJobs.org": env_int("PERSONAL_MAX_REMOTEJOBS_ORG_CALLS", 0, maximum=2)}
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
    audit = []
    candidates, screen_stats, rejection_by_source = screen_candidates(unique, audit=audit)
    history_file = Path(report_path).with_name("personal_discovery_history.local.json")
    history_before = load_history(history_file)
    for job in candidates:
        old = history_before.get(job["job_url"], {})
        job["discovery_status"] = "previously_seen" if old else "new"
        job["review_status"] = old.get("review_status", "pending")
        job["ai_judged"] = bool(old.get("ai_judged", False))
    pending_candidates = [job for job in candidates
                          if pending_for_review(history_before, job)]
    selection_limit = env_int("PERSONAL_MAX_AI_CANDIDATES", 40, minimum=1, maximum=100)
    scoring_pool = [job for job in pending_candidates if not job.get("review_only")]
    shortlist = prioritize_candidates(scoring_pool, selection_limit)
    chosen_urls = {j["job_url"] for j in shortlist}
    for row in audit:
        old = history_before.get(row["job_url"], {})
        row["ai_selected"] = row["job_url"] in chosen_urls
        row["seen_before"] = bool(old)
        row["review_status"] = old.get("review_status", "pending")
        row["ai_judged"] = bool(old.get("ai_judged", False))
    audit_file = write_screening_audit(report_path, audit)
    candidates.sort(key=lambda j: (-j["priority"], j.get("source", ""),
                                   j.get("job_url", "")))
    pending_candidates.sort(key=lambda j: (-j["priority"], j.get("source", ""),
                                           j.get("job_url", "")))
    incremental = Counter((job["source"], job.get("source_query", "legacy/unknown"))
                          for job in unique)
    eval_stats = {"incremental_unique_by_query": [
                      {"source": s, "query": q, "new_unique": count}
                      for (s, q), count in sorted(incremental.items())],
                  "unique": len(unique), "prefiltered_candidates": len(candidates),
                  "precheck": screen_stats, "rejections_by_source": rejection_by_source,
                  "ai_shortlist_count": len(shortlist), "ai_shortlist_limit": selection_limit,
                  "exploratory_review_only": len(pending_candidates) - len(scoring_pool),
                  "pending_for_review": len(pending_candidates),
                  "already_judged_skipped": len(candidates) - len(pending_candidates),
                  "new_candidates": sum(j["discovery_status"] == "new" for j in pending_candidates),
                  "new_postings": sum(row["seen_before"] is False for row in audit),
                  "deferred_by_selection_limit": len(scoring_pool) - len(shortlist),
                  "shortlist_by_source": dict(Counter(j["source"] for j in shortlist)),
                  "shortlist_urls": [j["job_url"] for j in shortlist],
                  "screening_audit_file": str(audit_file),
                  "audit_rows": len(audit),
                  "manual_review_urls": [j["job_url"] for j in pending_candidates if j.get("review_only")]}
    if collect_only:
        completed = pending_candidates  # prior reviewed/AI-judged jobs stay in history, not the queue
    else:
        completed, ai = Evaluator(candidate_profile, PersonalCache(), max_calls=max_ai).evaluate(shortlist)
        eval_stats.update(ai)
    eval_stats["request_provenance"] = http.request_log
    judged_now = {job["job_url"] for job in completed if job.get("assessment")}
    # Publish before marking any jobs AI-judged. If Sheet access fails,
    # cached Gemini assessments remain recoverable on the next scheduled run.
    # Otherwise a completed-but-unpublished job would be silently skipped.
    if write_sheet:
        from personal_sheets import write_personal_results
        # Persist exploratory/manual-review-only vacancies separately from AI
        # Evaluations. Human Review Status and Notes are preserved by URL.
        manual_jobs = [job for job in candidates if job.get("review_only")]
        sheet_stats = write_personal_results(
            completed, stats, http.calls, errors, eval_stats, manual_jobs=manual_jobs
        )
        eval_stats["sheet"] = sheet_stats
    eval_stats["history"] = update_history(history_file, unique, evaluated_urls=judged_now)
    eval_stats["history_file"] = str(history_file)
    path = write_report(report_path, completed, stats, http.calls, errors, eval_stats)
    print(f"Personal run complete: {len(raw)} fetched, {len(unique)} unique, "
          f"{len(candidates)} screened candidates, {len(shortlist)} AI shortlist, "
          f"{len(completed)} evaluated/collected. "
          f"Calls: {dict(http.calls)}. Report: {path}. Audit: {audit_file}")
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
