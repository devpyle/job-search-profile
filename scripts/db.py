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
"""


def init_schema(conn):
    conn.executescript(SCHEMA_SQL)
    conn.execute("UPDATE jobs SET status='Interviewing' WHERE status IN ('Phone Screen','Interview')")
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


def move_job(db, job_id, status):
    db.execute("UPDATE jobs SET status=? WHERE id=?", (status, job_id))
    db.commit()


def delete_job(db, job_id):
    db.execute("DELETE FROM notes     WHERE job_id=?", (job_id,))
    db.execute("DELETE FROM documents WHERE job_id=?", (job_id,))
    db.execute("DELETE FROM jobs      WHERE id=?",     (job_id,))
    db.commit()


def get_all_job_ids(db):
    return {r["id"] for r in db.execute("SELECT id FROM jobs").fetchall()}


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
        db.execute("UPDATE jobs SET status='Ready' WHERE id=?", (job_id,))
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
