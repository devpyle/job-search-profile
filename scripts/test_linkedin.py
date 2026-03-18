#!/usr/bin/env python3
"""Quick test — LinkedIn public guest API, remote + local area only."""

import os
import sys
import smtplib
from email.message import EmailMessage
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import HOME_CITY, HOME_STATE, HOME_METRO_TERMS, LI_REMOTE_QUERIES, LI_LOCAL_QUERIES

GMAIL_APP_PW = os.environ["GMAIL_APP_PW"]
EMAIL        = os.environ.get("GMAIL_TO", os.environ.get("GMAIL_FROM", ""))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

BASE_URL   = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
LOCAL_TERMS = set(HOME_METRO_TERMS) | {f", {HOME_STATE.lower()}"}


def fetch(keywords: str, remote: bool) -> list[dict]:
    params = {
        "keywords": keywords,
        "geoId":    "103644278",  # United States
        "f_TPR":    "r604800",    # last 7 days
        "start":    0,
    }
    if remote:
        params["f_WT"] = "2"
    r    = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=10)
    tag  = "remote" if remote else "local"
    print(f"  [{tag}] {keywords[:55]}: HTTP {r.status_code}")
    soup = BeautifulSoup(r.text, "html.parser")
    jobs = []
    for card in soup.find_all("li"):
        title_el   = card.find("h3")
        company_el = card.find("h4")
        loc_el     = card.find("span", class_=lambda c: c and "job-search-card__location" in c)
        link_el    = card.find("a", href=True)
        if title_el and company_el:
            jobs.append({
                "title":    title_el.text.strip(),
                "company":  company_el.text.strip(),
                "location": loc_el.text.strip() if loc_el else "",
                "url":      link_el["href"].split("?")[0] if link_el else "",
                "remote":   remote,
            })
    return jobs


def is_valid_location(job: dict) -> bool:
    loc = job["location"].lower()
    if job["remote"]:
        return "remote" in loc or loc in ("", "united states")
    return any(term in loc for term in LOCAL_TERMS)


def main():
    all_jobs = []

    print("Remote searches:")
    for q in LI_REMOTE_QUERIES:
        try:
            jobs = fetch(q, remote=True)
            print(f"    -> {len(jobs)} results")
            all_jobs.extend(jobs)
        except Exception as e:
            print(f"  Failed: {e}")

    print("Local searches:")
    for q in LI_LOCAL_QUERIES:
        try:
            jobs = fetch(q, remote=False)
            print(f"    -> {len(jobs)} results")
            all_jobs.extend(jobs)
        except Exception as e:
            print(f"  Failed: {e}")

    filtered = [j for j in all_jobs if is_valid_location(j)]
    print(f"\n{len(all_jobs)} total -> {len(filtered)} after location filter")

    seen, unique = set(), []
    for j in filtered:
        key = f"{j['title'].lower()}|{j['company'].lower()}"
        if key not in seen:
            seen.add(key)
            unique.append(j)
    print(f"{len(unique)} after dedup")

    remote_jobs = [j for j in unique if j["remote"]]
    local_jobs  = [j for j in unique if not j["remote"]]

    lines = [
        f"LinkedIn Test — {len(unique)} jobs",
        f"{len(remote_jobs)} remote | {len(local_jobs)} {HOME_CITY} area\n",
    ]
    if remote_jobs:
        lines.append("── REMOTE ──────────────────")
        for j in remote_jobs:
            lines += [f"🌐 {j['title']} — {j['company']}", f"   {j['location']}", f"   {j['url']}", ""]
    if local_jobs:
        lines.append(f"── {HOME_CITY.upper()} AREA ─────────────")
        for j in local_jobs:
            lines += [f"📍 {j['title']} — {j['company']}", f"   {j['location']}", f"   {j['url']}", ""]

    body = "\n".join(lines)
    msg  = EmailMessage()
    msg["Subject"] = f"LinkedIn Test — {len(remote_jobs)} remote | {len(local_jobs)} {HOME_CITY}"
    msg["From"]    = EMAIL
    msg["To"]      = EMAIL
    msg.set_content(body)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(EMAIL, GMAIL_APP_PW)
        smtp.send_message(msg)
    print("Email sent.")


if __name__ == "__main__":
    main()
