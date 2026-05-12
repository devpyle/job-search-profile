"""UKG/UltiPro direct source — scrapes recruiting.ultipro.com job boards.

Each company that hosts on UKG has a board at:
    https://recruiting.ultipro.com/{tenant}/JobBoard/{board_id}/

Configure UKG_COMPANIES in config.py as a list of (tenant, board_id, display_name)
tuples. Find the tenant + board_id by visiting a company's UKG-hosted careers page
and reading the URL.
"""

import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from config import PORTAL_TARGET_TITLES, PORTAL_BLOCK_SUFFIXES  # noqa: E402

try:
    from config import UKG_COMPANIES  # noqa: E402
except ImportError:
    UKG_COMPANIES = []

sys.path.insert(0, str(Path(__file__).parent.parent))
from models import Job  # noqa: E402
from log import log  # noqa: E402


def _title_match(title: str) -> bool:
    t = title.lower()
    if not any(kw in t for kw in PORTAL_TARGET_TITLES):
        return False
    if any(t.endswith(sfx) or f" {sfx}," in t or f" {sfx} " in t
           for sfx in PORTAL_BLOCK_SUFFIXES):
        return False
    return True


def _location_string(item: dict) -> str:
    loc = item.get("primaryLocation") or item.get("PrimaryLocation") or {}
    parts = [
        loc.get("city") or loc.get("City"),
        loc.get("state") or loc.get("State"),
        loc.get("country") or loc.get("Country"),
    ]
    return ", ".join(p for p in parts if p)


def search_ukg() -> list[Job]:
    if not UKG_COMPANIES:
        return []

    jobs: list[Job] = []
    boards_hit = 0
    for entry in UKG_COMPANIES:
        try:
            tenant, board_id, display = entry
        except (ValueError, TypeError):
            log(f"Bad UKG_COMPANIES entry (expected (tenant, board_id, name)): {entry!r}",
                source="UKG")
            continue

        base = f"https://recruiting.ultipro.com/{tenant}/JobBoard/{board_id}"
        try:
            r = requests.post(
                f"{base}/SearchJobs/",
                json={
                    "opportunitySearch": {
                        "Top": 50, "Skip": 0,
                        "QueryString": "",
                        "OrderBy": [{"Value": "postedDateDesc"}],
                    }
                },
                timeout=10,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            )
            if r.status_code != 200:
                continue
            opportunities = r.json().get("opportunities") or r.json().get("Opportunities") or []
            count_before = len(jobs)
            for item in opportunities:
                title = item.get("title") or item.get("Title") or ""
                if not _title_match(title):
                    continue
                opp_id = (
                    item.get("opportunityId")
                    or item.get("OpportunityId")
                    or item.get("id")
                    or ""
                )
                posted = (item.get("postedDate") or item.get("PostedDate") or "")[:10]
                jobs.append(Job(
                    title=title,
                    company=display,
                    location=_location_string(item),
                    url=f"{base}/OpportunityDetail?opportunityId={opp_id}",
                    posted=posted,
                    source="UKG",
                ))
            if len(jobs) > count_before:
                boards_hit += 1
            time.sleep(0.5)
        except Exception as e:
            log(f"Error ({display}): {e}", source="UKG")

    log(f"{len(jobs)} results from {boards_hit}/{len(UKG_COMPANIES)} boards", source="UKG")
    return jobs
