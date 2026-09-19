import os
import re
import time

import requests

from dotenv import load_dotenv

# Load API credentials before importing modules
# that initialize external service clients.
load_dotenv()

from sheets import get_existing_job_urls, save_jobs_to_sheet
from validator import BATCH_SIZE, validate_jobs_batch
from outreach import generate_outreach

from validation_cache import (
    get_cached_validation,
    save_cached_validation,
    get_cache_status,
)

# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

ARBEITNOW_URL = "https://www.arbeitnow.com/api/job-board-api"
REMOTIVE_URL = "https://remotive.com/api/remote-jobs"
ADZUNA_BASE_URL = "https://api.adzuna.com/v1/api/jobs/gb/search"

ADZUNA_APP_ID = os.getenv("ADZUNA_APP_ID")
ADZUNA_APP_KEY = os.getenv("ADZUNA_APP_KEY")

MAX_ARBEITNOW_PAGES = 10

ADZUNA_RESULTS_PER_QUERY = 20
ADZUNA_PAGES_PER_QUERY = 1

ADZUNA_SEARCH_TERMS = [
    "executive assistant",
    "administrative assistant",
    "personal assistant",
    "office assistant",
    "executive support",
    "assistant to CEO",
]

ASSISTANT_KEYWORDS = [
    "executive assistant",
    "administrative assistant",
    "admin assistant",
    "personal assistant",
    "executive support",
    "executive coordinator",
    "administrative coordinator",
    "office assistant",
    "virtual assistant",
    "team assistant",
    "management assistant",
    "assistant to the ceo",
    "assistant to ceo",
    "assistant to the founder",
    "assistant to founder",
    "assistant to the director",
    "office coordinator",
    "executive administrator",
]


# --------------------------------------------------
# API RETRY HANDLING
# --------------------------------------------------

RETRY_STATUS_CODES = {
    429,
    500,
    502,
    503,
    504,
}

MAX_REQUEST_RETRIES = 3


def get_json_with_retries(
    url,
    params=None,
    source_name="API",
    max_retries=MAX_REQUEST_RETRIES,
):
    for attempt in range(1, max_retries + 1):
        try:
            response = requests.get(
                url,
                params=params,
                timeout=30,
            )

            if response.status_code == 200:
                return response.json()

            if response.status_code in RETRY_STATUS_CODES:
                if attempt < max_retries:
                    wait_seconds = 2 ** (attempt - 1)

                    print(
                        f"{source_name} returned HTTP "
                        f"{response.status_code}. "
                        f"Retrying in {wait_seconds}s..."
                    )

                    time.sleep(wait_seconds)
                    continue

            raise RuntimeError(
                f"{source_name} request failed with " f"HTTP {response.status_code}."
            )

        except requests.RequestException as error:
            if attempt < max_retries:
                wait_seconds = 2 ** (attempt - 1)

                print(
                    f"{source_name} request failed. " f"Retrying in {wait_seconds}s..."
                )

                time.sleep(wait_seconds)
                continue

            raise RuntimeError(
                f"{source_name} request failed after " f"{max_retries} attempts."
            ) from error


# --------------------------------------------------
# ARBEITNOW
# --------------------------------------------------


def fetch_arbeitnow_jobs():
    all_jobs = []
    next_url = ARBEITNOW_URL
    page_number = 1
    seen_page_urls = set()

    while next_url and page_number <= MAX_ARBEITNOW_PAGES:
        if next_url in seen_page_urls:
            print("Repeated Arbeitnow page detected. Stopping.")
            break

        seen_page_urls.add(next_url)

        print(f"Fetching Arbeitnow page {page_number}...")

        data = get_json_with_retries(
            next_url,
            source_name="Arbeitnow",
        )

        page_jobs = data.get("data", [])

        all_jobs.extend(page_jobs)

        print(f"Jobs retrieved from Arbeitnow page " f"{page_number}: {len(page_jobs)}")

        if not page_jobs:
            break

        next_url = data.get("links", {}).get("next")
        page_number += 1

    return all_jobs


def normalize_arbeitnow_jobs(raw_jobs):
    normalized_jobs = []

    for job in raw_jobs:
        normalized_jobs.append(
            {
                "job_title": job.get("title"),
                "company_name": job.get("company_name"),
                "location": job.get("location"),
                "job_description": job.get("description"),
                "job_url": job.get("url"),
                "remote": job.get("remote"),
                "tags": job.get("tags"),
                "job_types": job.get("job_types"),
                "created_at": job.get("created_at"),
                "source": "Arbeitnow",
            }
        )

    return normalized_jobs


# --------------------------------------------------
# REMOTIVE
# --------------------------------------------------


def fetch_remotive_jobs():
    print("\nFetching Remotive jobs...")

    data = get_json_with_retries(
        REMOTIVE_URL,
        source_name="Remotive",
    )

    jobs = data.get("jobs", [])

    print(f"Jobs retrieved from Remotive: {len(jobs)}")

    return jobs


def normalize_remotive_jobs(raw_jobs):
    normalized_jobs = []

    for job in raw_jobs:
        category = job.get("category")
        job_type = job.get("job_type")

        normalized_jobs.append(
            {
                "job_title": job.get("title"),
                "company_name": job.get("company_name"),
                "location": job.get("candidate_required_location"),
                "job_description": job.get("description"),
                "job_url": job.get("url"),
                "remote": True,
                "tags": [category] if category else [],
                "job_types": [job_type] if job_type else [],
                "created_at": job.get("publication_date"),
                "source": "Remotive",
            }
        )

    return normalized_jobs


# --------------------------------------------------
# ADZUNA
# --------------------------------------------------


def fetch_adzuna_jobs():
    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
        raise ValueError("Adzuna credentials were not found. Check your .env file.")

    all_jobs = []

    print("\nFetching Adzuna jobs...")

    for search_term in ADZUNA_SEARCH_TERMS:
        print(f'\nSearching Adzuna for: "{search_term}"')

        for page in range(1, ADZUNA_PAGES_PER_QUERY + 1):
            url = f"{ADZUNA_BASE_URL}/{page}"

            params = {
                "app_id": ADZUNA_APP_ID,
                "app_key": ADZUNA_APP_KEY,
                "results_per_page": ADZUNA_RESULTS_PER_QUERY,
                "what": search_term,
                "content-type": "application/json",
            }

            try:
                data = get_json_with_retries(
                    url,
                    params=params,
                    source_name=f'Adzuna "{search_term}"',
                )

            except RuntimeError as error:
                print(f"Skipping Adzuna query: {error}")
                continue

            results = data.get("results", [])

            print(
                f"  Page {page}: {len(results)} jobs returned "
                f"(Adzuna reports {data.get('count', 0)} matches)"
            )

            all_jobs.extend(results)

    print(f"\nTotal raw Adzuna jobs retrieved: {len(all_jobs)}")

    return all_jobs


def normalize_adzuna_jobs(raw_jobs):
    normalized_jobs = []

    for job in raw_jobs:
        company = job.get("company") or {}
        location = job.get("location") or {}

        normalized_jobs.append(
            {
                "job_title": job.get("title"),
                "company_name": company.get("display_name"),
                "location": location.get("display_name"),
                "job_description": job.get("description"),
                "job_url": job.get("redirect_url"),
                "remote": None,
                "tags": [],
                "job_types": [],
                "created_at": job.get("created"),
                "source": "Adzuna",
            }
        )

    return normalized_jobs


# --------------------------------------------------
# TEXT NORMALIZATION
# --------------------------------------------------


def normalize_text(value):
    if not value:
        return ""

    value = str(value).lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def normalize_url(value):
    """
    Normalize URLs for duplicate checking.

    This removes whitespace, URL fragments and trailing slashes.
    It does not remove query parameters because some job URLs
    use them to identify individual vacancies.
    """
    if not value:
        return ""

    url = str(value).strip()
    url = url.split("#", 1)[0]
    url = url.rstrip("/")

    return url


def get_job_identity(job):
    """
    Return a company/title identity for additional duplicate checking.
    """
    company = normalize_text(job.get("company_name"))
    title = normalize_text(job.get("job_title"))

    if not company or not title:
        return None

    return (company, title)


# --------------------------------------------------
# REMOVE DUPLICATES WITHIN DISCOVERED JOBS
# --------------------------------------------------


def remove_duplicates(jobs):
    unique_jobs = []
    seen_urls = set()
    seen_keys = set()

    for job in jobs:
        url = normalize_url(job.get("job_url"))
        identity = get_job_identity(job)

        if url and url in seen_urls:
            continue

        if identity and identity in seen_keys:
            continue

        if url:
            seen_urls.add(url)

        if identity:
            seen_keys.add(identity)

        unique_jobs.append(job)

    return unique_jobs


# --------------------------------------------------
# PRELIMINARY JOB FILTERING
# --------------------------------------------------


def filter_assistant_jobs(jobs):
    candidate_jobs = []

    for job in jobs:
        title = normalize_text(job.get("job_title"))

        if any(keyword in title for keyword in ASSISTANT_KEYWORDS):
            candidate_jobs.append(job)

    return candidate_jobs


# --------------------------------------------------
# GOOGLE SHEETS EARLY DUPLICATE CHECK
# --------------------------------------------------


def remove_already_saved_jobs(candidate_jobs):
    """
    Exclude jobs already saved in Google Sheets before
    sending candidates to Gemini.

    Also remove duplicate URLs and matching company/title
    combinations within the remaining candidate list.
    """

    existing_urls = {
        normalize_url(url) for url in get_existing_job_urls() if normalize_url(url)
    }

    new_candidates = []

    seen_urls = set()
    seen_identities = set()

    skipped_saved = 0
    skipped_batch_duplicates = 0

    for job in candidate_jobs:
        url = normalize_url(job.get("job_url"))
        identity = get_job_identity(job)

        # Jobs without a URL cannot be saved reliably.
        if not url:
            print(
                "Skipping job without URL:",
                job.get("job_title"),
                "|",
                job.get("company_name"),
            )
            continue

        # Check against existing Google Sheets URLs.
        if url in existing_urls:
            skipped_saved += 1

            print(
                "ALREADY SAVED:",
                job.get("job_title"),
                "|",
                job.get("company_name"),
                "|",
                url,
            )

            continue

        # Check for duplicates within this run.
        if url in seen_urls:
            skipped_batch_duplicates += 1
            continue

        if identity and identity in seen_identities:
            skipped_batch_duplicates += 1
            continue

        seen_urls.add(url)

        if identity:
            seen_identities.add(identity)

        new_candidates.append(job)

    print("\n====================================")
    print("GOOGLE SHEETS DUPLICATE CHECK")
    print("====================================")

    print(f"Previously saved jobs excluded: {skipped_saved}")
    print(f"Additional duplicates excluded: {skipped_batch_duplicates}")
    print(f"Candidates remaining: {len(new_candidates)}")

    return new_candidates


# --------------------------------------------------
# LLM VALIDATION
# --------------------------------------------------


def validate_candidate_jobs(candidate_jobs):
    validated_jobs = []

    print("\n====================================")
    print("LLM VALIDATION WITH CACHE")
    print("====================================")

    if not candidate_jobs:
        print("No new candidates to validate.")
        return validated_jobs

        # ----------------------------------------------
        # 1. CHECK THE CACHE
        # ----------------------------------------------

    uncached_jobs = []
    cache_hits = 0
    cache_new = 0
    cache_changed = 0
    cache_invalid = 0

    for job in candidate_jobs:
        cache_status = get_cache_status(job)
        cached_result = get_cached_validation(job)

        if cached_result is None:
            uncached_jobs.append(job)
            print(
                f"CACHE MISS [{cache_status}]: "
                f"{job.get('job_title')} | "
                f"{job.get('company_name')} | "
                f"{job.get('source')} | "
                f"{job.get('job_url')}"
            )

            if cache_status == "new":
                cache_new += 1
            elif cache_status == "changed":
                cache_changed += 1
            elif cache_status == "invalid":
                cache_invalid += 1

            continue

        cache_hits += 1
        job["validation"] = cached_result

        passes = (
            cached_result["is_remote"]
            and cached_result["is_english"]
            and cached_result["is_relevant"]
        )

        print(f"\nCACHE HIT: {job.get('job_title')} - " f"{job.get('company_name')}")

        if passes:
            validated_jobs.append(job)
            print("Cached result: PASS")
        else:
            print("Cached result: REJECT")

    # ----------------------------------------------
    # 2. REPORT CACHE STATISTICS
    # ----------------------------------------------

    total_uncached = len(uncached_jobs)

    print("\n====================================")
    print("CACHE SUMMARY")
    print("====================================")

    print(f"Total candidates: {len(candidate_jobs)}")
    print(f"Cached results reused: {cache_hits}")
    print(f"New jobs not in cache: {cache_new}")
    print(f"Changed jobs requiring revalidation: {cache_changed}")
    print(f"Invalid/no-URL jobs: {cache_invalid}")
    print(f"Jobs requiring Gemini: {total_uncached}")

    # ----------------------------------------------
    # 3. VALIDATE ONLY UNCACHED JOBS
    # ----------------------------------------------

    total_batches = (total_uncached + BATCH_SIZE - 1) // BATCH_SIZE

    for batch_start in range(
        0,
        total_uncached,
        BATCH_SIZE,
    ):
        batch = uncached_jobs[batch_start : batch_start + BATCH_SIZE]

        batch_number = batch_start // BATCH_SIZE + 1

        print(
            f"\nValidating new batch "
            f"{batch_number}/{total_batches} "
            f"({len(batch)} jobs)..."
        )

        try:
            validations = validate_jobs_batch(batch)

        except Exception as error:
            print(f"Batch validation failed: {error}")
            print(f"WARNING: {len(batch)} jobs were not processed.")
            continue

        if len(validations) != len(batch):
            print("WARNING: Unexpected number of " "validation results.")
            print(f"Expected: {len(batch)} | " f"Received: {len(validations)}")
            print("Skipping this batch.")
            continue

        # ------------------------------------------
        # 4. PROCESS AND CACHE SUCCESSFUL RESULTS
        # ------------------------------------------

        for job, validation in zip(batch, validations):
            job["validation"] = validation

            print(f"\n{job.get('job_title')} - " f"{job.get('company_name')}")

            print(
                "Remote:",
                validation["is_remote"],
                "| English:",
                validation["is_english"],
                "| Relevant:",
                validation["is_relevant"],
            )

            print(
                "Confidence:",
                validation["confidence"],
            )

            print(
                "Reason:",
                validation["reason"],
            )

            passes = (
                validation["is_remote"]
                and validation["is_english"]
                and validation["is_relevant"]
            )

            # Cache accepted and rejected jobs.
            # A cache-write error should not stop
            # the rest of the workflow.
            try:
                save_cached_validation(job, validation)

            except Exception as error:
                print(f"WARNING: Could not cache result: {error}")

            if passes:
                validated_jobs.append(job)
                print("RESULT: PASS")
            else:
                print("RESULT: REJECT")

    # ----------------------------------------------
    # 5. FINAL REPORT
    # ----------------------------------------------

    print("\n====================================")
    print("VALIDATION SUMMARY")
    print("====================================")

    print(f"Candidates processed: {len(candidate_jobs)}")
    print(f"Cached results reused: {cache_hits}")
    print(f"New Gemini validations requested: {total_uncached}")
    print(f"Validated jobs retained: {len(validated_jobs)}")

    return validated_jobs


# --------------------------------------------------
# PERSONALIZED OUTREACH GENERATION
# --------------------------------------------------


def generate_outreach_messages(validated_jobs):
    print("\n====================================")
    print("OUTREACH GENERATION")
    print("====================================")

    if not validated_jobs:
        print("No qualifying jobs require outreach.")
        return validated_jobs

    for index, job in enumerate(
        validated_jobs,
        start=1,
    ):
        print(
            f"\nGenerating outreach "
            f"{index}/{len(validated_jobs)}: "
            f"{job['job_title']} - "
            f"{job['company_name']}"
        )

        try:
            message = generate_outreach(job)

            job["outreach_message"] = message

            print("\nGenerated message:")
            print(message)

        except Exception as error:
            job["outreach_message"] = None

            print(f"Outreach generation failed: {error}")

    return validated_jobs


# --------------------------------------------------
# REPORTING
# --------------------------------------------------


def count_by_source(jobs):
    counts = {}

    for job in jobs:
        source = job.get("source", "Unknown")
        counts[source] = counts.get(source, 0) + 1

    return counts


def print_summary(
    arbeitnow_jobs,
    remotive_jobs,
    adzuna_jobs,
    combined_jobs,
    unique_jobs,
    candidate_jobs,
):
    print("\n====================================")
    print("SUMMARY")
    print("====================================")

    print(f"Arbeitnow jobs: {len(arbeitnow_jobs)}")
    print(f"Remotive jobs: {len(remotive_jobs)}")
    print(f"Adzuna jobs: {len(adzuna_jobs)}")
    print(f"Combined normalized jobs: {len(combined_jobs)}")
    print(f"Unique jobs: {len(unique_jobs)}")
    print(f"Candidate assistant jobs: {len(candidate_jobs)}")

    print("\nCandidates by source:")

    source_counts = count_by_source(candidate_jobs)

    for source, count in source_counts.items():
        print(f"  {source}: {count}")


def print_candidates(candidate_jobs):
    print("\n====================================")
    print("CANDIDATE JOBS")
    print("====================================")

    if not candidate_jobs:
        print("No candidate assistant jobs found.")
        return

    for job in candidate_jobs:
        print("\n--- CANDIDATE ---")
        print("Source:", job["source"])
        print("Title:", job["job_title"])
        print("Company:", job["company_name"])
        print("Location:", job["location"])
        print("Remote:", job["remote"])
        print("URL:", job["job_url"])


# --------------------------------------------------
# MAIN WORKFLOW
# --------------------------------------------------


def main():

    # ----------------------------------------------
    # 1. FETCH RAW JOB DATA
    # ----------------------------------------------

    raw_arbeitnow_jobs = fetch_arbeitnow_jobs()
    raw_remotive_jobs = fetch_remotive_jobs()
    raw_adzuna_jobs = fetch_adzuna_jobs()

    # ----------------------------------------------
    # 2. NORMALIZE DATA
    # ----------------------------------------------

    arbeitnow_jobs = normalize_arbeitnow_jobs(raw_arbeitnow_jobs)

    remotive_jobs = normalize_remotive_jobs(raw_remotive_jobs)

    adzuna_jobs = normalize_adzuna_jobs(raw_adzuna_jobs)

    # ----------------------------------------------
    # 3. COMBINE ALL SOURCES
    # ----------------------------------------------

    combined_jobs = arbeitnow_jobs + remotive_jobs + adzuna_jobs

    # ----------------------------------------------
    # 4. REMOVE SOURCE DUPLICATES
    # ----------------------------------------------

    unique_jobs = remove_duplicates(combined_jobs)

    # ----------------------------------------------
    # 5. CHEAP JOB TITLE FILTER
    # ----------------------------------------------

    candidate_jobs = filter_assistant_jobs(unique_jobs)

    # ----------------------------------------------
    # 6. PRINT DISCOVERY RESULTS
    # ----------------------------------------------

    print_summary(
        arbeitnow_jobs,
        remotive_jobs,
        adzuna_jobs,
        combined_jobs,
        unique_jobs,
        candidate_jobs,
    )

    print_candidates(candidate_jobs)

    # ----------------------------------------------
    # 7. EXCLUDE PREVIOUSLY SAVED JOBS
    # ----------------------------------------------

    new_candidates = remove_already_saved_jobs(candidate_jobs)

    # ----------------------------------------------
    # 8. VALIDATE ONLY NEW OR CHANGED JOBS
    # ----------------------------------------------

    validated_jobs = validate_candidate_jobs(new_candidates)

    # ----------------------------------------------
    # 9. GENERATE PERSONALIZED OUTREACH
    # ----------------------------------------------

    validated_jobs = generate_outreach_messages(validated_jobs)

    # ----------------------------------------------
    # 10. SAVE RESULTS TO GOOGLE SHEETS
    # ----------------------------------------------

    save_jobs_to_sheet(validated_jobs)

    # ----------------------------------------------
    # 11. FINAL REPORT
    # ----------------------------------------------

    print("\n====================================")
    print("FINAL VALIDATED JOBS")
    print("====================================")

    if len(validated_jobs) == 0:
        print("No new jobs passed validation.")

    else:
        for job in validated_jobs:
            print(
                f"{job['job_title']} | " f"{job['company_name']} | " f"{job['source']}"
            )


# --------------------------------------------------
# EXECUTION
# --------------------------------------------------

if __name__ == "__main__":
    main()
