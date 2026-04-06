"""
Portal scanner — checks Greenhouse, Lever, and Ashby APIs for matching job postings.

Reuses company list and title filters from job_radar.py but runs independently
so it can be called from the dashboard without heavy dependencies.
"""

import hashlib
import html
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

# ── TITLE MATCHING ────────────────────────────────────────────────────────────

TARGET_TITLES = [
    "product owner", "product manager", "platform product",
    "technical product", "digital product", "api product",
    "data product", "feature owner", "service owner", "capability owner",
    "product analyst", "product operations", "product ops",
    "product delivery", "product consultant",
    "business analyst", "functional analyst", "business functional analyst",
    "systems analyst", "business systems analyst", "technical analyst",
    "solutions analyst", "integration analyst", "application analyst",
    "enterprise analyst", "platform analyst", "technical program analyst",
    "api analyst", "api specialist", "technical business analyst",
    "process improvement", "continuous improvement",
    "scrum master", "scrum product owner", "agile business analyst",
    "agile delivery", "iteration manager",
    "solutions architect", "business architect",
    "integration manager", "implementation manager",
    "technical customer success", "enterprise customer success",
    "customer success manager",
    "sales engineer", "pre-sales", "presales",
    "avp product", "director of product", "principal product",
]

BLOCK_SUFFIXES = ["representative", "rep", "support agent", "support rep"]

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
    # Consumer / neobanks
    "chime", "dave", "current", "moneylion", "varomoney", "one-finance",
    "majority", "albert", "cleo", "empower", "brigit",
    "possible-finance", "lili", "found", "relay", "step", "greenlight",
    "forbrightbank", "nubank", "tilthq",
    # Payments
    "stripe", "marqeta", "lithic", "highnote", "solid",
    "dwolla", "remitly", "wise", "checkout-com",
    "payoneer", "tipalti", "moderntreasury", "melio",
    "flywire", "nuvei", "transcard", "alacriti", "finzly",
    "trustly", "finix", "spreedly", "truv", "versapay",
    "anchorage", "adyen",
    # B2B banking
    "mercury", "novo", "bluevineus", "ramp", "brex",
    "bill", "expensify", "navan", "airbase",
    "center", "mesh-payments", "corpay", "fleetcor", "wex",
    # Lending / BNPL
    "sofi", "lendingclub", "upstart", "prosper", "avant",
    "earnest", "upgrade", "BestEgg",
    "affirm", "bread-financial", "opploans", "self-financial",
    "ondeck", "oportun", "kapitus", "kikoff", "wisetack",
    # Banking infra
    "plaid", "mxtechnologiesinc", "galileofinancialtechnologies", "unit", "synctera",
    "treasuryprime", "column", "alloy", "sardine",
    "socure", "persona", "onfido", "jumio", "checkr",
    "prove", "entersekt", "middesk", "unit21", "parafin",
    "pathward", "lendingtree", "whoop", "alt", "oneapp",
    # Wealth / investing
    "drivewealth", "alpaca", "apex-fintech",
    "paxos", "cross-river", "leadbank",
    "betterment", "wealthfront", "robinhood", "acorns",
    "stash", "m1-finance", "altruist",
    "tastytrade", "webull", "etoro",
    "riskalyze", "orion-advisor", "envestnet", "securitize",
    # Insurance
    "lemonade", "root", "hippo", "oscar-health",
    "policygenius", "ethos", "ethoslife", "kin",
    "pie-insurance", "openly", "sure",
    "next-insurance", "vouch", "corvus", "cowbell",
    "embroker", "newfront", "counterpart",
    "atbayjobs", "federato", "sureify",
    # Regtech
    "complyadvantage", "verafin", "flagright", "sentilink",
    "inscribe", "ocrolus", "codat", "employerdirecthealthcare",
    # Credit / data
    "creditkarma", "nerdwallet", "bankrate", "truebill",
    # Banking tech vendors
    "ncino", "q2", "alkami", "backbase", "bottomline",
    "finastra", "mambu", "thought-machine",
    "finxact", "technisys", "zafin", "mbanq",
    "nymbus", "bankjoy", "lumin-digital",
    "apiture", "jack-henry", "fiserv", "fis",
    # Major US banks
    "capital-one", "american-express",
    "citizens-bank", "truist", "first-citizens", "umb-financial",
    "western-alliance",
    # Payroll / HR fintech
    "gusto", "rippling", "deel",
    "ceridian", "paylocity", "paycom",
    "bamboohr", "justworks", "trinet", "paycor",
    # Earned wage access
    "earnin", "dailypay", "payactiv", "rain", "clair", "tapcheck",
    # Other fintech
    "intuit", "paypal", "lending-club", "prosper-marketplace",
    "broadridge", "tradeweb", "virtu-financial",
    "aledade", "redventures", "engine",
    "modernhealth", "sparkadvisors", "deepintent",
    "missionlane", "Jerry.ai", "form3", "inkind", "myfundedfutures",
    # NC / Raleigh-area
    "live-oak-bank", "liveoakbank",
    "coastal-credit-union", "pinnacle-financial", "pinnacle-bank",
    "townebank", "live-oak-bancshares",
    "navy-federal", "penfed", "becu",
    "alliant", "first-tech", "rbfcu", "vystar",
    "truliant", "self-help", "self-help-credit-union",
]


# ── LOCATION FILTERS (from job_radar.py) ──────────────────────────────────────

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
    r"|\b(singapore|hong kong|shanghai|beijing|tokyo|seoul|bangalore|bengaluru|mumbai|new delhi|hyderabad|pune|chennai|kolkata|noida|gurgaon|gurugram)\b"
    r"|\bindia\b|\bjapan\b|\bsouth korea\b|\bchina\b"
    # Middle East
    r"|\b(tel aviv|tlv|herzliya|haifa|jerusalem)\b|\bisrael\b"
    # Latin America
    r"|\b(são paulo|sao paulo|rio de janeiro|bogota|mexico city|ciudad de mexico|buenos aires|santiago|lima)\b"
    r"|\bbrazil\b|\bmexico\b(?! remote)|\bcolombia\b|\bargentina\b|\bchile\b|\bperu\b"
    # Southern Europe
    r"|\b(lisbon|porto|seville)\b|\bportugal\b|\bspain\b"
    # Region labels
    r"|^emea$|\bemea\b|^eu$|^europe$|\beurope\b(?! remote)"
    r"|\blatam\b|\bmena\b|\bapac\b|\bapj\b|\banz\b",
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
    r"|\bcharlotte\b(?! st)"
    r"|\b(salt lake city|cottonwood heights)\b"
    r"|\bphoenix\b"
    r"|\bhouston\b"
    r"|\bminneapolis\b"
    r"|\bphiladelphia\b"
    r"|\b(washington dc|washington, dc)\b"
    r"|\b(st louis|saint louis|kansas city)\b"
    r"|\b(ca|wa|ny|il|ma|tx|co|ga|fl|az|ut|or|mn|pa|tn)\s*-"
    r"|\bcalifornia\b|\b(washington state|washington, wa)\b",
    re.IGNORECASE,
)

_REMOTE_SIGNALS = ("remote", "work from home", "wfh", "distributed", "virtual")


def _is_non_us(location: str, description: str = "", title: str = "") -> bool:
    if _NON_US_RE.search(location):
        return True
    if title and _NON_US_RE.search(title):
        return True
    if description and _NON_US_RE.search(description):
        return True
    return False


def _is_onsite_non_local(location: str, description: str = "") -> bool:
    loc = location.lower()
    desc_intro = description[:800].lower() if description else ""

    if _LOC_CITY_RE.search(loc):
        if any(s in loc for s in _REMOTE_SIGNALS):
            return False
        if any(s in desc_intro for s in _REMOTE_SIGNALS):
            return False
        return True
    return False


def _clean_desc(text: str) -> str:
    if not text:
        return ""
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:5000]


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


def _job_id(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:12]


def _try_greenhouse(slug: str, seen_urls: set) -> list[dict]:
    try:
        r = requests.get(
            f"https://api.greenhouse.io/v1/boards/{slug}/jobs",
            params={"content": "false"}, timeout=8,
        )
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
            result.append({
                "job_id":   _job_id(url),
                "title":    title,
                "company":  _company_name(slug),
                "location": item.get("location", {}).get("name", "") or "",
                "url":      url,
                "posted":   (item.get("updated_at", "") or "")[:10],
                "source":   "Greenhouse",
                "description": "",
            })
        return result
    except Exception:
        return []


def _try_lever(slug: str, seen_urls: set) -> list[dict]:
    try:
        r = requests.get(
            f"https://api.lever.co/v0/postings/{slug}",
            params={"mode": "json"}, timeout=8,
        )
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
                desc_parts.append(
                    (lst.get("text", "") or "") + " " + (lst.get("content", "") or "")
                )
            result.append({
                "job_id":      _job_id(url),
                "title":       title,
                "company":     _company_name(slug),
                "location":    (item.get("categories") or {}).get("location", "") or "",
                "url":         url,
                "source":      "Lever",
                "description": _clean_desc(" ".join(desc_parts)),
                "posted":      "",
            })
        return result
    except Exception:
        return []


def _try_ashby(slug: str, seen_urls: set) -> list[dict]:
    try:
        r = requests.get(
            f"https://api.ashbyhq.com/posting-api/job-board/{slug}", timeout=8,
        )
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
            result.append({
                "job_id":      _job_id(url),
                "title":       title,
                "company":     _company_name(slug),
                "location":    item.get("location", "") or "",
                "url":         url,
                "posted":      (item.get("publishedDate", "") or "")[:10],
                "source":      "Ashby",
                "description": "",
            })
        return result
    except Exception:
        return []


def scan_all(progress_callback=None) -> list[dict]:
    """Scan all configured companies across Greenhouse, Lever, and Ashby.

    Args:
        progress_callback: optional callable(checked, total, hits) for progress updates.

    Returns list of matching job dicts.
    """
    seen_urls: set[str] = set()
    all_jobs: list[dict] = []
    total = len(COMPANIES)
    hits = 0

    def _scan_company(slug):
        found = _try_greenhouse(slug, seen_urls)
        found += _try_lever(slug, seen_urls)
        found += _try_ashby(slug, seen_urls)
        return slug, found

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_scan_company, slug): slug for slug in COMPANIES}
        checked = 0
        for future in as_completed(futures):
            slug, found = future.result()
            checked += 1
            if found:
                hits += 1
                all_jobs.extend(found)
            if progress_callback and checked % 20 == 0:
                progress_callback(checked, total, hits)

    # Filter out non-US and on-site non-local jobs
    before = len(all_jobs)
    all_jobs = [
        j for j in all_jobs
        if not _is_non_us(j.get("location", ""), j.get("description", ""), j.get("title", ""))
        and not _is_onsite_non_local(j.get("location", ""), j.get("description", ""))
    ]

    return all_jobs
