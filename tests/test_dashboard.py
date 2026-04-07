"""Smoke tests for the Flask dashboard — routes, DB operations, URL validation."""

import json

from tests.conftest import _insert_job


# ── GET routes return 200 ────────────────────────────────────────────────────


def test_board_page(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Board" in resp.data or b"board" in resp.data


def test_radar_page_empty(client):
    resp = client.get("/radar")
    assert resp.status_code == 200


def test_stories_page(client):
    resp = client.get("/stories")
    assert resp.status_code == 200


def test_portals_page(client):
    resp = client.get("/portals")
    assert resp.status_code == 200


def test_interviews_page(client):
    resp = client.get("/interviews")
    assert resp.status_code == 200


# ── Job detail page ──────────────────────────────────────────────────────────


def test_job_detail_exists(client, db):
    _insert_job(db)
    resp = client.get("/jobs/test123")
    assert resp.status_code == 200
    assert b"Test PO" in resp.data


def test_job_detail_missing(client):
    resp = client.get("/jobs/nonexistent")
    # Should redirect or 404
    assert resp.status_code in (302, 404)


# ── Save job from radar ─────────────────────────────────────────────────────


def test_save_job(client, db):
    resp = client.post("/jobs/save", json={
        "job_id": "abc123",
        "url": "https://example.com/job/new",
        "title": "New PO Role",
        "company": "TestCo",
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True

    row = db.execute("SELECT * FROM jobs WHERE id='abc123'").fetchone()
    assert row is not None
    assert row["title"] == "New PO Role"


def test_save_job_missing_id(client):
    resp = client.post("/jobs/save", json={"title": "No ID"})
    assert resp.status_code == 400


# ── Move job ─────────────────────────────────────────────────────────────────


def test_move_job(client, db):
    _insert_job(db)
    resp = client.post("/jobs/test123/move", json={"status": "Applied"})
    assert resp.status_code == 200
    row = db.execute("SELECT status FROM jobs WHERE id='test123'").fetchone()
    assert row["status"] == "Applied"


def test_move_job_invalid_status(client, db):
    _insert_job(db)
    resp = client.post("/jobs/test123/move", json={"status": "Bogus"})
    assert resp.status_code == 400


# ── Notes ────────────────────────────────────────────────────────────────────


def test_add_note(client, db):
    _insert_job(db)
    resp = client.post("/jobs/test123/notes", json={"body": "This looks great"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True

    notes = db.execute("SELECT * FROM notes WHERE job_id='test123'").fetchall()
    assert len(notes) == 1
    assert notes[0]["body"] == "This looks great"


def test_add_empty_note(client, db):
    _insert_job(db)
    resp = client.post("/jobs/test123/notes", json={"body": ""})
    assert resp.status_code == 400


# ── Apply URL validation ────────────────────────────────────────────────────


def test_save_apply_url_https(client, db):
    _insert_job(db)
    resp = client.post("/jobs/test123/apply_url", json={
        "url": "https://careers.acme.com/apply/123"
    })
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True


def test_save_apply_url_http(client, db):
    _insert_job(db)
    resp = client.post("/jobs/test123/apply_url", json={
        "url": "http://careers.acme.com/apply/123"
    })
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True


def test_save_apply_url_mailto(client, db):
    _insert_job(db)
    resp = client.post("/jobs/test123/apply_url", json={
        "url": "mailto:jobs@acme.com"
    })
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True


def test_save_apply_url_javascript_rejected(client, db):
    _insert_job(db)
    resp = client.post("/jobs/test123/apply_url", json={
        "url": "javascript:alert(1)"
    })
    assert resp.status_code == 400
    assert "http" in resp.get_json()["error"].lower()


def test_save_apply_url_data_rejected(client, db):
    _insert_job(db)
    resp = client.post("/jobs/test123/apply_url", json={
        "url": "data:text/html,<script>alert(1)</script>"
    })
    assert resp.status_code == 400


def test_save_apply_url_empty_clears(client, db):
    _insert_job(db)
    # First save a URL
    client.post("/jobs/test123/apply_url", json={"url": "https://example.com"})
    # Then clear it
    resp = client.post("/jobs/test123/apply_url", json={"url": ""})
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True


# ── Contacts ─────────────────────────────────────────────────────────────────


def test_add_contact(client, db):
    _insert_job(db, status="Interviewing")
    resp = client.post("/jobs/test123/contacts", json={
        "role": "recruiter",
        "name": "Jane Smith",
        "email": "jane@acme.com",
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert "id" in data


def test_add_contact_no_name(client, db):
    _insert_job(db, status="Interviewing")
    resp = client.post("/jobs/test123/contacts", json={
        "role": "recruiter",
        "name": "",
    })
    assert resp.status_code == 400


def test_delete_contact(client, db):
    _insert_job(db, status="Interviewing")
    # Add then delete
    resp = client.post("/jobs/test123/contacts", json={
        "role": "recruiter", "name": "Jane"
    })
    contact_id = resp.get_json()["id"]
    resp = client.delete(f"/jobs/test123/contacts/{contact_id}")
    assert resp.status_code == 200


# ── Radar operations ─────────────────────────────────────────────────────────


def test_dismiss_and_undo(client, db):
    resp = client.post("/radar/dismiss/abc123", json={})
    assert resp.status_code == 200
    row = db.execute("SELECT * FROM radar_dismissed WHERE job_id='abc123'").fetchone()
    assert row is not None

    resp = client.post("/radar/dismiss/abc123", json={"undo": True})
    assert resp.status_code == 200
    row = db.execute("SELECT * FROM radar_dismissed WHERE job_id='abc123'").fetchone()
    assert row is None


def test_mark_reviewed(client, db):
    resp = client.post("/radar/reviewed", json={"filename": "2026-04-01-am.md"})
    assert resp.status_code == 200
    row = db.execute(
        "SELECT * FROM radar_reviewed WHERE filename='2026-04-01-am.md'"
    ).fetchone()
    assert row is not None


def test_radar_comment(client, db):
    resp = client.post("/radar/comments/abc123", json={"body": "Not a fit"})
    assert resp.status_code == 200
    row = db.execute("SELECT body FROM radar_comments WHERE job_id='abc123'").fetchone()
    assert row["body"] == "Not a fit"


# ── Delete job ───────────────────────────────────────────────────────────────


def test_delete_job(client, db):
    _insert_job(db)
    resp = client.post("/jobs/test123/delete")
    assert resp.status_code == 200
    row = db.execute("SELECT * FROM jobs WHERE id='test123'").fetchone()
    assert row is None


# ── DB schema ────────────────────────────────────────────────────────────────


def test_all_tables_exist(db):
    tables = {row[0] for row in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    expected = {
        "jobs", "notes", "radar_comments", "radar_dismissed", "radar_reviewed",
        "job_apply_urls", "documents", "interview_contacts", "interview_rounds",
        "offer_details", "fit_analyses", "portal_scans", "portal_results",
    }
    assert expected.issubset(tables)
