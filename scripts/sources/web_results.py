"""Shared cleanup for web-search results (Brave, Tavily).

Web search returns pages, not postings. Real ATS postings often come back
under the page's generic title ("Modulr: Careers", "Jobs at Bolt.new") or
with site noise appended ("... - Logo - Myworkdayjobs.com"). This module
strips that noise and, for Greenhouse/Lever links whose title names no role,
asks the ATS API for the real job title. Results that still don't name a role
are dropped later by filters.is_non_role_web_result.
"""

import re
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))
from filters import ROLE_NOUN_RE  # noqa: E402

# Trailing " - Myworkdayjobs.com", " - Logo", " - Careers" segments, in any mix.
_TITLE_NOISE_RE = re.compile(
    r"(\s*[-|–—]\s*(myworkdayjobs\.com|logo|careers?))+\s*$", re.IGNORECASE
)
# Greenhouse page titles: "Job Application for <Role> at <Company>".
_GH_APPLICATION_RE = re.compile(r"^job application for (.+?) at (.+)$", re.IGNORECASE)

_GH_JOB_RE = re.compile(r"greenhouse\.io/([^/?#]+)/jobs/(\d+)")
_LEVER_JOB_RE = re.compile(r"jobs\.lever\.co/([^/?#]+)/([0-9a-f-]{36})")


def clean_title(title: str) -> tuple[str, str]:
    """Return (title, company) with site noise removed. company is '' unless
    the title itself names it (Greenhouse "Job Application for X at Y")."""
    title = _TITLE_NOISE_RE.sub("", (title or "").strip())
    m = _GH_APPLICATION_RE.match(title)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return title, ""


def resolve_ats_title(url: str, timeout: float = 8) -> tuple[str | None, bool]:
    """Look up the real posting title for a Greenhouse or Lever job URL.

    Returns (title, closed). title is None when the URL isn't a supported ATS
    link or the lookup failed; closed is True when the ATS says the posting
    no longer exists (HTTP 404).
    """
    try:
        m = _GH_JOB_RE.search(url or "")
        if m:
            r = requests.get(
                f"https://boards-api.greenhouse.io/v1/boards/{m[1]}/jobs/{m[2]}",
                timeout=timeout,
            )
            if r.status_code == 404:
                return None, True
            r.raise_for_status()
            return r.json().get("title") or None, False
        m = _LEVER_JOB_RE.search(url or "")
        if m:
            r = requests.get(f"https://api.lever.co/v0/postings/{m[1]}/{m[2]}", timeout=timeout)
            if r.status_code == 404:
                return None, True
            r.raise_for_status()
            return r.json().get("text") or None, False
    except (requests.RequestException, ValueError):
        pass
    return None, False


def normalize_web_job(job, company_from_url) -> bool:
    """Clean a web-search Job in place. Returns False if it should be dropped
    (the ATS reports the posting is gone)."""
    job.title, company = clean_title(job.title)
    if not job.company:
        job.company = company or company_from_url(job.url)
    if not ROLE_NOUN_RE.search(job.title):
        real, closed = resolve_ats_title(job.url)
        if closed:
            return False
        if real:
            job.title = real
    return True
