#!/usr/bin/env python3
"""
Job Search Dashboard — Kanban board for tracking applications + resume/CL generation.

Run:  python3 scripts/dashboard.py
Open: http://localhost:5000

Dependencies:
    pip install flask python-docx anthropic requests python-dotenv
"""

import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import anthropic
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from dotenv import load_dotenv
from flask import (Flask, g, jsonify, redirect, render_template,
                   request, send_file, url_for)

load_dotenv()

from startup import validate
validate(
    env_optional={"ANTHROPIC_API_KEY": "AI-powered document generation"},
    config_attrs=["CANDIDATE_NAME", "JOB_DOCS", "HOME_METRO_TERMS", "HOME_CITY"],
    script_name="dashboard.py",
)

# ── PATHS ─────────────────────────────────────────────────────────────────────

REPO_ROOT   = Path(__file__).parent.parent
DOCS_DIR    = REPO_ROOT / "docs"
OUTPUT_DIR  = REPO_ROOT / "output" / "job-radar"
DASH_DIR    = REPO_ROOT / "dashboard"
DB_PATH     = DASH_DIR / "data" / "jobs.db"
EXPORT_DIR  = REPO_ROOT / "output" / "documents"

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# ── PERSONAL CONFIG (from config.py) ──────────────────────────────────────────
sys.path.insert(0, str(REPO_ROOT))
from config import CANDIDATE_NAME, JOB_DOCS, HOME_METRO_TERMS, HOME_CITY  # noqa: E402
from portal_scanner import scan_all as portal_scan_all  # noqa: E402
import db as data  # noqa: E402

# ── KANBAN COLUMNS ────────────────────────────────────────────────────────────

STATUSES = [
    "New", "Reviewing", "Drafting", "Ready",
    "Applied", "Interviewing", "Offer",
    "Accepted", "Rejected", "Passed",
]
APP_STATUSES       = ["New", "Reviewing", "Drafting", "Ready", "Applied"]
INTERVIEW_STATUSES = ["Interviewing", "Offer"]
END_STATUSES       = ["Accepted", "Rejected", "Passed"]
ACTIVE_STATUSES    = APP_STATUSES  # kept for any legacy references

STATUS_COLORS = {
    "New":          "#94a3b8",
    "Reviewing":    "#3b82f6",
    "Drafting":     "#8b5cf6",
    "Ready":        "#10b981",
    "Applied":      "#06b6d4",
    "Interviewing": "#f97316",
    "Offer":        "#84cc16",
    "Accepted":     "#22c55e",
    "Rejected":     "#ef4444",
    "Passed":       "#6b7280",
}

# ── FLASK APP ─────────────────────────────────────────────────────────────────

app = Flask(
    __name__,
    template_folder=str(DASH_DIR / "templates"),
    static_folder=str(DASH_DIR / "static"),
)
app.secret_key = "job-search-dashboard-local"

# ── DATABASE ──────────────────────────────────────────────────────────────────

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(str(DB_PATH))
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(error):
    db = g.pop("db", None)
    if db:
        db.close()

def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    data.init_schema(conn)
    conn.close()

# ── REPORT PARSER ─────────────────────────────────────────────────────────────

def job_id_from_url(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()[:8]

def list_reports() -> list[dict]:
    files = sorted(OUTPUT_DIR.glob("[0-9][0-9][0-9][0-9]-*.md"), reverse=True)
    reports = []
    for f in files:
        if f.name.startswith("."):
            continue
        parts = f.stem.split("-")
        if len(parts) >= 4:
            date_str = "-".join(parts[:3])
            slot     = parts[3].upper()
            reports.append({
                "filename": f.name,
                "date":     date_str,
                "slot":     slot,
                "path":     str(f),
            })
    return reports

def parse_report(filepath: str) -> list[dict]:
    """Parse a radar .md file into a list of job dicts."""
    text = Path(filepath).read_text(encoding="utf-8")

    fname       = Path(filepath).stem
    parts       = fname.split("-")
    report_date = "-".join(parts[:3]) if len(parts) >= 3 else ""
    report_slot = parts[3].upper()    if len(parts) >= 4 else ""
    report_file = Path(filepath).name

    TIER_LABELS = {
        # Tier label mapping
        "APPLY NOW":    "Apply Now",
        "WORTH A LOOK": "Worth a Look",
        "WEAK MATCH":   "Weak Match",
        "FILTERED OUT": "Skip",
        # Casey's tier names
        "PERFECT FIT":  "Apply Now",
        "GOOD FIT":     "Worth a Look",
        "SKIP":         "Skip",
    }

    jobs: list[dict] = []
    current_tier = "Unknown"
    in_filtered  = False

    # Split on the ─── divider lines
    sections = re.split(r"\n[─\-]{20,}\n", text)

    for section in sections:
        section = section.strip()
        if not section:
            continue

        # Detect tier header (short section with a known label)
        upper = section.upper()
        matched = None
        for key, val in TIER_LABELS.items():
            if key in upper and len(section) < 100:
                matched = val
                break
        if matched:
            current_tier = matched
            in_filtered  = matched in ("Skip", "Weak Match")
            continue

        if in_filtered:
            # Compact format:  ✗/⚠️ TITLE — COMPANY  [reason]\n   URL
            pending_job: Optional[dict] = None
            for line in section.split("\n"):
                line = line.strip()
                if not line:
                    continue
                if line.startswith("✗") or line.startswith("⚠") or line.startswith("⛔"):
                    line = re.sub(r"^[✗⚠⛔️\s]+", "", line).strip()
                    reason_match = re.search(r"\[([^\]]+)\]\s*$", line)
                    reason = reason_match.group(1) if reason_match else ""
                    if reason_match:
                        line = line[:reason_match.start()].strip()
                    if " — " in line:
                        title_part, company_part = line.split(" — ", 1)
                    else:
                        title_part, company_part = line, ""
                    pending_job = {
                        "title": title_part.strip(), "company": company_part.strip(),
                        "location": "", "salary": "", "reason": reason,
                        "description": "", "posted": "", "source": "",
                        "url": "", "tier": current_tier,
                        "report_date": report_date, "report_slot": report_slot,
                        "report_file": report_file, "job_id": "",
                    }
                    jobs.append(pending_job)
                elif line.startswith("http") and jobs and not jobs[-1]["url"]:
                    jobs[-1]["url"]    = line
                    jobs[-1]["job_id"] = job_id_from_url(line)
        else:
            # Full format — jobs separated by blank lines
            blocks = re.split(r"\n\n+", section)
            for block in blocks:
                block = block.strip()
                if not block:
                    continue
                lines = block.split("\n")
                if len(lines) < 2:
                    continue

                job: dict = {
                    "title": "", "company": "", "location": "", "salary": "",
                    "reason": "", "description": "", "posted": "", "source": "",
                    "url": "", "tier": current_tier,
                    "report_date": report_date, "report_slot": report_slot,
                    "report_file": report_file, "job_id": "",
                }

                # Line 0: [📍 ]TITLE — COMPANY (LOCATION)
                header = re.sub(r"^📍\s*", "", lines[0]).strip()
                loc_m  = re.search(r"\(([^)]+)\)\s*$", header)
                if loc_m:
                    job["location"] = loc_m.group(1)
                    header = header[:loc_m.start()].strip()
                if " — " in header:
                    t, c = header.split(" — ", 1)
                    job["title"]   = t.strip()
                    job["company"] = c.strip()
                else:
                    job["title"] = header.strip()

                idx = 1
                # Line 1: ↳ REASON
                if idx < len(lines) and lines[idx].startswith("↳"):
                    job["reason"] = lines[idx][1:].strip()
                    idx += 1

                # Lines until Salary: or 🔗 = description snippet
                desc_parts = []
                while idx < len(lines) and not lines[idx].startswith("Salary:") and "🔗" not in lines[idx]:
                    desc_parts.append(lines[idx].strip())
                    idx += 1
                job["description"] = " ".join(desc_parts).strip()

                # Metadata: Salary: X | Posted: Y | Source: Z
                if idx < len(lines) and lines[idx].startswith("Salary:"):
                    for part in lines[idx].split(" | "):
                        part = part.strip()
                        if part.startswith("Salary:"):   job["salary"] = part[7:].strip()
                        elif part.startswith("Posted:"):  job["posted"] = part[7:].strip()
                        elif part.startswith("Source:"):  job["source"] = part[7:].strip()
                    idx += 1

                # URL: 🔗 URL
                if idx < len(lines) and "🔗" in lines[idx]:
                    url = lines[idx].replace("🔗", "").strip()
                    job["url"]    = url
                    job["job_id"] = job_id_from_url(url) if url else ""

                if job["title"] and job["url"]:
                    jobs.append(job)

    return [j for j in jobs if j["job_id"]]

# ── DOC GENERATION ────────────────────────────────────────────────────────────
ALWAYS_EXCL = {"pre-2011-early-career.md", "job-search-strategy.md"}

def _read_doc(filename: str) -> str:
    p = DOCS_DIR / filename
    return p.read_text(encoding="utf-8") if p.exists() else ""


def generate_documents(job: dict, instructions: str = "") -> dict:
    """Call Claude Sonnet to generate resume + cover letter markdown."""
    rules    = _read_doc("resume-generation-rules.md")
    personal = _read_doc("personal-info.md")
    skills   = _read_doc("technical-skills.md")
    edu      = _read_doc("education.md")

    history_parts = [_read_doc(f) for f in JOB_DOCS]
    history = "\n\n---\n\n".join(p for p in history_parts if p)

    regen_block = f"\n\nSPECIAL INSTRUCTIONS:\n{instructions}" if instructions else ""

    prompt = f"""You are generating a tailored resume and cover letter for {CANDIDATE_NAME}.

RESUME GENERATION RULES (follow all exactly):
{rules}

ADDITIONAL RULES (these override the rules above where they conflict):
- Output format: clean Markdown — NOT HTML. The output will be converted to DOCX.
- Jobs MUST be listed in strict chronological order, newest to oldest.
- For each job, curate only the most relevant achievements for THIS specific role. Do not dump all bullets — select and tailor.
- Resume structure: # Name / contact line / ## Summary / ## Experience / ### Job Title sections / ## Skills / ## Education
- Cover letter: plain paragraphs only — date, greeting, 3-4 body paragraphs, sign-off. No markdown headers.
- Respond ONLY with a valid JSON object — no preamble, no explanation, no markdown fences.
- JSON format: {{"resume": "...", "cover_letter": "..."}}
- Do NOT use **bold** or any other inline emphasis inside bullet points or the summary. Plain text only for all bullets and the summary paragraph. Bold in bullets looks like AI wrote it.
- Use - for bullet points.
- Company name and dates go on the line directly below the ### Job Title line, formatted as: **Company Name** | Location | Start – End

ATS KEYWORD OPTIMIZATION:
Before writing, extract 15-20 key terms from the job description — specific technologies, methodologies, domain concepts, and role-specific phrases the ATS will scan for. Then naturally weave those terms into the resume and cover letter by reformulating existing experience to use the JD's vocabulary. Rules:
- NEVER invent experience. Only rephrase what is already in the work history.
- If the JD says "payment orchestration" and the work history says "payment routing and processing," use "payment orchestration" instead.
- If the JD says "RTP" or "FedNow" and the candidate has real-time payments experience, name those rails explicitly.
- Concentrate keywords in the Summary and the most relevant job bullets.
- Include a Skills section that mirrors the JD's terminology where the candidate has genuine proficiency.
- Do not keyword-stuff — every term must read naturally in context.
{regen_block}

CANDIDATE PERSONAL INFO:
{personal}

EDUCATION:
{edu}

TECHNICAL SKILLS:
{skills}

WORK HISTORY (newest to oldest — use in this order, do not reorder):
{history}

JOB TO TARGET:
Title:    {job.get('title', '')}
Company:  {job.get('company', '')}
Location: {job.get('location', '')}
Description:
{job.get('description', '(no description provided)')}

Generate the resume and cover letter. Return ONLY the JSON object."""

    result = subprocess.run(
        ["claude", "-p", prompt],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude CLI error: {result.stderr[:300]}")

    raw   = result.stdout.strip()
    raw   = raw.replace("```json", "").replace("```", "").strip()
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        data = json.loads(match.group())
        return {
            "resume":       data.get("resume", ""),
            "cover_letter": data.get("cover_letter", ""),
        }
    raise ValueError(f"Could not parse Claude response: {raw[:300]}")


def generate_fit_analysis(job: dict) -> dict:
    """Call Claude to produce a structured fit analysis for a job."""
    personal = _read_doc("personal-info.md")
    skills   = _read_doc("technical-skills.md")
    history_parts = [_read_doc(f) for f in JOB_DOCS]
    history = "\n\n---\n\n".join(p for p in history_parts if p)

    prompt = f"""You are analyzing how well {CANDIDATE_NAME}'s experience matches a job posting.

CANDIDATE PROFILE:
{personal}

TECHNICAL SKILLS:
{skills}

WORK HISTORY (includes Key Achievements and Signature Stories in STAR format):
{history}

JOB POSTING:
Title:    {job.get('title', '')}
Company:  {job.get('company', '')}
Location: {job.get('location', '')}
Description:
{job.get('description', '(no description provided)')}

Produce a fit analysis as a JSON object with these fields:

1. "match_score": A number 1-10. Be honest — a 7 means strong match with minor gaps, a 5 means significant gaps.

2. "matches": A markdown list mapping each major JD requirement to specific experience from the work history. Format each as:
   - **JD Requirement** — matching experience from specific role. Be specific with details.
   Only include requirements where there IS a real match.

3. "gaps": A markdown list of JD requirements the candidate does NOT directly match, with a mitigation strategy for each. Format:
   - **Gap** — mitigation: how adjacent experience or transferable skills could address this.
   If there are no gaps, say "No significant gaps identified."

4. "stories": Pick 3-5 Signature Stories (STAR format) from the work history that are most relevant to THIS job's requirements. For each, write:
   - **Story title** (from which role) — why it's relevant to this JD
   Then reproduce the STAR story verbatim from the work history.

5. "summary": 2-3 sentence overall assessment. What's the strongest selling point? What's the biggest risk?

Return ONLY a valid JSON object with keys: match_score, matches, gaps, stories, summary.
No markdown fences, no preamble."""

    result = subprocess.run(
        ["claude", "-p", prompt],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude CLI error: {result.stderr[:300]}")

    raw   = result.stdout.strip()
    raw   = raw.replace("```json", "").replace("```", "").strip()
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        data = json.loads(match.group())
        return {
            "match_score": data.get("match_score", 0),
            "matches":     data.get("matches", ""),
            "gaps":        data.get("gaps", ""),
            "stories":     data.get("stories", ""),
            "summary":     data.get("summary", ""),
        }
    raise ValueError(f"Could not parse fit analysis response: {raw[:300]}")


# ── DOCX EXPORT ───────────────────────────────────────────────────────────────

def _add_formatted_run(paragraph, text: str, size: int = 11,
                        bold: bool = False, italic: bool = False,
                        color: Optional[tuple] = None):
    run = paragraph.add_run(text)
    run.font.name  = "Calibri"
    run.font.size  = Pt(size)
    run.font.bold  = bold
    run.font.italic = italic
    if color:
        run.font.color.rgb = RGBColor(*color)
    return run

def _inline_runs(paragraph, text: str, size: int = 11, base_color=None):
    """Parse **bold** and *italic* inline markers and add runs."""
    pattern = re.compile(r"\*\*(.+?)\*\*|\*(.+?)\*")
    last = 0
    for m in pattern.finditer(text):
        if m.start() > last:
            _add_formatted_run(paragraph, text[last:m.start()], size=size, color=base_color)
        content  = m.group(1) or m.group(2)
        is_bold  = m.group(1) is not None
        _add_formatted_run(paragraph, content, size=size, bold=is_bold,
                           italic=not is_bold, color=base_color)
        last = m.end()
    if last < len(text):
        _add_formatted_run(paragraph, text[last:], size=size, color=base_color)

def _add_rule(doc):
    """Thin horizontal rule above section headers."""
    p   = doc.add_paragraph()
    pPr = p._p.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    top  = OxmlElement("w:top")
    top.set(qn("w:val"),   "single")
    top.set(qn("w:sz"),    "4")
    top.set(qn("w:space"), "1")
    top.set(qn("w:color"), "AAAAAA")
    pBdr.append(top)
    pPr.append(pBdr)
    p.paragraph_format.space_before = Pt(8)
    p.paragraph_format.space_after  = Pt(2)
    return p

BLUE = (31, 73, 125)

def markdown_to_docx(md_text: str) -> Document:
    """Convert resume/cover-letter markdown to a python-docx Document."""
    doc = Document()

    # Page margins
    for section in doc.sections:
        section.top_margin    = Inches(0.75)
        section.bottom_margin = Inches(0.75)
        section.left_margin   = Inches(0.85)
        section.right_margin  = Inches(0.85)

    # Remove default empty paragraph
    for el in list(doc.element.body):
        doc.element.body.remove(el)

    lines = md_text.split("\n")
    i     = 0
    while i < len(lines):
        raw = lines[i]
        s   = raw.strip()

        if not s:
            i += 1
            continue

        if s.startswith("# "):
            # Name — large, centered, blue
            p   = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            _add_formatted_run(p, s[2:].strip(), size=22, bold=True, color=BLUE)
            p.paragraph_format.space_after = Pt(2)

        elif s.startswith("## "):
            # Section header — small caps style, blue, with rule above
            _add_rule(doc)
            p = doc.add_paragraph()
            _add_formatted_run(p, s[3:].strip().upper(), size=10, bold=True, color=BLUE)
            p.paragraph_format.space_after = Pt(3)

        elif s.startswith("### "):
            # Job title
            p = doc.add_paragraph()
            _add_formatted_run(p, s[4:].strip(), size=11, bold=True)
            p.paragraph_format.space_before = Pt(6)
            p.paragraph_format.space_after  = Pt(1)

        elif s == "---":
            pass  # skip markdown HRs (we use _add_rule before ## headers)

        elif s.startswith("- "):
            # Bullet
            p = doc.add_paragraph(style="List Bullet")
            _inline_runs(p, s[2:].strip())
            p.paragraph_format.space_after = Pt(2)

        else:
            # Normal paragraph — centered for first 3 lines (contact info), left-aligned after
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER if i < 4 else WD_ALIGN_PARAGRAPH.LEFT
            _inline_runs(p, s)
            p.paragraph_format.space_after = Pt(3)

        i += 1

    return doc

# ── STORY BANK PARSER ─────────────────────────────────────────────────────────

def _parse_stories_from_docs() -> list[dict]:
    """Extract Signature Story (STAR) sections from all job docs."""
    stories = []
    for filename in JOB_DOCS:
        text = _read_doc(filename)
        if not text:
            continue

        # Extract company/title from frontmatter
        company = title = ""
        for line in text.split("\n"):
            if line.startswith("company:"):
                company = line.split(":", 1)[1].strip().strip('"')
            elif line.startswith("title:"):
                title = line.split(":", 1)[1].strip().strip('"')

        # Find Signature story section
        sig_match = re.search(
            r"## Signature stor(?:y|ies)\s*\(STAR(?:\s+format)?\)\s*\n(.*?)(?=\n## |\Z)",
            text, re.DOTALL,
        )
        if not sig_match:
            continue

        body = sig_match.group(1).strip()

        # Check for ### sub-stories (multiple stories per role)
        sub_stories = re.split(r"### (.+)\n", body)
        if len(sub_stories) > 1:
            # sub_stories = ['', 'Story 1 — title', 'content', 'Story 2 — title', 'content', ...]
            for i in range(1, len(sub_stories), 2):
                story_title = sub_stories[i].strip()
                story_body  = sub_stories[i + 1].strip() if i + 1 < len(sub_stories) else ""
                stories.append({
                    "title":    story_title,
                    "role":     title,
                    "company":  company,
                    "filename": filename,
                    "body":     story_body,
                })
        else:
            # Single story
            stories.append({
                "title":    f"{title} — {company}",
                "role":     title,
                "company":  company,
                "filename": filename,
                "body":     body,
            })

    return stories

# ── ROUTES ────────────────────────────────────────────────────────────────────

@app.route("/")
def board():
    db = get_db()
    rows = data.get_board_jobs(db)

    jobs_by_status = {s: [] for s in STATUSES}
    for row in rows:
        status = row["status"] if row["status"] in STATUSES else "New"
        jobs_by_status[status].append(dict(row))

    return render_template(
        "board.html",
        jobs_by_status=jobs_by_status,
        app_statuses=APP_STATUSES,
        end_statuses=END_STATUSES,
        statuses=STATUSES,
        status_colors=STATUS_COLORS,
    )


@app.route("/interviews")
def interviews():
    db   = get_db()
    rows = data.get_interview_jobs(db)

    jobs = []
    for row in rows:
        job = dict(row)
        job["recruiter_name"] = data.get_recruiter_name(db, job["id"])
        jobs.append(job)

    return render_template(
        "interviews.html",
        jobs=jobs,
        status_colors=STATUS_COLORS,
    )


@app.route("/radar")
@app.route("/radar/<date>/<slot>")
def radar(date=None, slot=None):
    reports = list_reports()
    if not reports:
        return render_template("radar.html", jobs=[], reports=reports, current=None)

    if date and slot:
        path     = OUTPUT_DIR / f"{date}-{slot.lower()}.md"
        filename = path.name
    else:
        path     = Path(reports[0]["path"])
        filename = reports[0]["filename"]
        date     = reports[0]["date"]
        slot     = reports[0]["slot"]

    jobs = parse_report(str(path)) if path.exists() else []

    show_dismissed = request.args.get("dismissed") == "1"

    db             = get_db()
    saved_ids      = data.get_all_job_ids(db)
    dismissed_ids  = data.get_dismissed_ids(db)
    reviewed_files = data.get_reviewed_filenames(db)
    comments       = data.get_radar_comments(db)

    for job in jobs:
        job["is_saved"]     = job["job_id"] in saved_ids
        job["is_dismissed"] = job["job_id"] in dismissed_ids
        job["comment"]      = comments.get(job["job_id"], "")

    if not show_dismissed:
        jobs = [j for j in jobs if not j["is_dismissed"]]

    is_reviewed = filename in reviewed_files
    for r in reports:
        r["is_reviewed"] = r["filename"] in reviewed_files

    current = {"filename": filename, "date": date, "slot": slot}
    return render_template("radar.html", jobs=jobs, reports=reports, current=current,
                           show_dismissed=show_dismissed, dismissed_count=len(dismissed_ids),
                           is_reviewed=is_reviewed)


@app.route("/stories")
def story_bank():
    stories = _parse_stories_from_docs()

    # Collect fit analysis stories to show which jobs each story was surfaced for
    db = get_db()
    analyses = data.get_fit_analyses_with_stories(db)

    # For each doc story, find which fit analyses referenced it (by keyword match)
    for story in stories:
        story["used_in"] = []
        # Match by a key phrase from the story body (first 60 chars of the Situation line)
        situation_line = ""
        for line in story["body"].split("\n"):
            if line.startswith("**Situation:**"):
                situation_line = line.replace("**Situation:**", "").strip()[:60]
                break
        if situation_line:
            for a in analyses:
                if a["stories_md"] and situation_line[:40] in a["stories_md"]:
                    story["used_in"].append({
                        "title":   a["title"],
                        "company": a["company"],
                    })

    return render_template("stories.html", stories=stories)


@app.route("/portals")
def portals():
    db = get_db()
    scan = data.get_latest_scan(db)

    jobs = []
    if scan:
        scan = dict(scan)
        rows = data.get_scan_results(db, scan["id"])

        saved_ids     = data.get_all_job_ids(db)
        dismissed_ids = data.get_dismissed_ids(db)

        remote_signals = ("remote", "work from home", "wfh", "distributed", "virtual")
        for row in rows:
            j = dict(row)
            j["is_saved"]     = j["job_id"] in saved_ids
            j["is_dismissed"] = j["job_id"] in dismissed_ids
            loc = (j.get("location") or "").lower()
            if any(t in loc for t in HOME_METRO_TERMS):
                j["loc_tag"] = "local"
            elif any(s in loc for s in remote_signals):
                j["loc_tag"] = "remote"
            else:
                j["loc_tag"] = "other"
            jobs.append(j)

    loc_counts = {"local": 0, "remote": 0, "other": 0}
    for j in jobs:
        loc_counts[j.get("loc_tag", "other")] += 1

    return render_template(
        "portals.html",
        scan=scan,
        jobs=jobs,
        company_count=len(set(j["company"] for j in jobs)),
        loc_counts=loc_counts,
        local_label=f"{HOME_CITY} area",
    )


@app.route("/portals/scan", methods=["POST"])
def run_portal_scan():
    try:
        results = portal_scan_all()
        db = get_db()
        companies_hit = len(set(j["company"] for j in results))
        scan_id = data.insert_scan(db, len(results), companies_hit)
        data.insert_scan_results(db, scan_id, results)
        return jsonify({"ok": True, "found": len(results), "companies": companies_hit})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/jobs/save", methods=["POST"])
def save_job():
    payload = request.json or {}
    job_id  = payload.get("job_id")
    if not job_id:
        return jsonify({"ok": False, "error": "missing job_id"}), 400
    db = get_db()
    try:
        data.save_job(db, job_id, payload)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/radar/reviewed", methods=["POST"])
def mark_radar_reviewed():
    filename = (request.json or {}).get("filename", "")
    if not filename:
        return jsonify({"ok": False, "error": "missing filename"}), 400
    db = get_db()
    data.mark_reviewed(db, filename)
    return jsonify({"ok": True})


@app.route("/radar/dismiss/<job_id>", methods=["POST"])
def dismiss_radar_job(job_id):
    undo = (request.json or {}).get("undo", False)
    db   = get_db()
    if undo:
        data.undismiss_job(db, job_id)
    else:
        data.dismiss_job(db, job_id)
    return jsonify({"ok": True})


@app.route("/radar/comments/<job_id>", methods=["POST"])
def save_radar_comment(job_id):
    body = (request.json or {}).get("body", "").strip()
    db   = get_db()
    data.save_radar_comment(db, job_id, body)
    return jsonify({"ok": True})


@app.route("/jobs/<job_id>/move", methods=["POST"])
def move_job(job_id):
    payload = request.json or {}
    status  = payload.get("status") or request.form.get("status", "")
    if status not in STATUSES:
        return jsonify({"ok": False, "error": "invalid status"}), 400
    db = get_db()
    data.move_job(db, job_id, status)
    return jsonify({"ok": True})


@app.route("/jobs/<job_id>/notes", methods=["POST"])
def add_note(job_id):
    payload = request.json or {}
    body = (payload.get("body") or request.form.get("body", "")).strip()
    if not body:
        return jsonify({"ok": False, "error": "empty note"}), 400
    db = get_db()
    data.add_note(db, job_id, body)
    notes = data.get_notes(db, job_id)
    return jsonify({"ok": True, "notes": [dict(n) for n in notes]})


@app.route("/jobs/<job_id>")
def job_detail(job_id):
    db  = get_db()
    job = data.get_job(db, job_id)
    if not job:
        return "Job not found", 404
    notes     = data.get_notes(db, job_id)
    docs      = data.get_documents(db, job_id)
    apply_url = data.get_apply_url(db, job_id)
    fit       = data.get_fit_analysis(db, job_id)

    contacts = offer = rounds = None
    if dict(job)["status"] in ("Interviewing", "Offer"):
        contacts = data.get_contacts(db, job_id)
        rounds   = data.get_rounds(db, job_id)
    if dict(job)["status"] == "Offer":
        offer = data.get_offer(db, job_id)

    return render_template(
        "job_detail.html",
        job=dict(job),
        notes=[dict(n) for n in notes],
        docs=[dict(d) for d in docs],
        apply_url=apply_url,
        fit=fit,
        contacts=contacts,
        rounds=rounds,
        offer=offer,
        statuses=STATUSES,
        status_colors=STATUS_COLORS,
    )


@app.route("/jobs/<job_id>/apply_url", methods=["POST"])
def save_apply_url(job_id):
    url = (request.json or {}).get("url", "").strip()
    if url and not url.lower().startswith(("http://", "https://", "mailto:")):
        return jsonify({"ok": False, "error": "URL must start with http://, https://, or mailto:"}), 400
    db = get_db()
    if url:
        data.save_apply_url(db, job_id, url)
    else:
        data.delete_apply_url(db, job_id)
    return jsonify({"ok": True})


@app.route("/jobs/<job_id>/contacts", methods=["POST"])
def add_contact(job_id):
    payload = request.json or {}
    name = payload.get("name", "").strip()
    if not name:
        return jsonify({"ok": False, "error": "name required"}), 400
    db = get_db()
    new_id = data.add_contact(db, job_id, payload)
    return jsonify({"ok": True, "id": new_id})


@app.route("/jobs/<job_id>/contacts/<int:contact_id>", methods=["DELETE"])
def delete_contact(job_id, contact_id):
    db = get_db()
    data.delete_contact(db, contact_id, job_id)
    return jsonify({"ok": True})


@app.route("/jobs/<job_id>/rounds", methods=["POST"])
def add_round(job_id):
    payload = request.json or {}
    db = get_db()
    data.add_round(db, job_id, payload)
    return jsonify({"ok": True})


@app.route("/jobs/<job_id>/rounds/<int:round_id>", methods=["POST"])
def update_round(job_id, round_id):
    payload = request.json or {}
    db = get_db()
    data.update_round(db, round_id, job_id, payload)
    return jsonify({"ok": True})


@app.route("/jobs/<job_id>/rounds/<int:round_id>", methods=["DELETE"])
def delete_round(job_id, round_id):
    db = get_db()
    data.delete_round(db, round_id, job_id)
    return jsonify({"ok": True})


@app.route("/jobs/<job_id>/offer", methods=["POST"])
def save_offer(job_id):
    payload = request.json or {}
    db = get_db()
    data.save_offer(db, job_id, payload)
    return jsonify({"ok": True})


@app.route("/jobs/<job_id>/generate", methods=["POST"])
def generate(job_id):
    db  = get_db()
    job = data.get_job(db, job_id)
    if not job:
        return jsonify({"ok": False, "error": "job not found"}), 404

    payload      = request.json or {}
    instructions = payload.get("instructions", "").strip()

    try:
        result = generate_documents(dict(job), instructions)
        max_v  = data.get_max_doc_version(db, job_id)
        data.insert_document(db, job_id, max_v + 1,
                             result["resume"], result["cover_letter"], instructions)
        db.execute("UPDATE jobs SET status='Drafting' WHERE id=? AND status IN ('New','Reviewing')", (job_id,))
        db.commit()
        doc_id = db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        return jsonify({"ok": True, "doc_id": doc_id, "version": max_v + 1})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/jobs/<job_id>/fit-analysis", methods=["POST"])
def run_fit_analysis(job_id):
    db  = get_db()
    job = data.get_job(db, job_id)
    if not job:
        return jsonify({"ok": False, "error": "job not found"}), 404
    try:
        result = generate_fit_analysis(dict(job))
        data.save_fit_analysis(db, job_id, result)
        return jsonify({"ok": True, "score": result["match_score"]})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/jobs/<job_id>/documents/<int:doc_id>")
def view_draft(job_id, doc_id):
    db  = get_db()
    job = data.get_job(db, job_id)
    doc = data.get_document(db, doc_id, job_id)
    if not job or not doc:
        return "Not found", 404
    all_docs = data.get_all_doc_versions(db, job_id)
    return render_template(
        "draft.html",
        job=dict(job),
        doc=dict(doc),
        all_docs=[dict(d) for d in all_docs],
        statuses=STATUSES,
    )


@app.route("/jobs/<job_id>/documents/<int:doc_id>/save", methods=["POST"])
def save_document(job_id, doc_id):
    payload    = request.json or {}
    resume_md  = payload.get("resume_md", "")
    cl_md      = payload.get("coverletter_md", "")
    mark_final = bool(payload.get("mark_final"))
    db = get_db()
    data.save_document(db, doc_id, job_id, resume_md, cl_md, mark_final)
    return jsonify({"ok": True})


@app.route("/jobs/<job_id>/documents/<int:doc_id>/download/<doc_type>")
def download_doc(job_id, doc_id, doc_type):
    db  = get_db()
    job = data.get_job(db, job_id)
    doc = data.get_document(db, doc_id, job_id)
    if not job or not doc:
        return "Not found", 404

    if doc_type == "resume":
        md_text  = doc["resume_md"] or ""
        prefix   = "Resume"
    else:
        md_text  = doc["coverletter_md"] or ""
        prefix   = "CoverLetter"

    safe_company = re.sub(r"[^\w]", "_", job["company"] or "")[:30]
    safe_title   = re.sub(r"[^\w]", "_", job["title"]   or "")[:30]
    filename     = f"{prefix}_{safe_company}_{safe_title}_v{doc['version']}.docx"
    tmp_path     = EXPORT_DIR / filename

    word_doc = markdown_to_docx(md_text)
    word_doc.save(str(tmp_path))

    return send_file(
        str(tmp_path),
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@app.route("/jobs/<job_id>/delete", methods=["POST"])
def delete_job(job_id):
    db = get_db()
    data.delete_job(db, job_id)
    return jsonify({"ok": True})


# ── MAIN ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    print("─" * 50)
    print("  Job Search Dashboard")
    print("  http://localhost:5000")
    print("─" * 50)
    app.run(debug=False, host="127.0.0.1", port=5000)
