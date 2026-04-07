"""LinkedIn job search via HTML scraping."""

import re
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from config import LI_REMOTE_QUERIES, LI_LOCAL_QUERIES  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent.parent))
from models import Job  # noqa: E402
from normalize import _clean_desc  # noqa: E402
from filters import LI_NC_LOCATIONS  # noqa: E402
from log import log  # noqa: E402

LI_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.linkedin.com/",
}
LI_BASE_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
LI_DETAIL_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"

LI_RALEIGH_QUERIES = LI_LOCAL_QUERIES


def _li_parse_cards(soup, remote: bool) -> list[Job]:
    """Parse job cards from a LinkedIn search results soup."""
    jobs = []
    for card in soup.find_all("li"):
        title_el   = card.find("h3")
        company_el = card.find("h4")
        loc_el     = card.find("span", class_=lambda c: c and "job-search-card__location" in c)
        link_el    = card.find("a", href=True)
        if not (title_el and company_el):
            continue
        loc = loc_el.text.strip() if loc_el else ""
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


def _li_fetch(keywords: str, remote: bool) -> list[Job]:
    from bs4 import BeautifulSoup
    import random
    base_params = {
        "keywords": keywords,
        "geoId":    "103644278",
        "f_TPR":    "r604800",
        "f_JT":     "F",
        "sortBy":   "DD",
    }
    if remote:
        base_params["f_WT"] = "2,3"
    session = requests.Session()
    session.headers.update(LI_HEADERS)
    jobs = []
    for page in range(2):
        if page > 0:
            time.sleep(random.uniform(3, 7))
        params = {**base_params, "start": page * 25}
        try:
            r = session.get(LI_BASE_URL, params=params, timeout=10)
            r.raise_for_status()
        except Exception:
            break
        soup = BeautifulSoup(r.text, "html.parser")
        page_jobs = _li_parse_cards(soup, remote)
        jobs.extend(page_jobs)
        if len(page_jobs) < 20:
            break
        if page == 0:
            time.sleep(1.5)
    return jobs


def _li_fetch_description(job_url: str) -> str:
    """Fetch full job description from LinkedIn detail endpoint."""
    from bs4 import BeautifulSoup
    m = re.search(r"(\d{7,})", job_url)
    if not m:
        return ""
    job_id = m.group(1)
    try:
        r = requests.get(LI_DETAIL_URL.format(job_id=job_id), headers=LI_HEADERS, timeout=10)
        if r.status_code != 200:
            return ""
        soup = BeautifulSoup(r.text, "html.parser")
        desc_el = soup.find("div", class_=lambda c: c and "description__text" in c)
        if desc_el:
            return _clean_desc(desc_el.get_text(" ", strip=True))
    except Exception:
        pass
    return ""


def li_enrich_descriptions(jobs: list[Job]) -> None:
    """Fetch full descriptions for LinkedIn jobs that don't have one yet."""
    import random
    li_jobs = [j for j in jobs if j.source == "LinkedIn" and not j.description]
    if not li_jobs:
        return
    log(f"Fetching descriptions for {len(li_jobs)} LinkedIn jobs...", source="LinkedIn")
    for i, job in enumerate(li_jobs):
        if i > 0:
            time.sleep(random.uniform(2, 5))
        desc = _li_fetch_description(job.url)
        if desc:
            job.description = desc


def search_linkedin() -> list[Job]:
    try:
        from bs4 import BeautifulSoup  # noqa: F401
    except ImportError:
        log("BeautifulSoup not installed, skipping", source="LinkedIn")
        return []
    jobs = []
    for q in LI_REMOTE_QUERIES:
        try:
            jobs.extend(_li_fetch(q, remote=True))
        except Exception as e:
            log(f"Remote query failed ({q[:40]}): {e}", source="LinkedIn")
    for q in LI_RALEIGH_QUERIES:
        try:
            jobs.extend(_li_fetch(q, remote=False))
        except Exception as e:
            log(f"Local query failed ({q[:40]}): {e}", source="LinkedIn")
    return jobs
