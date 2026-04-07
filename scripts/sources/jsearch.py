"""JSearch (RapidAPI) job search source."""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from config import (  # noqa: E402
    JSEARCH_REMOTE_QUERIES, JSEARCH_LOCAL_QUERIES,
    HOME_METRO_TERMS, HOME_STATE, HOME_CITY,
)

sys.path.insert(0, str(Path(__file__).parent.parent))
from models import Job  # noqa: E402
from normalize import _clean_desc  # noqa: E402
from log import log  # noqa: E402

JSEARCH_API_KEY = os.environ.get("JSEARCH_API_KEY", "")


def search_jsearch() -> list[Job]:
    if not JSEARCH_API_KEY:
        return []
    remote_queries = JSEARCH_REMOTE_QUERIES
    local_queries  = JSEARCH_LOCAL_QUERIES
    local_cities   = set(HOME_METRO_TERMS)
    jobs = []
    headers = {"X-RapidAPI-Key": JSEARCH_API_KEY, "X-RapidAPI-Host": "jsearch.p.rapidapi.com"}
    for q in remote_queries + local_queries:
        for attempt in range(3):
            try:
                r = requests.get(
                    "https://jsearch.p.rapidapi.com/search",
                    headers=headers,
                    params={"query": q, "num_pages": "1", "date_posted": "week"},
                    timeout=20,
                )
                r.raise_for_status()
                data = r.json()
                if not isinstance(data.get("data"), list):
                    break
                for item in data["data"]:
                    is_remote = item.get("job_is_remote", False)
                    city  = (item.get("job_city") or "").lower()
                    state = (item.get("job_state") or "").lower()
                    local_match = (city in local_cities) or (state in (HOME_STATE.lower(), HOME_STATE.lower() + " " + HOME_CITY.lower()))
                    if not is_remote and not local_match:
                        continue
                    loc = "Remote" if is_remote else f"{item.get('job_city', '')}, {item.get('job_state', '')}"
                    sal_min = item.get("job_min_salary") or 0
                    sal_max = item.get("job_max_salary") or 0
                    if item.get("job_salary_period") == "HOUR":
                        sal_min = sal_min * 2080 if sal_min else 0
                        sal_max = sal_max * 2080 if sal_max else 0
                    posted = ""
                    ts = item.get("job_posted_at_timestamp")
                    if ts:
                        days_ago = int((datetime.now(timezone.utc).timestamp() - ts) // 86400)
                        posted = f"{days_ago}d ago" if days_ago > 0 else "today"
                    jobs.append(Job(
                        title=item.get("job_title", ""),
                        company=item.get("employer_name", ""),
                        location=loc,
                        description=_clean_desc(item.get("job_description", ""))[:2000],
                        salary_min=sal_min or None,
                        salary_max=sal_max or None,
                        url=item.get("job_apply_link") or item.get("job_google_link", ""),
                        posted=posted,
                        source="JSearch",
                    ))
                break
            except requests.exceptions.Timeout:
                if attempt >= 2:
                    log(f"Timeout ({q}) — skipping after 3 attempts", source="JSearch")
            except Exception as e:
                log(f"Error ({q}): {e}", source="JSearch")
                break
    log(f"{len(jobs)} results", source="JSearch")
    return jobs
