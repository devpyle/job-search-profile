"""
config.example.py — Copy this to config.py and fill in your details.
config.py is gitignored — it stays local and is never committed.
"""

# ── CANDIDATE ─────────────────────────────────────────────────────────────────

CANDIDATE_NAME = "Your Name"

# Brief career summary used in the Claude rating prompt.
# Tell Claude who you are, what you've done, and what you're looking for.
CANDIDATE_BACKGROUND = """\
- Current role: [Your current title] at [company type] — [brief specialty]
- Prior: [Role] at [company type] (YYYY-YYYY), [Role] at [company type] (YYYY-YYYY)
- Target roles: Product Owner, Product Manager, [other titles]
- Industries: fintech, banking, SaaS, enterprise software, [others]
- Location: [City, State] — remote preferred, open to hybrid. US-only.
- Salary floor: $XXX,000\
"""

# Used in the rating prompt to describe your "Apply Now" tier.
APPLY_NOW_DESCRIPTION = "strong fit: [your specialty] PO or PM role, ideally [your domain] or remote"

# ── LOCATION ──────────────────────────────────────────────────────────────────

HOME_CITY  = "Your City"
HOME_STATE = "NC"   # two-letter state abbreviation

# Terms used to match local job postings (LinkedIn/JSearch local queries)
HOME_METRO_TERMS = [
    "your city",
    "nearby city",
    "metro area name",
    "rtp",        # remove/replace with your region's shorthand
]

# ── JOB SEARCH ────────────────────────────────────────────────────────────────

MIN_SALARY = 100_000   # jobs with confirmed salary below this are filtered out

# Set to True to filter out jobs located outside the US.
# Set to False if you are searching internationally.
REQUIRE_US_LOCATION = True

# Adzuna country code — controls which Adzuna job market is searched.
# Common codes: us, gb, au, ca, de, fr, br, in, nz, sg, za
# See https://developer.adzuna.com/ for the full list.
ADZUNA_COUNTRY = "us"

# ── DASHBOARD — DOCUMENT GENERATION ───────────────────────────────────────────

# Job history doc filenames in docs/, newest → oldest.
# pre-2011 early career is always excluded.
JOB_DOCS = [
    "YYYY-present-company-title.md",
    "YYYY-YYYY-company-title.md",
    "YYYY-YYYY-company-title.md",
]


# ── SEARCH QUERIES ────────────────────────────────────────────────────────────
# Edit these to match your target job titles, industries, and specialties.
# The more specific, the better signal-to-noise ratio in your daily report.

ADZUNA_QUERIES = [
    {"what": "product owner API platform remote",               "sort_by": "date", "max_days_old": 7},
    {"what": "product owner [your specialty] remote",           "sort_by": "date", "max_days_old": 7},
    {"what": "product owner remote",                            "sort_by": "salary","max_days_old": 7},
    {"what": "product owner", "where": "Your City, ST",        "sort_by": "date", "max_days_old": 7},
    {"what": "product manager","where": "Your City, ST",        "sort_by": "date", "max_days_old": 7},
]

BRAVE_QUERIES = [
    '"product owner" [your specialty] remote job -staffing -recruiter',
    '"product owner" [your industry] remote job -staffing -recruiter',
    '"product owner" Your City ST job -staffing -recruiter',
    'site:boards.greenhouse.io "product owner" [your industry] remote',
    'site:jobs.lever.co "product owner" [your industry] remote',
    'site:jobs.ashbyhq.com "product owner" [your industry]',
]

TAVILY_QUERIES = [
    '"product owner" OR "product manager" [specialty] remote "job opening" OR "now hiring" OR "apply now"',
    '"product owner" OR "product manager" [industry] remote "job opening" OR "hiring" OR "apply"',
    'site:hiring.cafe "product owner" OR "product manager" remote',
    'site:boards.greenhouse.io "product owner" OR "product manager" [industry] remote',
    'site:myworkdayjobs.com "product owner" OR "product manager" [industry] "united states" OR "remote"',
]

LI_REMOTE_QUERIES = [
    "product owner [your specialty]",
    "product owner [your industry]",
    "platform product manager",
    "senior product owner",
]

LI_LOCAL_QUERIES = [
    f"product owner Your City ST",
    f"product manager Your City Region",
    # Add local companies worth targeting:
    'product owner "Company A" OR "Company B" OR "Company C"',
]

JSEARCH_REMOTE_QUERIES = [
    "Product Owner [your specialty] remote",
    "Product Owner [your industry] remote",
    "Senior Product Owner remote",
    "Senior Product Manager [your industry] remote",
]

JSEARCH_LOCAL_QUERIES = [
    "Product Owner Your City ST",
    "Product Manager Your City Region ST",
]

# ── PORTAL / ATS DIRECT SCANNER ─────────────────────────────────────────────
# Shared between job_radar.py (cron) and portal_scanner.py (dashboard).
# Companies to scan directly via Greenhouse, Lever, and Ashby ATS APIs.
# Use the company's ATS slug (the subdomain in boards.greenhouse.io/SLUG).

PORTAL_COMPANIES = [
    # Add company ATS slugs here. Find them by visiting a company's careers
    # page — the URL pattern tells you which ATS they use:
    #   boards.greenhouse.io/SLUG  →  Greenhouse
    #   jobs.lever.co/SLUG         →  Lever
    #   jobs.ashbyhq.com/SLUG      →  Ashby
    #
    # Example slugs:
    # "stripe", "plaid", "sofi", "chime", "ramp", "robinhood",
]

# Override display names for slugs that don't produce clean names.
# slug.replace("-", " ").title() is the default — only add overrides where that's wrong.
PORTAL_NAME_OVERRIDES = {
    # "companyslug": "Display Name",
}

# Job titles to match when scanning portals. Case-insensitive substring match.
# Both the radar and portal scanner use this list.
PORTAL_TARGET_TITLES = [
    "product owner", "product manager",
    # Add your target titles here, e.g.:
    # "software engineer", "data scientist", "designer",
]

# Suffixes that disqualify a title match (e.g. "support representative").
PORTAL_BLOCK_SUFFIXES = ["representative", "rep", "support agent", "support rep"]
