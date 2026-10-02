"""Tavily web search API source."""

import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import requests

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from config import TAVILY_QUERIES  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent.parent))
from models import Job  # noqa: E402
from normalize import _clean_desc  # noqa: E402
from log import log  # noqa: E402
from sources.web_results import normalize_web_job  # noqa: E402

TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")

DOMAIN_COMPANY_MAP: dict[str, str] = {
    "fisglobal":        "FIS",
    "fisv":             "Fiserv",
    "fiserv":           "Fiserv",
    "jpmorgan":         "JPMorgan Chase",
    "jpmorganchase":    "JPMorgan Chase",
    "goldmansachs":     "Goldman Sachs",
    "morganstanley":    "Morgan Stanley",
    "bankofamerica":    "Bank of America",
    "wellsfargo":       "Wells Fargo",
    "citigroup":        "Citi",
    "citi.com":         "Citi",
    "usbank":           "U.S. Bank",
    "pnc.com":          "PNC",
    "capitalone":       "Capital One",
    "americanexpress":  "American Express",
    "discover":         "Discover",
    "synchrony":        "Synchrony",
    "broadridge":       "Broadridge",
    "dtcc.com":         "DTCC",
    "intercontinentalexchange": "ICE",
    "ice.com":          "ICE",
    "nasdaq.com":       "Nasdaq",
    "bloomberg":        "Bloomberg",
    "factset":          "FactSet",
    "morningstar":      "Morningstar",
    "blackrock":        "BlackRock",
    "vanguard":         "Vanguard",
    "fidelity":         "Fidelity",
    "schwab":           "Charles Schwab",
    "stripe.com":       "Stripe",
    "plaid.com":        "Plaid",
    "brex.com":         "Brex",
    "marqeta":          "Marqeta",
    "adyen":            "Adyen",
    "paypal":           "PayPal",
    "square":           "Block (Square)",
    "intuit":           "Intuit",
    "salesforce":       "Salesforce",
    "servicenow":       "ServiceNow",
    "workday":          "Workday",
    "oracle":           "Oracle",
    "sap.com":          "SAP",
    "ibm.com":          "IBM",
    "microsoft":        "Microsoft",
    "amazon":           "Amazon",
    "google":           "Google",
}


def _company_from_url(url: str) -> str:
    """Best-effort company name extraction from a job URL."""
    if not url:
        return ""
    url_lower = url.lower()
    # Workday hosts look like <tenant>.wd5.myworkdayjobs.com; the tenant is
    # the employer (falling through to the map would match "workday" itself).
    wd = re.match(r"https?://([^.]+)\.(?:wd\d+\.)?myworkdayjobs\.com", url_lower)
    if wd:
        slug = wd.group(1)
        for key, name in DOMAIN_COMPANY_MAP.items():
            if key in slug:
                return name
        return slug.replace("-", " ").title()
    host = urlparse(url_lower).netloc
    for key, name in DOMAIN_COMPANY_MAP.items():
        # Keys with a dot are domains: match on a label boundary so
        # "ice.com" doesn't match "dice.com". Bare keys match anywhere in host.
        if "." in key:
            if host == key or host.endswith("." + key):
                return name
        elif key in host:
            return name
    return ""


def search_tavily() -> list[Job]:
    queries = TAVILY_QUERIES
    jobs = []
    for q in queries:
        try:
            r = requests.post(
                "https://api.tavily.com/search",
                json={"api_key": TAVILY_API_KEY, "query": q, "search_depth": "basic", "max_results": 8},
                timeout=15,
            )
            r.raise_for_status()
            for item in r.json().get("results", []):
                job = Job(
                    title=item.get("title", ""),
                    description=_clean_desc(item.get("content", "")),
                    url=item.get("url", ""),
                    source="Tavily",
                )
                if normalize_web_job(job, _company_from_url):
                    jobs.append(job)
        except Exception as e:
            log(f"Query failed ({q[:50]}): {e}", source="Tavily")
    return jobs
