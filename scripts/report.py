"""Report building, debug logging, and email delivery."""

import os
import smtplib
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import HOME_METRO_TERMS, HOME_STATE, REQUIRE_US_LOCATION  # noqa: E402

from models import Job  # noqa: E402
from log import log  # noqa: E402
from filters import (  # noqa: E402
    BLOCKED_COMPANIES, is_category_page, is_non_us_location,
    is_onsite_non_local, is_bad_scrape, is_local_raleigh, is_staffing,
    is_below_salary_floor, is_closed_listing, is_wrong_title, is_broken_url,
)
from rating import TIER_ORDER, rate_with_claude, _print_lock  # noqa: E402
from sources.linkedin import li_enrich_descriptions  # noqa: E402

REPO_ROOT = Path(__file__).parent.parent
OUTPUT_DIR = REPO_ROOT / "output" / "job-radar"
DEBUG_LOG_FILE = OUTPUT_DIR / "debug_job_log.txt"

GMAIL_APP_PW = os.environ.get("GMAIL_APP_PW", "")
EMAIL = os.environ.get("GMAIL_TO", os.environ.get("GMAIL_FROM", ""))


def write_debug_log(jobs: list[Job], raw_counts: dict):
    """Full log of every job — title, source, rating, description as fed to Claude."""
    today = date.today().isoformat()
    lines = ["=" * 80, f"JOB RADAR DEBUG LOG — {today}",
             f"Total jobs this run: {len(jobs)}", "Source counts:"]
    for src, count in sorted(raw_counts.items()):
        lines.append(f"  {src:<20} {count} jobs")
    lines.append("=" * 80)

    by_tier: dict[str, list[Job]] = {"Apply Now": [], "Worth a Look": [], "Weak Match": [], "Skip": []}
    for job in jobs:
        by_tier.setdefault(job.tier or "Skip", []).append(job)

    for tier in ["Apply Now", "Worth a Look", "Weak Match", "Skip"]:
        tier_jobs = by_tier.get(tier, [])
        if not tier_jobs:
            continue
        lines += ["", "=" * 80, f"  {tier.upper()}  ({len(tier_jobs)} jobs)", "=" * 80]
        for job in tier_jobs:
            lines += [
                "", "─" * 60,
                f"TITLE:    {job.title}",
                f"COMPANY:  {job.company}",
                f"SOURCE:   {job.source}",
                f"LOCATION: {job.location}",
                f"URL:      {job.url}",
                f"SALARY:   {job.salary_str()}",
                f"RATING:   {job.tier}",
                f"REASON:   {job.reason}",
                f"DESC LEN: {len(job.description or '')} chars",
                "DESCRIPTION:",
                job.description or "(no description)",
                "─" * 60,
            ]
    try:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        DEBUG_LOG_FILE.write_text("\n".join(lines), encoding="utf-8")
        log(f"Debug log: {DEBUG_LOG_FILE} ({len(jobs)} jobs, {sum(raw_counts.values())} raw)")
    except Exception as e:
        log(f"Warning: could not write debug log: {e}")


def build_report(jobs: list[Job], seen: dict, now: datetime,
                 dedup_keys_fn=None) -> tuple[str, list[Job], dict, list[dict]]:
    # dedup_keys_fn is passed in by caller to avoid circular import
    new_jobs: list[Job] = []
    new_seen = dict(seen)
    today_str = date.today().isoformat()
    filtered: list[dict] = []

    def _reject(job, filter_name):
        filtered.append({
            "title": job.title, "company": job.company,
            "url": job.url, "source": job.source,
            "filter_name": filter_name,
        })

    within_run_seen: set[str] = set()

    for job in jobs:
        keys = dedup_keys_fn(job)
        if any(k in new_seen for k in keys):
            continue  # dedup — don't log
        if any(k in within_run_seen for k in keys):
            continue  # dedup — don't log
        if is_category_page(job.title, job.url, job.description):
            _reject(job, "category_page")
            continue
        if job.url and "virtualvocations.com" in job.url.lower():
            _reject(job, "virtualvocations")
            continue
        if job.company and job.company.lower().strip() in BLOCKED_COMPANIES:
            _reject(job, "blocked_company")
            continue
        if is_wrong_title(job.title):
            _reject(job, "wrong_title")
            continue
        if is_bad_scrape(job):
            _reject(job, "bad_scrape")
            continue
        if REQUIRE_US_LOCATION and is_non_us_location(job):
            _reject(job, "non_us_location")
            continue
        if is_onsite_non_local(job):
            _reject(job, "onsite_non_local")
            continue
        if is_staffing(job.title, job.company, job.description):
            _reject(job, "staffing")
            continue
        if is_below_salary_floor(job):
            _reject(job, "below_salary_floor")
            continue
        if is_closed_listing(job.description):
            _reject(job, "closed_listing")
            continue
        if is_broken_url(job.url):
            _reject(job, "broken_url")
            continue
        new_jobs.append(job)
        for k in keys:
            new_seen[k] = today_str
            within_run_seen.add(k)

    li_enrich_descriptions(new_jobs)

    log(f"Rating {len(new_jobs)} jobs with Claude Haiku (3 parallel, batched)...", source="Rating")
    rated: list[Optional[Job]] = [None] * len(new_jobs)
    BATCH_SIZE = 3

    def _rate_one(args: tuple[int, Job]) -> tuple[int, Job]:
        i, job = args
        tier, reason, salary_text = rate_with_claude(job)
        job.tier = tier
        job.reason = reason
        if salary_text and not job.salary_min:
            job.salary_text = salary_text
        with _print_lock:
            log(f"{i+1}/{len(new_jobs)} {tier} — {job.title[:60]}", source="Rating", verbose=True)
        return i, job

    for batch_start in range(0, len(new_jobs), BATCH_SIZE):
        batch = [(i, new_jobs[i]) for i in range(batch_start, min(batch_start + BATCH_SIZE, len(new_jobs)))]
        with ThreadPoolExecutor(max_workers=BATCH_SIZE) as executor:
            futures = {executor.submit(_rate_one, item): item[0] for item in batch}
            for future in as_completed(futures):
                try:
                    i, job = future.result()
                    rated[i] = job
                except Exception as e:
                    i = futures[future]
                    with _print_lock:
                        log(f"Error (job {i}): {e}", source="Rating")
                    new_jobs[i].tier = "Worth a Look"
                    new_jobs[i].reason = "Rating unavailable"
                    rated[i] = new_jobs[i]
        if batch_start + BATCH_SIZE < len(new_jobs):
            time.sleep(5)

    new_jobs = [j for j in rated if j is not None]

    def _sort_key(j: Job) -> tuple:
        loc = j.location.lower()
        is_local = any(term in loc for term in HOME_METRO_TERMS) or f", {HOME_STATE.lower()}" in loc
        return (TIER_ORDER.get(j.tier, 99), 0 if is_local else 1)

    new_jobs.sort(key=_sort_key)

    priority = [j for j in new_jobs if j.tier in ("Apply Now", "Worth a Look")]
    weak = [j for j in new_jobs if j.tier == "Weak Match"]
    skipped = [j for j in new_jobs if j.tier == "Skip"]
    slot = "AM" if now.hour < 12 else "PM"

    lines = [
        f"💼 JOB RADAR — {now.strftime('%A, %B %-d, %Y')} ({slot})",
        f"{len(new_jobs)} new | {len(priority)} priority ({sum(1 for j in new_jobs if j.tier == 'Apply Now')} Apply Now)",
        "",
    ]

    if not new_jobs:
        lines.append("No new positions found since last run.")
    else:
        tier_labels = {"Apply Now": "🔥 APPLY NOW", "Worth a Look": "👀 WORTH A LOOK"}
        current_tier = None

        for tier_name in ("Apply Now", "Worth a Look"):
            tier_jobs = [j for j in priority if j.tier == tier_name]
            if not tier_jobs:
                continue

            local_jobs = [j for j in tier_jobs if is_local_raleigh(j)]
            remote_jobs = [j for j in tier_jobs if not is_local_raleigh(j)]
            ordered = local_jobs + remote_jobs

            if tier_name != current_tier:
                current_tier = tier_name
                lines.append(f"\n{'─' * 40}")
                lines.append(tier_labels[tier_name])
                lines.append(f"{'─' * 40}")

            for job in ordered:
                pin = "📍 " if is_local_raleigh(job) else ""
                header = f"{pin}{job.title}"
                if job.company:
                    header += f" — {job.company}"
                if job.location:
                    header += f" ({job.location})"
                lines.append(header)

                if job.reason:
                    lines.append(f"↳ {job.reason}")
                if job.description:
                    snippet = job.description[:200].strip().replace("\n", " ")
                    if len(job.description) > 200:
                        snippet += "…"
                    lines.append(snippet)

                meta = [f"Salary: {job.salary_str()}"]
                if job.posted:
                    meta.append(f"Posted: {job.posted}")
                meta.append(f"Source: {job.source}")
                lines.append(" | ".join(meta))
                if job.url:
                    lines.append(f"🔗 {job.url}")
                lines.append("")

        if weak:
            lines.append(f"\n{'─' * 40}")
            lines.append(f"⚠️  WEAK MATCH ({len(weak)} jobs)")
            lines.append(f"{'─' * 40}")
            for job in weak:
                entry = f"⚠️ {job.title}"
                if job.company:
                    entry += f" — {job.company}"
                if job.reason:
                    entry += f"  [{job.reason}]"
                lines.append(entry)
                if job.url:
                    lines.append(f"   {job.url}")

        if skipped:
            lines.append(f"\n{'─' * 40}")
            lines.append(f"✗  SKIP ({len(skipped)} jobs — scan to catch mistakes)")
            lines.append(f"{'─' * 40}")
            for job in skipped:
                entry = f"✗ {job.title}"
                if job.company:
                    entry += f" — {job.company}"
                if job.reason:
                    entry += f"  [{job.reason}]"
                lines.append(entry)
                if job.url:
                    lines.append(f"   {job.url}")

    return "\n".join(lines), new_jobs, new_seen, filtered


def send_email(subject: str, body: str, attachment: Path | None = None):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = EMAIL
    msg["To"] = EMAIL
    msg.set_content(body)
    if attachment and attachment.exists():
        msg.add_attachment(
            attachment.read_bytes(),
            maintype="text", subtype="markdown",
            filename=attachment.name,
        )
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(EMAIL, GMAIL_APP_PW)
        smtp.send_message(msg)
