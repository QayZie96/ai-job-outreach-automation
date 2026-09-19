import re
import hashlib
import json
import sqlite3

from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from validator import MODEL, load_validation_prompt

# Store the cache beside the project's Python files.
CACHE_PATH = Path(__file__).resolve().parent / "validation_cache.db"


def get_cache_url(job):
    """
    Return a stable identifier for a job.

    For Adzuna, use its numeric listing ID rather than
    the URL path or tracking parameters.
    """

    url = str(job.get("job_url") or "").strip()

    if not url:
        return ""

    source = str(job.get("source") or "").strip().lower()

    if source == "adzuna":
        parsed = urlsplit(url)

        if parsed.hostname in (
            "adzuna.co.uk",
            "www.adzuna.co.uk",
        ):
            match = re.fullmatch(
                r"/jobs/(?:land/ad|details)/(\d+)/?",
                parsed.path,
            )

            if match:
                listing_id = match.group(1)

                return "https://www.adzuna.co.uk/jobs/details/" f"{listing_id}"

    return url


def get_connection():
    """Open the cache database and create its table if necessary."""

    connection = sqlite3.connect(CACHE_PATH)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS validation_cache (
            job_url TEXT PRIMARY KEY,
            fingerprint TEXT NOT NULL,
            result_json TEXT NOT NULL,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)

    connection.commit()

    return connection


def get_job_fingerprint(job):
    """
    Identify the exact job content and validation configuration.

    A changed description, location, remote-work indicator,
    validation prompt, or Gemini model invalidates the old result.
    """

    payload = {
        "job_title": job.get("job_title"),
        "company_name": job.get("company_name"),
        "location": job.get("location"),
        "job_description": job.get("job_description"),
        "remote": job.get("remote"),
        "validation_prompt": load_validation_prompt(),
        "model": MODEL,
        "cache_version": 1,
    }

    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )

    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def get_cached_validation(job):
    """
    Return a previous validation result if the job is unchanged.

    Return None when the job is new or its content has changed.
    """

    url = get_cache_url(job)

    if not url:
        return None

    fingerprint = get_job_fingerprint(job)

    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT fingerprint, result_json
            FROM validation_cache
            WHERE job_url = ?
            """,
            (url,),
        ).fetchone()

    if row is None:
        return None

    saved_fingerprint, result_json = row

    if saved_fingerprint != fingerprint:
        return None

    try:
        result = json.loads(result_json)

        if not isinstance(result, dict):
            return None

        required_fields = (
            "is_remote",
            "is_english",
            "is_relevant",
            "confidence",
            "reason",
        )

        if any(field not in result for field in required_fields):
            return None

        if any(
            type(result[field]) is not bool
            for field in (
                "is_remote",
                "is_english",
                "is_relevant",
            )
        ):
            return None

        return result

    except (ValueError, TypeError):
        return None


def save_cached_validation(job, validation):
    """Save a completed Gemini validation result."""

    url = get_cache_url(job)

    if not url:
        return

    fingerprint = get_job_fingerprint(job)

    result_json = json.dumps(
        validation,
        ensure_ascii=False,
    )

    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO validation_cache (
                job_url,
                fingerprint,
                result_json,
                updated_at
            )
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)

            ON CONFLICT(job_url)
            DO UPDATE SET
                fingerprint = excluded.fingerprint,
                result_json = excluded.result_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                url,
                fingerprint,
                result_json,
            ),
        )


def get_cache_status(job):
    """
    Return one of:
    - 'hit' -> URL exists and fingerprint matches
    - 'changed' -> URL exists but fingerprint changed
    - 'new' -> URL not found in cache
    - 'invalid' -> job has no usable URL
    """

    url = get_cache_url(job)

    if not url:
        return "invalid"

    fingerprint = get_job_fingerprint(job)

    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT fingerprint
            FROM validation_cache
            WHERE job_url = ?
            """,
            (url,),
        ).fetchone()

    if row is None:
        return "new"

    saved_fingerprint = row[0]

    if saved_fingerprint == fingerprint:
        return "hit"

    return "changed"
