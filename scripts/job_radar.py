#!/usr/bin/env python3
"""Job radar — queries Adzuna, Brave, and Tavily, saves a dated report, emails results."""

import json
import os
import re
import smtplib
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

ADZUNA_APP_ID = os.environ["ADZUNA_APP_ID"]
ADZUNA_APP_KEY = os.environ["ADZUNA_APP_KEY"]
BRAVE_API_KEY = os.environ["BRAVE_API_KEY"]
TAVILY_API_KEY = os.environ["TAVILY_API_KEY"]
GMAIL_APP_PW = os.environ["GMAIL_APP_PW"]
EMAIL = "your@email.com"

REPO_ROOT = Path(__file__).parent.parent
OUTPUT_DIR = REPO_ROOT / "output" / "job-radar"
SEEN_FILE = OUTPUT_DIR / ".seen.json"


@dataclass
class Job:
    title: str
    company: str = ""
    location: str = ""
    description: str = ""
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    url: str = ""
    posted: str = ""
    source: str = ""
    stars: int = 0

    def dedup_key(self) -> str:
        if self.company:
            return f"{self.title.lower().strip()}|{self.company.lower().strip()}"
        return self.url

    def salary_str(self) -> str:
        if self.salary_min and self.salary_max:
            return f"${self.salary_min:,.0f}–${self.salary_max:,.0f}"
        if self.salary_min:
            return f"${self.salary_min:,.0f}+"
        return "Not listed"


# Job board search/category page URL fragments — browse pages, not individual listings
CATEGORY_URL_FRAGMENTS = [
    "glassdoor.com/Job/", "indeed.com/q-", "indeed.com/jobs",
    "linkedin.com/jobs/search", "linkedin.com/jobs/api-", "linkedin.com/jobs/product-",
    "ziprecruiter.com/Jobs/", "jobgether.com/remote-jobs/",
    "remoterocketship.com/jobs/", "remoterocketship.com/us/jobs/",
    "remotive.com/remote-jobs/", "wellfound.com/jobs", "builtin",
    "flexjobs.com/jobs", "workingnomads.com/jobs", "getwork.com/jobs",
    "careerjet.com", "simplyhired.com/search", "jobgether.com/en/",
    "dailyremote.com/remote-", "beamjobs.com", "resumeworded.com",
    "zety.com", "kickresume.com", "remotebob.io",
]

# Non-job content to filter (blog posts, articles, resume guides, cost breakdowns)
NON_JOB_TITLE_RE = re.compile(
    r"resume (samples?|templates?|examples?|guide)|"
    r"(cost|price|pricing)\s+(breakdown|guide|in \d{4})|"
    r"how to (write|build|create)|"
    r"(top|best)\s+\d+\s+(tools?|skills?|tips?|ways?)",
    re.IGNORECASE
)

# Title patterns that indicate a category/search page rather than a single job
CATEGORY_TITLE_RE = re.compile(
    r"\d[\d,+]+\s+\w.*jobs?\s+(in|for|at)\b"        # "2,129 product owner jobs in..."
    r"|^(browse|search(\s+the\s+best)?)\s+"           # "Browse 57..." / "Search the best..."
    r"|jobs?\s+in\s+(remote|united states|us)\b"
    r"|(top|best)\s+remote\s+\w.*jobs?\s+(in|from)\b" # "Top/Best Remote PM Jobs in..."
    r"|^\d[\d,+]+\s+(remote|open)\s+\w+\s+jobs?\b"   # "312 product owner remote jobs"
    r"|today.s top \d",                               # "Today's top 4000+..."
    re.IGNORECASE
)


def is_category_page(title: str, url: str) -> bool:
    if any(frag in url for frag in CATEGORY_URL_FRAGMENTS):
        return True
    if bool(CATEGORY_TITLE_RE.search(title)):
        return True
    if bool(NON_JOB_TITLE_RE.search(title)):
        return True
    return False


STAFFING_KEYWORDS = [
    "staffing", "recruiting", "recruiter", "talent solutions", "search group",
    "placement", "manpower", "robert half", "adecco", "kelly services",
    "randstad", "insight global", "apex systems", "our client", "on behalf of",
]

MIN_SALARY = 120_000


def is_staffing(title: str, company: str, description: str) -> bool:
    combined = f"{title} {company} {description}".lower()
    return any(kw in combined for kw in STAFFING_KEYWORDS)


def is_below_salary_floor(salary_min: Optional[float]) -> bool:
    """Drop only if salary is explicitly listed AND under the floor."""
    return salary_min is not None and salary_min > 0 and salary_min < MIN_SALARY


def rate(title: str, description: str = "", location: str = "", salary_min=None) -> int:
    t = title.lower()
    d = description.lower()
    combined = t + " " + d + " " + location.lower()

    is_po_pm = any(w in t for w in ["product owner", "product manager"])
    is_ba_fa = any(w in t for w in ["business analyst", "functional analyst"])
    has_api_platform = any(w in combined for w in ["api", "platform", "middleware", "integration"])
    has_fintech = any(w in combined for w in ["fintech", "banking", "financial", "payments", "digital bank"])
    is_remote = "remote" in combined
    has_salary = salary_min is not None

    if is_po_pm and has_api_platform and (has_fintech or is_remote) and has_salary:
        return 5
    if is_po_pm and has_api_platform:
        return 4
    if is_po_pm and (has_fintech or is_remote):
        return 4
    if is_po_pm:
        return 3
    if is_ba_fa:
        return 3
    return 2


def load_seen() -> set:
    if SEEN_FILE.exists():
        return set(json.loads(SEEN_FILE.read_text()))
    return set()


def save_seen(seen: set):
    SEEN_FILE.write_text(json.dumps(sorted(seen), indent=2))


def search_adzuna() -> list[Job]:
    # Adzuna US API doesn't support where=remote; omit where for remote searches
    # and include "remote" in the keyword string instead.
    queries = [
        {"what": "product owner API platform remote", "sort_by": "date", "max_days_old": 7},
        {"what": "product manager middleware fintech", "where": "Raleigh, NC", "sort_by": "date", "max_days_old": 7},
        {"what": "product owner digital banking remote", "sort_by": "date", "max_days_old": 7},
        {"what": "business analyst API integration remote", "sort_by": "date", "max_days_old": 7},
        {"what": "platform product manager remote", "sort_by": "salary", "max_days_old": 14},
    ]
    jobs = []
    for q in queries:
        try:
            params = {
                "app_id": ADZUNA_APP_ID,
                "app_key": ADZUNA_APP_KEY,
                "results_per_page": 20,
                "full_time": 1,
                "content-type": "application/json",
                **q,
            }
            r = requests.get(
                "https://api.adzuna.com/v1/api/jobs/us/search/1",
                params=params,
                timeout=10,
            )
            r.raise_for_status()
            for j in r.json().get("results", []):
                created = j.get("created", "")
                try:
                    dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    days_ago = (datetime.now(timezone.utc) - dt).days
                    posted = f"{days_ago}d ago"
                except Exception:
                    posted = created[:10] if created else ""
                jobs.append(Job(
                    title=j.get("title", ""),
                    company=j.get("company", {}).get("display_name", ""),
                    location=j.get("location", {}).get("display_name", ""),
                    description=j.get("description", ""),
                    salary_min=j.get("salary_min"),
                    salary_max=j.get("salary_max"),
                    url=j.get("redirect_url", ""),
                    posted=posted,
                    source="Adzuna",
                ))
        except Exception as e:
            print(f"Adzuna query failed ({q['what']}): {e}")
    return jobs


def search_brave() -> list[Job]:
    queries = [
        '"product owner" fintech API remote job -staffing -recruiter -resume -"how to"',
        '"product manager" middleware platform Raleigh Durham Charlotte RTP job -staffing -recruiter',
        '"business analyst" digital banking API remote job -staffing -recruiter -resume',
    ]
    jobs = []
    headers = {
        "Accept": "application/json",
        "X-Subscription-Token": BRAVE_API_KEY,
    }
    for q in queries:
        time.sleep(1.2)  # Brave free tier: 1 req/sec
        try:
            r = requests.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": q, "count": 10, "freshness": "pw"},
                headers=headers,
                timeout=10,
            )
            r.raise_for_status()
            for item in r.json().get("web", {}).get("results", []):
                jobs.append(Job(
                    title=item.get("title", ""),
                    description=item.get("description", ""),
                    url=item.get("url", ""),
                    source="Brave",
                ))
        except Exception as e:
            print(f"Brave query failed ({q[:50]}): {e}")
    return jobs


def search_tavily() -> list[Job]:
    queries = [
        '"product owner" OR "product manager" API platform middleware remote "job opening" OR "now hiring" OR "apply now"',
        '"product owner" OR "product manager" digital banking fintech remote "job opening" OR "hiring" OR "apply"',
        '"business analyst" OR "functional analyst" API integration fintech remote "job opening" OR "hiring" OR "apply"',
        '"product owner" OR "product manager" SaaS enterprise platform remote "job opening" OR "now hiring" OR "apply now"',
    ]
    jobs = []
    for q in queries:
        try:
            r = requests.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": TAVILY_API_KEY,
                    "query": q,
                    "search_depth": "basic",
                    "max_results": 8,
                },
                timeout=15,
            )
            r.raise_for_status()
            for item in r.json().get("results", []):
                jobs.append(Job(
                    title=item.get("title", ""),
                    description=item.get("content", ""),
                    url=item.get("url", ""),
                    source="Tavily",
                ))
        except Exception as e:
            print(f"Tavily query failed ({q[:50]}): {e}")
    return jobs


LI_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}
LI_BASE_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
LI_NC_LOCATIONS = {
    "raleigh", "durham", "chapel hill", "cary", "morrisville", "apex",
    "holly springs", "wake forest", "research triangle", "rtp",
    ", nc", "north carolina",
}

LI_REMOTE_QUERIES = [
    "product owner API platform",
    "product manager middleware fintech",
    "platform product manager",
    "product owner digital banking",
]

LI_RALEIGH_QUERIES = [
    "product owner Raleigh NC",
    "product manager Raleigh Durham RTP",
    "business analyst Raleigh NC",
    'product owner "First Citizens" OR "Q2" OR "Red Hat" OR "SAS Institute" OR "Bandwidth" OR "Pendo"',
    'product manager "Fidelity" OR "MetLife" OR "Cisco" OR "IBM" OR "NetApp" OR "Lenovo" Raleigh',
]


def _li_fetch(keywords: str, remote: bool) -> list[Job]:
    from bs4 import BeautifulSoup
    params = {
        "keywords": keywords,
        "geoId": "103644278",
        "f_TPR": "r604800",
        "start": 0,
    }
    if remote:
        params["f_WT"] = "2"
    r = requests.get(LI_BASE_URL, params=params, headers=LI_HEADERS, timeout=10)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    jobs = []
    for card in soup.find_all("li"):
        title_el = card.find("h3")
        company_el = card.find("h4")
        loc_el = card.find("span", class_=lambda c: c and "job-search-card__location" in c)
        link_el = card.find("a", href=True)
        if not (title_el and company_el):
            continue
        loc = loc_el.text.strip() if loc_el else ""
        # Location filter
        loc_lower = loc.lower()
        if remote:
            if loc_lower and "remote" not in loc_lower and loc_lower != "united states":
                continue
        else:
            if not any(area in loc_lower for area in LI_NC_LOCATIONS):
                continue
        jobs.append(Job(
            title=title_el.text.strip(),
            company=company_el.text.strip(),
            location=loc,
            url=link_el["href"].split("?")[0] if link_el else "",
            source="LinkedIn",
        ))
    return jobs


def search_linkedin() -> list[Job]:
    try:
        from bs4 import BeautifulSoup  # noqa: F401 — verify import available
    except ImportError:
        print("  BeautifulSoup not installed, skipping LinkedIn")
        return []

    jobs = []
    for q in LI_REMOTE_QUERIES:
        try:
            results = _li_fetch(q, remote=True)
            jobs.extend(results)
        except Exception as e:
            print(f"  LinkedIn remote query failed ({q[:40]}): {e}")

    for q in LI_RALEIGH_QUERIES:
        try:
            results = _li_fetch(q, remote=False)
            jobs.extend(results)
        except Exception as e:
            print(f"  LinkedIn Raleigh query failed ({q[:40]}): {e}")

    return jobs


def build_report(jobs: list[Job], seen: set, now: datetime) -> tuple[str, list[Job], set]:
    new_jobs = []
    new_seen = set(seen)
    for job in jobs:
        key = job.dedup_key()
        if not key:
            continue
        if key in new_seen:
            continue
        if is_category_page(job.title, job.url):
            continue
        if is_staffing(job.title, job.company, job.description):
            continue
        if is_below_salary_floor(job.salary_min):
            continue
        job.stars = rate(job.title, job.description, job.location, job.salary_min)
        new_jobs.append(job)
        new_seen.add(key)

    new_jobs.sort(key=lambda j: j.stars, reverse=True)
    strong = sum(1 for j in new_jobs if j.stars >= 4)
    slot = "AM" if now.hour < 12 else "PM"

    lines = [
        f"💼 JOB RADAR — {now.strftime('%A, %B %-d, %Y')} ({slot})",
        f"{len(new_jobs)} new positions found | {strong} strong matches",
        "",
    ]

    if not new_jobs:
        lines.append("No new positions found since last run.")
    else:
        for job in new_jobs:
            header = "⭐" * job.stars + " " + job.title
            if job.company:
                header += f" — {job.company}"
            if job.location:
                header += f" ({job.location})"
            lines.append(header)

            if job.description:
                snippet = job.description[:220].strip().replace("\n", " ")
                if len(job.description) > 220:
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

        top = new_jobs[0]
        if top.stars >= 4:
            company_part = f" at {top.company}" if top.company else ""
            lines.append(
                f"💡 Top pick: {top.title}{company_part} — "
                "strong match for your API platform background. Apply today."
            )

    return "\n".join(lines), new_jobs, new_seen


def send_email(subject: str, body: str):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = EMAIL
    msg["To"] = EMAIL
    msg.set_content(body)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(EMAIL, GMAIL_APP_PW)
        smtp.send_message(msg)


def main():
    now = datetime.now()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    seen = load_seen()

    print("Searching Adzuna...")
    adzuna_jobs = search_adzuna()
    print(f"  {len(adzuna_jobs)} results")

    print("Searching Brave...")
    brave_jobs = search_brave()
    print(f"  {len(brave_jobs)} results")

    print("Searching Tavily...")
    tavily_jobs = search_tavily()
    print(f"  {len(tavily_jobs)} results")

    print("Searching LinkedIn...")
    linkedin_jobs = search_linkedin()
    print(f"  {len(linkedin_jobs)} results")

    all_jobs = adzuna_jobs + brave_jobs + tavily_jobs + linkedin_jobs
    report, new_jobs, new_seen = build_report(all_jobs, seen, now)

    slot = "am" if now.hour < 12 else "pm"
    outfile = OUTPUT_DIR / f"{now.strftime('%Y-%m-%d')}-{slot}.md"
    outfile.write_text(report)
    print(f"Saved: {outfile}")

    save_seen(new_seen)

    strong = sum(1 for j in new_jobs if j.stars >= 4)
    subject = f"Job Radar {now.strftime('%b %-d')} {slot.upper()} — {len(new_jobs)} new, {strong} strong"
    send_email(subject, report)
    print("Email sent.")


if __name__ == "__main__":
    main()
