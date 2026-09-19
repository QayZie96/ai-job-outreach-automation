import os
from pathlib import Path
import re

from bs4 import BeautifulSoup

from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build

BASE_DIR = Path(__file__).resolve().parent

CREDENTIALS_PATH = BASE_DIR / "credentials" / "google-service-account.json"

SHEET_NAME = "Jobs"


def description_to_text(description):
    """Convert HTML job descriptions into readable plain text."""

    if not description:
        return ""

    soup = BeautifulSoup(str(description), "html.parser")

    for tag in soup.find_all(["script", "style"]):
        tag.decompose()

    for item in soup.find_all("li"):
        item.insert_before("\n• ")

    for tag in soup.find_all(["p", "div", "br", "ul", "ol", "h1", "h2", "h3"]):
        tag.insert_before("\n")

    text = soup.get_text(separator=" ", strip=False)

    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]

    return "\n".join(line for line in lines if line)


HEADERS = [
    "Job Title",
    "Company",
    "Location",
    "Job Description",
    "Job URL",
    "Personalized Outreach",
]


def get_sheets_service():
    """Authenticate using the Google service account."""

    if not CREDENTIALS_PATH.is_file():
        raise FileNotFoundError(
            "Google credentials file not found at: " f"{CREDENTIALS_PATH}"
        )

    credentials = service_account.Credentials.from_service_account_file(
        str(CREDENTIALS_PATH),
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )

    return build(
        "sheets",
        "v4",
        credentials=credentials,
        cache_discovery=False,
    )


def get_spreadsheet_id():
    load_dotenv(BASE_DIR / ".env")

    spreadsheet_id = os.getenv("GOOGLE_SHEET_ID", "").strip()

    if not spreadsheet_id:
        raise ValueError("GOOGLE_SHEET_ID is missing from .env")

    return spreadsheet_id


def append_rows(rows):
    """Append rows beneath the existing data in the Jobs tab."""

    if not rows:
        print("No rows to append.")
        return

    service = get_sheets_service()
    spreadsheet_id = get_spreadsheet_id()

    result = (
        service.spreadsheets()
        .values()
        .append(
            spreadsheetId=spreadsheet_id,
            range=f"'{SHEET_NAME}'!A:F",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": rows},
        )
        .execute()
    )

    updated_rows = result.get("updates", {}).get("updatedRows", 0)

    print(f"Google Sheets: appended {updated_rows} row(s).")

    return result


def get_existing_job_urls():
    """Read job URLs already stored in column E."""

    service = get_sheets_service()
    spreadsheet_id = get_spreadsheet_id()

    result = (
        service.spreadsheets()
        .values()
        .get(
            spreadsheetId=spreadsheet_id,
            range=f"'{SHEET_NAME}'!E2:E",
        )
        .execute()
    )

    rows = result.get("values", [])

    return {row[0].strip() for row in rows if row and row[0].strip()}


def save_jobs_to_sheet(jobs):
    """Append only jobs not already in the spreadsheet."""

    existing_urls = get_existing_job_urls()
    new_urls = set()
    rows_to_append = []

    for job in jobs:
        url = str(job.get("job_url") or "").strip()
        outreach = job.get("outreach_message")

        if not url:
            print(
                "Skipping job without a URL:",
                job.get("job_title", "Unknown title"),
            )
            continue

        if not outreach:
            print(
                "Skipping job without an outreach draft:",
                job.get("job_title", "Unknown title"),
            )
            continue

        if url in existing_urls or url in new_urls:
            print("Skipping duplicate:", url)
            continue

        rows_to_append.append(
            [
                job.get("job_title", ""),
                job.get("company_name", ""),
                job.get("location", ""),
                description_to_text(job.get("job_description", "")),
                url,
                outreach,
            ]
        )

        new_urls.add(url)

    if not rows_to_append:
        print("Google Sheets: no new jobs to add.")
        return

    append_rows(rows_to_append)
