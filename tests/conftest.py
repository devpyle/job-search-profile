"""Shared fixtures for the job search test suite."""

import sqlite3
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# Mock config module — installed before any script import tries `from config`
# ---------------------------------------------------------------------------

def _install_mock_config():
    """Create a fake config module so scripts can import from it."""
    if "config" in sys.modules:
        return sys.modules["config"]

    mod = types.ModuleType("config")
    mod.CANDIDATE_NAME = "Test User"
    mod.CANDIDATE_BACKGROUND = "Test background"
    mod.APPLY_NOW_DESCRIPTION = "strong fit"
    mod.HOME_CITY = "Testville"
    mod.HOME_STATE = "NC"
    mod.HOME_METRO_TERMS = ["testville", "testarea"]
    mod.MIN_SALARY = 100_000
    mod.REQUIRE_US_LOCATION = True
    mod.ADZUNA_COUNTRY = "us"
    mod.JOB_DOCS = []
    mod.ADZUNA_QUERIES = []
    mod.BRAVE_QUERIES = []
    mod.TAVILY_QUERIES = []
    mod.LI_REMOTE_QUERIES = []
    mod.LI_LOCAL_QUERIES = []
    mod.JSEARCH_REMOTE_QUERIES = []
    mod.JSEARCH_LOCAL_QUERIES = []
    mod.PORTAL_COMPANIES = []
    mod.PORTAL_NAME_OVERRIDES = {}
    mod.PORTAL_TARGET_TITLES = ["product owner"]
    mod.PORTAL_BLOCK_SUFFIXES = ["representative"]
    sys.modules["config"] = mod
    return mod


def _install_mock_portal_scanner():
    """Create a fake portal_scanner so dashboard.py can import it."""
    if "portal_scanner" in sys.modules:
        return
    mod = types.ModuleType("portal_scanner")
    mod.scan_all = lambda: []
    sys.modules["portal_scanner"] = mod


# Install mocks before anything else imports config/portal_scanner
_install_mock_config()
_install_mock_portal_scanner()


# ---------------------------------------------------------------------------
# Dashboard fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def dashboard_app(tmp_path):
    """Create a Flask test app with a fresh SQLite database."""
    # Patch DB_PATH and EXPORT_DIR before importing routes
    import scripts.dashboard as dash

    original_db = dash.DB_PATH
    original_export = dash.EXPORT_DIR
    original_output = dash.OUTPUT_DIR
    original_docs = dash.DOCS_DIR

    dash.DB_PATH = tmp_path / "test.db"
    dash.EXPORT_DIR = tmp_path / "exports"
    dash.EXPORT_DIR.mkdir()
    dash.OUTPUT_DIR = tmp_path / "radar"
    dash.OUTPUT_DIR.mkdir()
    dash.DOCS_DIR = tmp_path / "docs"
    dash.DOCS_DIR.mkdir()

    dash.init_db()
    dash.app.config["TESTING"] = True

    yield dash.app

    dash.DB_PATH = original_db
    dash.EXPORT_DIR = original_export
    dash.OUTPUT_DIR = original_output
    dash.DOCS_DIR = original_docs


@pytest.fixture()
def client(dashboard_app):
    """Flask test client."""
    return dashboard_app.test_client()


@pytest.fixture()
def db(dashboard_app, tmp_path):
    """Direct database connection for test assertions."""
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def _insert_job(db, job_id="test123", title="Test PO", company="Acme",
                status="New", url="https://example.com/job/1",
                status_changed_at=None):
    """Helper to insert a test job."""
    from datetime import datetime
    now = datetime.now().isoformat()
    db.execute(
        """INSERT INTO jobs (id, url, title, company, location, salary, source,
           tier, reason, description, posted, report_file, saved_at, status, status_changed_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (job_id, url, title, company, "Remote", "$100k", "test",
         "Apply Now", "Good fit", "Job description", "2026-04-01",
         "2026-04-01-am.md", now, status, status_changed_at or now),
    )
    db.commit()
    return job_id
