"""Offline-only v4.1 candidate-fit guardrails and local discovery history.

No HTTP, Gemini, Sheets, or dependence on the original RAY application.
This is deterministic triage rather than proof of hiring eligibility.
"""
from __future__ import annotations

import csv
import hashlib
from datetime import datetime, timezone
import html
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

LANGUAGES = ("spanish", "german", "dutch", "french", "italian", "portuguese",
             "polish", "swedish", "danish", "norwegian", "finnish", "turkish",
             "arabic", "japanese", "russian", "ukrainian", "czech",
             "chinese", "mandarin", "korean", "hindi", "armenian")
OPTIONAL = re.compile(r"\b(preferred|desirable|advantage|optional|a plus|nice.to.have|bonus|not required|a benefit)\b", re.I)
DUTIES = re.compile(r"\b(manag|coordinat|automat|analys|analyz|report|data|workflow|"
                    r"catalog|inventory|customer|commerce|supplier|operations|project|"
                    r"marketing|crm|website|process|sourcing|order|pricing|support)\w*", re.I)
CORE = re.compile(r"\b(e.commerce|marketplace|catalog(?:ue)?|pricing|merchant|"
                  r"seller|inventory|procurement|product data|supplier|revenue operations)\b", re.I)
AUTOMATION = re.compile(r"\b(ai automation|workflow automation|automati(?:on|ng)|"
                        r"digital enablement|process improvement|business systems|n8n)\b", re.I)
ADJACENT = re.compile(r"\b(marketing operations|marketing coordinator|marketing assistant|"
                      r"crm|lifecycle|campaign operations|marketing automation|email marketing|"
                      r"marketing specialist|project coordinator|project assistant|"
                      r"office assistant|office administrator|administrative assistant|"
                      r"operations assistant|business support|sales support|implementation|"
                      r"onboarding|customer success|commercial operations|data analyst)\b", re.I)
SENIOR = re.compile(r"\b(director|head of|vp|vice president|chief|senior|sr\.|lead)\b", re.I)


def _clean(text: str) -> str:
    """Job descriptions reach this module as stripped source text or raw HTML."""
    value = str(text or "")
    value = re.sub(r"(?is)<(?:script|style)\b[^>]*>.*?</(?:script|style)>", " ", value)
    value = re.sub(r"<[^>]+>", " ", value)
    return " ".join(html.unescape(value).split())[:15000]


def mandatory_language(title: str, description: str) -> str | None:
    """Return ONLY an evidenced advanced mandatory non-English/Greek language.

    Detect joint requirements (English and Spanish), role-specific language, and
    explicit required/fluent/native/C1-C2 statements. Ignore preferences.
    """
    title, desc = _clean(title).lower(), _clean(description).lower()
    for language in LANGUAGES:
        lang = re.escape(language)
        if re.search(rf"\b{lang}(?:[- ]speaking|[- ]fluen\w*)\b|"
                     rf"\b{lang}\s+(?:fluency|required|c1|c2)\b", title):
            return language.title()
        # A B2 requirement may appear as "speak English and German fluently".
        # Merely mentioning Germany or German clients is insufficient evidence.
        if (re.search(rf"\bwith\s+{lang}\b", title)
                and re.search(
                    rf"\b{lang}\b.{0,55}\b(?:fluent|fluently|b2|c1|c2|required|mandatory)\b|"
                    rf"\bspeak\s+english\s+and\s+{lang}\s+fluently\b", desc)):
            return language.title()
        # "Native-level German" is mandatory language evidence, not a market label.
        for native_match in re.finditer(rf"\bnative[- ]level\s+{lang}\b", desc):
            # Optional/preferred/native-level desirable is not mandatory.
            trailing = desc[native_match.end():native_match.end() + 75]
            if not re.search(r"\b(?:a plus|preferred|optional|desirable|not required)\b", trailing):
                return language.title()
        patterns = (
            rf"\b(?:fluent|fluency|native|c1|c2|business fluent|professional proficiency)"
            rf"\s+(?:in\s+)?{lang}\b",
            rf"\b{lang}\s+(?:language\s+)?(?:fluency|proficiency)\s+(?:is\s+)?(?:required|essential|mandatory|needed)\b",
            rf"\b(?:must|require\w*|need)\s+(?:to\s+)?(?:speak|write|understand|know)?\s*{lang}\b",
            rf"\b(?:excellent|strong|advanced|professional)\s+"
            rf"(?:written\s+and\s+spoken\s+|verbal\s+and\s+written\s+)?"
            rf"(?:english\s+and\s+)?{lang}\s+(?:language\s+)?(?:skills|proficiency|fluency)\b",
            rf"\b(?:english\s+and\s+{lang}|{lang}\s+and\s+english)\s+"
            rf"(?:language\s+)?(?:skills|proficiency|fluency)\b",
            rf"\bfluency\s+in\s+(?:english\s+and\s+)?{lang}\b",
        )
        for pattern in patterns:
            for match in re.finditer(pattern, desc):
                # Restrict preference negation to the local clause to avoid
                # unrelated 'German is a plus' defeating mandatory French.
                lo = max(0, desc.rfind('.', 0, match.start()) + 1,
                         desc.rfind(';', 0, match.start()) + 1)
                hi_dots = [x for x in (desc.find('.', match.end()), desc.find(';', match.end())) if x != -1]
                hi = min(hi_dots) if hi_dots else min(len(desc), match.end() + 90)
                clause = desc[lo:hi]
                if OPTIONAL.search(clause) and not re.search(r"\b(?:must|required|essential|mandatory|needed)\b", clause):
                    continue
                if re.search(r"\bnot required\b", clause):
                    continue
                return language.title()
        # Local-language requirements, only on affirmative constructions.
        if language == "dutch" and re.search(r"(?:je spreekt|spreekt|beheers)\s+(?:vloeiend|uitstekend)\s+nederlands|vloeiend nederlands", desc):
            return "Dutch"
        if language == "german" and re.search(r"(?:du sprichst|sie sprechen)\s+(?:flie\u00dfend|fliessend|sehr gut)\s+deutsch|verhandlungssichere deutschkenntnisse", desc):
            return "German"
    return None


def calibrated_factors(title: str, description: str) -> dict:
    """Transparent flags, never an AI fit score. Only unambiguous exclusions hard-block."""
    title, desc = _clean(title), _clean(description)
    low, tlow = desc.lower(), title.lower()
    blockers, boosts = [], 0
    language = mandatory_language(title, desc)
    if language:
        return {"hard_exclusion": "mandatory_language", "reason": f"Advanced mandatory {language}",
                "flags": [f"mandatory_{language.lower()}"], "priority_delta": 0,
                "force_review": False, "promote_review": False}

    # Explicit language-pair translation/localization roles require fluency in
    # the target language. Avoid spending Gemini calls on "English to Armenian"
    # or similar requirements unsupported by the user's English/Greek profile.
    if re.search(
        r"\benglish\s+(?:to|into)\s+(?:armenian|spanish|german|"
        r"dutch|french|italian|portuguese|polish|russian|ukrainian|"
        r"turkish|arabic|japanese|czech|korean|chinese|hindi)\b",
        tlow,
    ):
        return {"hard_exclusion": "mandatory_language",
                "reason": "Translation/localization target language not in verified profile",
                "flags": ["unsupported_translation_language"], "priority_delta": 0,
                "force_review": False, "promote_review": False}

    # Explicit specialist capabilities absent from the verified portfolio
    # remain human-review leads; they are not discarded as unrelated.
    if re.search(r"\bsewing\s+specialist\b", tlow) and re.search(
        r"\bhands[- ]on\s+experience\s+with\s+sewing\b", low
    ):
        blockers.append("sewing_specialist_experience_unverified")
    if re.search(r"\bamazon\s+marketplace\s+manager\b", tlow) and re.search(
        r"\bdeep\s+understanding\s+of\s+amazon\s+seller\s+central\b", low
    ):
        blockers.append("amazon_seller_central_expertise_unverified")
    if re.search(r"\b(?:senior|sr\.?|director|head of|vp|vice president)\b", tlow):
        blockers.append("advanced_role_seniority_review")

    # Substantial non-English descriptions are *not* proof of mandatory
    # language fluency, but are unsuitable for scarce automatic AI scoring.
    # Use function words, not a job's geography, to request human review.
    posting_words = re.findall(r"[a-zà-ÿ]+", low[:5000])
    dutch_words = {
        "voor", "zoeken", "iemand", "geen", "het", "een", "met", "van",
        "die", "dat", "de", "er", "wordt", "ook", "maar", "zijn",
        "moet", "als", "opdracht", "ervaring", "waar", "bij", "om",
        "deze", "dit", "alle", "meer", "willen", "juist", "kunnen",
        "naar", "ons", "over", "zorgen",
    }
    if (len(posting_words) >= 75
            and sum(w in dutch_words for w in posting_words) / len(posting_words) >= 0.14):
        blockers.append("predominantly_dutch_language_posting_review")
    if (re.search(r"\b(?:creative\s*/\s*content|creative\s+content)\s+lead\b", tlow)
            and re.search(r"\bcreative\s+direction\b|\bart\s+direction\b", low)):
        blockers.append("creative_direction_specialism_unverified")
    if (re.search(r"\bproduct\s+manager\b", tlow)
            and re.search(
                r"\b3\+?\s+years?\s+of\s+product\s+management\s+experience\b"
                r".{0,45}\bin\s+a\s+product\s+company\b", low
            )):
        blockers.append("dedicated_product_manager_experience_unverified")

    # Only explicit AI annotation/rating work, not AI implementation or automation.
    ai_annotation = bool(re.search(r"\b(?:train|training|evaluate|evaluation|rate|rating|label|annotat)"
                                   r".{0,35}\b(?:ai models?|language models?|llms?|model responses?|ai outputs?)\b|"
                                   r"\b(?:ai models?|language models?|llms?|model responses?|ai outputs?)"
                                   r".{0,35}\b(?:train|training|rate|rating|label|annotat)\b", low))
    ai_annotation = ai_annotation or bool(re.search(r"help\s+train\s+(?:next[ -]generation\s+)?ai\s+systems|"
                                                 r"review.{0,45}feedback.{0,80}simulated.{0,45}scenarios|"
                                                 r"improving\s+ai\s+outputs", low))
    if ai_annotation and re.search(r"\b(expert|annotator|trainer|evaluator|ai training)\b", tlow) and not AUTOMATION.search(title):
        return {"hard_exclusion": "incompatible_role", "reason": "AI model rating/annotation is outside target work",
                "flags": ["ai_annotation_role"], "priority_delta": 0,
                "force_review": False, "promote_review": False}

    if re.search(r"\b(?:bachelor'?s?|master'?s?|university|college)\s+(?:degree|diploma)\b|"
                 r"\bdegree\s+(?:in|required|from|at least)\b", low):
        mentions = re.findall(r".{0,45}(?:bachelor'?s?|master'?s?|university|college)\s+(?:degree|diploma).{0,115}|"
                              r".{0,45}\bdegree\s+(?:in|required|from|at least).{0,115}", low)
        if mentions and not all(OPTIONAL.search(m) or re.search(r"equivalent\s+(?:professional\s+)?experience|"
                              r"experience\s+in\s+lieu|or\s+equivalent", m) for m in mentions):
            blockers.append("formal_degree_not_verified")

    # Specific, substantial management tenure (not 7 years overall operations).
    if re.search(r"\b(?:[5-9]|1\d)\+?\s+years?(?:\s+of)?\s+"
                 r"(?:customer service management|managing\s+(?:large\s+)?teams|"
                 r"people management|direct management|leadership experience|"
                 r"in a\s+(?:management|leadership)\s+role)\b|"
                 r"\b(?:[5-9]|1\d)\s+years?[\x27\u2019]?\s+experience\s+in\s+a\s+customer\s+service\s+management\s+role\b|"
                 r"\b(?:proven|extensive)\s+people[ -]leadership\s+experience\b|"
                 r"\b(?:managing|leading|direct oversight of)\s+(?:a\s+)?"
                 r"(?:40|50|60|70|80|90|100)[-+ ]+(?:people|staff|employees|reports)\b", low):
        blockers.append("substantial_people_leadership_required")
    elif SENIOR.search(title) and re.search(r"\b(proven|extensive|significant)\s+(?:people[ -])?leadership|"
                                           r"\bmanage\s+a\s+team\s+of\s+\d+", low):
        blockers.append("leadership_experience_review")

    # Specialisms user cannot establish through marketplace + practical projects.
    if re.search(r"\b(?:[5-9]|1\d)\+?\s+years?(?:\s+of)?\s+(?:"
                 r"(?:experience|hands.on experience|proven experience)\s+)?(?:in\s+)?"
                 r"(?:sap|oracle erp|netsuite|crypto exchanges?|fintech|banking|paid media|"
                 r"email marketing|enterprise saas|clinical|biotech|digital advertising|"
                 r"supply chain management)\b", low) or \
       re.search(r"\b(?:[5-9]|1\d)\+?\s+years?\s+of\s+sap\s+functional", low):
        blockers.append("specialist_tenure_unverified")
    if re.search(r"\b(?:8|9|10|11|12|15)\+?\s+years?\s+(?:of\s+)?(?:relevant\s+)?"
                 r"(?:experience|work experience)", low):
        blockers.append("extended_experience_required")
    if re.search(r"\badvanced\s+proficiency\s+with\s+(?:marketo|hubspot|salesforce marketing cloud)\b", low):
        blockers.append("advanced_marketing_stack_unverified")
    if re.search(r"\b(?:must|required|essential)\s+(?:have\s+)?(?:hands.on\s+)?(?:sap|netsuite|marketo|klaviyo|"
                 r"amazon seller central|salesforce administrator)\s+(?:experience|expertise|knowledge)\b", low):
        blockers.append("named_platform_expertise_unverified")

    # Senior individual-contributor titles can be interesting but rarely
    # establish hireability from transferable operations evidence alone.
    # Preserve them for human review, not automatic AI expenditure.
    if re.search(r"\b(?:staff|principal)\b", tlow):
        blockers.append("advanced_individual_contributor_seniority")

    if CORE.search(title): boosts += 18
    elif AUTOMATION.search(title): boosts += 14
    elif ADJACENT.search(title): boosts += 12
    elif re.search(r"\b(?:assistant|coordinator|administrator|office support|analyst|associate)\b", title, re.I):
        boosts += 7 if DUTIES.search(desc) else 0
    if re.search(r"\b(?:junior|entry.level|assistant|coordinator)\b", title, re.I): boosts += 5
    if re.search(r"\b(?:director|head of|vp|vice president|chief)\b", title, re.I): blockers.append("executive_seniority")
    if re.search(r"\b(?:senior|staff|principal)\b", title, re.I) and blockers:
        blockers.append("senior_specialist")
    if blockers:
        boosts -= 18 + 6 * min(3, len(blockers))
    return {"hard_exclusion": None, "reason": "", "flags": blockers,
            "priority_delta": boosts, "force_review": bool(blockers),
            "promote_review": bool(ADJACENT.search(title) and DUTIES.search(desc))}


def replay_audit(audit_path: str | Path, report_path: str | Path | None = None,
                 output_path: str | Path | None = None) -> dict:
    """Reclassify the same frozen URL inventory; excluded descriptions are truncated.

    Previously retained jobs get full text from the collect-only report; other
    jobs use audit excerpts only. No HTTP/AI calls, and no made-up geo eligibility.
    """
    audit_path = Path(audit_path)
    report = json.loads(Path(report_path).read_text(encoding="utf-8")) if report_path else {}
    full = {j["job_url"]: j.get("job_description", "") for j in report.get("evaluated_jobs", [])}
    with audit_path.open(newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    seen = set()
    transitions = []
    counts = {"old": {}, "new": {}, "evidence_full": 0, "evidence_excerpt": 0}
    for row in rows:
        url = row["job_url"]
        if url in seen:
            raise ValueError(f"Frozen audit has duplicate job URL: {url}")
        seen.add(url)
        title = row["job_title"]
        desc = full.get(url) or row.get("description_excerpt", "")
        kind = "full" if url in full else "excerpt"
        counts["evidence_" + kind] += 1
        factors = calibrated_factors(title, desc)
        before = row["screen_outcome"]
        after = before
        if factors["hard_exclusion"] and before in ("candidate", "review_only"):
            after = factors["hard_exclusion"] + "_excluded"
        elif before == "candidate" and factors["force_review"]:
            after = "review_only"
        elif (before == "role_out_of_scope" and factors["promote_review"]
              and row.get("role_reason") == "insufficient operational role evidence"
              and not re.search(r"\b(?:engineer|architect|developer|intern|internship|executive)\b", title, re.I)):
            after = "review_only"  # eligibility remains unverified, not 'eligible'
        rank = int(row["priority"]) if row.get("priority", "").lstrip("-").isdigit() else 0
        rank += factors["priority_delta"]
        if after == "review_only" and kind == "excerpt": rank -= 10
        transitions.append({"source": row["source"], "company": row["company"], "job_title": title,
                            "job_url": url, "old_outcome": before, "new_outcome": after,
                            "evidence": kind, "geography": row.get("eligibility", "not_checked"),
                            "rank": rank, "flags": ";".join(factors["flags"]),
                            "reason": factors["reason"]})
        counts["old"][before] = counts["old"].get(before, 0) + 1
        counts["new"][after] = counts["new"].get(after, 0) + 1
    if output_path:
        dest = Path(output_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(transitions[0]) if transitions else [])
            writer.writeheader()
            for row in transitions:
                writer.writerow({k: "'" + v if isinstance(v, str) and v.lstrip().startswith(("=", "+", "-", "@")) else v
                                 for k, v in row.items()})
    return {"total": len(transitions), **counts,
            "changed": sum(x["old_outcome"] != x["new_outcome"] for x in transitions),
            "transitions": transitions}


def load_history(history_path: str | Path) -> dict:
    path = Path(history_path)
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if not isinstance(data, dict):
        raise ValueError("Invalid history file")
    return data


def _atomic_history(path: Path, records: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    try:
        temp.write_text(json.dumps(records, indent=2, ensure_ascii=False, sort_keys=True),
                        encoding="utf-8")
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def _posting_fingerprint(job: dict) -> str:
    """Stable across complete descriptions and matching first-2500-character audit excerpts."""
    title = str(job.get("job_title") or job.get("title") or "").strip().lower()
    description = _clean(job.get("job_description") or job.get("description_excerpt") or "")[:2500].lower()
    return hashlib.sha256((title + "\n" + description).encode("utf-8")).hexdigest()


def pending_for_review(history: dict, job: dict) -> bool:
    """Seen is not judged. Explicit user decisions and completed AI reviews are terminal."""
    old = history.get(str(job.get("job_url") or ""), {})
    return (old.get("review_status", "pending") not in ("reviewed", "dismissed", "applied")
            and not old.get("ai_judged", False))


def mark_review(history_path: str | Path, url: str, status: str) -> dict:
    """Only an explicit local command can mark or reset a human review decision."""
    if status not in ("pending", "reviewed", "dismissed", "applied"):
        raise ValueError("Invalid review status")
    history_path = Path(history_path)
    data = load_history(history_path)
    if url not in data:
        raise ValueError("Unknown job URL; seed or collect the job first")
    rec = data[url]
    rec["review_status"] = status
    rec["reviewed_at"] = (datetime.now(timezone.utc).isoformat()
                          if status != "pending" else None)
    if status == "pending":
        rec["ai_judged"] = False
        rec["ai_judged_at"] = None
        rec["content_updated_since_review"] = False
    _atomic_history(history_path, data)
    return {"job_url": url, "review_status": status}


def update_history(history_path: str | Path, jobs: list[dict],
                   timestamp: str | None = None, evaluated_urls=None) -> dict:
    """Remember observed postings and review decisions; absence does not imply closure."""
    dest = Path(history_path)
    timestamp = timestamp or datetime.now(timezone.utc).isoformat()
    previous = load_history(dest)
    evaluated_urls = set(evaluated_urls or [])
    present = set()
    new_count = 0
    for job in jobs:
        url = str(job.get("job_url") or "")
        parsed = urlsplit(url)
        if parsed.scheme not in {"https", "http"} or not parsed.netloc:
            continue
        present.add(url)
        old = previous.get(url, {})
        if not old:
            new_count += 1
        fingerprint = _posting_fingerprint(job)
        old_fp = old.get("content_fingerprint")
        changed = bool(old_fp and old_fp != fingerprint)
        ai_judged = bool(old.get("ai_judged", False) or url in evaluated_urls)
        previous[url] = {
            **old,
            "url": url,
            "source": str(job.get("source") or old.get("source", "")),
            "company": str(job.get("company_name") or job.get("company") or old.get("company", "")),
            "title": str(job.get("job_title") or old.get("title", "")),
            "first_seen": old.get("first_seen", timestamp),
            "last_seen": timestamp,
            "last_seen_in_provider_run": timestamp,
            "status": "seen_in_feed_unverified_open",
            "geography_status": str(job.get("precheck_eligibility") or job.get("eligibility") or "uncertain"),
            "manual_review_only": bool(job.get("review_only", True)),
            "requires_manual_recheck": True,
            "review_status": old.get("review_status", "pending"),
            "reviewed_at": old.get("reviewed_at"),
            "ai_judged": ai_judged,
            "ai_judged_at": timestamp if url in evaluated_urls else old.get("ai_judged_at"),
            "content_fingerprint": fingerprint,
            "content_updated_since_review": bool(
                old.get("content_updated_since_review", False) or
                (changed and (old.get("review_status") in
                 ("reviewed", "dismissed", "applied") or old.get("ai_judged")))
            ),
        }
    for url, old in previous.items():
        if url not in present:
            old["status"] = "not_seen_in_latest_run_status_unknown"
            old["requires_manual_recheck"] = True
    _atomic_history(dest, previous)
    return {"tracked": len(previous), "new_in_history": new_count,
            "seen_this_run": len(present),
            "not_seen_this_run_status_unknown": len(previous) - len(present),
            "already_judged": sum(not pending_for_review(previous, j) for j in jobs)}



def _main():
    import argparse
    parser = argparse.ArgumentParser(description="Offline candidate screening, observation history, and manual review state; never calls job APIs.")
    parser.add_argument("--audit", help="Frozen screening audit CSV for replay")
    parser.add_argument("--report", help="Matching collect-only report, for description evidence or observation timestamp")
    parser.add_argument("--output", help="Write replay decisions to CSV")
    parser.add_argument("--seed-reports", nargs="+", metavar="JSON",
                        help="Oldest-to-newest collect-only reports to seed history")
    parser.add_argument("--seed-audit", help="Seed ALL screened URL observations from an audit CSV")
    parser.add_argument("--mark-url", help="Previously observed job URL to mark")
    parser.add_argument("--status", choices=("pending", "reviewed", "dismissed", "applied"),
                        help="Human decision; pending explicitly reopens an existing job")
    parser.add_argument("--history", default="personal_discovery_history.local.json")
    args = parser.parse_args()
    mode_count = sum(bool(x) for x in (args.audit, args.seed_reports, args.seed_audit, args.mark_url))
    if mode_count != 1:
        parser.error("Choose exactly one of --audit, --seed-reports, --seed-audit, --mark-url")
    if args.audit:
        result = replay_audit(args.audit, args.report, args.output)
        print(json.dumps({k: v for k, v in result.items() if k != "transitions"}, indent=2))
    elif args.mark_url:
        if not args.status:
            parser.error("--mark-url requires --status")
        print(json.dumps(mark_review(args.history, args.mark_url, args.status), indent=2))
    elif args.seed_audit:
        run_timestamp = None
        if args.report:
            run_timestamp = json.loads(Path(args.report).read_text(encoding="utf-8")).get("run_utc")
        with Path(args.seed_audit).open(newline="", encoding="utf-8-sig") as fh:
            rows = list(csv.DictReader(fh))
        jobs = [{"job_url": r["job_url"], "source": r.get("source", ""),
                 "job_title": r.get("job_title", ""), "company_name": r.get("company", ""),
                 "description_excerpt": r.get("description_excerpt", ""),
                 "eligibility": r.get("eligibility", "uncertain"),
                 "review_only": r.get("screen_outcome") != "candidate"}
                for r in rows]
        print(json.dumps(update_history(args.history, jobs, run_timestamp), indent=2))
    else:
        for p in args.seed_reports:
            raw = json.loads(Path(p).read_text(encoding="utf-8"))
            stats = update_history(args.history, raw["evaluated_jobs"], raw["run_utc"])
        print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    _main()
