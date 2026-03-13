#!/usr/bin/env python3
"""Adzuna job search MCP server for David's job radar."""

import os
import requests
from dotenv import load_dotenv
from fastmcp import FastMCP

load_dotenv()

APP_ID = os.environ["ADZUNA_APP_ID"]
APP_KEY = os.environ["ADZUNA_APP_KEY"]
BASE_URL = "https://api.adzuna.com/v1/api/jobs/us/search/1"

mcp = FastMCP("adzuna-jobs")


@mcp.tool()
def search_jobs(
    what: str,
    where: str = "remote",
    max_days_old: int = 7,
    sort_by: str = "date",
    full_time: bool = True,
    results_per_page: int = 20,
) -> list[dict]:
    """Search Adzuna for US job postings.

    Args:
        what: Job title / keywords (e.g. "product owner API platform")
        where: Location string (e.g. "remote", "Raleigh NC")
        max_days_old: Only return jobs posted within this many days
        sort_by: Sort order — "date" or "salary"
        full_time: If True, restrict to full-time roles
        results_per_page: Number of results to return (max 50)
    """
    params = {
        "app_id": APP_ID,
        "app_key": APP_KEY,
        "what": what,
        "where": where,
        "max_days_old": max_days_old,
        "sort_by": sort_by,
        "results_per_page": results_per_page,
        "content-type": "application/json",
    }
    if full_time:
        params["full_time"] = 1

    response = requests.get(BASE_URL, params=params, timeout=10)
    response.raise_for_status()
    data = response.json()

    jobs = []
    for job in data.get("results", []):
        jobs.append({
            "title": job.get("title"),
            "company": job.get("company", {}).get("display_name"),
            "location": job.get("location", {}).get("display_name"),
            "description": job.get("description"),
            "salary_min": job.get("salary_min"),
            "salary_max": job.get("salary_max"),
            "created": job.get("created"),
            "url": job.get("redirect_url"),
        })
    return jobs


if __name__ == "__main__":
    mcp.run()
