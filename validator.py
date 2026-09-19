import json
import os
from pathlib import Path

from google import genai

MODEL = "gemini-3.5-flash-lite"
BATCH_SIZE = 20

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

PROMPT_PATH = Path(__file__).parent / "prompts" / "validation_prompt.txt"


def load_validation_prompt():
    return PROMPT_PATH.read_text(encoding="utf-8")


def clean_json_response(content):
    content = content.strip()

    if content.startswith("```json"):
        content = content[7:]
    elif content.startswith("```"):
        content = content[3:]

    if content.endswith("```"):
        content = content[:-3]

    return content.strip()


def validate_jobs_batch(jobs):
    validation_prompt = load_validation_prompt()

    jobs_payload = []

    for index, job in enumerate(jobs):
        jobs_payload.append(
            {
                "job_index": index,
                "job_title": job.get("job_title"),
                "company_name": job.get("company_name"),
                "location": job.get("location"),
                "source_remote_value": job.get("remote"),
                "job_description": job.get("job_description"),
            }
        )

    prompt = f"""
{validation_prompt}

You are validating MULTIPLE jobs.

For every job supplied, return exactly one result.

The job_index in your output MUST match the job_index supplied in the input.

Return ONLY a valid JSON array.

Each object must have exactly this structure:

{{
    "job_index": 0,
    "is_remote": true,
    "is_english": true,
    "is_relevant": true,
    "confidence": 0.95,
    "reason": "Short explanation"
}}

Do not omit jobs.
Do not reorder jobs.
Do not include markdown or commentary outside the JSON array.

JOBS TO VALIDATE:

{json.dumps(jobs_payload, ensure_ascii=False)}
"""

    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
    )

    content = clean_json_response(response.text)

    results = json.loads(content)

    if not isinstance(results, list):
        raise ValueError("Gemini response was not a JSON array.")

    if len(results) != len(jobs):
        raise ValueError(
            f"Expected {len(jobs)} validation results, "
            f"but Gemini returned {len(results)}."
        )

    results_by_index = {}

    for result in results:
        job_index = result.get("job_index")

        if not isinstance(job_index, int):
            raise ValueError("Validation result is missing a valid job_index.")

        results_by_index[job_index] = result

    ordered_results = []

    for index in range(len(jobs)):
        if index not in results_by_index:
            raise ValueError(f"Gemini did not return validation for job index {index}.")

        ordered_results.append(results_by_index[index])

    return ordered_results
