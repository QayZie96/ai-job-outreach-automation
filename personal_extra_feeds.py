"""Optional public remote-job feed adapters for personal RAY.

No HTTP occurs here. All providers are opt-in through the capped collector.
All output retains the original board's URL and attribution for human review.
"""
from __future__ import annotations

from datetime import timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET


def _text(value):
    if value is None:
        return ""
    return str(value).strip()


def _date(value):
    value = _text(value)
    if not value:
        return ""
    # WWR RSS dates are RFC 2822; JSON feeds usually use ISO 8601.
    if "," in value[:6]:
        try:
            return parsedate_to_datetime(value).astimezone(timezone.utc).date().isoformat()
        except (TypeError, ValueError, OverflowError):
            return ""
    return value[:10]


def _salary(*values):
    return " ".join(_text(value) for value in values if _text(value))


def _job(source, title, company, url, *, identifier="", location="Unknown",
         description="", date="", salary="", job_types=None, tags=None):
    url = _text(url)
    parsed = urlsplit(url)
    if not _text(title) or not _text(company) or parsed.scheme != "https" or not parsed.netloc:
        return None
    return {
        "source": source,
        "source_job_id": _text(identifier) or url,
        "job_title": _text(title),
        "company_name": _text(company),
        "location": _text(location) or "Unknown",
        "remote": True,  # Provider is remote-focused, NOT proof of Greece eligibility.
        "location_restrictions": [],
        "timezone_restrictions": [],
        "job_description": _text(description),
        "job_url": url,
        "created_at": _date(date),
        "job_types": job_types or [],
        "tags": tags or [],
        "seniority": None,
        "salary": _text(salary),
        "source_attribution": url,
    }


def normalize_remote_ok(rows):
    if not isinstance(rows, list):
        raise ValueError("Remote OK response must be a JSON list")
    result = []
    for item in rows:
        if not isinstance(item, dict) or not item.get("position"):
            continue  # First item is Remote OK's legal notice, not a vacancy.
        job = _job(
            "Remote OK", item.get("position"), item.get("company"),
            item.get("url"), identifier=item.get("id"),
            location=item.get("location") or "Unknown",
            description=item.get("description"), date=item.get("date"),
            salary=(_salary(item.get("salary_min"), "–", item.get("salary_max"))
                    if item.get("salary_min") or item.get("salary_max") else ""),
            tags=item.get("tags") if isinstance(item.get("tags"), list) else [],
        )
        if job:
            result.append(job)
    return result


def normalize_remotejobs(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ValueError("RemoteJobs.org response missing data list")
    result = []
    for item in payload["data"][:50]:
        if not isinstance(item, dict):
            continue
        company = item.get("company") or {}
        company = company.get("name") if isinstance(company, dict) else company
        region = item.get("location")
        if isinstance(region, dict):
            region = region.get("name") or region.get("display_name") or ""
        types = item.get("employment_types") or []
        if not isinstance(types, list):
            types = [types]
        job = _job(
            "RemoteJobs.org", item.get("title"), company,
            item.get("url") or item.get("job_url"),
            identifier=item.get("id"),
            location=region or "Unknown",
            description=item.get("description"),
            date=item.get("posted_at"),
            salary=item.get("salary_text") or item.get("salary_source_text") or "",
            job_types=types,
        )
        if job:
            result.append(job)
    return result


def normalize_wwr_rss(xml_text):
    if not isinstance(xml_text, str):
        raise ValueError("We Work Remotely feed must be RSS text")
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ValueError("We Work Remotely malformed RSS document") from exc
    if root.tag != "rss" or root.find("channel") is None:
        raise ValueError("We Work Remotely unexpected RSS document")
    results = []
    for item in root.findall("./channel/item")[:120]:
        original_title = _text(item.findtext("title"))
        # WWR publishes e.g. "Employer: Job title".
        if ":" not in original_title:
            continue  # No verified company identity: don't manufacture it.
        company, title = original_title.split(":", 1)
        job = _job(
            "We Work Remotely", title, company, item.findtext("link"),
            identifier=item.findtext("guid"),
            location="Unknown", # RSS does not establish permitted hiring countries.
            description=item.findtext("description"),
            date=item.findtext("pubDate"),
        )
        if job:
            results.append(job)
    return results
