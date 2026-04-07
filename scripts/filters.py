"""Job filtering functions and supporting constants/regex patterns."""

import re
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import MIN_SALARY, HOME_METRO_TERMS, HOME_STATE  # noqa: E402

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
    r"|\bcustomer (service|care) (rep|representative|specialist|associate|coordinator|manager|operations)\b"
    r"|\bcustomer success (rep|representative|specialist|associate|coordinator|operations)\b"  # block support-level CS only
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

STAFFING_KEYWORDS = [
    "staffing", "recruiting", "recruiter", "talent solutions", "search group",
    "placement", "manpower", "robert half", "adecco", "kelly services",
    "randstad", "insight global", "apex systems", "our client", "on behalf of",
]

BLOCKED_COMPANIES: set[str] = {
    "eeze",
}


# ── Filter functions ─────────────────────────────────────────────────────────

def is_category_page(title: str, url: str, description: str = "") -> bool:
    if any(frag in url for frag in CATEGORY_URL_FRAGMENTS):
        return True
    if CATEGORY_TITLE_RE.search(title) or NON_JOB_TITLE_RE.search(title):
        return True
    if _EXPIRED_RE.search(title) or (description and _EXPIRED_RE.search(description[:500])):
        return True
    return False


def is_non_us_location(job) -> bool:
    if _NON_US_RE.search(job.location):
        return True
    if job.description and _NON_US_RE.search(job.description):
        return True
    return False


def is_onsite_non_local(job) -> bool:
    """Returns True if the job requires on-site attendance at a non-Raleigh location."""
    remote_signals = ("remote", "work from home", "wfh", "distributed", "virtual")
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

    if job.url and _URL_CITY_RE.search(job.url):
        if any(s in job.title.lower() for s in remote_signals):
            return False
        if any(s in loc for s in remote_signals):
            return False
        if any(s in desc_intro for s in remote_signals):
            if any(s in desc_intro for s in onsite_signals):
                return True
            return False
        return True

    if _LOC_CITY_RE.search(loc):
        if any(s in loc for s in remote_signals):
            return False
        if any(s in desc_intro for s in remote_signals):
            if any(s in desc_intro for s in onsite_signals):
                return True
            return False
        return True

    return False


def is_bad_scrape(job) -> bool:
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


def is_local_raleigh(job) -> bool:
    loc = job.location.lower()
    return any(area in loc for area in LI_NC_LOCATIONS)


def is_staffing(title: str, company: str, description: str) -> bool:
    combined = f"{title} {company} {description}".lower()
    return any(kw in combined for kw in STAFFING_KEYWORDS)


def _parse_salary_string(s: str) -> int:
    """Convert salary strings like '$120K', '$120,000' to int lower bound."""
    if not s:
        return 0
    s_lower = str(s).lower().replace(",", "")
    if re.search(r"/\s*(hour|hr|week|wk|month|mo)", s_lower):
        return 0
    m = re.search(r"\$?\s*(\d+(?:\.\d+)?)\s*k?", s_lower)
    if not m:
        return 0
    raw = m.group(1)
    if re.fullmatch(r"(19|20)\d\d", raw.strip()):
        return 0
    val = float(raw)
    if "k" in s_lower[m.start():m.end() + 2]:
        val *= 1000
    return int(val)


def _is_plausible_salary(raw_str: str) -> bool:
    """Return True only if the dollar amount looks like an annual salary."""
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


def is_below_salary_floor(job) -> bool:
    """Drop only when salary IS listed AND the entire range is confirmed below floor."""
    sal_min = job.salary_min or 0
    sal_max = job.salary_max or 0

    if sal_min > 0 and sal_max > 0:
        return sal_max < MIN_SALARY
    if sal_max > 0:
        return sal_max < MIN_SALARY
    if sal_min > 0:
        return False
    if job.salary_text:
        sal = _parse_salary_string(job.salary_text)
        if sal > 0:
            return sal < MIN_SALARY
    return False


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
