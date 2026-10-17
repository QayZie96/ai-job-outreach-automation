"""Offline, permission-respecting Adzuna hosted-detail HTML comparison.

Never makes HTTP requests. Does NOT open Adzuna, job boards, publisher sites,
Gemini, or Google Sheets. Save ONE Adzuna-hosted page manually in your browser
first, then inspect the saved HTML against an existing collect-only report.

Usage:
  python adzuna_saved_page_probe.py --report adzuna_probe/run_auth.json \
      --job-id 5930905647 --html adzuna_probe/5930905647.html
"""
from __future__ import annotations

import argparse
from difflib import SequenceMatcher
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup


_HOSTS = frozenset({"adzuna.de", "www.adzuna.de"})
_CAP = 5_000_000


def _clean_markup(value: object) -> str:
    html = str(value or "")
    return " ".join(BeautifulSoup(html, "html.parser").stripped_strings)


def _jobposting_nodes(tree):
    if isinstance(tree, list):
        for v in tree:
            yield from _jobposting_nodes(v)
    elif isinstance(tree, dict):
        kind = tree.get("@type", "")
        kinds = kind if isinstance(kind, list) else [kind]
        if any(k == "JobPosting" or str(k).endswith("/JobPosting") for k in kinds):
            yield tree
        if "@graph" in tree:
            yield from _jobposting_nodes(tree["@graph"])


def _title_ratio(a, b) -> float:
    clean = lambda x: re.sub(r"[^a-z0-9]+", " ", str(x or "").casefold()).strip()
    return SequenceMatcher(None, clean(a), clean(b)).ratio()


def inspect_saved_page(report_path: Path, job_id: str, html_path: Path) -> dict:
    data = json.loads(Path(report_path).read_text(encoding="utf-8"))
    jobs = data.get("evaluated_jobs", [])
    if not isinstance(jobs, list):
        raise ValueError("Not a collect-only Personal RAY report")
    matches = [j for j in jobs if j.get("source") == "Adzuna"
               and str(j.get("source_job_id")) == str(job_id)]
    if len(matches) != 1:
        raise ValueError("Expected exactly one matching Adzuna job ID in report")
    job = matches[0]
    parsed = urlsplit(job.get("job_url", ""))
    if (parsed.scheme != "https" or parsed.hostname not in _HOSTS
            or parsed.path != f"/details/{job_id}"):
        raise ValueError("Refusing non-Adzuna or redirect-style /land/ad listing")
    size = Path(html_path).stat().st_size
    if size > _CAP:
        raise ValueError("Local HTML exceeds five-megabyte safety limit")
    soup = BeautifulSoup(Path(html_path).read_text(encoding="utf-8", errors="replace"),
                         "html.parser")
    # Never treat a manually saved redirect to another provider as Adzuna data.
    identities = []
    for link in soup.find_all("link", rel="canonical"):
        identities.append(link.get("href", ""))
    for meta in soup.find_all("meta", attrs={"property": "og:url"}):
        identities.append(meta.get("content", ""))
    for url in identities:
        p = urlsplit(url)
        if p.scheme in {"http", "https"} and p.hostname not in _HOSTS:
            return {"status": "blocked_non_adzuna_page", "job_id": job_id,
                    "network_requests": 0, "snippet_chars": len(_clean_markup(job.get("job_description")))}
    for element in soup(["script", "style", "noscript"]):
        if element.name != "script" or element.get("type", "").split(";")[0].strip().lower() != "application/ld+json":
            element.decompose()
    title = str(job.get("job_title") or "")
    candidates = []
    for element in soup.find_all("script", attrs={"type": re.compile(r"application/ld\+json", re.I)}):
        try:
            raw = json.loads(element.string or element.get_text())
        except (ValueError, TypeError):
            continue
        for node in _jobposting_nodes(raw):
            desc = _clean_markup(node.get("description"))
            if desc:
                candidates.append(("JobPosting JSON-LD", desc, _title_ratio(title, node.get("title"))))
    # Conservative DOM fallback: do not confuse the entire page with job text.
    for selector in ('[itemprop="description"]', '[data-testid="job-description"]',
                     ".job-description", "#job-description"):
        for el in soup.select(selector):
            desc = _clean_markup(str(el))
            if desc:
                candidates.append((f"HTML: {selector}", desc, 0.0))
    excerpt = _clean_markup(job.get("job_description"))
    result = {"job_id": str(job_id), "job_title": title,
              "snippet_chars": len(excerpt), "saved_html_bytes": size,
              "network_requests": 0, "external_redirects_followed": 0,
              "canonical_identity_checked": bool(identities)}
    if not candidates:
        text = _clean_markup(str(soup))[:1500].lower()
        result.update({"status": "access_challenge_or_empty"
                       if any(s in text for s in ("verify that you're not a robot", "access denied",
                                                   "captcha", "javascript is disabled"))
                       else "no_structured_job_description_found",
                       "extracted_description_chars": 0,
                       "source": None, "title_similarity": None})
        return result
    candidates.sort(key=lambda c: (c[2], len(c[1])), reverse=True)
    source, full, similarity = candidates[0]
    result.update({
        "source": source, "extracted_description_chars": len(full),
        "title_similarity": round(similarity, 3) if source == "JobPosting JSON-LD" else None,
        "status": ("longer_description_candidate"
                   if len(full) >= max(800, len(excerpt) + 250)
                   and (source != "JobPosting JSON-LD" or similarity >= 0.35)
                   else "insufficient_or_mismatched_description"),
    })
    # Excerpts and full text are intentionally NEVER stored or printed.
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--html", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(inspect_saved_page(args.report, args.job_id, args.html),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
