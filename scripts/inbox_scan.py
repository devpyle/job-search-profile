#!/usr/bin/env python3
"""Scan the Gmail inbox for job-search correspondence and reconcile with the board.

Uses Gmail IMAP (app password in gitignored config.py). Pre-filters with Gmail's
own search syntax (X-GM-RAW) to rejection/interview-signal mail in a recent
window, then matches each message to a company on the Kanban board and classifies
it as a rejection, an interview/next-step, or other.

Default is REPORT-ONLY: it prints what it found and changes nothing. Pass
--apply to auto-update matched active jobs to Rejected (interviews are always
reported, never auto-moved — those deserve your eyes).

    python3 scripts/inbox_scan.py                 # report only, last 14 days
    python3 scripts/inbox_scan.py --days 30
    python3 scripts/inbox_scan.py --apply          # also mark clear rejections Rejected
"""
import argparse
import email
import imaplib
import re
import sqlite3
import sys
from email.header import decode_header, make_header
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))
from config import GMAIL_ADDRESS, GMAIL_APP_PASSWORD  # noqa: E402

DB_PATH = REPO_ROOT / "dashboard" / "data" / "jobs.db"

# Statuses where an inbound rejection/interview email is still meaningful.
ACTIVE = ("Reviewing", "Drafting", "Ready", "Applied", "Interviewing")

REJECT_PATTERNS = [
    r"not moving forward", r"won'?t be moving forward", r"not be moving forward",
    r"decided (?:not|to move forward with other)", r"other candidates",
    r"regret to inform", r"unfortunately", r"not (?:be )?select(?:ed|ing)",
    r"position has been filled", r"role has been filled", r"filled the (?:position|role)",
    r"pursue other", r"will not be proceeding", r"not to proceed",
    r"no longer (?:be )?consider", r"not a (?:match|fit) at this time",
    # "wish you" must be in a sign-off-to-a-search context; a receipt that says
    # "wish you the best of luck with your application" is NOT a rejection.
    r"wish you (?:the best|well|success|luck) (?:in|with|as you|wherever|on) (?:your )?(?:search|job|future|career|endeavors|next|continued|the)",
    r"keep your (?:resume|information) on file",
    # Softer Workday/Greenhouse/Lever templates that dodge the harsher phrases.
    # NOTE: keep these rejection-SPECIFIC. Footer boilerplate that also appears
    # in application receipts ("best of luck", "future opportunities", "join our
    # talent community", "encourage you to apply") was deliberately NOT included
    # here — it false-positives confirmations once the HTML body is readable.
    r"pursue other (?:applicants|candidates)", r"more closely (?:fit|match|align)",
    r"(?:tough|difficult|hard) decision", r"pursuing other (?:applicants|candidates)",
    r"other (?:applicants|candidates) (?:better|who|that|more)",
    r"decided to move forward with (?:other|another)", r"move forward with other",
    r"chosen to (?:move forward|proceed) with", r"selected (?:other|another)",
    r"not (?:be )?moving forward with your application",
    r"not to (?:move forward|proceed|advance)",
    r"will not be moving forward", r"not be advancing",
    r"do(?:es)? not align (?:at this time|with (?:our|the))",
    r"we (?:have )?decided to go (?:in a different|with)",
    r"not (?:be )?select(?:ed|ing) (?:you|your)", r"position (?:is )?no longer available",
]
INTERVIEW_PATTERNS = [
    r"schedule (?:a|an|some|your)", r"set up (?:a|some) time", r"availability",
    r"next steps?", r"move forward", r"would like to (?:speak|talk|chat|meet)",
    r"phone screen", r"interview", r"invite you", r"looking forward to speaking",
    r"book (?:a|some) time", r"calendar", r"times that work",
]

# Gmail search (X-GM-RAW) signal terms. Kept quote-free-friendly; the whole
# query is wrapped in one IMAP quoted string at call time (internal quotes
# escaped). Single high-signal words catch the mail; precise phrase matching
# happens in Python against the body below.
GM_SIGNAL = (
    '(unfortunately OR regret OR interview OR availability OR candidacy OR '
    'shortlisted OR "phone screen" OR "next steps" OR "moving forward" OR '
    '"your application" OR "no longer" OR '
    # Softer rejection templates the narrow set was missing (e.g. Workday's
    # "thank you for your interest ... pursue other applicants").
    '"your interest" OR "pursue other" OR "other applicants" OR '
    '"other candidates" OR "difficult decision" OR "tough decision" OR '
    '"move forward with other" OR "different direction" OR "future opportunities" OR '
    '"future endeavors" OR "wish you" OR "best of luck" OR "reached a decision" OR '
    '"careful review" OR "careful consideration" OR "talent community" OR '
    '"not to move forward" OR "position has been filled" OR "decided to")'
    ' -category:promotions'
)

# Generic words that appear in many company names AND in unrelated marketing
# mail — never distinctive enough to match on alone.
GENERIC = {
    "inc", "llc", "ltd", "corp", "co", "company", "companies", "group", "solutions",
    "solution", "software", "technology", "technologies", "systems", "financial",
    "finance", "bank", "banking", "digital", "the", "and", "for", "services",
    "service", "credit", "union", "federal", "national", "american", "global",
    "partners", "capital", "holdings", "insurance", "health", "care", "data",
    "cloud", "labs", "media", "risk", "title", "first", "enterprise", "affiliates",
    "management", "consulting", "int", "usa", "corporation", "network", "platform",
    "ai", "mutual", "app", "team", "hr", "io",
}

CONFIRM_PATTERNS = [
    r"thank you for applying", r"we(?:'ve| have)? received your application",
    r"received your application", r"application (?:has been )?received",
    r"thanks for applying", r"your application (?:was|has been) submitted",
]

# Applicant-tracking / recruiting-email domains. Mail from these is job-related;
# match the company via the sender display name or subject instead of the domain.
ATS_DOMAINS = (
    "greenhouse.io", "lever.co", "myworkday.com", "myworkdayjobs.com", "icims.com",
    "ashbyhq.com", "jobvite.com", "workable.com", "smartrecruiters.com", "taleo.net",
    "successfactors.com", "bamboohr.com", "hire.lever.co", "us.greenhouse-mail.io",
    "greenhouse-mail.io", "eightfold.ai", "paylocity.com", "dayforcehcm.com",
    "recruiting.com", "avature.net", "gr.hs-sites.com", "hireclick.com",
)


def norm_company(name: str) -> set:
    """Distinctive lowercase tokens in a company name (generic words removed)."""
    if not name:
        return set()
    name = re.sub(r"\(.*?\)", " ", name)          # drop parenthetical locations
    toks = re.findall(r"[a-z0-9]{2,}", name.lower())
    return {t for t in toks if t not in GENERIC and len(t) >= 2}


def decode(s) -> str:
    try:
        return str(make_header(decode_header(s or "")))
    except Exception:
        return s or ""


def body_text(msg) -> str:
    """Best-effort readable body, capped.

    Walks every text part and returns the longest. Critically this includes
    text/html: many ATS senders (Workday especially) ship HTML-only mail with
    no text/plain alternative, so a plain-text-only reader returned "" and the
    classifier saw only the subject — silently misfiling clear rejections as
    "other". HTML is decoded (handles base64/quoted-printable), stripped of
    style/head/script blocks, then de-tagged.
    """
    best = ""
    for p in msg.walk():
        ct = p.get_content_type()
        if ct not in ("text/plain", "text/html"):
            continue
        payload = p.get_payload(decode=True)
        if not payload:
            continue
        try:
            t = payload.decode(p.get_content_charset() or "utf-8", "ignore")
        except Exception:
            continue
        if ct == "text/html":
            t = re.sub(r"<(style|head|script)[^>]*>.*?</\1>", " ", t, flags=re.S | re.I)
            t = re.sub(r"<[^>]+>", " ", t)
            t = re.sub(r"&nbsp;|&zwnj;", " ", t)
            t = re.sub(r"&[a-z]+;|&#\d+;", " ", t)
        t = re.sub(r"\s+", " ", t).strip()
        if len(t) > len(best):
            best = t
    return best[:4000]


def classify(subject: str, body: str) -> str:
    blob = f"{subject}\n{body}".lower()
    # Conditional/future language in application receipts is not a decision:
    # "if you are not selected, you will be notified" must not read as a reject.
    blob = re.sub(r"(?:if|should|in the event|unless) [^.]*?not (?:be )?select[^.]*?\.", " ", blob)
    if any(re.search(p, blob) for p in REJECT_PATTERNS):
        # A rejection phrase wins even if the word "interview" appears in a footer.
        return "rejection"
    # Auto-acknowledgements read as "interview" on the word alone — pull them out.
    if any(re.search(p, blob) for p in CONFIRM_PATTERNS) and \
       not re.search(r"schedul|availability|calendar|book a time|times that work", blob):
        return "confirmation"
    if any(re.search(p, blob) for p in INTERVIEW_PATTERNS):
        return "interview"
    return "other"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--apply", action="store_true",
                    help="auto-mark clear rejections as Rejected on the board")
    args = ap.parse_args()

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    jobs = [dict(r) for r in conn.execute(
        f"SELECT id, company, title, status FROM jobs "
        f"WHERE status IN ({','.join('?'*len(ACTIVE))})", ACTIVE).fetchall()]
    # Pre-compute token sets, longest company names first for greedier matching.
    for j in jobs:
        j["_toks"] = norm_company(j["company"])
    jobs = [j for j in jobs if j["_toks"]]
    print(f"[scan] {len(jobs)} active jobs on the board", flush=True)

    M = imaplib.IMAP4_SSL("imap.gmail.com")
    M.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD.replace(" ", ""))
    M.select("INBOX")
    raw_q = f'{GM_SIGNAL} newer_than:{args.days}d'
    imap_q = '"' + raw_q.replace('"', '\\"') + '"'  # one IMAP quoted string
    typ, data = M.search(None, "X-GM-RAW", imap_q)
    ids = data[0].split()
    print(f"[scan] {len(ids)} signal emails in the last {args.days} days\n", flush=True)

    hits = {"rejection": [], "interview": [], "confirmation": [], "other": []}
    for num in ids:
        typ, msgdata = M.fetch(num, "(RFC822)")
        if not msgdata or not msgdata[0]:
            continue
        msg = email.message_from_bytes(msgdata[0][1])
        frm = decode(msg.get("From"))
        subj = decode(msg.get("Subject"))
        date = decode(msg.get("Date"))

        addr_m = re.search(r"[\w.+-]+@([\w.-]+)", frm)
        domain = (addr_m.group(1).lower() if addr_m else "")
        from_name = frm.split("<")[0].lower()
        is_ats = any(domain == d or domain.endswith("." + d) or domain.endswith(d)
                     for d in ATS_DOMAINS)

        # Match a board company to THIS sender, precisely:
        #  - own-domain mail: a distinctive company token appears in the domain
        #    (iqvia -> iqvia.com, q2 -> q2.com). Kills all marketing senders.
        #  - ATS mail: a distinctive token appears in the sender name or subject.
        namesubj = set(re.findall(r"[a-z0-9]{2,}", f"{from_name} {subj.lower()}"))
        labels = domain.split(".")
        sld = labels[-2] if len(labels) >= 2 else domain
        match = None
        for j in jobs:
            toks = j["_toks"]
            if not toks:
                continue
            # Own-domain: a company token IS a domain label, or the second-level
            # label starts with it (e.g. "cardflight" == label; "iqvia" in labels).
            on_domain = any(
                (len(t) >= 3 and t in labels) or t == sld or
                (len(t) >= 4 and sld.startswith(t))
                for t in toks)
            if not is_ats and on_domain:
                match = j
                break
            if is_ats and (toks & namesubj):
                match = j
                break
        if not match:
            continue

        body = body_text(msg)
        kind = classify(subj, body)
        hits[kind].append({
            "job": match, "from": frm, "subject": subj, "date": date})

    M.logout()

    def show(kind, emoji):
        rows = hits[kind]
        print(f"{emoji} {kind.upper()} ({len(rows)})", flush=True)
        for h in rows:
            j = h["job"]
            print(f"   • {j['company']} [{j['status']}] — {j['title'][:45]}", flush=True)
            print(f"     from: {h['from'][:70]}", flush=True)
            print(f"     subj: {h['subject'][:80]}", flush=True)
        print(flush=True)

    show("rejection", "❌")
    show("interview", "📅")
    print(f"✅ APPLICATION CONFIRMATIONS: {len(hits['confirmation'])} "
          f"(receipts, not actionable)", flush=True)
    print(f"•  OTHER / UNCLASSIFIED: {len(hits['other'])}\n", flush=True)

    # --apply never touches Interviewing/Offer: a reply in a live interview
    # thread routinely quotes text that trips the rejection patterns.
    SAFE_TO_AUTOREJECT = ("Reviewing", "Drafting", "Ready", "Applied")
    if args.apply and hits["rejection"]:
        updated, skipped = [], []
        for h in hits["rejection"]:
            j = h["job"]
            if j["status"] in SAFE_TO_AUTOREJECT:
                conn.execute(
                    "UPDATE jobs SET status='Rejected', status_changed_at=datetime('now') "
                    "WHERE id=? AND status=?", (j["id"], j["status"]))
                updated.append(j["company"])
            else:
                skipped.append(f"{j['company']} [{j['status']}]")
        conn.commit()
        print(f"[apply] marked Rejected: {', '.join(updated) or '(none)'}", flush=True)
        if skipped:
            print(f"[apply] SKIPPED (interview-stage, review by hand): "
                  f"{', '.join(skipped)}", flush=True)
    conn.close()


if __name__ == "__main__":
    main()
