"""UKG/UltiPro direct source — scrapes recruiting.ultipro.com job boards.

Each company that hosts on UKG has a board at one of:
    https://recruiting.ultipro.com/{tenant}/JobBoard/{board_id}/
    https://recruiting2.ultipro.com/{tenant}/JobBoard/{board_id}/

Configure UKG_COMPANIES in config.py as a list of either:
    (tenant, board_id, display_name)
    (tenant, board_id, display_name, subdomain)   # subdomain = "recruiting" or "recruiting2"

When the subdomain is omitted, "recruiting" is used and "recruiting2" is tried
as a fallback if the first request 404s.
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
    locs = item.get("Locations") or item.get("locations") or []
    if not locs:
        return ""
    addr = (locs[0] or {}).get("Address") or {}
    state = addr.get("State") or {}
    country = addr.get("Country") or {}
    parts = [
        addr.get("City"),
        state.get("Name") or state.get("Code"),
        country.get("Name") or country.get("Code"),
    ]
    return ", ".join(p for p in parts if p)


def search_ukg() -> list[Job]:
    if not UKG_COMPANIES:
        return []

    jobs: list[Job] = []
    boards_hit = 0
    for entry in UKG_COMPANIES:
        try:
            if len(entry) == 4:
                tenant, board_id, display, subdomain = entry
                subdomains = [subdomain]
            elif len(entry) == 3:
                tenant, board_id, display = entry
                subdomains = ["recruiting", "recruiting2"]
            else:
                raise ValueError("wrong tuple length")
        except (ValueError, TypeError):
            log(f"Bad UKG_COMPANIES entry (expected (tenant, board_id, name) or +subdomain): {entry!r}",
                source="UKG")
            continue

        r = None
        base = None
        for sub in subdomains:
            try_base = f"https://{sub}.ultipro.com/{tenant}/JobBoard/{board_id}"
            try:
                r = requests.post(
                    f"{try_base}/JobBoardView/LoadSearchResults",
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
            except Exception as e:
                log(f"Error ({display} @ {sub}): {e}", source="UKG")
                r = None
                continue
            if r.status_code == 200:
                base = try_base
                break

        if not r or r.status_code != 200 or base is None:
            continue

        try:
            payload = r.json()
            opportunities = payload.get("opportunities") or payload.get("Opportunities") or []
            count_before = len(jobs)
            for item in opportunities:
                title = item.get("Title") or item.get("title") or ""
                if not _title_match(title):
                    continue
                opp_id = item.get("Id") or item.get("id") or ""
                posted = (item.get("PostedDate") or item.get("postedDate") or "")[:10]
                jobs.append(Job(
                    title=title,
                    company=display,
                    location=_location_string(item),
                    description=item.get("BriefDescription") or "",
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
