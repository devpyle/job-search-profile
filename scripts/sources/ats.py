"""ATS direct source — Greenhouse, Lever, Ashby career APIs."""

import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from config import (  # noqa: E402
    PORTAL_COMPANIES, PORTAL_NAME_OVERRIDES,
    PORTAL_TARGET_TITLES, PORTAL_BLOCK_SUFFIXES,
)

sys.path.insert(0, str(Path(__file__).parent.parent))
from models import Job  # noqa: E402
from normalize import _clean_desc  # noqa: E402
from log import log  # noqa: E402


def search_ats_companies() -> list[Job]:
    """Queries Greenhouse, Lever, and Ashby career APIs directly. No key needed."""

    jobs: list[Job] = []
    seen_urls: set[str] = set()

    def _title_match(title: str) -> bool:
        t = title.lower()
        if not any(kw in t for kw in PORTAL_TARGET_TITLES):
            return False
        if any(t.endswith(sfx) or f" {sfx}," in t or f" {sfx} " in t
               for sfx in PORTAL_BLOCK_SUFFIXES):
            return False
        return True

    def _company_name(slug: str) -> str:
        return PORTAL_NAME_OVERRIDES.get(slug, slug.replace("-", " ").title())

    def _try_greenhouse(slug: str) -> list[Job]:
        try:
            r = requests.get(f"https://api.greenhouse.io/v1/boards/{slug}/jobs",
                             params={"content": "false"}, timeout=8)
            if r.status_code != 200:
                return []
            result = []
            for item in r.json().get("jobs", []):
                title = item.get("title", "")
                if not _title_match(title):
                    continue
                url = item.get("absolute_url", "") or ""
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                result.append(Job(
                    title=title,
                    company=_company_name(slug),
                    location=item.get("location", {}).get("name", "") or "",
                    url=url,
                    posted=(item.get("updated_at", "") or "")[:10],
                    source="Greenhouse",
                ))
            return result
        except Exception:
            return []

    def _try_lever(slug: str) -> list[Job]:
        try:
            r = requests.get(f"https://api.lever.co/v0/postings/{slug}",
                             params={"mode": "json"}, timeout=8)
            if r.status_code != 200:
                return []
            items = r.json() if isinstance(r.json(), list) else []
            result = []
            for item in items:
                title = item.get("text", "")
                if not _title_match(title):
                    continue
                url = item.get("hostedUrl", "") or ""
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                desc_parts = [
                    item.get("descriptionPlain", "") or "",
                    item.get("additionalPlain", "") or "",
                ]
                for lst in (item.get("lists") or []):
                    desc_parts.append((lst.get("text", "") or "") + " " + (lst.get("content", "") or ""))
                desc = _clean_desc(" ".join(desc_parts))
                result.append(Job(
                    title=title,
                    company=_company_name(slug),
                    location=(item.get("categories") or {}).get("location", "") or "",
                    description=desc,
                    url=url,
                    source="Lever",
                ))
            return result
        except Exception:
            return []

    def _try_ashby(slug: str) -> list[Job]:
        try:
            r = requests.get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}", timeout=8)
            if r.status_code != 200:
                return []
            result = []
            for item in r.json().get("jobs", []):
                title = item.get("title", "")
                if not _title_match(title):
                    continue
                url = item.get("jobUrl", "") or item.get("applyUrl", "") or ""
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                result.append(Job(
                    title=title,
                    company=_company_name(slug),
                    location=item.get("location", "") or "",
                    url=url,
                    posted=(item.get("publishedDate", "") or "")[:10],
                    source="Ashby",
                ))
            return result
        except Exception:
            return []

    total = len(PORTAL_COMPANIES)
    total_tried = total_hits = 0
    log(f"Checking {total} companies across Greenhouse / Lever / Ashby...", source="ATS")
    for slug in PORTAL_COMPANIES:
        found  = _try_greenhouse(slug)
        found += _try_lever(slug)
        found += _try_ashby(slug)
        if found:
            total_hits += 1
            jobs.extend(found)
            titles = ", ".join(j.title for j in found[:2])
            log(f"✓ {slug} ({len(found)}): {titles}", source="ATS", verbose=True)
        total_tried += 1
        if total_tried % 50 == 0:
            log(f"{total_tried}/{total} checked — {len(jobs)} matches so far", source="ATS", verbose=True)
            time.sleep(1)

    log(f"{len(jobs)} results from {total_hits}/{total_tried} companies", source="ATS")
    return jobs
