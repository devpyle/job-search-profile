"""Adzuna job search API source."""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from config import ADZUNA_QUERIES, ADZUNA_COUNTRY  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent.parent))
from models import Job  # noqa: E402
from normalize import _clean_desc  # noqa: E402
from log import log  # noqa: E402

ADZUNA_APP_ID = os.environ.get("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY = os.environ.get("ADZUNA_APP_KEY", "")


def search_adzuna() -> list[Job]:
    queries = ADZUNA_QUERIES
    jobs = []
    for q in queries:
        try:
            r = requests.get(
                f"https://api.adzuna.com/v1/api/jobs/{ADZUNA_COUNTRY}/search/1",
                params={"app_id": ADZUNA_APP_ID, "app_key": ADZUNA_APP_KEY,
                        "results_per_page": 20, "full_time": 1,
                        "content-type": "application/json", **q},
                timeout=10,
            )
            r.raise_for_status()
            for j in r.json().get("results", []):
                created = j.get("created", "")
                try:
                    dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    days_ago = (datetime.now(timezone.utc) - dt).days
                    posted = f"{days_ago}d ago" if days_ago > 0 else "today"
                except Exception:
                    posted = created[:10] if created else ""
                if str(j.get("salary_is_predicted", "0")) == "1":
                    sal_min, sal_max = None, None
                else:
                    sal_min = j.get("salary_min") or None
                    sal_max = j.get("salary_max") or None
                jobs.append(Job(
                    title=j.get("title", ""),
                    company=j.get("company", {}).get("display_name", ""),
                    location=j.get("location", {}).get("display_name", ""),
                    description=_clean_desc(j.get("description", "")),
                    salary_min=sal_min, salary_max=sal_max,
                    url=j.get("redirect_url", ""),
                    posted=posted, source="Adzuna",
                ))
        except Exception as e:
            log(f"Query failed ({q['what']}): {e}", source="Adzuna")
    return jobs
