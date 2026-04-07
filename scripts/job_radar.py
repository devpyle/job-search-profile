#!/usr/bin/env python3
"""Job radar — queries Adzuna, Brave, Tavily, LinkedIn, Remotive, WeWorkRemotely,
Himalayas, Jobicy, RemoteOK, JSearch, and ATS-direct. Saves a dated report, emails the .md.

Usage:
  Scheduled (cron):  python3 job_radar.py
  Manual test run:   python3 job_radar.py --run
  Verbose output:    python3 job_radar.py --run --verbose
"""

import json
import os
import re
import sqlite3
import sys
import time as _time
from datetime import date, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from log import log, init as log_init
from models import Job, _TITLE_CLEANUP_RE  # noqa: F401
from normalize import _clean_desc, format_salary_text, matches_keywords  # noqa: F401
from filters import (  # noqa: F401
    CATEGORY_URL_FRAGMENTS, NON_JOB_TITLE_RE, CATEGORY_TITLE_RE,
    _EXPIRED_RE, _WRONG_TITLE_RE, _NON_US_RE, _URL_CITY_RE, _LOC_CITY_RE,
    LI_NC_LOCATIONS, _SALARY_CONTEXT_RE, STAFFING_KEYWORDS, BLOCKED_COMPANIES,
    is_category_page, is_non_us_location, is_onsite_non_local, is_bad_scrape,
    is_local_raleigh, is_staffing, _parse_salary_string, _is_plausible_salary,
    is_below_salary_floor, is_closed_listing, is_wrong_title, is_broken_url,
)
from rating import (  # noqa: F401
    TIER_ORDER, RATING_PROMPT, extract_salary_from_text, rate_with_claude,
    _print_lock,
)
from sources.adzuna import search_adzuna  # noqa: F401
from sources.brave import search_brave  # noqa: F401
from sources.tavily import search_tavily, _company_from_url, DOMAIN_COMPANY_MAP  # noqa: F401
from sources.linkedin import (  # noqa: F401
    search_linkedin, _li_parse_cards, _li_fetch, _li_fetch_description,
    li_enrich_descriptions, LI_HEADERS, LI_BASE_URL, LI_DETAIL_URL, LI_RALEIGH_QUERIES,
)
from sources.remote_boards import (  # noqa: F401
    search_remotive, search_weworkremotely, search_himalayas,
    search_remoteok, search_jobicy,
)
from sources.jsearch import search_jsearch  # noqa: F401
from sources.ats import search_ats_companies  # noqa: F401
from report import build_report, write_debug_log, send_email  # noqa: F401
from startup import validate

load_dotenv()

# ── STARTUP VALIDATION ────────────────────────────────────────────────────────
validate(
    env_required={
        "ADZUNA_APP_ID": "Adzuna job search",
        "ADZUNA_APP_KEY": "Adzuna job search",
        "TAVILY_API_KEY": "Tavily web search",
        "ANTHROPIC_API_KEY": "Claude AI job rating",
    },
    env_optional={
        "BRAVE_API_KEY": "Brave web search (skipped if absent)",
        "JSEARCH_API_KEY": "JSearch/RapidAPI (skipped if absent)",
        "GMAIL_APP_PW": "Email delivery (report saved to disk if absent)",
        "GMAIL_TO": "Email recipient",
        "GMAIL_FROM": "Email sender",
    },
    config_attrs=[
        "CANDIDATE_BACKGROUND", "APPLY_NOW_DESCRIPTION",
        "HOME_CITY", "HOME_STATE", "HOME_METRO_TERMS", "MIN_SALARY",
        "ADZUNA_QUERIES", "BRAVE_QUERIES", "TAVILY_QUERIES",
        "LI_REMOTE_QUERIES", "LI_LOCAL_QUERIES",
        "JSEARCH_REMOTE_QUERIES", "JSEARCH_LOCAL_QUERIES",
        "ADZUNA_COUNTRY", "REQUIRE_US_LOCATION",
        "PORTAL_COMPANIES", "PORTAL_NAME_OVERRIDES",
        "PORTAL_TARGET_TITLES", "PORTAL_BLOCK_SUFFIXES",
    ],
    script_name="job_radar.py",
)

# ── SECRETS (from .env) ────────────────────────────────────────────────────────
BRAVE_API_KEY   = os.environ.get("BRAVE_API_KEY", "")
GMAIL_APP_PW    = os.environ.get("GMAIL_APP_PW", "")
JSEARCH_API_KEY = os.environ.get("JSEARCH_API_KEY", "")
EMAIL           = os.environ.get("GMAIL_TO", os.environ.get("GMAIL_FROM", ""))

import db as data  # noqa: E402

REPO_ROOT        = Path(__file__).parent.parent
OUTPUT_DIR       = REPO_ROOT / "output" / "job-radar"
SEEN_FILE        = OUTPUT_DIR / ".seen.json"
DB_PATH          = REPO_ROOT / "dashboard" / "data" / "jobs.db"
SEEN_EXPIRY_DAYS = 60


# ── SEEN FILE ─────────────────────────────────────────────────────────────────

def load_seen() -> dict:
    today_str = date.today().isoformat()
    if not SEEN_FILE.exists():
        return {}
    raw = json.loads(SEEN_FILE.read_text())
    if isinstance(raw, list):
        log(f"Migrating .seen.json to timestamped format ({len(raw)} entries)", source="Dedup")
        seen = {k: today_str for k in raw}
    else:
        seen = raw
    cutoff = (date.today() - timedelta(days=SEEN_EXPIRY_DAYS)).isoformat()
    before = len(seen)
    seen = {k: v for k, v in seen.items() if v >= cutoff}
    expired = before - len(seen)
    if expired:
        log(f"Expired {expired} seen entries older than {SEEN_EXPIRY_DAYS} days", source="Dedup")
    return seen


def save_seen(seen: dict):
    SEEN_FILE.write_text(json.dumps(seen, indent=2, sort_keys=True))


# ── MULTI-KEY DEDUPLICATION ───────────────────────────────────────────────────

def normalize_title(title: str) -> str:
    """Strips trailing location/remote noise so 'Senior PO (Remote)' and
    'Senior PO - Remote, US' map to the same key, but 'Senior PO - Payments'
    and 'Senior PO - Lending' remain distinct."""
    t = title.lower().strip()
    location_words = {"remote", "us", "usa", "united states", "nationwide",
                      "anywhere", "hybrid", "onsite", "on-site", "contract",
                      "full-time", "full time", "part-time", "part time"}
    t = re.sub(r"\(([^)]*)\)",
               lambda m: "" if m.group(1).strip().lower() in location_words else m.group(0),
               t).strip()
    for sep in [" - ", " | ", " – "]:
        if sep in t:
            parts = t.split(sep)
            suffix_words = set(re.split(r"[\s,]+", parts[-1]))
            if suffix_words.issubset(location_words):
                t = sep.join(parts[:-1]).strip()
    return re.sub(r"\s+", " ", t).strip()


def _url_key(url: str) -> str:
    """Strips query params so the same page with different tracking params matches."""
    return url.split("?")[0].rstrip("/").lower()


def dedup_keys(job: Job) -> list[str]:
    """Returns all dedup keys for a job — any one matching means it's a duplicate."""
    keys = []
    company = job.company.lower().strip() if job.company else ""
    title = normalize_title(job.title)
    if company:
        keys.append(f"{company}|{title}")
    if job.url:
        keys.append(_url_key(job.url))
    if not keys:
        keys.append(f"__nourl__|{title}|{job.source.lower()}")
    return keys


# ── SOURCE TIMING ────────────────────────────────────────────────────────────

def _timed_source_call(name, fn):
    """Call a source function, return (jobs, error_count, latency_ms)."""
    t0 = _time.monotonic()
    error_count = 0
    try:
        jobs = fn()
    except Exception as e:
        log(f"Source failed: {e}", source=name)
        jobs = []
        error_count = 1
    latency_ms = int((_time.monotonic() - t0) * 1000)
    return jobs, error_count, latency_ms


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main(force_run: bool = False):
    now = datetime.now()
    run_started = now.isoformat()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    seen = load_seen()

    raw_counts: dict[str, int] = {}
    source_meta: dict[str, dict] = {}

    def _search(name, fn):
        log("Searching...", source=name)
        jobs, errors, latency = _timed_source_call(name, fn)
        raw_counts[name] = len(jobs)
        source_meta[name] = {"error_count": errors, "latency_ms": latency}
        log(f"{len(jobs)} results ({latency}ms)", source=name)
        return jobs

    ats_jobs       = _search("ATS", search_ats_companies)
    adzuna_jobs    = _search("Adzuna", search_adzuna)
    jobicy_jobs    = _search("Jobicy", search_jobicy)
    himalayas_jobs = _search("Himalayas", search_himalayas)
    remoteok_jobs  = _search("RemoteOK", search_remoteok)
    remotive_jobs  = _search("Remotive", search_remotive)

    if JSEARCH_API_KEY:
        jsearch_jobs = _search("JSearch", search_jsearch)
    else:
        jsearch_jobs = []

    linkedin_jobs = _search("LinkedIn", search_linkedin)

    if BRAVE_API_KEY:
        brave_jobs = _search("Brave", search_brave)
    else:
        brave_jobs = []
        log("Skipping (BRAVE_API_KEY not set)", source="Brave")

    tavily_jobs = _search("Tavily", search_tavily)
    wwr_jobs    = _search("WeWorkRemotely", search_weworkremotely)

    all_jobs = (
        ats_jobs + adzuna_jobs + jobicy_jobs + himalayas_jobs + remoteok_jobs
        + remotive_jobs + jsearch_jobs + linkedin_jobs + brave_jobs + tavily_jobs
        + wwr_jobs
    )

    report, new_jobs, new_seen, filtered = build_report(all_jobs, seen, now, dedup_keys_fn=dedup_keys)

    write_debug_log(new_jobs, raw_counts)

    slot = "am" if now.hour < 12 else "pm"
    report_file = f"{now.strftime('%Y-%m-%d')}-{slot}.md"
    outfile = OUTPUT_DIR / report_file
    outfile.write_text(report)
    log(f"Saved: {outfile}")

    save_seen(new_seen)

    # ── Persist run stats to dashboard DB ────────────────────────────────────
    source_new_counts: dict[str, int] = {}
    for j in new_jobs:
        source_new_counts[j.source] = source_new_counts.get(j.source, 0) + 1

    try:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        data.init_schema(conn)

        run_id = data.insert_run(conn, run_started)
        for src, raw in raw_counts.items():
            meta = source_meta.get(src, {})
            data.insert_source_stat(
                conn, run_id, src,
                raw_count=raw,
                new_count=source_new_counts.get(src, 0),
                error_count=meta.get("error_count", 0),
                latency_ms=meta.get("latency_ms", 0),
            )
        if filtered:
            data.insert_filtered_jobs(conn, run_id, filtered)
        data.finish_run(conn, run_id,
                        finished_at=datetime.now().isoformat(),
                        total_raw=sum(raw_counts.values()),
                        total_new=len(new_jobs),
                        total_rated=len(new_jobs),
                        report_file=report_file)
        conn.close()
        log(f"Run stats saved (run_id={run_id}, {len(filtered)} filtered)", source="Health")
    except Exception as e:
        log(f"Warning: could not save run stats: {e}", source="Health")

    # ── Email ────────────────────────────────────────────────────────────────
    apply_now = sum(1 for j in new_jobs if j.tier == "Apply Now")
    priority  = sum(1 for j in new_jobs if j.tier in ("Apply Now", "Worth a Look"))
    subject = f"Job Radar {now.strftime('%b %-d')} {slot.upper()} — {apply_now} Apply Now | {priority} priority / {len(new_jobs)} total"
    if EMAIL and GMAIL_APP_PW:
        send_email(subject, report, attachment=outfile)
        log("Email sent.", source="Email")
    else:
        log("Skipped (GMAIL_FROM/GMAIL_TO/GMAIL_APP_PW not configured). Report saved to disk.", source="Email")


if __name__ == "__main__":
    log_init()
    force_run = "--run" in sys.argv
    if force_run:
        log("Manual run")
    main(force_run=force_run)
