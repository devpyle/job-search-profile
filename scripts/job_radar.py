#!/usr/bin/env python3
"""Job radar — queries Adzuna, Brave, Tavily, LinkedIn, Remotive, WeWorkRemotely,
Himalayas, Jobicy, RemoteOK, JSearch, and ATS-direct. Saves a dated report, emails the .md.

Usage:
  Scheduled (cron):  python3 job_radar.py
  Manual test run:   python3 job_radar.py --run
"""

import html
import json
import os
import re
import sys
import time
import smtplib
import threading
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Optional

import anthropic
import requests
from dotenv import load_dotenv

load_dotenv()

# ── SECRETS (from .env) ────────────────────────────────────────────────────────
ADZUNA_APP_ID     = os.environ["ADZUNA_APP_ID"]
ADZUNA_APP_KEY    = os.environ["ADZUNA_APP_KEY"]
BRAVE_API_KEY     = os.environ["BRAVE_API_KEY"]
TAVILY_API_KEY    = os.environ["TAVILY_API_KEY"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
GMAIL_APP_PW      = os.environ["GMAIL_APP_PW"]
JSEARCH_API_KEY   = os.environ.get("JSEARCH_API_KEY", "")
EMAIL             = os.environ.get("GMAIL_TO", os.environ.get("GMAIL_FROM", ""))

# ── PERSONAL CONFIG (from config.py) ──────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import (  # noqa: E402
    CANDIDATE_BACKGROUND, APPLY_NOW_DESCRIPTION,
    HOME_CITY, HOME_STATE, HOME_METRO_TERMS, MIN_SALARY,
    ADZUNA_QUERIES, BRAVE_QUERIES, TAVILY_QUERIES,
    LI_REMOTE_QUERIES, LI_LOCAL_QUERIES,
    JSEARCH_REMOTE_QUERIES, JSEARCH_LOCAL_QUERIES,
)

claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

REPO_ROOT        = Path(__file__).parent.parent
OUTPUT_DIR       = REPO_ROOT / "output" / "job-radar"
SEEN_FILE        = OUTPUT_DIR / ".seen.json"
DEBUG_LOG_FILE   = OUTPUT_DIR / "debug_job_log.txt"  # overwritten each run; upload to Claude to verify
SEEN_EXPIRY_DAYS = 60

_print_lock = threading.Lock()  # prevents interleaved output from parallel rating workers

# Suffixes to strip when normalizing titles for dedup
_TITLE_CLEANUP_RE = re.compile(
    r"\s*[-–|]\s*(remote|remote,?\s*(us|usa)?|hybrid|onsite|on-site"
    r"|united states?|us|usa|\w{2,3},\s*\w{2})\s*$",
    re.IGNORECASE,
)

TIER_ORDER = {"Apply Now": 0, "Worth a Look": 1, "Weak Match": 2, "Skip": 3}


def _clean_desc(text: str) -> str:
    """Strip HTML tags, unescape entities, collapse whitespace."""
    if not text:
        return ""
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:5000]


@dataclass
class Job:
    title: str
    company: str = ""
    location: str = ""
    description: str = ""
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    url: str = ""
    posted: str = ""
    source: str = ""
    tier: str = ""
    reason: str = ""
    salary_text: str = ""  # salary string when not in structured min/max fields

    def dedup_key(self) -> str:
        normalized = _TITLE_CLEANUP_RE.sub("", self.title).lower().strip()
        if self.company:
            return f"{normalized}|{self.company.lower().strip()}"
        return self.url

    def salary_str(self) -> str:
        # Guard: salary_min must be > 30,000 to be a real salary.
        # Some ATS responses return tiny values (e.g. salary_min=2 from "$2B ARR mention").
        sal_min = self.salary_min if (self.salary_min and self.salary_min > 30_000) else None
        sal_max = self.salary_max if (self.salary_max and self.salary_max > 30_000) else None
        if sal_min and sal_max:
            return f"${sal_min:,.0f}–${sal_max:,.0f}"
        if sal_min:
            return f"${sal_min:,.0f}+"
        if self.salary_text:
            return self.salary_text
        return "Not listed"


# ── CATEGORY / NOISE FILTERS ──────────────────────────────────────────────────

CATEGORY_URL_FRAGMENTS = [
    "glassdoor.com/Job/", "indeed.com/q-", "indeed.com/jobs",
    "linkedin.com/jobs/search", "linkedin.com/jobs/api-", "linkedin.com/jobs/product-",
    "linkedin.com/jobs/collections/",
    "ziprecruiter.com/Jobs/", "jobgether.com/remote-jobs/",
    "remoterocketship.com/jobs/", "remoterocketship.com/us/jobs/",
    "remotive.com/remote-jobs/", "wellfound.com/jobs", "builtin",
    "flexjobs.com/jobs", "workingnomads.com/jobs", "getwork.com/jobs",
    "careerjet.com", "simplyhired.com/search", "jobgether.com/en/",
    "dailyremote.com/remote-", "beamjobs.com", "resumeworded.com",
    "zety.com", "kickresume.com", "remotebob.io",
    "wikipedia.org", "monster.com/jobs", "dice.com/jobs",
    "arc.dev/remote-jobs", "fractional.jobs", "crossover.com",
    "lensa.com", "ladders.com/jobs", "visasponsorshipjobs", "jobbank.gc.ca",
    "hiring.cafe/jobs/", "remoteok.com/remote-", "roberthalf.com",
    "weworkremotely.com/categories/", "ratracerebellion.com", "jaabz.com",
    "remotefront.com/remote-jobs/", "careervault.io", "jooble.org",
    "totaljobs.com", "reed.co.uk", "cv-library.co.uk", "jobs.ac.uk", "jobsite.co.uk",
    "wuaze.com", "wixsite.com", "weebly.com", "wordpress.com",
    "blogspot.com", "sites.google.com",
]

NON_JOB_TITLE_RE = re.compile(
    r"resume (samples?|templates?|examples?|guide)|"
    r"(cost|price|pricing)\s+(breakdown|guide|in \d{4})|"
    r"how to (write|build|create)|"
    r"(top|best)\s+\d+\s+(tools?|skills?|tips?|ways?)",
    re.IGNORECASE,
)

CATEGORY_TITLE_RE = re.compile(
    r"\d[\d,+]+\s+\w.*jobs?\s+(in|for|at)\b"
    r"|^(browse|search(\s+the\s+best)?)\s+"
    r"|jobs?\s+in\s+(remote|united states|us)\b"
    r"|(top|best)\s+remote\s+\w.*jobs?\s+(in|from)\b"
    r"|^\d[\d,+]+\s+(remote|open)\s+\w+\s+jobs?\b"
    r"|today.s top \d"
    r"|resume (samples?|templates?|examples?|guide)"
    r"|how to (write|build|create|hire|find|get)"
    r"|(top|best)\s+\d+\s+(tools?|skills?|tips?|ways?|sites?)"
    r"|work.?from.?home\s+(jobs?|board|hub)"
    r"|remote\s+\w[\w\s]+jobs?\s+in\s+\w"
    r"|\w[\w\s]+jobs?\s+in\s+(north america|united states|the us|latin america|europe|canada)\b"
    r"|^remote\s+jobs?\s*[-–|]"
    r"|^now hiring:"
    r"|\bwikipedia\b"
    r"|\bsalary\b.*(guide|report|data|range)"
    r"|(list of|roundup|compilation).*(jobs?|roles?)",
    re.IGNORECASE,
)

_EXPIRED_RE = re.compile(
    r"no longer (accepting|available|active|taking)"
    r"|position (has been|is) (filled|closed)"
    r"|this (job|position|role) (has|is) (expired|closed|filled|no longer)"
    r"|job (has expired|is no longer|has been filled)"
    r"|applications? (are |is )?(now |currently )?(closed|no longer being accepted)"
    r"|posting (has|is) (expired|closed|been removed)"
    r"|we('re| are) (no longer|not) accepting"
    r"|thank you for your interest.*no longer"
    r"|this (listing|posting|requisition) (is|has been) (closed|removed|filled|expired)"
    r"|role has been filled|search has been closed"
    r"|not currently hiring|deadline (has passed|was|is past)",
    re.IGNORECASE,
)

_WRONG_TITLE_RE = re.compile(
    r"^head of product\b"                        # usually people management
    r"|\bdata analyst\b"                         # wrong function
    r"|\b(sales|marketing) (manager|director|executive|rep|consultant|account)\b"
    r"|\bcustomer (service|success|care) (rep|representative|specialist|associate|coordinator|manager|operations)\b"
    r"|\bcustomer experience (associate|representative|specialist|rep|coordinator)\b"  # CX support roles
    r"|\bclient success\b"                       # wrong function
    r"|\b(backend|frontend|software|engineering) (manager|lead|director)\b"
    r"|^project manager\b"                       # project manager at start (not "product")
    r"|\belectrical products\b"                  # engineering products, not PM
    r"|supply chain\b"
    r"|entry.?level\b"
    r"|\bbusiness owner\b"                       # franchise/business ownership listings
    r"|\b(coordinator|negotiator|recruiter)\b"   # wrong level/function
    r"|\b(games?|gaming|esports) (product|title|portfolio|manager)\b"  # gaming PM
    r"|\breal estate\b"                          # wrong domain
    r"|\bsecurity (manager|guard|officer)\b"     # wrong function
    r"|\btalent acquisition\b"                   # HR/recruiting roles
    r"|\bcommand center\b"                       # IT ops roles
    r"|\bsupport engineer\b"                     # engineering support roles
    r"|\bbilling success manager\b"              # customer success/billing ops
    r"|\bsenior independent\b"                   # A.Team freelance listings
    r"|\baccount executive\b"                    # sales roles
    r"|\bsales (lead|executive|manager|rep|representative|development)\b"
    r"|\b(sdr|bdr|account executive|sales development)\b"
    r"|\bproduct designer\b"                     # UX/design roles (not PM)
    r"|\bproduct design(er)?\b"                  # design track
    r"|\bproduct marketing\b"                    # marketing, not PM
    r"|\bproduct security engineer\b"            # security engineering
    r"|\bcustomer success manager\b"             # CSM roles (not PM/PO/BA)
    r"|\blife underwriter\b"                     # insurance underwriting
    r"|\bimplementation specialist\b"            # implementation ops
    r"|\bcontact center rep\b"                   # contact center staffing
    r"|\bvacation specialist\b"                  # travel staffing
    r"|\bai trainer\b"                           # freelance AI training
    r"|\b(junior|associate) client partner\b"    # junior sales at consulting firms
    r"|\bqa analyst\b"                           # quality assurance
    r"|\bindependent operator\b"                 # AtWork Group franchise listings
    r"|\bsmb owner\b"                            # SMB ownership listings
    r"|\bregional sales lead\b"                  # sales leadership
    r"|\bkey account manager\b"                  # sales
    r"|\bpartnership sales manager\b"            # sales
    r"|\benterprise (billing|sales) (success|executive)\b"
    r"|\bdirector.*talent acquisition\b"         # recruiting leadership
    r"|\bsenior account executive\b"             # sales
    r"|\bsenior client delivery\b"               # delivery/ops
    r"|\bclinical product lead\b.*temp\b"        # temp clinical roles requiring clinical degree
    r"|\bmanagement consultant\b"                # consulting placement
    r"|\bcustomer service representative\b"      # explicitly spell out - slips through shorter pattern
    r"|\bbusiness development representative\b"  # BDR/sales dev roles
    r"|^entrepreneur\b"                          # AtWork Group bizdev listings (title-start only)
    r"|\bengineering manager\b"                  # eng people management (not PM)
    r"|\bdigital marketing\b"                    # marketing function (not PM)
    r"|\bfranchise\b"                            # franchise/bizdev listings
    r"|program manager,?\s+sales\b"              # sales engineering program mgr (Samsara pattern)
    r"|\bbusiness consultant\b"                  # consulting placement
    r"|\bteam lead.*command\b"                   # IT ops
    r"|\bpatient.specific instrument\b",         # medical device manufacturing
    re.IGNORECASE,
)

_NON_US_RE = re.compile(
    # UK
    r"\b(london|manchester|birmingham|edinburgh|glasgow|leeds|bristol|liverpool|sheffield|cambridge|oxford)\b"
    r"|\bunited kingdom\b|\buk\b(?! based remote)|\bengland\b|\bscotland\b|\bwales\b|\bnorthern ireland\b"
    # Canada
    r"|\b(toronto|vancouver|montreal|ottawa|calgary|edmonton|winnipeg)\b|\bcanada\b"
    # Australia / NZ
    r"|\b(sydney|melbourne|brisbane|perth|adelaide|auckland|wellington)\b|\baustralia\b|\bnew zealand\b"
    # Western Europe
    r"|\b(berlin|munich|hamburg|frankfurt|cologne|amsterdam|rotterdam|paris|lyon|madrid|barcelona|rome|milan|zurich|vienna|brussels|stockholm|oslo|copenhagen|helsinki|dublin)\b"
    # Baltic / Eastern Europe
    r"|\b(tallinn|riga|vilnius|warsaw|prague|budapest|bucharest|sofia|zagreb|bratislava)\b"
    r"|\bestonia\b|\blatvia\b|\blithuania\b|\bpoland\b|\bczech\b|\bhungary\b|\bromania\b"
    # Nordic
    r"|\bsweden\b|\bnorway\b|\bdenmark\b|\bfinland\b|\biceland\b"
    # Asia
    r"|\b(singapore|hong kong|shanghai|beijing|tokyo|seoul|bangalore|mumbai|new delhi|hyderabad)\b"
    r"|\bindia\b|\bjapan\b|\bsouth korea\b|\bchina\b"
    # Middle East (Melio, Lemonade, Payoneer have TLV offices)
    r"|\b(tel aviv|tlv|herzliya|haifa|jerusalem)\b|\bisrael\b"
    # Latin America (Adyen LATAM, Nubank)
    r"|\b(são paulo|sao paulo|rio de janeiro|bogota|mexico city|ciudad de mexico|buenos aires|santiago|lima)\b"
    r"|\bbrazil\b|\bmexico\b(?! remote)|\bcolombia\b|\bargentina\b|\bchile\b|\bperu\b"
    # Southern Europe (Complyadvantage Lisbon, Securitize Spain)
    r"|\b(lisbon|porto|seville)\b|\bportugal\b|\bspain\b"
    # Region labels used by EU job boards (Deel, Lemonade EU)
    r"|^emea$|\bemea\b|^eu$|^europe$|\beurope\b(?! remote)",
    re.IGNORECASE,
)

_URL_CITY_RE = re.compile(
    r"new[-_]york|new%20york|san[-_]francisco|san%20francisco|los[-_]angeles|los%20angeles"
    r"|chicago|boston|seattle|austin|atlanta|denver|minneapolis|philadelphia"
    r"|phoenix|houston|dallas|miami|washington[-_]dc|washington%20dc"
    r"|jersey[-_]city|jersey%20city|hoboken|stamford"
    r"|charlotte(?!sville)|new[-_]jersey|new%20jersey|connecticut"
    r"|london|manchester|birmingham|berlin|munich|amsterdam|paris"
    r"|madrid|barcelona|rome|milan|zurich|vienna|brussels|stockholm|oslo|copenhagen"
    r"|tallinn|riga|vilnius|warsaw|prague|budapest|bucharest"
    r"|toronto|vancouver|montreal|sydney|melbourne",
    re.IGNORECASE,
)

# Regex to detect non-Raleigh US cities in the job's location FIELD (not URL).
# ATS URLs (greenhouse.io/sofi/jobs/123) have no city slugs so _URL_CITY_RE misses them.
# The location field is the reliable source for ATS jobs — check it directly.
# Only triggers when remote is NOT in the location string.
_LOC_CITY_RE = re.compile(
    # Bay Area
    r"\b(san francisco|menlo park|palo alto|san jose|mountain view|sunnyvale|redwood city)\b"
    # NYC / NJ
    r"|\b(new york|new york city|manhattan|brooklyn|jersey city|hoboken|stamford)\b"
    # Seattle area
    r"|\b(seattle|bellevue|kirkland|redmond)\b"
    # Other major non-Raleigh US metros
    r"|\bchicago\b"
    r"|\bboston\b"
    r"|\b(los angeles|west hollywood|santa monica|culver city)\b"
    r"|\b(dallas|fort worth|frisco)\b"
    r"|\b(denver|boulder)\b"
    r"|\bmiami\b"
    r"|\batlanta\b"
    r"|\baustin\b"
    r"|\b(nashville|memphis)\b"
    r"|\bcharlotte\b(?! st)"  # Charlotte NC — not Raleigh metro (~3h away)
    r"|\b(salt lake city|cottonwood heights)\b"
    r"|\bphoenix\b"
    r"|\bhouston\b"
    r"|\bminneapolis\b"
    r"|\bphiladelphia\b"
    r"|\b(washington dc|washington, dc)\b"
    r"|\b(st louis|saint louis|kansas city)\b"
    # State abbreviation + dash convention (e.g. "CA - San Francisco", "WA - Seattle")
    r"|\b(ca|wa|ny|il|ma|tx|co|ga|fl|az|ut|or|mn|pa|tn)\s*-"
    r"|\bcalifornia\b|\b(washington state|washington, wa)\b",
    re.IGNORECASE,
)

LI_NC_LOCATIONS = {
    "raleigh", "durham", "chapel hill", "cary", "morrisville", "apex",
    "holly springs", "wake forest", "research triangle", "rtp",
    ", nc", "north carolina",
}

# Requires salary context words OR explicit annual qualifier to avoid grabbing
# financial metrics like "$257B ARR" or "$100M raised" as salary hints.
_SALARY_CONTEXT_RE = re.compile(
    r'(salary|compensation|base pay|total pay|pay range|annual pay|base salary'
    r'|earn|total comp|tc|starting at|up to|range of)'
    r'[^$]{0,80}\$\s*(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*[kK]?'
    r'|\$\s*(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*[kK]?[^$\w]{0,5}'
    r'(?:[-to]+\s*\$?\s*(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*[kK]?)?'
    r'[^\w]{0,30}(?:per year|annually|\/yr|\/year|USD|usd)'
    r'|\b(\d{1,3}(?:,\d{3})+)\s*(?:[-to]+\s*(\d{1,3}(?:,\d{3})+))?'
    r'\s*(?:per year|annually|\/yr|\/year)',
    re.IGNORECASE,
)


def is_category_page(title: str, url: str, description: str = "") -> bool:
    if any(frag in url for frag in CATEGORY_URL_FRAGMENTS):
        return True
    if CATEGORY_TITLE_RE.search(title) or NON_JOB_TITLE_RE.search(title):
        return True
    if _EXPIRED_RE.search(title) or (description and _EXPIRED_RE.search(description[:500])):
        return True
    return False


def is_non_us_location(job: "Job") -> bool:
    if _NON_US_RE.search(job.location):
        return True
    if job.description and _NON_US_RE.search(job.description):
        return True
    return False


def is_onsite_non_local(job: "Job") -> bool:
    """
    Returns True if the job requires on-site attendance at a non-Raleigh location.

    Two detection paths:
      1. URL-based: URL contains a city slug (LinkedIn, Brave, Tavily job links)
      2. Location-field: location field contains a non-Raleigh city (ATS jobs;
         Greenhouse/Lever/Ashby URLs have no city slugs, so URL check alone misses them)

    Remote signals in the location string override the filter so that postings
    like "San Francisco or Remote" still pass through.
    """
    remote_signals = ("remote", "work from home", "wfh", "distributed", "virtual")
    # Phrases that confirm required in-office attendance — override remote signals
    onsite_signals = (
        "come into our office",
        "expected to come into",
        "required to be in office",
        "required to be in the office",
        "in-office",
        "onsite required",
        "on-site required",
    )
    loc = job.location.lower()
    desc_intro = job.description[:800].lower() if job.description else ""

    # ── Path 1: URL-based city detection (LinkedIn / Brave / Tavily) ──────────
    if job.url and _URL_CITY_RE.search(job.url):
        if any(s in job.title.lower() for s in remote_signals):
            return False
        if any(s in loc for s in remote_signals):
            return False
        if any(s in desc_intro for s in remote_signals):
            # Even if "remote" appears, explicit office-required language overrides it
            if any(s in desc_intro for s in onsite_signals):
                return True
            return False
        return True

    # ── Path 2: Location-field city detection (ATS jobs) ─────────────────────
    if _LOC_CITY_RE.search(loc):
        # Keep if remote appears in the location field itself
        # e.g. "San Francisco or Remote", "Remote - San Francisco"
        if any(s in loc for s in remote_signals):
            return False
        # Some ATS postings list the office city in location but say "fully remote"
        # in the description body. Check only first 800 chars (intro section).
        if any(s in desc_intro for s in remote_signals):
            # Even if "remote" appears, explicit office-required language overrides it
            if any(s in desc_intro for s in onsite_signals):
                return True
            return False
        return True

    return False


def is_bad_scrape(job: "Job") -> bool:
    desc = (job.description or "").strip()
    if not desc:
        return False
    if desc.startswith("{") or desc.startswith("["):
        return True
    if desc.count("var(--") >= 2 or desc.count('"theme') >= 2:
        return True
    if desc.count("<") > 10 and len(re.sub(r"<[^>]+>", "", desc)) < len(desc) * 0.3:
        return True
    return False


def is_local_raleigh(job: "Job") -> bool:
    loc = job.location.lower()
    return any(area in loc for area in LI_NC_LOCATIONS)


STAFFING_KEYWORDS = [
    "staffing", "recruiting", "recruiter", "talent solutions", "search group",
    "placement", "manpower", "robert half", "adecco", "kelly services",
    "randstad", "insight global", "apex systems", "our client", "on behalf of",
]

# Companies confirmed to be non-US / wrong fit — add as you find them.
BLOCKED_COMPANIES: set[str] = {
    "eeze",
}

# Maps URL domain keywords → display company name for Tavily results (no company field).
# Key = substring that appears in the job URL (lowercase). First match wins.
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

# MIN_SALARY imported from config.py


def is_staffing(title: str, company: str, description: str) -> bool:
    combined = f"{title} {company} {description}".lower()
    return any(kw in combined for kw in STAFFING_KEYWORDS)


def _parse_salary_string(s: str) -> int:
    """Convert salary strings like '$120K', '$120,000' to int lower bound.
    Returns 0 (pass through) for hourly/weekly/monthly rates or unparseable values."""
    if not s:
        return 0
    s_lower = str(s).lower().replace(",", "")
    if re.search(r"/\s*(hour|hr|week|wk|month|mo)", s_lower):
        return 0  # not annual — pass through rather than misinterpret
    m = re.search(r"\$?\s*(\d+(?:\.\d+)?)\s*k?", s_lower)
    if not m:
        return 0
    raw = m.group(1)
    if re.fullmatch(r"(19|20)\d\d", raw.strip()):
        return 0  # looks like a year
    val = float(raw)
    if "k" in s_lower[m.start():m.end() + 2]:
        val *= 1000
    return int(val)


def _is_plausible_salary(raw_str: str) -> bool:
    """Return True only if the dollar amount looks like an annual salary (not a valuation/ARR)."""
    nums = re.findall(r"[\d,]+", raw_str.replace("$", ""))
    if not nums:
        return False
    try:
        val = int(nums[0].replace(",", ""))
        if "k" in raw_str.lower():
            val *= 1000
    except ValueError:
        return False
    return 40_000 <= val <= 500_000


def is_below_salary_floor(job: "Job") -> bool:
    """Drop only when salary IS listed AND the entire range is confirmed below floor.

    Bug fix: original code checked salary_min for the floor. For a range like
    $140K-$180K this gave sal=140K and dropped the job even though $150K (floor)
    falls within the range. Correct logic: if salary_max is set, use that — only
    drop when the TOP of the range is below the floor. If only salary_min (no max),
    pass through — a single low min may just be the base of an unlisted range.
    """
    sal_min = job.salary_min or 0
    sal_max = job.salary_max or 0

    # Both min and max present — use MAX to determine if range reaches the floor
    if sal_min > 0 and sal_max > 0:
        return sal_max < MIN_SALARY

    # Only max (no min) — check max directly
    if sal_max > 0:
        return sal_max < MIN_SALARY

    # Only min (no max posted) — cannot confirm the ceiling, pass through
    if sal_min > 0:
        return False

    # Fall back to string salary field (Himalayas, RemoteOK, Remotive)
    if job.salary_text:
        sal = _parse_salary_string(job.salary_text)
        if sal > 0:
            return sal < MIN_SALARY

    return False  # no salary info — let it through


def is_closed_listing(description: str) -> bool:
    return bool(description and _EXPIRED_RE.search(description))


def is_wrong_title(title: str) -> bool:
    return bool(_WRONG_TITLE_RE.search(title))


def is_broken_url(url: str) -> bool:
    if not url:
        return False
    try:
        r = requests.head(url, timeout=5, allow_redirects=True,
                          headers={"User-Agent": "Mozilla/5.0"})
        return r.status_code >= 400
    except Exception:
        return False


def extract_salary_from_text(text: str) -> Optional[str]:
    """Scan description text for a salary range. Requires salary context words or
    explicit annual qualifier to avoid grabbing financial metrics as salary hints."""
    if not text:
        return None
    for m in _SALARY_CONTEXT_RE.finditer(text):
        raw = m.group(0).strip()
        if re.fullmatch(r"\d{4,5}", raw.replace(",", "").replace("$", "").strip()):
            continue
        if _is_plausible_salary(raw):
            return raw
    return None


# ── CLAUDE RATING ─────────────────────────────────────────────────────────────

RATING_PROMPT = f"""\
You are a job-fit rater.

Candidate background:
{CANDIDATE_BACKGROUND}

Rate this job with one of these tiers:
- "Apply Now" — {APPLY_NOW_DESCRIPTION}
- "Worth a Look" — good fit: product role related to their background, worth reviewing
- "Weak Match" — marginal: product-adjacent or BA role, not a priority
- "Skip" — poor fit: irrelevant role, non-US location (e.g. Europe, Canada, Asia), onsite/hybrid outside {HOME_CITY} {HOME_STATE} (e.g. onsite in New York, Chicago, San Francisco), or clearly below salary floor

CRITICAL RATING RULES — these override everything else:
1. Missing salary is NEVER a reason to Skip or downgrade. Rate on title and domain fit alone.
2. Missing or unclear location/remote status is NEVER a reason to Skip or downgrade.
3. A short or incomplete description is NEVER a reason to Skip. If the title fits and no hard disqualifier is confirmed, rate Worth a Look or higher.
4. "Cannot assess" is NOT a valid Skip reason. When in doubt, rate Worth a Look.
5. Only Skip when a hard disqualifier is CONFIRMED — not merely suspected.

Return ONLY a JSON object with these keys:
{{
  "tier": "<one of the four tiers above>",
  "reason": "<one sentence explaining the rating>",
  "salary": "<extracted salary range from description, or empty string if none found>"
}}

Job:
Title: {title}
Company: {company}
Location: {location}
Salary: {salary}
Description: {description}
"""


def rate_with_claude(job: Job) -> tuple[str, str, str]:
    salary = job.salary_str() if (job.salary_min or job.salary_max) else ""
    desc = job.description[:4000] if job.description else "(no description)"

    # Pre-extract salary from description as a hint
    salary_hint = ""
    if not salary:
        pre_salary = extract_salary_from_text(job.description or "")
        if pre_salary:
            salary_hint = f"\nSalary found in description: {pre_salary}"

    prompt = RATING_PROMPT.format(
        title=job.title,
        company=job.company or "(unknown)",
        location=job.location or "(unknown)",
        salary=(salary or "(not listed)") + salary_hint,
        description=desc,
    )

    # Exponential backoff retry on rate limits (15s → 30s → 60s → 120s)
    max_retries = 4
    for attempt in range(max_retries):
        try:
            response = claude.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=400,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text.strip()
            raw = raw.replace("```json", "").replace("```", "").strip()
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                data = json.loads(match.group())
                tier = data.get("tier", "Worth a Look")
                if tier not in TIER_ORDER:
                    tier = "Worth a Look"
                # Validate Claude's extracted salary — it sometimes grabs company
                # financial metrics ("$257B ARR", "$100M raised") as salary values.
                raw_salary = data.get("salary") or ""
                if raw_salary and not _is_plausible_salary(str(raw_salary)):
                    raw_salary = ""
                return tier, data.get("reason", ""), raw_salary
        except anthropic.RateLimitError:
            wait = 15 * (2 ** attempt)  # 15s, 30s, 60s, 120s
            with _print_lock:
                print(f"  Rate limit (attempt {attempt+1}/{max_retries}) — waiting {wait}s...")
            time.sleep(wait)
        except Exception as e:
            with _print_lock:
                print(f"  Claude rating failed for '{job.title}': {e}")
            break
    return "Worth a Look", "Rating unavailable", ""


# ── SEEN FILE ─────────────────────────────────────────────────────────────────

def load_seen() -> dict:
    today_str = date.today().isoformat()
    if not SEEN_FILE.exists():
        return {}
    raw = json.loads(SEEN_FILE.read_text())
    if isinstance(raw, list):
        print(f"  Migrating .seen.json to timestamped format ({len(raw)} entries)")
        seen = {k: today_str for k in raw}
    else:
        seen = raw
    cutoff = (date.today() - timedelta(days=SEEN_EXPIRY_DAYS)).isoformat()
    before = len(seen)
    seen = {k: v for k, v in seen.items() if v >= cutoff}
    expired = before - len(seen)
    if expired:
        print(f"  Expired {expired} seen entries older than {SEEN_EXPIRY_DAYS} days")
    return seen


def save_seen(seen: dict):
    SEEN_FILE.write_text(json.dumps(seen, indent=2, sort_keys=True))


# ── MULTI-KEY DEDUPLICATION ───────────────────────────────────────────────────

def normalize_title(title: str) -> str:
    """Strips trailing location/remote noise so 'Senior PO (Remote)' and
    'Senior PO - Remote, US' map to the same key, but 'Senior PO - Payments'
    and 'Senior PO - Lending' remain distinct."""
    t = title.lower().strip()
    location_words = {"remote", "us", "usa", "united states", "nationwide",
                      "anywhere", "hybrid", "onsite", "on-site", "contract",
                      "full-time", "full time", "part-time", "part time"}
    # Strip parentheticals that are pure location/remote noise
    t = re.sub(r"\(([^)]*)\)",
               lambda m: "" if m.group(1).strip().lower() in location_words else m.group(0),
               t).strip()
    # Strip trailing location suffix only if the segment is purely location words
    for sep in [" - ", " | ", " – "]:
        if sep in t:
            parts = t.split(sep)
            suffix_words = set(re.split(r"[\s,]+", parts[-1]))
            if suffix_words.issubset(location_words):
                t = sep.join(parts[:-1]).strip()
    return re.sub(r"\s+", " ", t).strip()


def _url_key(url: str) -> str:
    """Strips query params so the same page with different tracking params matches."""
    return url.split("?")[0].rstrip("/").lower()


def dedup_keys(job: Job) -> list[str]:
    """Returns all dedup keys for a job — any one matching means it's a duplicate.
    Company|title key is only added when company is known so that empty-company
    jobs from search engines don't collide on title alone across employers."""
    keys = []
    company = job.company.lower().strip() if job.company else ""
    title = normalize_title(job.title)
    if company:
        keys.append(f"{company}|{title}")
    if job.url:
        keys.append(_url_key(job.url))
    if not keys:
        # No company, no URL — weak fallback so job doesn't resurface every day
        keys.append(f"__nourl__|{title}|{job.source.lower()}")
    return keys


# ── SEARCH: ADZUNA ────────────────────────────────────────────────────────────

def search_adzuna() -> list[Job]:
    queries = ADZUNA_QUERIES
    jobs = []
    for q in queries:
        try:
            r = requests.get(
                "https://api.adzuna.com/v1/api/jobs/us/search/1",
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
            print(f"Adzuna query failed ({q['what']}): {e}")
    return jobs


# ── SEARCH: BRAVE ─────────────────────────────────────────────────────────────

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
            print(f"Brave query failed ({q[:50]}): {e}")
    return jobs


# ── SEARCH: TAVILY ────────────────────────────────────────────────────────────

def _company_from_url(url: str) -> str:
    """Best-effort company name extraction from a job URL."""
    if not url:
        return ""
    url_lower = url.lower()
    # Workday subdomain: pluxee.myworkdayjobs.com → Pluxee
    wd = re.match(r"https?://([^.]+)\.myworkdayjobs\.com", url_lower)
    if wd:
        slug = wd.group(1)
        for key, name in DOMAIN_COMPANY_MAP.items():
            if key in slug:
                return name
        return slug.replace("-", " ").title()
    # Known domain map
    for key, name in DOMAIN_COMPANY_MAP.items():
        if key in url_lower:
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
                url     = item.get("url", "")
                title   = item.get("title", "")
                company = _company_from_url(url)
                jobs.append(Job(
                    title=title,
                    description=_clean_desc(item.get("content", "")),
                    url=url,
                    company=company,
                    source="Tavily",
                ))
        except Exception as e:
            print(f"Tavily query failed ({q[:50]}): {e}")
    return jobs


# ── SEARCH: LINKEDIN ──────────────────────────────────────────────────────────

LI_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.linkedin.com/",
}
LI_BASE_URL    = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
LI_DETAIL_URL  = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"

LI_RALEIGH_QUERIES = LI_LOCAL_QUERIES   # alias used in _li_is_local_valid() below


def _li_parse_cards(soup, remote: bool) -> list[Job]:
    """Parse job cards from a LinkedIn search results soup."""
    jobs = []
    for card in soup.find_all("li"):
        title_el   = card.find("h3")
        company_el = card.find("h4")
        loc_el     = card.find("span", class_=lambda c: c and "job-search-card__location" in c)
        link_el    = card.find("a", href=True)
        if not (title_el and company_el):
            continue
        loc = loc_el.text.strip() if loc_el else ""
        loc_lower = loc.lower()
        if remote:
            if loc_lower and "remote" not in loc_lower and loc_lower != "united states":
                continue
        else:
            if not any(area in loc_lower for area in LI_NC_LOCATIONS):
                continue
        jobs.append(Job(
            title=title_el.text.strip(),
            company=company_el.text.strip(),
            location=loc,
            url=link_el["href"].split("?")[0] if link_el else "",
            source="LinkedIn",
        ))
    return jobs


def _li_fetch(keywords: str, remote: bool) -> list[Job]:
    from bs4 import BeautifulSoup
    import random
    base_params = {
        "keywords": keywords,
        "geoId":    "103644278",   # United States
        "f_TPR":    "r604800",     # last 7 days
        "f_JT":     "F",           # full-time only
        "sortBy":   "DD",          # newest first
    }
    if remote:
        base_params["f_WT"] = "2,3"  # remote + hybrid
    session = requests.Session()
    session.headers.update(LI_HEADERS)
    jobs = []
    for page in range(2):  # pages 0 and 1 (25 results each)
        if page > 0:
            time.sleep(random.uniform(3, 7))
        params = {**base_params, "start": page * 25}
        try:
            r = session.get(LI_BASE_URL, params=params, timeout=10)
            r.raise_for_status()
        except Exception:
            break
        soup = BeautifulSoup(r.text, "html.parser")
        page_jobs = _li_parse_cards(soup, remote)
        jobs.extend(page_jobs)
        if len(page_jobs) < 20:  # fewer than expected — no more pages
            break
        if page == 0:
            time.sleep(1.5)
    return jobs


def _li_fetch_description(job_url: str) -> str:
    """Fetch full job description from LinkedIn detail endpoint. Returns empty string on failure."""
    from bs4 import BeautifulSoup
    m = re.search(r"(\d{7,})", job_url)  # job ID is 7+ digit number anywhere in URL
    if not m:
        return ""
    job_id = m.group(1)
    try:
        r = requests.get(LI_DETAIL_URL.format(job_id=job_id), headers=LI_HEADERS, timeout=10)
        if r.status_code != 200:
            return ""
        soup = BeautifulSoup(r.text, "html.parser")
        desc_el = soup.find("div", class_=lambda c: c and "description__text" in c)
        if desc_el:
            return _clean_desc(desc_el.get_text(" ", strip=True))
    except Exception:
        pass
    return ""


def li_enrich_descriptions(jobs: list[Job]) -> None:
    """Fetch full descriptions for LinkedIn jobs that don't have one yet.
    Mutates jobs in place. Called after pre-filtering to avoid fetching for discarded jobs."""
    import random
    li_jobs = [j for j in jobs if j.source == "LinkedIn" and not j.description]
    if not li_jobs:
        return
    print(f"  Fetching descriptions for {len(li_jobs)} LinkedIn jobs...")
    for i, job in enumerate(li_jobs):
        if i > 0:
            time.sleep(random.uniform(2, 5))
        desc = _li_fetch_description(job.url)
        if desc:
            job.description = desc


def search_linkedin() -> list[Job]:
    try:
        from bs4 import BeautifulSoup  # noqa: F401
    except ImportError:
        print("  BeautifulSoup not installed, skipping LinkedIn")
        return []
    jobs = []
    for q in LI_REMOTE_QUERIES:
        try:
            jobs.extend(_li_fetch(q, remote=True))
        except Exception as e:
            print(f"  LinkedIn remote query failed ({q[:40]}): {e}")
    for q in LI_RALEIGH_QUERIES:
        try:
            jobs.extend(_li_fetch(q, remote=False))
        except Exception as e:
            print(f"  LinkedIn Raleigh query failed ({q[:40]}): {e}")
    return jobs


# ── SEARCH: REMOTIVE ──────────────────────────────────────────────────────────

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
            print(f"  Remotive error ({params}): {e}")
    print(f"  Remotive: {len(jobs)} results")
    return jobs


# ── SEARCH: WEWORKREMOTELY ────────────────────────────────────────────────────

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
            print(f"  WeWorkRemotely error ({feed_url}): {e}")
    print(f"  WeWorkRemotely: {len(jobs)} results")
    return jobs


# ── SEARCH: HIMALAYAS ─────────────────────────────────────────────────────────

def search_himalayas() -> list[Job]:
    queries = [
        ("product-management", "product owner"),
        ("product-management", "product manager"),
        ("management", "product owner"),
    ]
    jobs = []
    seen_urls: set[str] = set()
    target_keywords = ["product owner", "product manager", "platform product", "scrum master"]
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
                    if not any(w in title.lower() for w in target_keywords):
                        continue
                    url = item.get("applicationLink", "") or ""
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)
                    sal_min = item.get("minSalary") or 0
                    sal_max = item.get("maxSalary") or 0
                    salary_text = ""
                    if sal_min and item.get("currency", "").upper() == "USD":
                        salary_text = f"${sal_min:,}–${sal_max:,}" if sal_max else f"${sal_min:,}+"
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
                print(f"  Himalayas error (offset={offset}): {e}")
                break
    print(f"  Himalayas: {len(jobs)} results")
    return jobs


# ── SEARCH: REMOTEOK ──────────────────────────────────────────────────────────

def search_remoteok() -> list[Job]:
    """Free public JSON API — no key required. One call per run."""
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
            print(f"  RemoteOK error: HTTP {resp.status_code}")
            return []
        seen_urls: set[str] = set()
        for item in resp.json():
            if not isinstance(item, dict) or "position" not in item:
                continue
            title = item.get("position", "") or ""
            if not any(w in title.lower() for w in target_keywords):
                continue
            url = item.get("url", "") or f"https://remoteok.com/l/{item.get('id', '')}"
            if url in seen_urls:
                continue
            seen_urls.add(url)
            sal_min = item.get("salary_min") or 0
            sal_max = item.get("salary_max") or 0
            salary_text = ""
            if sal_min:
                try:
                    salary_text = f"${int(sal_min):,}–${int(sal_max):,}" if sal_max else f"${int(sal_min):,}+"
                except (ValueError, TypeError):
                    salary_text = ""
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
        print(f"  RemoteOK error: {e}")
    print(f"  RemoteOK: {len(jobs)} results")
    return jobs


# ── SEARCH: JOBICY ────────────────────────────────────────────────────────────

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
    target_keywords = ["product owner", "product manager", "platform product", "scrum master"]
    for params in queries:
        try:
            resp = requests.get("https://jobicy.com/api/v2/remote-jobs", params=params, timeout=20)
            if resp.status_code != 200:
                print(f"  Jobicy error ({params.get('tag','?')}): HTTP {resp.status_code}")
                continue
            for item in resp.json().get("jobs", []):
                url = item.get("url", "") or ""
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                title = item.get("jobTitle", "") or ""
                if not any(w in title.lower() for w in target_keywords):
                    continue
                sal_min = item.get("annualSalaryMin") or 0
                sal_max = item.get("annualSalaryMax") or 0
                salary_text = ""
                if sal_min and str(item.get("salaryCurrency", "")).upper() == "USD":
                    try:
                        salary_text = f"${int(sal_min):,}–${int(sal_max):,}" if sal_max else f"${int(sal_min):,}+"
                    except (ValueError, TypeError):
                        salary_text = ""
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
            print(f"  Jobicy error ({params.get('tag','?')}): {e}")
    print(f"  Jobicy: {len(jobs)} results")
    return jobs


# ── SEARCH: JSEARCH (RapidAPI) ────────────────────────────────────────────────

def search_jsearch() -> list[Job]:
    if not JSEARCH_API_KEY:
        return []
    remote_queries = JSEARCH_REMOTE_QUERIES
    local_queries  = JSEARCH_LOCAL_QUERIES
    local_cities   = set(HOME_METRO_TERMS)
    jobs = []
    headers = {"X-RapidAPI-Key": JSEARCH_API_KEY, "X-RapidAPI-Host": "jsearch.p.rapidapi.com"}
    for q in remote_queries + local_queries:
        for attempt in range(3):
            try:
                r = requests.get(
                    "https://jsearch.p.rapidapi.com/search",
                    headers=headers,
                    params={"query": q, "num_pages": "1", "date_posted": "week"},
                    timeout=20,
                )
                r.raise_for_status()
                data = r.json()
                if not isinstance(data.get("data"), list):
                    break
                for item in data["data"]:
                    is_remote = item.get("job_is_remote", False)
                    city  = (item.get("job_city") or "").lower()
                    state = (item.get("job_state") or "").lower()
                    local_match = (city in local_cities) or (state in (HOME_STATE.lower(), HOME_STATE.lower() + " " + HOME_CITY.lower()))
                    if not is_remote and not local_match:
                        continue
                    loc = "Remote" if is_remote else f"{item.get('job_city', '')}, {item.get('job_state', '')}"
                    sal_min = item.get("job_min_salary") or 0
                    sal_max = item.get("job_max_salary") or 0
                    if item.get("job_salary_period") == "HOUR":
                        sal_min = sal_min * 2080 if sal_min else 0
                        sal_max = sal_max * 2080 if sal_max else 0
                    posted = ""
                    ts = item.get("job_posted_at_timestamp")
                    if ts:
                        days_ago = int((datetime.now(timezone.utc).timestamp() - ts) // 86400)
                        posted = f"{days_ago}d ago" if days_ago > 0 else "today"
                    jobs.append(Job(
                        title=item.get("job_title", ""),
                        company=item.get("employer_name", ""),
                        location=loc,
                        description=_clean_desc(item.get("job_description", ""))[:2000],
                        salary_min=sal_min or None,
                        salary_max=sal_max or None,
                        url=item.get("job_apply_link") or item.get("job_google_link", ""),
                        posted=posted,
                        source="JSearch",
                    ))
                break
            except requests.exceptions.Timeout:
                if attempt >= 2:
                    print(f"  JSearch timeout ({q}) — skipping after 3 attempts")
            except Exception as e:
                print(f"  JSearch error ({q}): {e}")
                break
    print(f"  JSearch: {len(jobs)} results")
    return jobs


# ── SEARCH: ATS DIRECT (Greenhouse / Lever / Ashby) ──────────────────────────

def search_ats_companies() -> list[Job]:
    """Queries Greenhouse, Lever, and Ashby career APIs directly. No key needed."""
    # Slug → display name overrides for cases where slug.replace("-"," ").title() is wrong
    ATS_NAME_OVERRIDES = {
        "mxtechnologiesinc":          "MX Technologies",
        "galileofinancialtechnologies":"Galileo Financial Technologies",
        "moderntreasury":             "Modern Treasury",
        "treasuryprime":              "Treasury Prime",
        "bluevineus":                 "Bluevine",
        "leadbank":                   "Lead Bank",
        "BestEgg":                    "Best Egg",
        "oneapp":                     "OnePay",
        "forbrightbank":              "Forbright Bank",
        "tilthq":                     "Tilt",
        "atbayjobs":                  "At-Bay",
        "anchorage":                  "Anchorage Digital",
        "versapay":                   "Versapay",
        "ethoslife":                  "Ethos Life",
        "securitize":                 "Securitize",
        "truebill":                   "Rocket Money (Truebill)",
        "nubank":                     "Nubank",
        "whoop":                      "WHOOP",
        "spreedly":                   "Spreedly",
        "truv":                       "Truv",
        "entersekt":                  "Entersekt",
        "aledade":                    "Aledade",
        "redventures":                "Red Ventures",
        "oportun":                    "Oportun",
        "modernhealth":               "Modern Health",
        "sparkadvisors":              "Spark Advisors",
        "employerdirecthealthcare":   "Employer Direct Healthcare",
        "deepintent":                 "DeepIntent",
        "myfundedfutures":            "My Funded Futures",
        "missionlane":                "Mission Lane",
        "Jerry.ai":                   "Jerry",
    }

    COMPANIES = [
        # ── Consumer / neobanks ───────────────────────────────────────────────
        "chime", "dave", "current", "moneylion", "varomoney", "one-finance",
        "majority", "albert", "cleo", "empower", "brigit",
        "possible-finance", "lili", "found", "relay", "step", "greenlight",
        "forbrightbank",  # Lever confirmed slug (forbright-bank was 404)
        "nubank",         # Brazilian neobank; has US remote + Miami roles
        "tilthq",         # Tilt credit-building app; Ashby confirmed
        # ── Payments ─────────────────────────────────────────────────────────
        "stripe", "marqeta", "lithic", "highnote", "solid",
        "dwolla", "remitly", "wise", "checkout-com",
        "payoneer", "tipalti", "moderntreasury", "melio",
        "flywire", "nuvei", "transcard", "alacriti", "finzly",
        "trustly", "finix", "spreedly", "truv", "versapay",
        "anchorage",      # crypto custody; most roles will be Skipped by Claude
        "adyen",          # Dutch payments; all PM roles on-site — location filter catches
        # ── B2B banking / business banking ───────────────────────────────────
        "mercury", "novo", "bluevineus", "ramp", "brex",
        "bill", "expensify", "navan", "airbase",
        "center", "mesh-payments", "corpay", "fleetcor", "wex",
        # ── Lending / BNPL ────────────────────────────────────────────────────
        "sofi", "lendingclub", "upstart", "prosper", "avant",
        "earnest", "upgrade", "BestEgg",
        "affirm", "bread-financial", "opploans", "self-financial",
        "ondeck", "oportun", "kapitus",
        "kikoff",         # credit-builder; SF on-site — location filter catches
        "wisetack",
        # ── Banking infrastructure / embedded finance ─────────────────────────
        "plaid", "mxtechnologiesinc", "galileofinancialtechnologies", "unit", "synctera",
        "treasuryprime", "column", "alloy", "sardine",
        "socure", "persona", "onfido", "jumio", "checkr",
        "prove", "entersekt",
        "middesk", "unit21", "parafin",
        "pathward",       # banking-as-a-service
        "lendingtree",    # fintech marketplace; all roles Seattle/Denver on-site
        "whoop",          # wearables; all PM roles Boston on-site
        "alt",            # collectibles fintech; all roles crypto/digital assets
        "oneapp",         # OnePay (Walmart); Ashby slug
        # ── Wealth / investing ────────────────────────────────────────────────
        "drivewealth", "alpaca", "apex-fintech",
        "paxos", "cross-river", "leadbank",
        "betterment", "wealthfront", "robinhood", "acorns",
        "stash", "m1-finance", "altruist",
        "tastytrade", "webull", "etoro",
        "riskalyze", "orion-advisor", "envestnet",
        "securitize",     # blockchain securities
        # ── Insurance (insurtech) ─────────────────────────────────────────────
        "lemonade", "root", "hippo", "oscar-health",
        "policygenius", "ethos", "ethoslife", "kin",
        "pie-insurance", "openly", "sure",
        "next-insurance", "vouch", "corvus", "cowbell",
        "embroker", "newfront", "counterpart",
        "atbayjobs", "federato", "sureify",
        # ── Regtech / compliance / identity ──────────────────────────────────
        "complyadvantage", "verafin", "flagright", "sentilink",
        "inscribe", "ocrolus", "codat",
        "employerdirecthealthcare",
        # ── Credit / data / scoring ───────────────────────────────────────────
        "creditkarma", "nerdwallet", "bankrate",
        "truebill",       # Rocket Money / Truebill
        # ── Banking technology vendors ────────────────────────────────────────
        "ncino", "q2", "alkami", "backbase", "bottomline",
        "finastra", "mambu", "thought-machine",
        "finxact", "technisys", "zafin", "mbanq",
        "nymbus", "bankjoy", "lumin-digital",
        "apiture", "jack-henry", "fiserv", "fis",
        # ── Major US banks ────────────────────────────────────────────────────
        "capital-one", "american-express",
        "citizens-bank", "truist", "first-citizens", "umb-financial",
        "western-alliance",
        # ── Payroll / HR fintech ──────────────────────────────────────────────
        "gusto", "rippling", "deel",
        "ceridian", "paylocity", "paycom",
        "bamboohr", "justworks", "trinet", "paycor",
        # ── Earned wage access ────────────────────────────────────────────────
        "earnin", "dailypay", "payactiv", "rain", "clair", "tapcheck",
        # ── Other fintech ─────────────────────────────────────────────────────
        "intuit", "paypal", "lending-club", "prosper-marketplace",
        "broadridge", "tradeweb", "virtu-financial",
        "aledade", "redventures", "engine",
        "modernhealth", "sparkadvisors", "deepintent",
        "missionlane",    # consumer credit card fintech
        "Jerry.ai",       # Jerry insurtech/auto super app (case-sensitive Ashby slug)
        "form3", "inkind", "myfundedfutures",
        # ── NC / Raleigh-area banks and institutions ──────────────────────────
        "live-oak-bank", "liveoakbank",
        "coastal-credit-union", "pinnacle-financial", "pinnacle-bank",
        "townebank", "live-oak-bancshares",
        "navy-federal", "penfed", "becu",
        "alliant", "first-tech", "rbfcu", "vystar",
        "truliant", "self-help", "self-help-credit-union",
    ]

    TARGET_TITLES = [
        "product owner", "product manager", "platform product",
        "scrum master", "business analyst", "functional analyst",
        "business functional analyst", "systems analyst",
        "avp product", "director of product", "principal product",
    ]
    BLOCK_SUFFIXES = ["representative", "specialist", "rep",
                      "support agent", "support rep"]

    jobs: list[Job] = []
    seen_urls: set[str] = set()

    def _title_match(title: str) -> bool:
        t = title.lower()
        if not any(kw in t for kw in TARGET_TITLES):
            return False
        if any(t.endswith(sfx) or f" {sfx}," in t or f" {sfx} " in t
               for sfx in BLOCK_SUFFIXES):
            return False
        return True

    def _company_name(slug: str) -> str:
        return ATS_NAME_OVERRIDES.get(slug, slug.replace("-", " ").title())

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
                # Concatenate all description sections for fuller context
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
            # API returns "jobs" key (not "jobPostings" — that was a bug causing 0 results)
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

    total = len(COMPANIES)
    total_tried = total_hits = 0
    print(f"  ATS: checking {total} companies across Greenhouse / Lever / Ashby...")
    for slug in COMPANIES:
        found  = _try_greenhouse(slug)
        found += _try_lever(slug)
        found += _try_ashby(slug)
        if found:
            total_hits += 1
            jobs.extend(found)
            titles = ", ".join(j.title for j in found[:2])
            print(f"    ✓ {slug} ({len(found)}): {titles}")
        total_tried += 1
        if total_tried % 50 == 0:
            print(f"  ATS: {total_tried}/{total} checked — {len(jobs)} matches so far")
            time.sleep(1)

    print(f"  ATS direct: {len(jobs)} results from {total_hits}/{total_tried} companies")
    return jobs


# ── DEBUG LOG ─────────────────────────────────────────────────────────────────

def write_debug_log(jobs: list[Job], raw_counts: dict):
    """Full log of every job — title, source, rating, description as fed to Claude.
    Overwrites on each run. Upload to Claude to verify description quality."""
    today = date.today().isoformat()
    lines = ["=" * 80, f"JOB RADAR DEBUG LOG — {today}",
             f"Total jobs this run: {len(jobs)}", "Source counts:"]
    for src, count in sorted(raw_counts.items()):
        lines.append(f"  {src:<20} {count} jobs")
    lines.append("=" * 80)

    by_tier: dict[str, list[Job]] = {"Apply Now": [], "Worth a Look": [], "Weak Match": [], "Skip": []}
    for job in jobs:
        by_tier.setdefault(job.tier or "Skip", []).append(job)

    for tier in ["Apply Now", "Worth a Look", "Weak Match", "Skip"]:
        tier_jobs = by_tier.get(tier, [])
        if not tier_jobs:
            continue
        lines += ["", "=" * 80, f"  {tier.upper()}  ({len(tier_jobs)} jobs)", "=" * 80]
        for job in tier_jobs:
            lines += [
                "", "─" * 60,
                f"TITLE:    {job.title}",
                f"COMPANY:  {job.company}",
                f"SOURCE:   {job.source}",
                f"LOCATION: {job.location}",
                f"URL:      {job.url}",
                f"SALARY:   {job.salary_str()}",
                f"RATING:   {job.tier}",
                f"REASON:   {job.reason}",
                f"DESC LEN: {len(job.description or '')} chars",
                "DESCRIPTION:",
                job.description or "(no description)",
                "─" * 60,
            ]
    try:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        DEBUG_LOG_FILE.write_text("\n".join(lines), encoding="utf-8")
        print(f"  Debug log: {DEBUG_LOG_FILE} ({len(jobs)} jobs, {sum(raw_counts.values())} raw)")
    except Exception as e:
        print(f"  Warning: could not write debug log: {e}")


# ── BUILD REPORT ──────────────────────────────────────────────────────────────

def build_report(jobs: list[Job], seen: dict, now: datetime) -> tuple[str, list[Job], dict]:
    new_jobs: list[Job] = []
    new_seen = dict(seen)
    seen_urls: set[str] = set()
    today_str = date.today().isoformat()

    # ── Source ordering: richest data first so best description wins dedup ──
    # Order already established by caller (ATS → Adzuna → Jobicy → Himalayas →
    # RemoteOK → Remotive → JSearch → LinkedIn → Brave → Tavily → WWR)

    within_run_seen: set[str] = set()  # catches same job from multiple sources today

    for job in jobs:
        keys = dedup_keys(job)
        if any(k in new_seen for k in keys):
            continue
        if any(k in within_run_seen for k in keys):
            continue
        if is_category_page(job.title, job.url, job.description):
            continue
        if job.url and "virtualvocations.com" in job.url.lower():
            continue
        if job.company and job.company.lower().strip() in BLOCKED_COMPANIES:
            continue
        if is_wrong_title(job.title):
            continue
        if is_bad_scrape(job):
            continue
        if is_non_us_location(job):
            continue
        if is_onsite_non_local(job):
            continue
        if is_staffing(job.title, job.company, job.description):
            continue
        if is_below_salary_floor(job):
            continue
        if is_closed_listing(job.description):
            continue
        if is_broken_url(job.url):
            continue
        new_jobs.append(job)
        for k in keys:
            new_seen[k] = today_str
            within_run_seen.add(k)

    # ── Enrich LinkedIn jobs with full descriptions before rating ─────────────
    li_enrich_descriptions(new_jobs)

    # ── Parallel Claude rating — batches of 3, 5s sleep between batches ──────
    # BATCH_SIZE=3 fires simultaneously; 5s pause prevents token-burst rate limits.
    # On a normal 50-job run adds ~80s total. Worth it to get real scores.
    print(f"  Rating {len(new_jobs)} jobs with Claude Haiku (3 parallel, batched)...")
    rated: list[Optional[Job]] = [None] * len(new_jobs)
    BATCH_SIZE = 3

    def _rate_one(args: tuple[int, Job]) -> tuple[int, Job]:
        i, job = args
        tier, reason, salary_text = rate_with_claude(job)
        job.tier = tier
        job.reason = reason
        if salary_text and not job.salary_min:
            job.salary_text = salary_text
        with _print_lock:
            print(f"    {i+1}/{len(new_jobs)} {tier} — {job.title[:60]}")
        return i, job

    for batch_start in range(0, len(new_jobs), BATCH_SIZE):
        batch = [(i, new_jobs[i]) for i in range(batch_start, min(batch_start + BATCH_SIZE, len(new_jobs)))]
        with ThreadPoolExecutor(max_workers=BATCH_SIZE) as executor:
            futures = {executor.submit(_rate_one, item): item[0] for item in batch}
            for future in as_completed(futures):
                try:
                    i, job = future.result()
                    rated[i] = job
                except Exception as e:
                    i = futures[future]
                    with _print_lock:
                        print(f"  Rating error (job {i}): {e}")
                    new_jobs[i].tier = "Worth a Look"
                    new_jobs[i].reason = "Rating unavailable"
                    rated[i] = new_jobs[i]
        if batch_start + BATCH_SIZE < len(new_jobs):
            time.sleep(5)

    new_jobs = [j for j in rated if j is not None]
    new_jobs.sort(key=lambda j: TIER_ORDER.get(j.tier, 99))

    priority     = [j for j in new_jobs if j.tier in ("Apply Now", "Worth a Look")]
    low_priority = [j for j in new_jobs if j.tier in ("Weak Match", "Skip")]
    slot = "AM" if now.hour < 12 else "PM"

    lines = [
        f"💼 JOB RADAR — {now.strftime('%A, %B %-d, %Y')} ({slot})",
        f"{len(new_jobs)} new | {len(priority)} priority ({sum(1 for j in new_jobs if j.tier == 'Apply Now')} Apply Now)",
        "",
    ]

    if not new_jobs:
        lines.append("No new positions found since last run.")
    else:
        tier_labels = {"Apply Now": "🔥 APPLY NOW", "Worth a Look": "👀 WORTH A LOOK"}
        current_tier = None

        for tier_name in ("Apply Now", "Worth a Look"):
            tier_jobs = [j for j in priority if j.tier == tier_name]
            if not tier_jobs:
                continue

            # Raleigh jobs first within each tier
            local_jobs  = [j for j in tier_jobs if is_local_raleigh(j)]
            remote_jobs = [j for j in tier_jobs if not is_local_raleigh(j)]
            ordered = local_jobs + remote_jobs

            if tier_name != current_tier:
                current_tier = tier_name
                lines.append(f"\n{'─' * 40}")
                lines.append(tier_labels[tier_name])
                lines.append(f"{'─' * 40}")

            for job in ordered:
                pin = "📍 " if is_local_raleigh(job) else ""
                header = f"{pin}{job.title}"
                if job.company:
                    header += f" — {job.company}"
                if job.location:
                    header += f" ({job.location})"
                lines.append(header)

                if job.reason:
                    lines.append(f"↳ {job.reason}")
                if job.description:
                    snippet = job.description[:200].strip().replace("\n", " ")
                    if len(job.description) > 200:
                        snippet += "…"
                    lines.append(snippet)

                meta = [f"Salary: {job.salary_str()}"]
                if job.posted:
                    meta.append(f"Posted: {job.posted}")
                meta.append(f"Source: {job.source}")
                lines.append(" | ".join(meta))
                if job.url:
                    lines.append(f"🔗 {job.url}")
                lines.append("")

        if low_priority:
            lines.append(f"\n{'─' * 40}")
            lines.append(f"⬇️  FILTERED OUT ({len(low_priority)} jobs — scan to catch mistakes)")
            lines.append(f"{'─' * 40}")
            for job in low_priority:
                label = "⚠️" if job.tier == "Weak Match" else "✗"
                entry = f"{label} {job.title}"
                if job.company:
                    entry += f" — {job.company}"
                if job.reason:
                    entry += f"  [{job.reason}]"
                lines.append(entry)
                if job.url:
                    lines.append(f"   {job.url}")

    return "\n".join(lines), new_jobs, new_seen


# ── EMAIL ─────────────────────────────────────────────────────────────────────

def send_email(subject: str, body: str, attachment: Path | None = None):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = EMAIL
    msg["To"] = EMAIL
    msg.set_content(body)
    if attachment and attachment.exists():
        msg.add_attachment(
            attachment.read_bytes(),
            maintype="text", subtype="markdown",
            filename=attachment.name,
        )
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(EMAIL, GMAIL_APP_PW)
        smtp.send_message(msg)


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main(force_run: bool = False):
    now = datetime.now()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    seen = load_seen()

    # Source order: richest data first — first source to find a job wins dedup,
    # so the best description/salary anchors each listing.
    raw_counts: dict[str, int] = {}

    print("Searching ATS direct (Greenhouse / Lever / Ashby)...")
    ats_jobs = search_ats_companies()
    raw_counts["ATS"] = len(ats_jobs)

    print("Searching Adzuna...")
    adzuna_jobs = search_adzuna()
    raw_counts["Adzuna"] = len(adzuna_jobs)
    print(f"  {len(adzuna_jobs)} results")

    print("Searching Jobicy...")
    jobicy_jobs = search_jobicy()
    raw_counts["Jobicy"] = len(jobicy_jobs)

    print("Searching Himalayas...")
    himalayas_jobs = search_himalayas()
    raw_counts["Himalayas"] = len(himalayas_jobs)

    print("Searching RemoteOK...")
    remoteok_jobs = search_remoteok()
    raw_counts["RemoteOK"] = len(remoteok_jobs)

    print("Searching Remotive...")
    remotive_jobs = search_remotive()
    raw_counts["Remotive"] = len(remotive_jobs)

    if JSEARCH_API_KEY:
        print("Searching JSearch...")
        jsearch_jobs = search_jsearch()
        raw_counts["JSearch"] = len(jsearch_jobs)
    else:
        jsearch_jobs = []

    print("Searching LinkedIn...")
    linkedin_jobs = search_linkedin()
    raw_counts["LinkedIn"] = len(linkedin_jobs)
    print(f"  {len(linkedin_jobs)} results")

    print("Searching Brave...")
    brave_jobs = search_brave()
    raw_counts["Brave"] = len(brave_jobs)
    print(f"  {len(brave_jobs)} results")

    print("Searching Tavily...")
    tavily_jobs = search_tavily()
    raw_counts["Tavily"] = len(tavily_jobs)
    print(f"  {len(tavily_jobs)} results")

    print("Searching WeWorkRemotely...")
    wwr_jobs = search_weworkremotely()
    raw_counts["WeWorkRemotely"] = len(wwr_jobs)

    # Ordered: richest first
    all_jobs = (
        ats_jobs + adzuna_jobs + jobicy_jobs + himalayas_jobs + remoteok_jobs
        + remotive_jobs + jsearch_jobs + linkedin_jobs + brave_jobs + tavily_jobs
        + wwr_jobs
    )

    report, new_jobs, new_seen = build_report(all_jobs, seen, now)

    write_debug_log(new_jobs, raw_counts)

    slot = "am" if now.hour < 12 else "pm"
    outfile = OUTPUT_DIR / f"{now.strftime('%Y-%m-%d')}-{slot}.md"
    outfile.write_text(report)
    print(f"Saved: {outfile}")

    save_seen(new_seen)

    apply_now = sum(1 for j in new_jobs if j.tier == "Apply Now")
    priority  = sum(1 for j in new_jobs if j.tier in ("Apply Now", "Worth a Look"))
    subject = f"Job Radar {now.strftime('%b %-d')} {slot.upper()} — {apply_now} Apply Now | {priority} priority / {len(new_jobs)} total"
    send_email(subject, report, attachment=outfile)
    print("Email sent.")


if __name__ == "__main__":
    force_run = "--run" in sys.argv
    if force_run:
        print("Manual run")
    main(force_run=force_run)
