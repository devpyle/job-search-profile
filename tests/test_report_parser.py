"""Tests for the radar report parser in dashboard.py."""

import textwrap
from pathlib import Path


def test_parse_full_format_report(tmp_path, dashboard_app):
    """Parse a report with full-format (Apply Now / Worth a Look) jobs."""
    import scripts.dashboard as dash

    report = textwrap.dedent("""\
        Job Radar — 2026-04-01 AM

        ────────────────────────────────────────
        APPLY NOW
        ────────────────────────────────────────

        📍 Product Owner — Acme Corp (Remote, US)
        ↳ Strong fit: payments platform experience matches well
        We are looking for a Product Owner to lead our payments platform.
        Salary: $130,000–$160,000 | Posted: 2026-03-31 | Source: Adzuna
        🔗 https://boards.greenhouse.io/acme/jobs/100

        Product Manager — Beta Inc (Remote)
        ↳ Good match for API platform work
        Join our team building APIs for fintech.
        Salary: Not listed | Posted: 2026-03-30 | Source: LinkedIn
        🔗 https://jobs.lever.co/beta/200

        ────────────────────────────────────────
        WORTH A LOOK
        ────────────────────────────────────────

        Senior PO — Gamma LLC (Raleigh, NC)
        ↳ Local company, slightly different domain
        Gamma is hiring a senior PO for their platform team.
        Salary: $120,000–$140,000 | Posted: 2026-03-29 | Source: Brave
        🔗 https://gamma.com/careers/300

        ────────────────────────────────────────
        FILTERED OUT
        ────────────────────────────────────────

        ✗ Data Analyst — Wrong Co [wrong title]
           https://example.com/job/400

        ⚠ Junior PM — Staffing Agency [staffing agency]
           https://example.com/job/500
    """)

    report_path = tmp_path / "radar" / "2026-04-01-am.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report)

    jobs = dash.parse_report(str(report_path))

    # Should find all jobs with URLs
    titles = [j["title"] for j in jobs]
    assert "Product Owner" in titles
    assert "Product Manager" in titles
    assert "Senior PO" in titles
    assert "Data Analyst" in titles
    assert "Junior PM" in titles

    # Check tiers
    apply_now = [j for j in jobs if j["tier"] == "Apply Now"]
    assert len(apply_now) == 2

    worth_a_look = [j for j in jobs if j["tier"] == "Worth a Look"]
    assert len(worth_a_look) == 1

    skip = [j for j in jobs if j["tier"] == "Skip"]
    assert len(skip) == 2

    # Check metadata on first job
    acme = next(j for j in jobs if j["company"] == "Acme Corp")
    assert acme["location"] == "Remote, US"
    assert acme["salary"] == "$130,000–$160,000"
    assert acme["source"] == "Adzuna"
    assert acme["reason"] == "Strong fit: payments platform experience matches well"
    assert acme["url"] == "https://boards.greenhouse.io/acme/jobs/100"
    assert acme["job_id"]  # should be a hash


def test_parse_empty_report(tmp_path, dashboard_app):
    """Parsing an empty/header-only report should return an empty list."""
    import scripts.dashboard as dash

    report_path = tmp_path / "radar" / "2026-04-01-pm.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("Job Radar — 2026-04-01 PM\n\nNo new jobs found.\n")

    jobs = dash.parse_report(str(report_path))
    assert jobs == []


def test_job_id_from_url():
    """job_id_from_url should produce consistent 8-char hashes."""
    import scripts.dashboard as dash

    id1 = dash.job_id_from_url("https://example.com/job/1")
    id2 = dash.job_id_from_url("https://example.com/job/1")
    id3 = dash.job_id_from_url("https://example.com/job/2")

    assert id1 == id2
    assert id1 != id3
    assert len(id1) == 8


def test_list_reports(tmp_path, dashboard_app):
    """list_reports should find and sort radar .md files."""
    import scripts.dashboard as dash

    original = dash.OUTPUT_DIR
    dash.OUTPUT_DIR = tmp_path

    (tmp_path / "2026-04-01-am.md").write_text("report 1")
    (tmp_path / "2026-04-01-pm.md").write_text("report 2")
    (tmp_path / "2026-03-31-am.md").write_text("report 3")
    (tmp_path / ".seen.json").write_text("{}")  # should be ignored

    reports = dash.list_reports()
    assert len(reports) == 3
    # Newest first
    assert reports[0]["filename"] == "2026-04-01-pm.md"
    assert reports[0]["slot"] == "PM"

    dash.OUTPUT_DIR = original
