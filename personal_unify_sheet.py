"""Stage-only archive consolidation into the single Evaluations tab.

Default: read-only preview. Pass --apply explicitly to copy old Manual Review
rows into Evaluations as Backlog, without Gemini scores or deleting source rows.
No job-board collection, Gemini or scheduling. The production Personal Ray
workbook is explicitly forbidden by personal_sheets.verify_spreadsheet_destination.
"""
import argparse
import json

from dotenv import load_dotenv

from personal_discovery import BASE
from personal_sheets import migrate_manual_archive_to_evaluations


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Mutate the staging workbook")
    args = parser.parse_args()
    load_dotenv(BASE / ".env")
    result = migrate_manual_archive_to_evaluations(apply=args.apply)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
