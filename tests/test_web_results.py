"""Tests for web-search result cleanup and the not-a-role filter."""

from unittest.mock import patch, MagicMock

import tests.conftest  # noqa: F401

from filters import is_non_role_web_result
from models import Job
from sources.tavily import _company_from_url
from sources.web_results import clean_title, normalize_web_job, resolve_ats_title


# ── clean_title ──────────────────────────────────────────────────────────────

def test_clean_title_strips_workday_noise():
    assert clean_title("Senior Product Manager - Logo - Myworkdayjobs.com") == ("Senior Product Manager", "")


def test_clean_title_greenhouse_application_prefix():
    assert clean_title("Job Application for Product Owner at Acme Robotics") == ("Product Owner", "Acme Robotics")


def test_clean_title_leaves_real_title():
    assert clean_title("Business Analyst II") == ("Business Analyst II", "")


# ── is_non_role_web_result ───────────────────────────────────────────────────

def test_real_posting_is_a_role():
    assert not is_non_role_web_result(
        "Product Owner", "https://job-boards.greenhouse.io/globex/jobs/123456")


def test_generic_page_title_is_not_a_role():
    assert is_non_role_web_result("Globex: Careers", "https://example.com/careers/123")


def test_listing_page_title_is_not_a_role():
    assert is_non_role_web_result("Product Management & Digital jobs", "https://careers.example.com/x")


def test_greenhouse_board_root_is_not_a_role():
    assert is_non_role_web_result("Product Manager", "https://boards.greenhouse.io/globex")


def test_search_page_url_is_not_a_role():
    assert is_non_role_web_result("Product Owner", "https://jobs.example.com/en_US/careers/SearchJobs")


def test_homepage_is_not_a_role():
    assert is_non_role_web_result("Senior Product Manager", "https://www.example.com/")


# ── resolve_ats_title / normalize_web_job ────────────────────────────────────

def _resp(status, payload=None):
    r = MagicMock(status_code=status)
    r.json.return_value = payload or {}
    r.raise_for_status.return_value = None
    return r


@patch("sources.web_results.requests.get")
def test_resolve_greenhouse_title(mock_get):
    mock_get.return_value = _resp(200, {"title": "Senior Product Manager, Payments"})
    assert resolve_ats_title("https://boards.greenhouse.io/globex/jobs/42") == (
        "Senior Product Manager, Payments", False)


@patch("sources.web_results.requests.get")
def test_resolve_greenhouse_closed(mock_get):
    mock_get.return_value = _resp(404)
    assert resolve_ats_title("https://boards.greenhouse.io/globex/jobs/42") == (None, True)


def test_resolve_non_ats_url_skips_lookup():
    assert resolve_ats_title("https://www.example.com/jobs/42") == (None, False)


@patch("sources.web_results.requests.get")
def test_normalize_replaces_generic_title(mock_get):
    mock_get.return_value = _resp(200, {"title": "Product Owner, Integrations"})
    job = Job(title="Globex: Careers", url="https://boards.greenhouse.io/globex/jobs/7", source="Brave")
    assert normalize_web_job(job, lambda u: "")
    assert job.title == "Product Owner, Integrations"


@patch("sources.web_results.requests.get")
def test_normalize_drops_closed_posting(mock_get):
    mock_get.return_value = _resp(404)
    job = Job(title="Jobs at Globex", url="https://boards.greenhouse.io/globex/jobs/7", source="Tavily")
    assert not normalize_web_job(job, lambda u: "")


@patch("sources.web_results.requests.get")
def test_normalize_skips_lookup_when_title_names_role(mock_get):
    job = Job(title="Product Manager", url="https://boards.greenhouse.io/globex/jobs/7", source="Brave")
    assert normalize_web_job(job, lambda u: "")
    mock_get.assert_not_called()


# ── _company_from_url ────────────────────────────────────────────────────────

def test_company_from_workday_tenant_with_wd_host():
    assert _company_from_url("https://globexbank.wd5.myworkdayjobs.com/en-US/External/job/x") == "Globexbank"


def test_company_domain_key_needs_label_boundary():
    # "ice.com" must not match inside "dice.com"
    assert _company_from_url("https://www.dice.com/job-detail/abc") == ""
