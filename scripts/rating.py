"""Claude AI job rating — tier classification and salary extraction."""

import json
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Optional

import anthropic
from log import log
from filters import _SALARY_CONTEXT_RE, _is_plausible_salary

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import (  # noqa: E402
    CANDIDATE_BACKGROUND, APPLY_NOW_DESCRIPTION, HOME_CITY, HOME_STATE,
)

TIER_ORDER = {"Apply Now": 0, "Worth a Look": 1, "Weak Match": 2, "Skip": 3}

_print_lock = threading.Lock()

_claude = None


def _get_claude():
    global _claude
    if _claude is None:
        _claude = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    return _claude


RATING_PROMPT = f"""\
You are a job-fit rater.

Candidate background:
{CANDIDATE_BACKGROUND}

Rate this job with one of these tiers:
- "Apply Now" — {APPLY_NOW_DESCRIPTION}
- "Worth a Look" — good fit: product role related to their background, worth reviewing
- "Weak Match" — marginal: product-adjacent or BA role, not a priority
- "Skip" — poor fit: irrelevant role, non-US location (e.g. Europe, Canada, Asia), onsite/hybrid outside {HOME_CITY} {HOME_STATE} (e.g. onsite in New York, Chicago, San Francisco), or clearly below salary floor

CRITICAL RATING RULES — these override everything else:
1. Missing salary is NEVER a reason to Skip or downgrade. Rate on title and domain fit alone.
2. Missing or unclear location/remote status is NEVER a reason to Skip or downgrade.
3. A short or incomplete description is NEVER a reason to Skip. If the title fits and no hard disqualifier is confirmed, rate Worth a Look or higher.
4. "Cannot assess" is NOT a valid Skip reason. When in doubt, rate Worth a Look.
5. Only Skip when a hard disqualifier is CONFIRMED — not merely suspected.

Return ONLY a JSON object with these keys:
{{{{
  "tier": "<one of the four tiers above>",
  "reason": "<one sentence explaining the rating>",
  "salary": "<extracted salary range from description, or empty string if none found>"
}}}}

Job:
Title: {{title}}
Company: {{company}}
Location: {{location}}
Salary: {{salary}}
Description: {{description}}
"""


def extract_salary_from_text(text: str) -> Optional[str]:
    """Scan description text for a salary range. Requires salary context words or
    explicit annual qualifier to avoid grabbing financial metrics as salary hints."""
    if not text:
        return None
    for m in _SALARY_CONTEXT_RE.finditer(text):
        raw = m.group(0).strip()
        if re.fullmatch(r"\d{4,5}", raw.replace(",", "").replace("$", "").strip()):
            continue
        if _is_plausible_salary(raw):
            return raw
    return None


def rate_with_claude(job) -> tuple[str, str, str]:
    salary = job.salary_str() if (job.salary_min or job.salary_max) else ""
    desc = job.description[:4000] if job.description else "(no description)"

    salary_hint = ""
    if not salary:
        pre_salary = extract_salary_from_text(job.description or "")
        if pre_salary:
            salary_hint = f"\nSalary found in description: {pre_salary}"

    prompt = RATING_PROMPT.format(
        title=job.title,
        company=job.company or "(unknown)",
        location=job.location or "(unknown)",
        salary=(salary or "(not listed)") + salary_hint,
        description=desc,
    )

    max_retries = 4
    for attempt in range(max_retries):
        try:
            response = _get_claude().messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=400,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text.strip()
            raw = raw.replace("```json", "").replace("```", "").strip()
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                data = json.loads(match.group())
                tier = data.get("tier", "Worth a Look")
                if tier not in TIER_ORDER:
                    tier = "Worth a Look"
                raw_salary = data.get("salary") or ""
                if raw_salary and not _is_plausible_salary(str(raw_salary)):
                    raw_salary = ""
                return tier, data.get("reason", ""), raw_salary
        except anthropic.RateLimitError:
            wait = 15 * (2 ** attempt)
            with _print_lock:
                log(f"Rate limit (attempt {attempt+1}/{max_retries}) — waiting {wait}s...", source="Rating")
            time.sleep(wait)
        except Exception as e:
            with _print_lock:
                log(f"Failed for '{job.title}': {e}", source="Rating")
            break
    return "Worth a Look", "Rating unavailable", ""
