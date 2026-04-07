"""Remote job board sources — Remotive, WeWorkRemotely, Himalayas, RemoteOK, Jobicy."""

import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))
from models import Job  # noqa: E402
from normalize import _clean_desc, format_salary_text, matches_keywords  # noqa: E402
from log import log  # noqa: E402

TARGET_KEYWORDS = ["product owner", "product manager", "platform product", "scrum master"]


def search_remotive() -> list[Job]:
    queries = [
        {"category": "product"},
        {"category": "management", "search": "product owner"},
        {"search": "product manager"},
    ]
    jobs = []
    seen_urls: set[str] = set()
    for params in queries:
        try:
            r = requests.get("https://remotive.com/api/remote-jobs", params=params, timeout=20)
            if r.status_code != 200:
                continue
            for item in r.json().get("jobs", []):
                url = item.get("url", "") or ""
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                location = (item.get("candidate_required_location") or "").lower()
                if location and not any(x in location for x in [
                    "worldwide", "anywhere", "usa", "us only", "united states",
                    "north america", "americas", "",
                ]):
                    continue
                jobs.append(Job(
                    title=item.get("title", ""),
                    company=item.get("company_name", ""),
                    location="Remote",
                    description=_clean_desc(item.get("description", ""))[:500],
                    url=url,
                    salary_text=item.get("salary") or "",
                    posted=item.get("publication_date", ""),
                    source="Remotive",
                ))
            time.sleep(1.5)
        except Exception as e:
            log(f"Error ({params}): {e}", source="Remotive")
    log(f"{len(jobs)} results", source="Remotive")
    return jobs


def search_weworkremotely() -> list[Job]:
    feeds = [
        "https://weworkremotely.com/categories/remote-product-jobs.rss",
        "https://weworkremotely.com/categories/remote-management-jobs.rss",
    ]
    jobs = []
    for feed_url in feeds:
        try:
            r = requests.get(feed_url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            root = ET.fromstring(r.content)
            for item in root.findall(".//item"):
                title   = item.findtext("title", "").strip()
                link    = item.findtext("link", "").strip()
                desc    = item.findtext("description", "").strip()
                pubdate = item.findtext("pubDate", "").strip()
                if " at " in title:
                    title = title.split(" at ")[0].strip()
                jobs.append(Job(
                    title=title,
                    location="Remote",
                    description=_clean_desc(desc),
                    url=link,
                    posted=pubdate[:16] if pubdate else "",
                    source="WeWorkRemotely",
                ))
        except Exception as e:
            log(f"Error ({feed_url}): {e}", source="WWR")
    log(f"{len(jobs)} results", source="WWR")
    return jobs


def search_himalayas() -> list[Job]:
    queries = [
        ("product-management", "product owner"),
        ("product-management", "product manager"),
        ("management", "product owner"),
    ]
    jobs = []
    seen_urls: set[str] = set()
    for _category, _keyword in queries:
        for offset in [0, 20]:
            try:
                resp = requests.get(
                    "https://himalayas.app/jobs/api",
                    params={"limit": 20, "offset": offset},
                    timeout=15,
                )
                if resp.status_code != 200:
                    break
                data = resp.json()
                items = data if isinstance(data, list) else data.get("jobs", [])
                if not items:
                    break
                for item in items:
                    title = item.get("title", "") or ""
                    if not matches_keywords(title, TARGET_KEYWORDS):
                        continue
                    url = item.get("applicationLink", "") or ""
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)
                    sal_min = item.get("minSalary") or 0
                    sal_max = item.get("maxSalary") or 0
                    salary_text = ""
                    if sal_min and item.get("currency", "").upper() == "USD":
                        salary_text = format_salary_text(sal_min, sal_max)
                    jobs.append(Job(
                        title=title,
                        company=item.get("companyName", ""),
                        location="Remote",
                        description=_clean_desc(item.get("description", "") or item.get("excerpt", "")),
                        url=url,
                        salary_text=salary_text,
                        posted=item.get("pubDate", ""),
                        source="Himalayas",
                    ))
                time.sleep(1)
                if len(items) < 20:
                    break
            except Exception as e:
                log(f"Error (offset={offset}): {e}", source="Himalayas")
                break
    log(f"{len(jobs)} results", source="Himalayas")
    return jobs


def search_remoteok() -> list[Job]:
    """Free public JSON API — no key required."""
    target_keywords = [
        "product manager", "product owner", "product lead",
        "principal product", "platform product", "scrum master",
    ]
    jobs = []
    try:
        resp = requests.get(
            "https://remoteok.com/api",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=20,
        )
        if resp.status_code != 200:
            log(f"Error: HTTP {resp.status_code}", source="RemoteOK")
            return []
        seen_urls: set[str] = set()
        for item in resp.json():
            if not isinstance(item, dict) or "position" not in item:
                continue
            title = item.get("position", "") or ""
            if not matches_keywords(title, target_keywords):
                continue
            url = item.get("url", "") or f"https://remoteok.com/l/{item.get('id', '')}"
            if url in seen_urls:
                continue
            seen_urls.add(url)
            sal_min = item.get("salary_min") or 0
            sal_max = item.get("salary_max") or 0
            salary_text = format_salary_text(sal_min, sal_max) if sal_min else ""
            jobs.append(Job(
                title=title,
                company=item.get("company", "") or "",
                location="Remote",
                description=_clean_desc(item.get("description", "")),
                url=url,
                salary_text=salary_text,
                posted=(item.get("date", "") or "")[:10],
                source="RemoteOK",
            ))
    except Exception as e:
        log(f"Error: {e}", source="RemoteOK")
    log(f"{len(jobs)} results", source="RemoteOK")
    return jobs


def search_jobicy() -> list[Job]:
    queries = [
        {"geo": "usa", "industry": "management",         "tag": "product owner",          "count": 50},
        {"geo": "usa", "industry": "management",         "tag": "product manager",         "count": 50},
        {"geo": "usa", "industry": "accounting-finance", "tag": "product owner",           "count": 50},
        {"geo": "usa", "industry": "business",           "tag": "product owner",           "count": 50},
        {"geo": "usa",                                    "tag": "product owner API platform", "count": 50},
        {"geo": "usa",                                    "tag": "product owner fintech",   "count": 50},
    ]
    jobs = []
    seen_urls: set[str] = set()
    for params in queries:
        try:
            resp = requests.get("https://jobicy.com/api/v2/remote-jobs", params=params, timeout=20)
            if resp.status_code != 200:
                log(f"Error ({params.get('tag','?')}): HTTP {resp.status_code}", source="Jobicy")
                continue
            for item in resp.json().get("jobs", []):
                url = item.get("url", "") or ""
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                title = item.get("jobTitle", "") or ""
                if not matches_keywords(title, TARGET_KEYWORDS):
                    continue
                sal_min = item.get("annualSalaryMin") or 0
                sal_max = item.get("annualSalaryMax") or 0
                salary_text = ""
                if sal_min and str(item.get("salaryCurrency", "")).upper() == "USD":
                    salary_text = format_salary_text(sal_min, sal_max)
                jobs.append(Job(
                    title=title,
                    company=item.get("companyName", ""),
                    location="Remote",
                    description=_clean_desc(item.get("jobDescription", ""))[:500],
                    url=url,
                    salary_text=salary_text,
                    posted=item.get("pubDate", ""),
                    source="Jobicy",
                ))
            time.sleep(1.5)
        except Exception as e:
            log(f"Error ({params.get('tag','?')}): {e}", source="Jobicy")
    log(f"{len(jobs)} results", source="Jobicy")
    return jobs
