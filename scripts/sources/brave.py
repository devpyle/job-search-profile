"""Brave web search API source."""

import os
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from config import BRAVE_QUERIES  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent.parent))
from models import Job  # noqa: E402
from normalize import _clean_desc  # noqa: E402
from log import log  # noqa: E402

BRAVE_API_KEY = os.environ.get("BRAVE_API_KEY", "")


def search_brave() -> list[Job]:
    queries = BRAVE_QUERIES
    jobs = []
    headers = {"Accept": "application/json", "X-Subscription-Token": BRAVE_API_KEY}
    for q in queries:
        time.sleep(1.2)
        try:
            r = requests.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": q, "count": 10, "freshness": "pw"},
                headers=headers, timeout=10,
            )
            r.raise_for_status()
            for item in r.json().get("web", {}).get("results", []):
                jobs.append(Job(
                    title=item.get("title", ""),
                    description=_clean_desc(item.get("description", "")),
                    url=item.get("url", ""),
                    source="Brave",
                ))
        except Exception as e:
            log(f"Query failed ({q[:50]}): {e}", source="Brave")
    return jobs
