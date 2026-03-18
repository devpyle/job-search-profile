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
from config import CANDIDATE_NAME, JOB_DOCS  # noqa: E402

# ── KANBAN COLUMNS ────────────────────────────────────────────────────────────

STATUSES = [
    "New", "Reviewing", "Drafting", "Ready",
    "Applied", "Phone Screen", "Interview", "Offer",
    "Accepted", "Rejected", "Passed",
]
ACTIVE_STATUSES = STATUSES[:8]
END_STATUSES    = STATUSES[8:]

STATUS_COLORS = {
    "New":          "#94a3b8",
    "Reviewing":    "#3b82f6",
    "Drafting":     "#8b5cf6",
    "Ready":        "#10b981",
    "Applied":      "#06b6d4",
    "Phone Screen": "#f97316",
    "Interview":    "#eab308",
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
    db = sqlite3.connect(str(DB_PATH))
    db.executescript("""
        CREATE TABLE IF NOT EXISTS jobs (
            id          TEXT PRIMARY KEY,
            url         TEXT UNIQUE,
            title       TEXT NOT NULL,
            company     TEXT,
            location    TEXT,
            salary      TEXT,
            source      TEXT,
            tier        TEXT,
            reason      TEXT,
            description TEXT,
            posted      TEXT,
            report_file TEXT,
            saved_at    TEXT NOT NULL,
            status      TEXT NOT NULL DEFAULT 'New'
        );

        CREATE TABLE IF NOT EXISTS notes (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id     TEXT NOT NULL,
            body       TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (job_id) REFERENCES jobs(id)
        );

        CREATE TABLE IF NOT EXISTS radar_comments (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id     TEXT NOT NULL,
            body       TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS radar_dismissed (
            job_id     TEXT PRIMARY KEY,
            dismissed_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS radar_reviewed (
            filename    TEXT PRIMARY KEY,
            reviewed_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS job_apply_urls (
            job_id    TEXT PRIMARY KEY,
            apply_url TEXT NOT NULL,
            saved_at  TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS documents (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id            TEXT NOT NULL,
            version           INTEGER NOT NULL DEFAULT 1,
            resume_md         TEXT,
            coverletter_md    TEXT,
            generation_notes  TEXT,
            generated_at      TEXT NOT NULL,
            is_final          INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (job_id) REFERENCES jobs(id)
        );
    """)
    db.commit()
    db.close()

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
        # David's tier names
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
- Bold metrics and key results using **bold** in the resume bullets.
- Use - for bullet points.
- Company name and dates go on the line directly below the ### Job Title line, formatted as: **Company Name** | Location | Start – End
{regen_block}

DAVID'S PERSONAL INFO:
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

# ── ROUTES ────────────────────────────────────────────────────────────────────

@app.route("/")
def board():
    db = get_db()
    rows = db.execute("""
        SELECT j.*,
               COUNT(DISTINCT n.id)          AS note_count,
               MAX(d.is_final)               AS has_final_docs,
               MAX(d.id)                     AS latest_doc_id
        FROM   jobs j
        LEFT JOIN notes     n ON n.job_id = j.id
        LEFT JOIN documents d ON d.job_id = j.id
        GROUP BY j.id
        ORDER BY j.saved_at DESC
    """).fetchall()

    jobs_by_status = {s: [] for s in STATUSES}
    for row in rows:
        status = row["status"] if row["status"] in STATUSES else "New"
        jobs_by_status[status].append(dict(row))

    return render_template(
        "board.html",
        jobs_by_status=jobs_by_status,
        active_statuses=ACTIVE_STATUSES,
        end_statuses=END_STATUSES,
        statuses=STATUSES,
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
    saved_ids      = {r["id"] for r in db.execute("SELECT id FROM jobs").fetchall()}
    dismissed_ids  = {r["job_id"] for r in db.execute("SELECT job_id FROM radar_dismissed").fetchall()}
    reviewed_files = {r["filename"] for r in db.execute("SELECT filename FROM radar_reviewed").fetchall()}
    comments       = {r["job_id"]: r["body"] for r in db.execute(
        "SELECT job_id, body FROM radar_comments ORDER BY created_at DESC"
    ).fetchall()}

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


@app.route("/jobs/save", methods=["POST"])
def save_job():
    data   = request.json or {}
    job_id = data.get("job_id")
    if not job_id:
        return jsonify({"ok": False, "error": "missing job_id"}), 400
    db = get_db()
    try:
        db.execute("""
            INSERT OR IGNORE INTO jobs
              (id, url, title, company, location, salary, source,
               tier, reason, description, posted, report_file, saved_at, status)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'New')
        """, (
            job_id, data.get("url"), data.get("title"), data.get("company"),
            data.get("location"), data.get("salary"), data.get("source"),
            data.get("tier"), data.get("reason"), data.get("description"),
            data.get("posted"), data.get("report_file"),
            datetime.now().isoformat(),
        ))
        db.commit()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/radar/reviewed", methods=["POST"])
def mark_radar_reviewed():
    filename = (request.json or {}).get("filename", "")
    if not filename:
        return jsonify({"ok": False, "error": "missing filename"}), 400
    db = get_db()
    db.execute(
        "INSERT OR IGNORE INTO radar_reviewed (filename, reviewed_at) VALUES (?,?)",
        (filename, datetime.now().isoformat()),
    )
    db.commit()
    return jsonify({"ok": True})


@app.route("/radar/dismiss/<job_id>", methods=["POST"])
def dismiss_radar_job(job_id):
    undo = (request.json or {}).get("undo", False)
    db   = get_db()
    if undo:
        db.execute("DELETE FROM radar_dismissed WHERE job_id = ?", (job_id,))
    else:
        db.execute(
            "INSERT OR IGNORE INTO radar_dismissed (job_id, dismissed_at) VALUES (?,?)",
            (job_id, datetime.now().isoformat()),
        )
    db.commit()
    return jsonify({"ok": True})


@app.route("/radar/comments/<job_id>", methods=["POST"])
def save_radar_comment(job_id):
    body = (request.json or {}).get("body", "").strip()
    db   = get_db()
    db.execute("DELETE FROM radar_comments WHERE job_id = ?", (job_id,))
    if body:
        db.execute(
            "INSERT INTO radar_comments (job_id, body, created_at) VALUES (?,?,?)",
            (job_id, body, datetime.now().isoformat()),
        )
    db.commit()
    return jsonify({"ok": True})


@app.route("/jobs/<job_id>/move", methods=["POST"])
def move_job(job_id):
    data   = request.json or {}
    status = data.get("status") or request.form.get("status", "")
    if status not in STATUSES:
        return jsonify({"ok": False, "error": "invalid status"}), 400
    db = get_db()
    db.execute("UPDATE jobs SET status=? WHERE id=?", (status, job_id))
    db.commit()
    return jsonify({"ok": True})


@app.route("/jobs/<job_id>/notes", methods=["POST"])
def add_note(job_id):
    data = request.json or {}
    body = (data.get("body") or request.form.get("body", "")).strip()
    if not body:
        return jsonify({"ok": False, "error": "empty note"}), 400
    db = get_db()
    db.execute(
        "INSERT INTO notes (job_id, body, created_at) VALUES (?,?,?)",
        (job_id, body, datetime.now().isoformat()),
    )
    db.commit()
    notes = db.execute(
        "SELECT * FROM notes WHERE job_id=? ORDER BY created_at DESC", (job_id,)
    ).fetchall()
    return jsonify({"ok": True, "notes": [dict(n) for n in notes]})


@app.route("/jobs/<job_id>")
def job_detail(job_id):
    db  = get_db()
    job = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not job:
        return "Job not found", 404
    notes = db.execute(
        "SELECT * FROM notes WHERE job_id=? ORDER BY created_at DESC", (job_id,)
    ).fetchall()
    docs = db.execute(
        "SELECT * FROM documents WHERE job_id=? ORDER BY version DESC", (job_id,)
    ).fetchall()
    apply_url_row = db.execute(
        "SELECT apply_url FROM job_apply_urls WHERE job_id=?", (job_id,)
    ).fetchone()
    apply_url = apply_url_row["apply_url"] if apply_url_row else ""
    return render_template(
        "job_detail.html",
        job=dict(job),
        notes=[dict(n) for n in notes],
        docs=[dict(d) for d in docs],
        apply_url=apply_url,
        statuses=STATUSES,
        status_colors=STATUS_COLORS,
    )


@app.route("/jobs/<job_id>/apply_url", methods=["POST"])
def save_apply_url(job_id):
    url = (request.json or {}).get("url", "").strip()
    db  = get_db()
    if url:
        db.execute(
            "INSERT OR REPLACE INTO job_apply_urls (job_id, apply_url, saved_at) VALUES (?,?,?)",
            (job_id, url, datetime.now().isoformat()),
        )
    else:
        db.execute("DELETE FROM job_apply_urls WHERE job_id=?", (job_id,))
    db.commit()
    return jsonify({"ok": True})


@app.route("/jobs/<job_id>/generate", methods=["POST"])
def generate(job_id):
    db  = get_db()
    job = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not job:
        return jsonify({"ok": False, "error": "job not found"}), 404

    data         = request.json or {}
    instructions = data.get("instructions", "").strip()

    try:
        result = generate_documents(dict(job), instructions)
        max_v  = db.execute(
            "SELECT COALESCE(MAX(version),0) AS v FROM documents WHERE job_id=?", (job_id,)
        ).fetchone()["v"]
        db.execute("""
            INSERT INTO documents
              (job_id, version, resume_md, coverletter_md, generation_notes, generated_at)
            VALUES (?,?,?,?,?,?)
        """, (
            job_id, max_v + 1,
            result["resume"], result["cover_letter"],
            instructions, datetime.now().isoformat(),
        ))
        db.execute("UPDATE jobs SET status='Drafting' WHERE id=? AND status IN ('New','Reviewing')", (job_id,))
        db.commit()
        doc_id = db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        return jsonify({"ok": True, "doc_id": doc_id, "version": max_v + 1})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/jobs/<job_id>/documents/<int:doc_id>")
def view_draft(job_id, doc_id):
    db  = get_db()
    job = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    doc = db.execute(
        "SELECT * FROM documents WHERE id=? AND job_id=?", (doc_id, job_id)
    ).fetchone()
    if not job or not doc:
        return "Not found", 404
    all_docs = db.execute(
        "SELECT id, version, generated_at, is_final FROM documents WHERE job_id=? ORDER BY version DESC",
        (job_id,),
    ).fetchall()
    return render_template(
        "draft.html",
        job=dict(job),
        doc=dict(doc),
        all_docs=[dict(d) for d in all_docs],
        statuses=STATUSES,
    )


@app.route("/jobs/<job_id>/documents/<int:doc_id>/save", methods=["POST"])
def save_document(job_id, doc_id):
    data       = request.json or {}
    resume_md  = data.get("resume_md", "")
    cl_md      = data.get("coverletter_md", "")
    mark_final = bool(data.get("mark_final"))
    db         = get_db()
    db.execute(
        "UPDATE documents SET resume_md=?, coverletter_md=?, is_final=? WHERE id=? AND job_id=?",
        (resume_md, cl_md, 1 if mark_final else 0, doc_id, job_id),
    )
    if mark_final:
        db.execute("UPDATE jobs SET status='Ready' WHERE id=?", (job_id,))
    db.commit()
    return jsonify({"ok": True})


@app.route("/jobs/<job_id>/documents/<int:doc_id>/download/<doc_type>")
def download_doc(job_id, doc_id, doc_type):
    db  = get_db()
    job = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    doc = db.execute(
        "SELECT * FROM documents WHERE id=? AND job_id=?", (doc_id, job_id)
    ).fetchone()
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
    db.execute("DELETE FROM notes     WHERE job_id=?", (job_id,))
    db.execute("DELETE FROM documents WHERE job_id=?", (job_id,))
    db.execute("DELETE FROM jobs      WHERE id=?",     (job_id,))
    db.commit()
    return jsonify({"ok": True})


# ── MAIN ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    print("─" * 50)
    print("  Job Search Dashboard")
    print("  http://localhost:5000")
    print("─" * 50)
    app.run(debug=True, port=5000, use_reloader=True)
