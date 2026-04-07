"""SQLite data access layer — all queries in named functions."""

from datetime import datetime

SCHEMA_SQL = """
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

    CREATE TABLE IF NOT EXISTS interview_contacts (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id     TEXT NOT NULL,
        role       TEXT NOT NULL,
        name       TEXT NOT NULL,
        title      TEXT,
        email      TEXT,
        linkedin   TEXT,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS interview_rounds (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id       TEXT NOT NULL,
        round_num    INTEGER NOT NULL DEFAULT 1,
        date         TEXT,
        format       TEXT,
        interviewers TEXT,
        notes        TEXT,
        thank_you    INTEGER NOT NULL DEFAULT 0,
        created_at   TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS offer_details (
        job_id    TEXT PRIMARY KEY,
        base      TEXT,
        bonus     TEXT,
        equity    TEXT,
        benefits  TEXT,
        deadline  TEXT,
        notes     TEXT,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS fit_analyses (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id       TEXT NOT NULL UNIQUE,
        match_score  REAL,
        matches_md   TEXT,
        gaps_md      TEXT,
        stories_md   TEXT,
        summary      TEXT,
        generated_at TEXT NOT NULL,
        FOREIGN KEY (job_id) REFERENCES jobs(id)
    );

    CREATE TABLE IF NOT EXISTS portal_scans (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        scanned_at   TEXT NOT NULL,
        jobs_found   INTEGER NOT NULL DEFAULT 0,
        companies_hit INTEGER NOT NULL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS portal_results (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        scan_id      INTEGER NOT NULL,
        job_id       TEXT NOT NULL,
        title        TEXT NOT NULL,
        company      TEXT,
        location     TEXT,
        url          TEXT,
        source       TEXT,
        description  TEXT,
        posted       TEXT,
        FOREIGN KEY (scan_id) REFERENCES portal_scans(id)
    );

    CREATE TABLE IF NOT EXISTS radar_runs (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        started_at   TEXT NOT NULL,
        finished_at  TEXT,
        total_raw    INTEGER NOT NULL DEFAULT 0,
        total_new    INTEGER NOT NULL DEFAULT 0,
        total_rated  INTEGER NOT NULL DEFAULT 0,
        report_file  TEXT
    );

    CREATE TABLE IF NOT EXISTS source_stats (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id      INTEGER NOT NULL,
        source      TEXT NOT NULL,
        raw_count   INTEGER NOT NULL DEFAULT 0,
        new_count   INTEGER NOT NULL DEFAULT 0,
        error_count INTEGER NOT NULL DEFAULT 0,
        latency_ms  INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY (run_id) REFERENCES radar_runs(id)
    );

    CREATE TABLE IF NOT EXISTS filtered_jobs (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id      INTEGER NOT NULL,
        title       TEXT NOT NULL,
        company     TEXT,
        url         TEXT,
        source      TEXT,
        filter_name TEXT NOT NULL,
        created_at  TEXT NOT NULL,
        FOREIGN KEY (run_id) REFERENCES radar_runs(id)
    );

    CREATE TABLE IF NOT EXISTS company_signals (
        company_lower TEXT PRIMARY KEY,
        signal        TEXT NOT NULL DEFAULT 'dismiss',
        count         INTEGER NOT NULL DEFAULT 0,
        updated_at    TEXT NOT NULL
    );
"""


def init_schema(conn):
    conn.executescript(SCHEMA_SQL)
    conn.execute("UPDATE jobs SET status='Interviewing' WHERE status IN ('Phone Screen','Interview')")
    # Additive migrations
    try:
        conn.execute("ALTER TABLE jobs ADD COLUMN status_changed_at TEXT")
    except Exception:
        pass  # column already exists
    conn.execute("UPDATE jobs SET status_changed_at = saved_at WHERE status_changed_at IS NULL")
    conn.commit()


# ── Jobs ──────────────────────────────────────────────────────────────────────

def get_board_jobs(db):
    return db.execute("""
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


def get_interview_jobs(db):
    return db.execute("""
        SELECT j.*,
               COUNT(DISTINCT ir.id) AS round_count,
               MAX(ir.date)          AS latest_round_date
        FROM   jobs j
        LEFT JOIN interview_rounds ir ON ir.job_id = j.id
        WHERE  j.status IN ('Interviewing','Offer')
        GROUP BY j.id
        ORDER BY j.saved_at DESC
    """).fetchall()


def get_job(db, job_id):
    return db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()


def save_job(db, job_id, data):
    now = datetime.now().isoformat()
    db.execute("""
        INSERT OR IGNORE INTO jobs
          (id, url, title, company, location, salary, source,
           tier, reason, description, posted, report_file, saved_at, status, status_changed_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'New',?)
    """, (
        job_id, data.get("url"), data.get("title"), data.get("company"),
        data.get("location"), data.get("salary"), data.get("source"),
        data.get("tier"), data.get("reason"), data.get("description"),
        data.get("posted"), data.get("report_file"),
        now, now,
    ))
    db.commit()


def move_job(db, job_id, status):
    db.execute("UPDATE jobs SET status=?, status_changed_at=? WHERE id=?",
               (status, datetime.now().isoformat(), job_id))
    db.commit()


def delete_job(db, job_id):
    db.execute("DELETE FROM notes     WHERE job_id=?", (job_id,))
    db.execute("DELETE FROM documents WHERE job_id=?", (job_id,))
    db.execute("DELETE FROM jobs      WHERE id=?",     (job_id,))
    db.commit()


def get_all_job_ids(db):
    return {r["id"] for r in db.execute("SELECT id FROM jobs").fetchall()}


def check_ready_requirements(db, job_id):
    """Check if a job meets requirements to move to Ready status."""
    missing = []
    has_final = db.execute(
        "SELECT 1 FROM documents WHERE job_id=? AND is_final=1 LIMIT 1", (job_id,)
    ).fetchone()
    if not has_final:
        missing.append("Final document (mark a resume/cover letter as final)")
    has_url = db.execute(
        "SELECT 1 FROM job_apply_urls WHERE job_id=?", (job_id,)
    ).fetchone()
    if not has_url:
        missing.append("Apply URL")
    return {"ok": len(missing) == 0, "missing": missing}


STALE_THRESHOLDS = {
    "New": 3, "Reviewing": 5, "Drafting": 7, "Ready": 3,
    "Applied": 14, "Interviewing": 7,
}


def get_stale_job_ids(db, thresholds=None):
    """Return set of job IDs that have been in their current status too long."""
    if thresholds is None:
        thresholds = STALE_THRESHOLDS
    statuses = list(thresholds.keys())
    placeholders = ",".join("?" * len(statuses))
    rows = db.execute(
        f"SELECT id, status, status_changed_at FROM jobs WHERE status IN ({placeholders})",
        statuses,
    ).fetchall()
    now = datetime.now()
    stale = set()
    for row in rows:
        changed = row["status_changed_at"]
        if not changed:
            continue
        try:
            changed_dt = datetime.fromisoformat(changed)
        except (ValueError, TypeError):
            continue
        days = (now - changed_dt).days
        if days >= thresholds.get(row["status"], 999):
            stale.add(row["id"])
    return stale


# ── Notes ─────────────────────────────────────────────────────────────────────

def add_note(db, job_id, body):
    db.execute(
        "INSERT INTO notes (job_id, body, created_at) VALUES (?,?,?)",
        (job_id, body, datetime.now().isoformat()),
    )
    db.commit()


def get_notes(db, job_id):
    return db.execute(
        "SELECT * FROM notes WHERE job_id=? ORDER BY created_at DESC", (job_id,)
    ).fetchall()


# ── Documents ─────────────────────────────────────────────────────────────────

def get_documents(db, job_id):
    return db.execute(
        "SELECT * FROM documents WHERE job_id=? ORDER BY version DESC", (job_id,)
    ).fetchall()


def get_document(db, doc_id, job_id):
    return db.execute(
        "SELECT * FROM documents WHERE id=? AND job_id=?", (doc_id, job_id)
    ).fetchone()


def get_all_doc_versions(db, job_id):
    return db.execute(
        "SELECT id, version, generated_at, is_final FROM documents WHERE job_id=? ORDER BY version DESC",
        (job_id,),
    ).fetchall()


def get_max_doc_version(db, job_id):
    return db.execute(
        "SELECT COALESCE(MAX(version),0) AS v FROM documents WHERE job_id=?", (job_id,)
    ).fetchone()["v"]


def insert_document(db, job_id, version, resume_md, cl_md, notes):
    db.execute("""
        INSERT INTO documents
          (job_id, version, resume_md, coverletter_md, generation_notes, generated_at)
        VALUES (?,?,?,?,?,?)
    """, (job_id, version, resume_md, cl_md, notes, datetime.now().isoformat()))


def save_document(db, doc_id, job_id, resume_md, cl_md, is_final):
    db.execute(
        "UPDATE documents SET resume_md=?, coverletter_md=?, is_final=? WHERE id=? AND job_id=?",
        (resume_md, cl_md, 1 if is_final else 0, doc_id, job_id),
    )
    if is_final:
        # Only auto-move to Ready if apply URL exists
        has_url = db.execute(
            "SELECT 1 FROM job_apply_urls WHERE job_id=?", (job_id,)
        ).fetchone()
        if has_url:
            now = datetime.now().isoformat()
            db.execute("UPDATE jobs SET status='Ready', status_changed_at=? WHERE id=?", (now, job_id))
    db.commit()


# ── Apply URLs ────────────────────────────────────────────────────────────────

def get_apply_url(db, job_id):
    row = db.execute(
        "SELECT apply_url FROM job_apply_urls WHERE job_id=?", (job_id,)
    ).fetchone()
    return row["apply_url"] if row else ""


def save_apply_url(db, job_id, url):
    db.execute(
        "INSERT OR REPLACE INTO job_apply_urls (job_id, apply_url, saved_at) VALUES (?,?,?)",
        (job_id, url, datetime.now().isoformat()),
    )
    db.commit()


def delete_apply_url(db, job_id):
    db.execute("DELETE FROM job_apply_urls WHERE job_id=?", (job_id,))
    db.commit()


# ── Fit Analysis ──────────────────────────────────────────────────────────────

def get_fit_analysis(db, job_id):
    row = db.execute("SELECT * FROM fit_analyses WHERE job_id=?", (job_id,)).fetchone()
    return dict(row) if row else None


def save_fit_analysis(db, job_id, result):
    db.execute("""
        INSERT OR REPLACE INTO fit_analyses
          (job_id, match_score, matches_md, gaps_md, stories_md, summary, generated_at)
        VALUES (?,?,?,?,?,?,?)
    """, (
        job_id, result["match_score"],
        result["matches"], result["gaps"],
        result["stories"], result["summary"],
        datetime.now().isoformat(),
    ))
    db.execute("UPDATE jobs SET status='Reviewing' WHERE id=? AND status='New'", (job_id,))
    db.commit()


def get_fit_analyses_with_stories(db):
    return db.execute(
        "SELECT fa.job_id, fa.stories_md, j.title, j.company "
        "FROM fit_analyses fa JOIN jobs j ON j.id = fa.job_id"
    ).fetchall()


# ── Interview Contacts ────────────────────────────────────────────────────────

def get_contacts(db, job_id):
    return [dict(r) for r in db.execute(
        "SELECT * FROM interview_contacts WHERE job_id=? ORDER BY created_at", (job_id,)
    ).fetchall()]


def get_recruiter_name(db, job_id):
    rec = db.execute(
        "SELECT name FROM interview_contacts WHERE job_id=? AND role='recruiter' LIMIT 1",
        (job_id,),
    ).fetchone()
    return rec["name"] if rec else None


def add_contact(db, job_id, data):
    db.execute(
        "INSERT INTO interview_contacts (job_id,role,name,title,email,linkedin,created_at) VALUES (?,?,?,?,?,?,?)",
        (job_id, data.get("role", "interviewer"), data.get("name", ""),
         data.get("title", ""), data.get("email", ""), data.get("linkedin", ""),
         datetime.now().isoformat()),
    )
    db.commit()
    return db.execute("SELECT last_insert_rowid()").fetchone()[0]


def delete_contact(db, contact_id, job_id):
    db.execute("DELETE FROM interview_contacts WHERE id=? AND job_id=?", (contact_id, job_id))
    db.commit()


# ── Interview Rounds ─────────────────────────────────────────────────────────

def get_rounds(db, job_id):
    return [dict(r) for r in db.execute(
        "SELECT * FROM interview_rounds WHERE job_id=? ORDER BY round_num", (job_id,)
    ).fetchall()]


def count_rounds(db, job_id):
    return db.execute(
        "SELECT COUNT(*) FROM interview_rounds WHERE job_id=?", (job_id,)
    ).fetchone()[0]


def add_round(db, job_id, data):
    num = count_rounds(db, job_id)
    db.execute(
        "INSERT INTO interview_rounds (job_id,round_num,date,format,interviewers,notes,thank_you,created_at) VALUES (?,?,?,?,?,?,?,?)",
        (job_id, num + 1, data.get("date", ""), data.get("format", ""),
         data.get("interviewers", ""), data.get("notes", ""),
         1 if data.get("thank_you") else 0, datetime.now().isoformat()),
    )
    db.commit()


def update_round(db, round_id, job_id, data):
    db.execute(
        "UPDATE interview_rounds SET date=?,format=?,interviewers=?,notes=?,thank_you=? WHERE id=? AND job_id=?",
        (data.get("date", ""), data.get("format", ""), data.get("interviewers", ""),
         data.get("notes", ""), 1 if data.get("thank_you") else 0,
         round_id, job_id),
    )
    db.commit()


def delete_round(db, round_id, job_id):
    db.execute("DELETE FROM interview_rounds WHERE id=? AND job_id=?", (round_id, job_id))
    db.commit()


# ── Offer Details ─────────────────────────────────────────────────────────────

def get_offer(db, job_id):
    row = db.execute("SELECT * FROM offer_details WHERE job_id=?", (job_id,)).fetchone()
    return dict(row) if row else {}


def save_offer(db, job_id, data):
    db.execute(
        "INSERT OR REPLACE INTO offer_details (job_id,base,bonus,equity,benefits,deadline,notes,updated_at) VALUES (?,?,?,?,?,?,?,?)",
        (job_id, data.get("base", ""), data.get("bonus", ""), data.get("equity", ""),
         data.get("benefits", ""), data.get("deadline", ""), data.get("notes", ""),
         datetime.now().isoformat()),
    )
    db.commit()


# ── Radar State ───────────────────────────────────────────────────────────────

def get_dismissed_ids(db):
    return {r["job_id"] for r in db.execute("SELECT job_id FROM radar_dismissed").fetchall()}


def dismiss_job(db, job_id):
    db.execute(
        "INSERT OR IGNORE INTO radar_dismissed (job_id, dismissed_at) VALUES (?,?)",
        (job_id, datetime.now().isoformat()),
    )
    db.commit()


def undismiss_job(db, job_id):
    db.execute("DELETE FROM radar_dismissed WHERE job_id = ?", (job_id,))
    db.commit()


def get_reviewed_filenames(db):
    return {r["filename"] for r in db.execute("SELECT filename FROM radar_reviewed").fetchall()}


def mark_reviewed(db, filename):
    db.execute(
        "INSERT OR IGNORE INTO radar_reviewed (filename, reviewed_at) VALUES (?,?)",
        (filename, datetime.now().isoformat()),
    )
    db.commit()


def get_radar_comments(db):
    return {r["job_id"]: r["body"] for r in db.execute(
        "SELECT job_id, body FROM radar_comments ORDER BY created_at DESC"
    ).fetchall()}


def save_radar_comment(db, job_id, body):
    db.execute("DELETE FROM radar_comments WHERE job_id = ?", (job_id,))
    if body:
        db.execute(
            "INSERT INTO radar_comments (job_id, body, created_at) VALUES (?,?,?)",
            (job_id, body, datetime.now().isoformat()),
        )
    db.commit()


# ── Portal Scans ──────────────────────────────────────────────────────────────

def get_latest_scan(db):
    return db.execute(
        "SELECT * FROM portal_scans ORDER BY scanned_at DESC LIMIT 1"
    ).fetchone()


def get_scan_results(db, scan_id):
    return db.execute(
        "SELECT * FROM portal_results WHERE scan_id=? ORDER BY company, title",
        (scan_id,),
    ).fetchall()


def insert_scan(db, jobs_found, companies_hit):
    db.execute(
        "INSERT INTO portal_scans (scanned_at, jobs_found, companies_hit) VALUES (?,?,?)",
        (datetime.now().isoformat(), jobs_found, companies_hit),
    )
    db.commit()
    return db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]


def insert_scan_results(db, scan_id, results):
    for j in results:
        db.execute("""
            INSERT INTO portal_results
              (scan_id, job_id, title, company, location, url, source, description, posted)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (
            scan_id, j["job_id"], j["title"], j["company"],
            j["location"], j["url"], j["source"],
            j.get("description", ""), j.get("posted", ""),
        ))
    db.commit()


# ── Radar Runs / Health ──────────────────────────────────────────────────────

def insert_run(db, started_at):
    db.execute(
        "INSERT INTO radar_runs (started_at) VALUES (?)",
        (started_at,),
    )
    db.commit()
    return db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]


def finish_run(db, run_id, finished_at, total_raw, total_new, total_rated, report_file):
    db.execute(
        "UPDATE radar_runs SET finished_at=?, total_raw=?, total_new=?, total_rated=?, report_file=? WHERE id=?",
        (finished_at, total_raw, total_new, total_rated, report_file, run_id),
    )
    db.commit()


def insert_source_stat(db, run_id, source, raw_count, new_count, error_count, latency_ms):
    db.execute(
        "INSERT INTO source_stats (run_id, source, raw_count, new_count, error_count, latency_ms) VALUES (?,?,?,?,?,?)",
        (run_id, source, raw_count, new_count, error_count, latency_ms),
    )
    db.commit()


def insert_filtered_jobs(db, run_id, filtered_list):
    now = datetime.now().isoformat()
    for fj in filtered_list:
        db.execute(
            "INSERT INTO filtered_jobs (run_id, title, company, url, source, filter_name, created_at) VALUES (?,?,?,?,?,?,?)",
            (run_id, fj["title"], fj.get("company", ""), fj.get("url", ""),
             fj.get("source", ""), fj["filter_name"], now),
        )
    db.commit()


def get_latest_run(db):
    return db.execute(
        "SELECT * FROM radar_runs ORDER BY started_at DESC LIMIT 1"
    ).fetchone()


def get_source_stats(db, run_id):
    return db.execute(
        "SELECT * FROM source_stats WHERE run_id=? ORDER BY raw_count DESC",
        (run_id,),
    ).fetchall()


def get_recent_runs(db, days=14):
    return db.execute(
        "SELECT * FROM radar_runs ORDER BY started_at DESC LIMIT ?",
        (days * 2,),
    ).fetchall()


def get_previous_run_stats(db, run_id):
    prev = db.execute(
        "SELECT id FROM radar_runs WHERE id < ? ORDER BY id DESC LIMIT 1",
        (run_id,),
    ).fetchone()
    if not prev:
        return []
    return db.execute(
        "SELECT * FROM source_stats WHERE run_id=?",
        (prev["id"],),
    ).fetchall()


def get_run_by_report_file(db, filename):
    return db.execute(
        "SELECT * FROM radar_runs WHERE report_file=? ORDER BY id DESC LIMIT 1",
        (filename,),
    ).fetchone()


def get_filtered_jobs(db, run_id):
    return db.execute(
        "SELECT * FROM filtered_jobs WHERE run_id=? ORDER BY filter_name, title",
        (run_id,),
    ).fetchall()


def get_filter_stats(db, run_id):
    return db.execute(
        "SELECT filter_name, COUNT(*) as count FROM filtered_jobs WHERE run_id=? GROUP BY filter_name ORDER BY count DESC",
        (run_id,),
    ).fetchall()


# ── Company Signals ──────────────────────────────────────────────────────────

def increment_company_signal(db, company, signal):
    """Increment dismiss/reject count for a company."""
    key = (company or "").lower().strip()
    if not key:
        return
    now = datetime.now().isoformat()
    db.execute("""
        INSERT INTO company_signals (company_lower, signal, count, updated_at)
        VALUES (?, ?, 1, ?)
        ON CONFLICT(company_lower) DO UPDATE SET
            signal = excluded.signal,
            count = count + 1,
            updated_at = excluded.updated_at
    """, (key, signal, now))
    db.commit()


def set_company_boost(db, company):
    """Explicitly boost a company (resets count to 1 with boost signal)."""
    key = (company or "").lower().strip()
    if not key:
        return
    now = datetime.now().isoformat()
    db.execute("""
        INSERT INTO company_signals (company_lower, signal, count, updated_at)
        VALUES (?, 'boost', 1, ?)
        ON CONFLICT(company_lower) DO UPDATE SET
            signal = 'boost',
            count = 1,
            updated_at = excluded.updated_at
    """, (key, now))
    db.commit()


def get_company_signals(db):
    """Return dict of {company_lower: {signal, count}}."""
    rows = db.execute("SELECT * FROM company_signals").fetchall()
    return {r["company_lower"]: {"signal": r["signal"], "count": r["count"]} for r in rows}
