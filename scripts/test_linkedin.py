#!/usr/bin/env python3
"""Quick test — LinkedIn public guest API, remote + Raleigh area only."""

import os
import smtplib
from email.message import EmailMessage

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

# Remote-only searches — f_WT=2 restricts to remote work type
REMOTE_QUERIES = [
    "product owner API platform",
    "product manager middleware fintech",
    "platform product manager",
    "product owner digital banking",
]

# Raleigh-area searches — location baked into keywords, post-filtered to NC
RALEIGH_QUERIES = [
    "product owner Raleigh NC",
    "product manager Raleigh Durham RTP",
    "business analyst Raleigh NC",
    # Known RTP/Triangle companies with product roles
    'product owner "First Citizens" OR "Q2" OR "Red Hat" OR "SAS Institute" OR "Bandwidth" OR "Pendo"',
    'product manager "Fidelity" OR "MetLife" OR "Cisco" OR "IBM" OR "NetApp" OR "Lenovo" Raleigh',
]

# NC locations to keep in post-filter
NC_LOCATIONS = {
    "raleigh", "durham", "chapel hill", "cary", "morrisville", "apex",
    "holly springs", "wake forest", "research triangle", "rtp",
    ", nc", "north carolina",
}

BASE_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"


def fetch(keywords: str, remote: bool) -> list[dict]:
    params = {
        "keywords": keywords,
        "geoId": "103644278",  # United States
        "f_TPR": "r604800",    # last 7 days
        "start": 0,
    }
    if remote:
        params["f_WT"] = "2"   # remote work type only

    r = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=10)
    tag = "remote" if remote else "raleigh"
    print(f"  [{tag}] {keywords[:55]}: HTTP {r.status_code}")
    soup = BeautifulSoup(r.text, "html.parser")
    jobs = []
    for card in soup.find_all("li"):
        title_el = card.find("h3")
        company_el = card.find("h4")
        loc_el = card.find("span", class_=lambda c: c and "job-search-card__location" in c)
        link_el = card.find("a", href=True)
        if title_el and company_el:
            jobs.append({
                "title": title_el.text.strip(),
                "company": company_el.text.strip(),
                "location": loc_el.text.strip() if loc_el else "",
                "url": link_el["href"].split("?")[0] if link_el else "",
                "remote": remote,
            })
    return jobs


def is_valid_location(job: dict) -> bool:
    loc = job["location"].lower()
    if job["remote"]:
        return "remote" in loc or loc in ("", "united states")
    else:
        return any(area in loc for area in NC_LOCATIONS)


def main():
    all_jobs = []

    print("Remote searches:")
    for q in REMOTE_QUERIES:
        try:
            jobs = fetch(q, remote=True)
            print(f"    -> {len(jobs)} results")
            all_jobs.extend(jobs)
        except Exception as e:
            print(f"  Failed: {e}")

    print("Raleigh searches:")
    for q in RALEIGH_QUERIES:
        try:
            jobs = fetch(q, remote=False)
            print(f"    -> {len(jobs)} results")
            all_jobs.extend(jobs)
        except Exception as e:
            print(f"  Failed: {e}")

    # Location filter
    filtered = [j for j in all_jobs if is_valid_location(j)]
    print(f"\n{len(all_jobs)} total -> {len(filtered)} after location filter")

    # Deduplicate
    seen = set()
    unique = []
    for j in filtered:
        key = f"{j['title'].lower()}|{j['company'].lower()}"
        if key not in seen:
            seen.add(key)
            unique.append(j)
    print(f"{len(unique)} after dedup")

    # Build email
    remote_jobs = [j for j in unique if j["remote"]]
    local_jobs = [j for j in unique if not j["remote"]]

    lines = [
        f"LinkedIn Test — {len(unique)} jobs",
        f"{len(remote_jobs)} remote | {len(local_jobs)} Raleigh area\n",
    ]

    if remote_jobs:
        lines.append("── REMOTE ──────────────────")
        for j in remote_jobs:
            lines.append(f"🌐 {j['title']} — {j['company']}")
            if j["location"]:
                lines.append(f"   {j['location']}")
            lines.append(f"   {j['url']}")
            lines.append("")

    if local_jobs:
        lines.append("── RALEIGH AREA ─────────────")
        for j in local_jobs:
            lines.append(f"📍 {j['title']} — {j['company']}")
            if j["location"]:
                lines.append(f"   {j['location']}")
            lines.append(f"   {j['url']}")
            lines.append("")

    body = "\n".join(lines)

    msg = EmailMessage()
    msg["Subject"] = f"LinkedIn Test — {len(remote_jobs)} remote | {len(local_jobs)} Raleigh"
    msg["From"] = "your@email.com"
    msg["To"] = "your@email.com"
    msg.set_content(body)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login("your@email.com", os.environ["GMAIL_APP_PW"])
        smtp.send_message(msg)
    print("Email sent.")


if __name__ == "__main__":
    main()
