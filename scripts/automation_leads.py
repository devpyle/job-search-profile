#!/usr/bin/env python3
"""
Automation-lead radar.

Finds LOCAL SMALL BUSINESSES hiring for repetitive, digitally-automatable roles (data
entry, bookkeeping/AP-AR, scheduling/dispatch, order entry, records, document handling).
The hiring post is a *budget signal*: they're about to spend ~$35-45K/yr on a person to
do work that can often be automated for a one-time build + a small retainer. Each such
post is a warm outbound lead for David's AI-automation consulting.

Pipeline (mirrors job_radar.py):
  1. Pull structured postings from Craigslist's search JSON API (sapi.craigslist.org) for
     a set of automatable-role queries, per metro area. No browser, no HTML scraping.
  2. Drop obvious non-targets (surveys, research studies, gig/data-labeling platforms,
     commission-only sales, staffing agencies, physical-labor roles) via negatives.
  3. Keep posts carrying an automatable signal; fetch each one's DETAIL record (body,
     authoritative lat/lon, real url, street/neighborhood, section).
  4. GEO-FILTER to the metro's bounding box (the area feed leaks cross-posted out-of-town
     listings), then regex-extract any phone/email from the body.
  5. Optionally enrich the shortlist with `claude -p`: automatability 1-10, is-it-a-real-
     -SMB, what to automate, an outreach angle, and a ready-to-send outreach draft.
  6. Write a ranked markdown lead sheet PER AREA to output/automation-leads/DATE-area.md

Usage:
  python3 scripts/automation_leads.py                       # Raleigh, keyword score only
  python3 scripts/automation_leads.py --score               # + claude enrichment + drafts
  python3 scripts/automation_leads.py --areas 36,41,61 --score --top 15
  python3 scripts/automation_leads.py --no-geo              # disable bounding-box filter
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / "output" / "automation-leads"

# load .env (ADZUNA_APP_ID/KEY, JSEARCH_API_KEY, GMAIL_*) and make report.send_email usable
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
try:
    from dotenv import load_dotenv
    load_dotenv(REPO / ".env")
except Exception:  # noqa: BLE001
    pass

# --- Craigslist metro area IDs (reference.craigslist.org/Areas) + geo bounding boxes ---
# bbox = (lat_min, lat_max, lon_min, lon_max) to fence out cross-posted out-of-town ads
AREAS = {
    36: ("raleigh",    "raleigh / durham / CH", (35.55, 36.20, -79.30, -78.20)),
    41: ("charlotte",  "charlotte, NC",         (34.95, 35.55, -81.15, -80.50)),
    61: ("greensboro", "greensboro / triad",    (35.80, 36.25, -80.15, -79.50)),
}

# David's one-liner, handed to claude so the outreach draft is grounded and consistent.
DAVID_BIO = ("David Myers — 15 years in fintech/banking as a product owner and systems "
             "analyst; now builds custom AI automations (LLM document processing, system "
             "integrations, workflow scripts) for small businesses. Portfolio: "
             "davidmyers.work")

# Adzuna: per-metro "where" string + a focused automatable-role query set (keep the
# call count modest — ~12 queries x N metros x 2 runs/day stays inside the free tier).
ADZ_WHERE = {36: "Raleigh, North Carolina",
             41: "Charlotte, North Carolina",
             61: "Greensboro, North Carolina"}
ADZ_QUERIES = [
    "data entry", "bookkeeper", "administrative assistant", "office manager",
    "accounts payable", "accounts receivable", "invoice specialist",
    "scheduling coordinator", "medical records", "order entry clerk",
    "dispatcher", "billing specialist",
]

# Roles whose day-to-day is largely repetitive digital task-movement -> automatable.
QUERIES = [
    "data entry", "data entry clerk", "administrative assistant", "office assistant",
    "scheduling coordinator", "appointment scheduler", "billing", "invoice",
    "accounts payable", "accounts receivable", "bookkeeper", "quickbooks",
    "order entry", "order processing", "medical records", "insurance verification",
    "records clerk", "transcription", "dispatcher", "claims processor",
    "office manager", "receptionist",
]

# If any appears in title/company, it's NOT a consulting lead.
NEGATIVE = [
    "survey", "surveys", "surveyor", "study", "studies", "participant", "research study",
    "focus group", "ai training", "video conversation", "conversation partner",
    "data annotation", "labeling", "labelling", "mturk", "user testing", "usertesting",
    "commission only", "commission-only", "100% commission", "uncapped commission",
    "mlm", "entry level sales", "sales trainee", "outside sales", "door to door",
    "driver", "cdl", "delivery", "warehouse", "forklift", "technician", "mechanic",
    "lube", "tire", "cleaner", "cleaning", "janitor", "housekeep", "server", "cashier",
    "cook", "line cook", "barista", "landscap", "construction", "roofing", "hvac install",
    "nurse", "cna", "caregiver", "security guard", "temp agency", "staffing",
]

# Company-name substrings that are never a consulting target: staffing/recruiting
# agencies (they're intermediaries, not the end business) and large enterprises that
# recur in the feeds. Matched against the company name only.
COMPANY_BLOCK = [
    # staffing / recruiting agencies
    "robert half", "accountemps", "insight global", "gpac", "aerotek", "randstad",
    "adecco", "teksystems", "kelly services", "manpower", "kforce", "addison group",
    "creative financial staffing", "cfs", "vaco", "beacon hill", "express employment",
    "spherion", "ledgent", "roth staffing", "ultimate staffing", "michael page",
    "robert walters", "lucas group", "hays", "integrity staffing", "trueblue",
    "staffmark", "nesco", "onward search", "motion recruitment", "jobot", "snelling",
    "apex systems", "apex focus group", "the judge group", "system one", "collabera",
    "recruit", "staffing", "talent", "personnel",
    # large enterprises that keep surfacing (not SMBs)
    "martin marietta", "pella", "centerwell", "humana", "gallagher", "leidos",
    "rent a center", "wells fargo", "bank of america", "truist", "lowe's", "honeywell",
    "siemens", "deloitte", "pwc", "kpmg", "ernst", "accenture", "cognizant", "infosys",
    "wipro", "cvs health", "walgreens", "unitedhealth", "optum", "novant", "atrium health",
    "wake county", "allen harim",
]

# Automatable signal -> role is heavy on moving structured data / scheduling / documents.
POSITIVE = [
    "data entry", "data-entry", "spreadsheet", "excel", "quickbooks", "reconcile",
    "reconciliation", "invoice", "invoicing", "billing", "accounts payable",
    "accounts receivable", "a/p", "a/r", "bookkeep", "posting payments", "order entry",
    "order processing", "purchase order", "schedule", "scheduling", "appointment",
    "calendar", "transcri", "medical records", "records", "insurance verification",
    "eligibility", "claims", "crm", "salesforce", "database", "filing", "file",
    "mailing", "mail merge", "inventory", "update", "enter", "input", "key in",
    "copy", "compile", "report", "reports", "forms", "form", "intake", "dispatch",
    "confirmations", "reminders", "follow-up", "follow up", "email", "portal",
]

_PHONE_RE = re.compile(r"(?<!\d)(?:\+?1[.\-\s]?)?\(?\d{3}\)?[.\-\s]?\d{3}[.\-\s]?\d{4}(?!\d)")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# ----------------------------------------------------------------------------- claude
# Strip ANTHROPIC_API_KEY so `claude -p` uses the Max subscription (OAuth), NOT the
# metered API. load_dotenv above pulls the key into os.environ; without this the CLI
# would bill the API key. Mirrors scripts/dashboard.py and scripts/rating.py.
_CLI_ENV = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
_CLI_ENV["PATH"] = os.pathsep.join(
    [str(Path.home() / ".npm-global/bin"), str(Path.home() / ".local/bin"),
     _CLI_ENV.get("PATH", "")])
_CLI_MODEL = "claude-sonnet-5"


def _resolve_claude() -> str:
    found = shutil.which("claude")
    if found:
        return found
    home = Path.home()
    for c in (home / ".npm-global/bin/claude", home / ".local/bin/claude",
              Path("/usr/local/bin/claude"), Path("/usr/bin/claude")):
        if c.exists():
            return str(c)
    return "claude"


_CLAUDE_BIN = _resolve_claude()
_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120 Safari/537.36")


# ------------------------------------------------------------------------- fetch/parse
def _get_json(url: str, tries: int = 4) -> dict | None:
    req = urllib.request.Request(url, headers={
        "User-Agent": _UA, "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9", "Referer": "https://www.craigslist.org/"})
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:  # noqa: PERF203
            if e.code == 403 and i < tries - 1:
                time.sleep(3.0 * (i + 1))  # backoff harder on rate-limit
                continue
            if i == tries - 1:
                print(f"  ! fetch failed: {e}", file=sys.stderr)
                return None
            time.sleep(1.5 * (i + 1))
        except Exception as e:  # noqa: BLE001
            if i == tries - 1:
                print(f"  ! fetch failed: {e}", file=sys.stderr)
                return None
            time.sleep(1.5 * (i + 1))
    return None


def _tagval(item: list, tag: int) -> str:
    for el in item:
        if isinstance(el, list) and len(el) == 2 and el[0] == tag:
            return str(el[1])
    return ""


def search(area_id: int, query: str) -> list[dict]:
    sub = AREAS.get(area_id, ("raleigh",))[0]
    url = ("https://sapi.craigslist.org/web/v8/postings/search/full"
           f"?batch={area_id}-0-360-0-0&cc=US&lang=en"
           f"&query={urllib.parse.quote(query)}&searchPath=jjj")
    data = (_get_json(url) or {}).get("data") or {}
    out = []
    for it in data.get("items") or []:
        if not isinstance(it, list) or not it:
            continue
        uuid = _tagval(it, 13)
        if not uuid:
            continue
        out.append({
            "uuid": uuid, "slug": _tagval(it, 6), "pay": _tagval(it, 7),
            "category": _tagval(it, 12), "company": _tagval(it, 8),
            "title": it[-1] if isinstance(it[-1], str) else "", "area": sub,
            "area_id": area_id, "source": "craigslist",
        })
    return out


def fetch_detail(uuid: str) -> dict | None:
    url = f"https://sapi.craigslist.org/web/v8/postings/{uuid}?lang=en&cc=US"
    data = (_get_json(url) or {}).get("data") or {}
    items = data.get("items") or []
    if not items:
        return None
    d = items[0]
    loc = d.get("location") or {}
    return {
        "url": d.get("url", ""),
        "body": d.get("body", "") or "",
        "section": d.get("section", ""),
        "lat": loc.get("lat"), "lon": loc.get("lon"),
        "addr": loc.get("displayAddress") or loc.get("description") or "",
        "posted": d.get("postedDate", ""),
    }


def adzuna_search(area_id: int) -> list[dict]:
    """Query Adzuna for automatable local roles. Results already carry description
    (body), lat/lon, company and a real url -- so they skip the CL detail fetch."""
    app_id = os.environ.get("ADZUNA_APP_ID", "")
    app_key = os.environ.get("ADZUNA_APP_KEY", "")
    where = ADZ_WHERE.get(area_id)
    if not (app_id and app_key and where):
        return []
    sub = AREAS[area_id][0]
    out, seen = [], set()
    for q in ADZ_QUERIES:
        try:
            r = urllib.request.Request(
                "https://api.adzuna.com/v1/api/jobs/us/search/1?" + urllib.parse.urlencode({
                    "app_id": app_id, "app_key": app_key, "what": q, "where": where,
                    "distance": 40, "max_days_old": 10, "results_per_page": 20,
                    "content-type": "application/json"}),
                headers={"User-Agent": _UA})
            with urllib.request.urlopen(r, timeout=12) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
        except Exception:  # noqa: BLE001
            continue
        for j in data.get("results", []):
            url = j.get("redirect_url", "")
            if not url or url in seen:
                continue
            seen.add(url)
            sal_min, sal_max = j.get("salary_min"), j.get("salary_max")
            pay = ""
            if sal_min and str(j.get("salary_is_predicted", "0")) != "1":
                pay = (f"${int(sal_min):,}–${int(sal_max):,}/yr" if sal_max
                       else f"${int(sal_min):,}/yr")
            out.append({
                "uuid": "", "slug": "", "source": "adzuna",
                "title": j.get("title", ""),
                "company": (j.get("company") or {}).get("display_name", ""),
                "category": (j.get("category") or {}).get("label", ""),
                "pay": pay, "url": url, "body": j.get("description", "") or "",
                "lat": j.get("latitude"), "lon": j.get("longitude"),
                "addr": (j.get("location") or {}).get("display_name", ""),
                "area": sub, "area_id": area_id,
            })
        time.sleep(0.3)
    return out


def extract_contact(body: str) -> tuple[str, str]:
    phones = _PHONE_RE.findall(body or "")
    emails = [e for e in _EMAIL_RE.findall(body or "")
              if "craigslist.org" not in e.lower()]
    return (phones[0] if phones else ""), (emails[0] if emails else "")


# ------------------------------------------------------------------------- scoring
def kw_score(post: dict) -> int:
    blob = (f"{post['title']} {post['company']} {post['category']} "
            f"{post.get('body', '')[:600]}").lower()
    return len({p for p in POSITIVE if p in blob})


def is_negative(post: dict) -> bool:
    blob = f"{post['title']} {post['company']} {post['category']}".lower()
    if any(n in blob for n in NEGATIVE):
        return True
    company = (post.get("company") or "").lower()
    return any(b in company for b in COMPANY_BLOCK)


def in_bbox(lat, lon, box) -> bool | None:
    if lat is None or lon is None:
        return None  # unknown -> keep but flag
    la0, la1, lo0, lo1 = box
    return la0 <= lat <= la1 and lo0 <= lon <= lo1


_SCORE_PROMPT = """You are qualifying an outbound lead for an AI-automation consultant and \
drafting his first-touch message. About him: {bio}

A GOOD lead is a REAL LOCAL SMALL/MID BUSINESS hiring for a role that is mostly repetitive, \
digital, rules-based work (moving data between systems, scheduling/dispatch, invoicing/AP-AR, \
order entry, records, document processing) -- that work can often be automated for a one-time \
build plus a small retainer instead of a ~$35-45K/yr hire. BAD leads: staffing/temp agencies, \
research studies, survey/gig/data-labeling platforms, commission sales, physical-labor roles, \
or large enterprises. If the company is a recognizable staffing/recruiting firm (e.g. Robert \
Half, Insight Global, Gpac, Aerotek, Randstad, Vaco) or a large national/public company, set \
real_smb=false regardless of how automatable the tasks are -- you can't sell a custom \
automation to a staffing agency's placement or to a Fortune-1000's back office this way.

Job post:
  Title:    {title}
  Company:  {company}
  Pay:      {pay}
  Location: {addr}
  Body:     {body}

Return ONLY compact JSON, no prose:
{{"automatable": <1-10 how much of this role is automatable digital task-work>,
 "real_smb": <true|false, genuine local small/mid business worth pitching>,
 "automate": "<one sentence: the specific workflow you'd automate>",
 "angle": "<one-sentence outreach hook referencing their pain>",
 "contact_name": "<person/role named in the body, or empty>",
 "draft": "<a ready-to-send outreach message, 4-6 sentences, warm and specific, not salesy: \
name the exact repetitive work from their post, explain you build automations that handle it \
for a one-time fee + small retainer instead of a full-time hire, and ask for a quick 15-min \
call. Sign as David Myers with davidmyers.work. Plain text, no placeholders left unfilled.>"}}"""


def claude_score(post: dict, timeout: int = 120) -> dict | None:
    prompt = _SCORE_PROMPT.format(
        bio=DAVID_BIO, title=post["title"] or "(none)",
        company=post["company"] or "(none)", pay=post["pay"] or "(not listed)",
        addr=post.get("addr") or "(none)", body=(post.get("body") or "")[:1800])
    try:
        r = subprocess.run([_CLAUDE_BIN, "-p", prompt, "--model", _CLI_MODEL],
                           capture_output=True, text=True, env=_CLI_ENV, timeout=timeout)
        if r.returncode != 0:
            return None
        txt = r.stdout.strip()
        s, e = txt.find("{"), txt.rfind("}")
        return json.loads(txt[s:e + 1]) if s != -1 and e != -1 else None
    except Exception:  # noqa: BLE001
        return None


# ------------------------------------------------------------------------- report
def write_report(area_id: int, kept: list[dict], n_raw: int, scored: bool) -> Path:
    sub, desc, _ = AREAS[area_id]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    today = dt.date.today().isoformat()
    path = OUT_DIR / f"{today}-{sub}.md"
    L = [f"# Automation-lead radar — {desc} — {today}", ""]
    L.append(f"{n_raw} unique postings → **{len(kept)} candidate leads** "
             "(local SMBs hiring for automatable roles, geo-filtered to the metro).")
    L.append("")
    L.append("Each lead is a business about to spend ~$35–45K/yr on a person to do work "
             "you can likely automate for a one-time build + retainer.")
    L.append("")
    for i, p in enumerate(kept, 1):
        ai = p.get("ai") or {}
        score = ai.get("automatable")
        tag = f" — automatable **{score}/10**" if score else f" — kw {p['kw']}"
        flag = "" if in_bbox(p.get("lat"), p.get("lon"), AREAS[area_id][2]) is not False else ""
        L.append(f"## {i}. {p['title']}{tag}")
        L.append(f"- **Business:** {p['company'] or '(not named in post)'}")
        loc = p.get("addr") or ""
        geo = "geo unverified" if p.get("lat") is None else f"{p['lat']:.3f},{p['lon']:.3f}"
        L.append(f"- **Pay:** {p['pay'] or '(not listed)'}  ·  **Where:** {loc or p['area']} ({geo})")
        L.append(f"- **Category:** {p['category'] or '—'}  ·  **Source:** {p.get('source', '—')}")
        contact = []
        if p.get("phone"):
            contact.append(f"📞 {p['phone']}")
        if p.get("email"):
            contact.append(f"✉️ {p['email']}")
        if ai.get("contact_name"):
            contact.append(f"👤 {ai['contact_name']}")
        L.append(f"- **Contact:** {'  ·  '.join(contact) if contact else 'via Craigslist reply relay'}")
        L.append(f"- **Post:** {p.get('url') or '(n/a)'}")
        if ai:
            if not ai.get("real_smb", True):
                L.append("- ⚠️ _flagged: may not be a genuine SMB target_")
            if ai.get("automate"):
                L.append(f"- **Automate:** {ai['automate']}")
            if ai.get("angle"):
                L.append(f"- **Outreach angle:** {ai['angle']}")
            if ai.get("draft"):
                L.append("- **Draft outreach:**")
                L.append("")
                L.append("  > " + ai["draft"].replace("\n", "\n  > "))
        L.append("")
    path.write_text("\n".join(L), encoding="utf-8")
    return path


# ------------------------------------------------------------------------- main
def _dedup_key(p: dict) -> str:
    return re.sub(r"[^a-z0-9]", "", f"{p.get('company', '')}{p.get('title', '')}".lower())


def scan_area(area_id: int, args) -> list[dict]:
    sub = AREAS[area_id][0]
    sources = set(args.sources.split(","))

    # ---- collect from each enabled source into one candidate pool
    pool: dict[str, dict] = {}
    if "craigslist" in sources:
        print(f"[{sub}] craigslist: {len(QUERIES)} queries...", file=sys.stderr)
        cl: dict[str, dict] = {}
        for q in QUERIES:
            for p in search(area_id, q):
                cl.setdefault(p["uuid"], p)
            time.sleep(0.4)
        for p in cl.values():
            pool.setdefault(_dedup_key(p) or p["uuid"], p)
    if "adzuna" in sources:
        az = adzuna_search(area_id)
        print(f"[{sub}] adzuna: {len(az)} postings", file=sys.stderr)
        for p in az:
            pool.setdefault(_dedup_key(p) or p["url"], p)  # CL wins ties (added first)

    posts = list(pool.values())
    kept = [p for p in posts if not is_negative(p)]
    for p in kept:
        p["kw"] = kw_score(p)
    kept = [p for p in kept if p["kw"] >= args.min_kw]
    kept.sort(key=lambda x: x["kw"], reverse=True)
    kept = kept[:args.max_detail]
    print(f"[{sub}] {len(posts)} unique → {len(kept)} keyword candidates; "
          "detailing + geo-filtering...", file=sys.stderr)

    # ---- enrich: CL posts need a detail fetch (body/geo/url); adzuna already has them
    box = AREAS[area_id][2]
    local = []
    for p in kept:
        if p.get("source") == "craigslist" and p.get("uuid"):
            p.update(fetch_detail(p["uuid"]) or {})
            time.sleep(1.2)  # detail endpoint rate-limits
        p["phone"], p["email"] = extract_contact(p.get("body", ""))
        if in_bbox(p.get("lat"), p.get("lon"), box) is False and not args.no_geo:
            continue  # confirmed out-of-metro
        local.append(p)
    print(f"[{sub}] {len(local)} leads inside the metro box", file=sys.stderr)

    if args.score and local:
        for i, p in enumerate(local[:args.top]):
            print(f"[{sub}] scoring {i+1}/{min(args.top, len(local))}: "
                  f"{p['title'][:48]}", file=sys.stderr)
            p["ai"] = claude_score(p)
        local.sort(key=lambda x: (x.get("ai") or {}).get("automatable", -1)
                   if x.get("ai") else -1, reverse=True)

    path = write_report(area_id, local, len(posts), args.score)
    print(f"[{sub}] wrote {path}  ({len(local)} leads)")
    return local


def build_digest(results: dict[int, list[dict]]) -> str:
    """A concise email body: genuine leads (scored >=5 and not flagged) per metro."""
    today = dt.date.today().isoformat()
    L = [f"Automation-lead radar — {today}", ""]
    total = 0
    for aid, leads in results.items():
        good = [p for p in leads if (p.get("ai") or {}).get("automatable", 0) >= 5
                and (p.get("ai") or {}).get("real_smb", True)]
        total += len(good)
        L.append(f"== {AREAS[aid][1]} — {len(good)} strong lead(s) "
                 f"of {len(leads)} local ==")
        if not good:
            L.append("  (nothing strong today)")
        for p in good:
            ai = p["ai"]
            L.append(f"  • [{ai['automatable']}/10] {p['title']} — "
                     f"{p['company'] or 'unnamed'}  ({p['pay'] or 'pay n/a'})")
            contact = p.get("phone") or p.get("email") or "CL reply relay"
            L.append(f"      where: {p.get('addr') or p['area']}  ·  contact: {contact}"
                     f"  ·  src: {p.get('source', '—')}")
            L.append(f"      {p['url']}")
            if ai.get("angle"):
                L.append(f"      angle: {ai['angle']}")
        L.append("")
    L.insert(1, f"{total} strong lead(s) across {len(results)} metro(s). "
                "Full sheets + ready-to-send drafts in output/automation-leads/.")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--areas", default="36",
                    help="CL area IDs: 36=Raleigh,41=Charlotte,61=Greensboro")
    ap.add_argument("--sources", default="craigslist,adzuna",
                    help="comma list: craigslist,adzuna")
    ap.add_argument("--score", action="store_true", help="claude enrichment + outreach drafts")
    ap.add_argument("--email", action="store_true", help="email the digest via report.send_email")
    ap.add_argument("--top", type=int, default=15, help="how many leads to claude-score")
    ap.add_argument("--min-kw", type=int, default=1, help="min keyword hits to keep")
    ap.add_argument("--max-detail", type=int, default=40,
                    help="cap keyword candidates that get a detail fetch")
    ap.add_argument("--no-geo", action="store_true", help="disable bounding-box filter")
    args = ap.parse_args()

    results: dict[int, list[dict]] = {}
    for aid in (int(a) for a in args.areas.split(",") if a.strip()):
        if aid not in AREAS:
            print(f"skip unknown area {aid}", file=sys.stderr)
            continue
        results[aid] = scan_area(aid, args)

    if args.email and results:
        try:
            from report import send_email
            body = build_digest(results)
            n = sum(len([p for p in v if (p.get("ai") or {}).get("automatable", 0) >= 5
                         and (p.get("ai") or {}).get("real_smb", True)]) for v in results.values())
            send_email(f"Automation leads — {n} strong ({dt.date.today().isoformat()})", body)
            print(f"emailed digest ({n} strong leads)")
        except Exception as e:  # noqa: BLE001
            print(f"! email failed: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
