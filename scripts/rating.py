"""Claude AI job rating — tier classification and salary extraction."""

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from log import log
from filters import _SALARY_CONTEXT_RE, _is_plausible_salary

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import (  # noqa: E402
    CANDIDATE_BACKGROUND, APPLY_NOW_DESCRIPTION, HOME_CITY, HOME_STATE,
)

TIER_ORDER = {"Apply Now": 0, "Worth a Look": 1, "Weak Match": 2, "Skip": 3}

_print_lock = threading.Lock()

# Rate via the `claude` CLI over the Claude.ai (OAuth / Max subscription) login,
# NOT the metered Anthropic API. Stripping ANTHROPIC_API_KEY forces the CLI onto
# the subscription; leaving it set bills per-token credits (and dies when the
# credit balance runs out). Mirrors the dashboard's generation path.
_CLI_ENV = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
# cron runs with a minimal PATH (/usr/local/bin:/usr/bin) that excludes the npm
# global bin where `claude` is installed, so add the usual user bin dirs.
_USER_BINS = [str(Path.home() / ".npm-global/bin"), str(Path.home() / ".local/bin"),
              "/usr/local/bin", "/usr/bin"]
_CLI_ENV["PATH"] = os.pathsep.join(_USER_BINS + [_CLI_ENV.get("PATH", "")])
_CLI_TIMEOUT = 120
_CLI_MODEL = "claude-haiku-4-5-20251001"  # fast + cheap tier for high-volume rating


def _resolve_claude() -> str:
    """Absolute path to the `claude` CLI. shutil.which handles the interactive
    case; the explicit fallbacks handle cron's minimal PATH."""
    found = shutil.which("claude")
    if found:
        return found
    home = Path.home()
    for cand in (home / ".npm-global/bin/claude", home / ".local/bin/claude",
                 Path("/usr/local/bin/claude"), Path("/usr/bin/claude")):
        if cand.exists():
            return str(cand)
    return "claude"  # last resort; will raise a clear error if truly absent


_CLAUDE_BIN = _resolve_claude()


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
            result = subprocess.run(
                [_CLAUDE_BIN, "-p", prompt, "--model", _CLI_MODEL],
                capture_output=True, text=True, timeout=_CLI_TIMEOUT, env=_CLI_ENV,
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip()[:200] or "claude CLI nonzero exit")
            raw = result.stdout.strip().replace("```json", "").replace("```", "").strip()
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
        except subprocess.TimeoutExpired:
            with _print_lock:
                log(f"Timeout (attempt {attempt+1}/{max_retries}) for '{job.title}'", source="Rating")
            continue
        except Exception as e:
            with _print_lock:
                log(f"Failed for '{job.title}': {e}", source="Rating")
            break
    return "Worth a Look", "Rating unavailable", ""
