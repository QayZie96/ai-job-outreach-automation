
# AI Job Discovery & Personalized Outreach Automation

## Overview

This project was developed as part of an AI automation case study.

It automates the discovery, evaluation, and organization of Executive Assistant, Administrative Assistant, Personal Assistant, and related job opportunities.

The workflow collects vacancies from multiple job APIs, evaluates their suitability using Google Gemini, generates personalized outreach drafts, and saves qualifying results to Google Sheets.

The system supports configurable outreach prompts, duplicate prevention, persistent validation caching, and scheduled execution.

Outreach messages are generated as drafts for human review. The workflow does not automatically contact employers.

## 1. Workflow Architecture

The automation follows this process:

1. Retrieve vacancies from Arbeitnow, Remotive, and Adzuna.
2. Normalize job information into a common data structure.
3. Remove duplicate listings and filter for relevant administrative job titles.
4. Exclude vacancies already saved in Google Sheets.
5. Check the local SQLite cache for previous validation results.
6. Send new or changed vacancies to Google Gemini for evaluation.
7. Retain vacancies that satisfy the remote-work, English-language, and role-relevance criteria.
8. Generate personalized outreach drafts using the selected sender profile.
9. Save qualifying vacancies and outreach drafts to Google Sheets.
10. Repeat the workflow through Windows Task Scheduler.

Previously evaluated, unchanged vacancies reuse their cached validation results, reducing unnecessary API requests.

## 2. Job Discovery

The workflow uses three job sources.

### Arbeitnow

Retrieves vacancies through the Arbeitnow Job Board API.

The implementation supports pagination and retrieves up to 10 pages per execution.

### Remotive

Retrieves remote-job listings through the Remotive API.

Remote-source membership alone does not establish worldwide applicant eligibility. Geographical restrictions are considered during validation.

### Adzuna

Uses the Adzuna UK Jobs API with targeted searches for Executive Assistant, Administrative Assistant, Personal Assistant, Office Assistant, Executive Support, and Assistant to CEO roles.

Adzuna may return abbreviated job descriptions rather than complete postings.

The automation preserves the source URL and available job information.

LinkedIn is not used as a discovery source.

## 3. Job Validation

Google Gemini evaluates candidate vacancies against three criteria.

### Remote work

The posting must clearly permit remote work.

On-site, hybrid, and unclear arrangements do not pass.

Explicit geographical eligibility restrictions are considered and may be noted in the validation explanation.

### English-language suitability

The role must be professionally workable in English without another mandatory professional language.

### Role relevance

The core responsibilities must relate to Executive Assistant, Administrative Assistant, Personal Assistant, Virtual Assistant, Office Assistant, Executive Support, or closely equivalent work.

The validator considers the actual responsibilities rather than relying solely on the job title.

The criteria are defined in:

prompts/validation_prompt.txt

They can be modified without rewriting the Python workflow.

The Gemini model is configured in validator.py.

## 4. Personalized Outreach

After a vacancy passes validation, Gemini generates a personalized first-contact message.

The generation process uses:

- The advertised job information.
- The selected sender profile.
- An editable outreach prompt.

The prompt requests a concise message that references specific details supported by the vacancy and connects them to genuine information about the sender.

It explicitly prohibits inventing qualifications, work history, software proficiency, achievements, or business capabilities.

### Individual outreach mode

The default mode generates messages from an individual applicant expressing interest in a vacancy.

Configuration:

OUTREACH_MODE=individual

Files:

prompts/outreach_prompt.txt
profiles/applicant_profile.txt

The included applicant profile contains demonstration data based on genuine marketplace and operations experience.

It does not claim previous formal Executive Assistant experience.

### Business outreach mode

The project also supports a configurable business outreach mode.

Configuration:

OUTREACH_MODE=business

Files:

prompts/business_outreach_prompt.txt
profiles/business_profile.txt

This mode requires genuine information about the sender's business before outreach can be generated.

The included business profile is not a completed representation of a real business.

No business capabilities, available candidates, services, or commercial terms should be invented to populate it.

## 5. Google Sheets Output

Qualifying vacancies are saved to the Jobs worksheet of the EA Job Outreach Dashboard.

The worksheet contains six columns:

| Column | Field |
|---|---|
| A | Job Title |
| B | Company |
| C | Location |
| D | Job Description |
| E | Job URL |
| F | Personalized Outreach |

Job descriptions are converted from HTML to readable text before being saved.

The workflow uses a Google service account to access the spreadsheet through the Google Sheets API.

Existing job URLs are checked before Gemini validation and again before saving to prevent duplicate rows.

The spreadsheet also includes optional Google Apps Script formatting to improve readability.

Generated outreach is intended for human review before use.

### Demonstration

Google Sheet (view-only):

[ADD SHARED GOOGLE SHEET LINK]

An exported copy of the populated spreadsheet is also provided with the final submission.

## 6. Validation Cache

The workflow uses SQLite to store previously completed Gemini validation results.

The cache records each job's identifier, a fingerprint of the validation inputs, and the resulting evaluation.

When an unchanged vacancy appears again, the previous result can be reused without another Gemini validation request.

The fingerprint accounts for:

- Job title and company.
- Location and remote-work indicator.
- Job description.
- Validation prompt.
- Gemini model configuration.

Adzuna listings use a normalized listing identifier to avoid unnecessary cache misses caused by changing tracking parameters or URL formats.

A new or changed vacancy requires fresh validation.

The database is generated locally and is not included in the source-code deliverable.

## 7. Project Structure

task1_job_outreach/
    main.py
    validator.py
    outreach.py
    sheets.py
    validation_cache.py
    run_workflow.ps1
    requirements.txt
    README.md

    prompts/
        validation_prompt.txt
        outreach_prompt.txt
        business_outreach_prompt.txt

    profiles/
        applicant_profile.txt
        business_profile.txt

Local-only files include the Python virtual environment, API credentials, execution logs, and SQLite database.

These are excluded from the public source-code package.

## 8. Prerequisites

The project requires:

- Python.
- Access to the Arbeitnow and Remotive APIs.
- Adzuna API credentials.
- A Google Gemini API key.
- A Google Cloud project with the Google Sheets API enabled.
- A Google service account with access to the destination spreadsheet.

Windows and PowerShell are required for the included scheduled-execution launcher.

The Python workflow itself can be run manually in other compatible environments, provided its dependencies and configuration are available.

## 9. Installation

Clone or download the source-code repository.

Open a terminal in the project directory.

Create a Python virtual environment:

    python -m venv .venv

Activate the environment on Windows PowerShell:

    .\.venv\Scripts\Activate.ps1

Install the required dependencies:

    python -m pip install -r requirements.txt

If PowerShell activation is restricted, use the virtual environment's Python executable directly:

    .\.venv\Scripts\python.exe -m pip install -r requirements.txt

## 10. Environment Configuration

Create a .env file in the project directory.

Configure the following variables using your own credentials:

    GEMINI_API_KEY=YOUR_GEMINI_API_KEY
    ADZUNA_APP_ID=YOUR_ADZUNA_APP_ID
    ADZUNA_APP_KEY=YOUR_ADZUNA_APP_KEY
    GOOGLE_SHEET_ID=YOUR_GOOGLE_SHEET_ID
    OUTREACH_MODE=individual

The destination Google Sheet must contain a worksheet named:

    Jobs

Its first row must contain the six output headers listed in Section 5.

### Google service account

Enable the Google Sheets API in your Google Cloud project.

Create a service account and obtain its JSON credentials.

Store the credentials locally at:

    credentials/google-service-account.json

Share the destination Google Sheet with the service account's email address and grant the permissions required to append rows.

Never commit API keys, the .env file, or service-account credentials to a public repository.

## 11. Manual Execution

From the project directory, run:

    .\.venv\Scripts\python.exe main.py

The workflow retrieves vacancies, applies filtering and validation, generates outreach for qualifying jobs, and saves new results to Google Sheets.

Console output includes discovery counts, duplicate-check information, cache statistics, validation results, and saving outcomes.

A run may legitimately produce no new qualifying vacancies.

Previously saved or cached jobs are not unnecessarily processed again.

## 12. Scheduled Execution

The project includes a PowerShell launcher:

    run_workflow.ps1

It runs the workflow using the project's virtual environment and working directory.

Execution output and errors are captured in timestamped log files inside the local logs/ directory.

### Windows Task Scheduler

The automation is configured to execute daily at 09:00 using Windows Task Scheduler.

Program:

    powershell.exe

Arguments:

    -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "FULL_PATH_TO_PROJECT\run_workflow.ps1"

Replace FULL_PATH_TO_PROJECT with the actual project directory.

The launcher was successfully tested both manually and through Task Scheduler's Run command.

An automatically triggered daily execution had not yet been independently confirmed at the time of preparing this documentation.

The computer must be available for a local scheduled task to execute. Windows Task Scheduler can be configured to run a missed task after the computer becomes available again.

## 13. Demonstration Results

The workflow successfully retrieved vacancies from its configured job sources, validated candidates using Gemini, generated a personalized outreach draft, and saved a qualifying vacancy to Google Sheets.

A Remote Office Assistant vacancy at Coalition Technologies was used as an end-to-end demonstration.

The populated spreadsheet contains the advertised role, employer, location, job description, source URL, and generated outreach draft.

Subsequent executions confirmed that previously saved jobs were not added again.

The cache was also tested using a repeated candidate set. All 70 candidates in one scheduled-task test reused previous validation results, requiring no new Gemini validation requests.

This demonstrates caching behavior for that particular run, rather than guaranteeing the same cache-hit rate for future vacancy sets.

## 14. Known Limitations

### Source coverage

The workflow searches three job APIs and cannot guarantee comprehensive coverage of all available vacancies.

Adzuna may provide abbreviated job descriptions, limiting the information available for validation and personalization.

### Validation accuracy

Gemini's classifications depend on the information supplied and may occasionally be incorrect.

Incomplete descriptions, ambiguous remote arrangements, and language requirements can affect classification reliability.

Generated validation results should be reviewed when accuracy is important.

### Job availability

A listing retrieved through an API is not independently guaranteed to remain open at the time of review.

### Outreach quality

Outreach drafts depend on the supplied job description and sender profile.

A human should review each message before contacting an employer.

The workflow does not automatically send outreach.

### Local scheduling and persistence

The included scheduling setup depends on a Windows computer being available.

The SQLite cache is stored locally. Moving execution to a temporary cloud environment would require an appropriate persistent-storage solution.

## 15. Security

API keys and service-account credentials are loaded from local configuration files.

The repository must not contain:

- .env files with real credentials.
- Google service-account JSON files.
- Local execution logs.
- Private SQLite cache databases.
- The Python virtual environment.

If credentials are accidentally exposed, revoke or rotate them and remove them from any published repository history.

## 16. Source Code

GitHub repository:

[ADD GITHUB REPOSITORY LINK]

The repository contains the Python workflow, editable prompts, demonstration profiles, dependency list, and scheduled-execution launcher.

Private credentials and local runtime data are intentionally excluded.