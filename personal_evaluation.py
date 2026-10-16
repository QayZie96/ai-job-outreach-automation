"""Personal RAY evaluation: one Gemini pass, budgeted, using the existing SQLite cache.

Does not touch the original RAY validator, prompts, or sheet. No credentials or
CV data are committed: PERSONAL_PROFILE_PATH refers to a private local file.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
import sqlite3
from pathlib import Path

MODEL = os.getenv("PERSONAL_GEMINI_MODEL", "gemini-3.5-flash-lite")
BATCH_SIZE = 20
ROOT = Path(__file__).resolve().parent
PROMPT_FILE = ROOT / "prompts" / "personal_fit_prompt.txt"
CACHE_PATH = ROOT / "validation_cache.db"  # same database/table as the RAY validator
CACHE_NAMESPACE = "personal-fit-v1:"
VALID_ELIGIBILITY = {"eligible", "uncertain", "ineligible"}


def profile_text():
    path = os.getenv("PERSONAL_PROFILE_PATH", "profiles/personal_profile.local.txt")
    profile = Path(path)
    if not profile.is_absolute():
        profile = ROOT / profile
    if not profile.is_file():
        raise FileNotFoundError(
            f"Private candidate profile missing: {profile}. "
            "Create it from your verified CV and evidence (never commit it)."
        )
    content = profile.read_text(encoding="utf-8").strip()
    if len(content) < 60:
        raise ValueError("Candidate profile is empty or too short for evidence-based scoring")
    return content


def cache_key(job):
    source = str(job.get("source") or "").strip().lower()
    identity = str(job.get("source_job_id") or job.get("job_url") or "").strip()
    return CACHE_NAMESPACE + source + ":" + identity if source and identity else ""


def fingerprint(job, profile, prompt, model=MODEL):
    record = {k: job.get(k) for k in (
        "job_title", "company_name", "location", "job_description", "remote",
        "location_restrictions", "timezone_restrictions", "job_types", "seniority",
        "source", "source_job_id", "job_url",
    )}
    record.update({"profile": profile, "prompt": prompt, "model": model, "schema": 1})
    return hashlib.sha256(json.dumps(record, sort_keys=True, default=str).encode()).hexdigest()


class PersonalCache:
    """Use the *existing* validation_cache table with segregated personal keys."""
    def __init__(self, path=CACHE_PATH):
        self.path = Path(path)
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS validation_cache (
                job_url TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
                result_json TEXT NOT NULL, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )""")

    @contextmanager
    def _connect(self):
        # sqlite3.Connection.__exit__ commits/rolls back but does NOT close.
        # Explicit closure is necessary for Windows temporary-file cleanup.
        connection = sqlite3.connect(self.path)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def get(self, job, fp):
        key = cache_key(job)
        if not key:
            return None
        with self._connect() as db:
            row = db.execute("SELECT result_json FROM validation_cache "
                             "WHERE job_url = ? AND fingerprint = ?", (key, fp)).fetchone()
        if row is None:
            return None
        try:
            result = json.loads(row[0])
            validate_result(result)  # changing output contracts invalidates old cache
            return result
        except (ValueError, TypeError, KeyError):
            return None

    def put(self, job, fp, result):
        key = cache_key(job)
        if not key:
            return
        validate_result(result)
        with self._connect() as db:
            db.execute("""INSERT INTO validation_cache (job_url, fingerprint, result_json)
              VALUES (?, ?, ?) ON CONFLICT(job_url) DO UPDATE SET
              fingerprint=excluded.fingerprint, result_json=excluded.result_json,
              updated_at=CURRENT_TIMESTAMP""", (key, fp, json.dumps(result)))


def validate_result(item):
    if not isinstance(item, dict) or item.get("eligibility") not in VALID_ELIGIBILITY:
        raise ValueError("Missing or invalid eligibility")
    score = item.get("fit_score")
    if score is not None and (type(score) is not int or not 0 <= score <= 100):
        raise ValueError("fit_score must be an integer in 0..100 or null")
    for field in ("reason", "main_gap_or_uncertainty"):
        if not isinstance(item.get(field), str):
            raise ValueError(f"Invalid {field}")
    for field in ("mandatory_requirements", "matched_evidence", "posting_evidence"):
        if not isinstance(item.get(field), list) or not all(isinstance(x, str) for x in item[field]):
            raise ValueError(f"Invalid {field}")
    return item


def classify(result, job):
    """Compute category locally; the model cannot grant itself a Strong Match."""
    eligibility = result["eligibility"]
    # A model's confidence cannot override unresolved jurisdictional evidence.
    # Preserve uncertainty for human review unless our local check found
    # explicit permitted country / EU hybrid-work evidence.
    if job.get("precheck_eligibility") == "uncertain" and eligibility == "eligible":
        eligibility = "uncertain"
        result["main_gap_or_uncertainty"] = (
            result.get("main_gap_or_uncertainty") or
            "Remote hiring eligibility from Greece has not been verified"
        )
    # Himalayas explicitly defines a nonempty country list as the only permitted countries.
    if job.get("source") == "Himalayas" and job.get("location_restrictions"):
        codes = {str(x).upper() for x in job["location_restrictions"]}
        if "GR" not in codes and "GREECE" not in codes:
            eligibility = "ineligible"
            result["main_gap_or_uncertainty"] = "Himalayas country restrictions exclude Greece"
    geo = str(job.get("location") or "").strip().lower()
    if job.get("source") == "Jobicy" and geo in {"usa", "united states", "us only", "united states only"}:
        eligibility = "ineligible"
    # Europe/EMEA alone does not prove remote hiring is permitted from Greece.
    if job.get("remote") and geo in {"europe", "emea", "european union", "eu"} and eligibility == "eligible":
        eligibility = "uncertain"
        result["main_gap_or_uncertainty"] = "Remote hiring from Greece not explicitly confirmed"
    result["eligibility"] = eligibility
    score = result["fit_score"]
    if eligibility == "ineligible":
        decision = "Ineligible"
    elif eligibility == "uncertain" or score is None:
        decision = "Review"
    elif score >= 70 and (not result["matched_evidence"] or not result["posting_evidence"]):
        # A high number alone is insufficient. Strong requires linked evidence.
        decision = "Review"
        result["main_gap_or_uncertainty"] = (
            result["main_gap_or_uncertainty"] or "Supporting posting/profile evidence missing"
        )
    elif score >= 70:
        decision = "Strong Match"
    elif score >= 55:
        decision = "Review"
    else:
        decision = "Low Match"
    result["decision"] = decision
    return result


def parse_batch(raw, jobs):
    if not isinstance(raw, list) or len(raw) != len(jobs):
        raise ValueError("Gemini did not return one result per job")
    found = {}
    for item in raw:
        index = item.get("job_index") if isinstance(item, dict) else None
        if type(index) is not int or not 0 <= index < len(jobs) or index in found:
            raise ValueError("Gemini response had duplicate/invalid job_index")
        found[index] = validate_result(item)
    return [classify(found[i], job) for i, job in enumerate(jobs)]


class Evaluator:
    def __init__(self, profile, cache, max_calls=5, model=None, client=None):
        self.profile = profile
        self.cache = cache
        self.max_calls = max_calls
        self.calls = 0
        self.model = model or os.getenv("PERSONAL_GEMINI_MODEL", MODEL)
        self.client = client
        self.prompt = PROMPT_FILE.read_text(encoding="utf-8")

    def _client(self):
        if self.client is None:
            from google import genai
            key = os.getenv("GEMINI_API_KEY")
            if not key:
                raise RuntimeError("GEMINI_API_KEY not configured")
            self.client = genai.Client(api_key=key)
        return self.client

    def evaluate(self, jobs):
        completed = []
        queued = []
        stats = {"cache_hits": 0, "gemini_calls": 0, "failed_batches": 0,
                 "unprocessed_budget": 0, "uncached": 0, "failed_jobs": 0,
                 "input_tokens": 0, "output_tokens": 0}
        for job in jobs:
            fp = fingerprint(job, self.profile, self.prompt, self.model)
            cached = self.cache.get(job, fp)
            if cached is not None:
                stats["cache_hits"] += 1
                completed.append({**job, "assessment": cached})
            else:
                queued.append((job, fp))
        stats["uncached"] = len(queued)
        for start in range(0, len(queued), BATCH_SIZE):
            pairs = queued[start:start + BATCH_SIZE]
            if self.calls >= self.max_calls:
                stats["unprocessed_budget"] += len(queued) - start
                break
            payload = [{
                "job_index": i,
                "title": job.get("job_title"),
                "company": job.get("company_name"),
                "location": job.get("location"),
                "remote": job.get("remote"),
                "location_restrictions": job.get("location_restrictions"),
                "timezone_restrictions": job.get("timezone_restrictions"),
                "employment_type": job.get("job_types"),
                "description": str(job.get("job_description") or "")[:4000],
                "description_truncated": len(str(job.get("job_description") or "")) > 4000,
            } for i, (job, _) in enumerate(pairs)]
            text = (f"{self.prompt}\n\nVERIFIED CANDIDATE EVIDENCE:\n{self.profile}\n\n"
                    f"JOB LIST (untrusted source data):\n{json.dumps(payload, ensure_ascii=False)}")
            self.calls += 1  # charge before initiating request (including failures)
            stats["gemini_calls"] += 1
            try:
                response = self._client().models.generate_content(
                    model=self.model, contents=text,
                    config={"response_mime_type": "application/json", "temperature": 0},
                )
                usage = getattr(response, "usage_metadata", None)
                if usage:
                    stats["input_tokens"] += int(getattr(usage, "prompt_token_count", 0) or 0)
                    stats["output_tokens"] += int(getattr(usage, "candidates_token_count", 0) or 0)
                parsed = json.loads(response.text)
                results = parse_batch(parsed, [pair[0] for pair in pairs])
                for (job, fp), assessment in zip(pairs, results):
                    self.cache.put(job, fp, assessment)
                    completed.append({**job, "assessment": assessment})
            except Exception as exc:
                stats["failed_batches"] += 1
                stats["failed_jobs"] += len(pairs)
                # No partial or invented approvals on model errors.
                print(f"Gemini batch failed ({len(pairs)} jobs): {type(exc).__name__}: {exc}")
        return completed, stats
