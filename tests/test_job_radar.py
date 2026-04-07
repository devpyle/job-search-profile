"""Tests for job_radar.py — filters, Job dataclass, helper functions."""

import os
import sys
from pathlib import Path
from unittest.mock import patch

# Ensure mock config is available
import tests.conftest  # noqa: F401


# We need to patch os.environ before importing job_radar since it reads keys at import time
@patch.dict(os.environ, {
    "ADZUNA_APP_ID": "test",
    "ADZUNA_APP_KEY": "test",
    "TAVILY_API_KEY": "test",
    "ANTHROPIC_API_KEY": "test",
})
def _import_job_radar():
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    import job_radar
    return job_radar


jr = _import_job_radar()
Job = jr.Job


# ── Job.dedup_key ────────────────────────────────────────────────────────────


def test_dedup_key_strips_location_suffix():
    j = Job(title="Product Owner - Remote", company="Acme")
    key = j.dedup_key()
    assert "remote" not in key
    assert "acme" in key


def test_dedup_key_same_title_company():
    j1 = Job(title="Product Owner", company="Acme")
    j2 = Job(title="Product Owner", company="Acme")
    assert j1.dedup_key() == j2.dedup_key()


def test_dedup_key_different_company():
    j1 = Job(title="Product Owner", company="Acme")
    j2 = Job(title="Product Owner", company="Beta")
    assert j1.dedup_key() != j2.dedup_key()


def test_dedup_key_no_company_uses_url():
    j = Job(title="Product Owner", url="https://example.com/job/1")
    assert j.dedup_key() == "https://example.com/job/1"


# ── Job.salary_str ───────────────────────────────────────────────────────────


def test_salary_str_range():
    j = Job(title="PO", salary_min=120_000, salary_max=150_000)
    assert "$120,000" in j.salary_str()
    assert "$150,000" in j.salary_str()


def test_salary_str_min_only():
    j = Job(title="PO", salary_min=120_000)
    assert "$120,000+" in j.salary_str()


def test_salary_str_text_fallback():
    j = Job(title="PO", salary_text="$120K-$150K")
    assert j.salary_str() == "$120K-$150K"


def test_salary_str_not_listed():
    j = Job(title="PO")
    assert j.salary_str() == "Not listed"


def test_salary_str_ignores_tiny_values():
    j = Job(title="PO", salary_min=2, salary_max=50)
    assert j.salary_str() == "Not listed"


# ── _clean_desc ──────────────────────────────────────────────────────────────


def test_clean_desc_strips_html():
    result = jr._clean_desc("<p>Hello <b>world</b></p>")
    assert "<" not in result
    assert "Hello" in result
    assert "world" in result


def test_clean_desc_unescapes_entities():
    result = jr._clean_desc("AT&amp;T &amp; partners")
    assert "AT&T" in result
    assert "& partners" in result


def test_clean_desc_truncates():
    long_text = "x" * 10000
    result = jr._clean_desc(long_text)
    assert len(result) <= 5000


def test_clean_desc_empty():
    assert jr._clean_desc("") == ""
    assert jr._clean_desc(None) == ""


# ── is_category_page ─────────────────────────────────────────────────────────


def test_category_page_aggregator_url():
    assert jr.is_category_page("Jobs", "https://indeed.com/jobs", "")


def test_category_page_aggregator_title():
    assert jr.is_category_page("1,500+ remote product manager jobs in US", "https://example.com", "")


def test_category_page_non_job_title():
    assert jr.is_category_page("Resume samples for product managers", "https://example.com", "")


def test_category_page_expired_in_title():
    assert jr.is_category_page("This position is no longer accepting applications", "https://example.com", "")


def test_category_page_expired_in_description():
    assert jr.is_category_page("Product Owner", "https://example.com",
                               "This job has expired and is no longer available")


def test_category_page_real_job():
    assert not jr.is_category_page(
        "Product Owner — Payments Platform",
        "https://boards.greenhouse.io/acme/jobs/123",
        "We are hiring a PO for our payments team."
    )


# ── is_non_us_location ──────────────────────────────────────────────────────


def test_non_us_uk_city():
    j = Job(title="PO", location="London, UK")
    assert jr.is_non_us_location(j)


def test_non_us_germany():
    j = Job(title="PO", location="Berlin, Germany")
    assert jr.is_non_us_location(j)


def test_non_us_india_in_description():
    j = Job(title="PO", location="", description="Based in Bangalore, India")
    assert jr.is_non_us_location(j)


def test_us_location_passes():
    j = Job(title="PO", location="Remote, US")
    assert not jr.is_non_us_location(j)


def test_us_city_passes():
    j = Job(title="PO", location="Raleigh, NC")
    assert not jr.is_non_us_location(j)


# ── is_onsite_non_local ─────────────────────────────────────────────────────


def test_onsite_sf_url():
    j = Job(title="PO", location="", url="https://linkedin.com/jobs/san-francisco")
    assert jr.is_onsite_non_local(j)


def test_onsite_sf_but_remote_in_title():
    j = Job(title="PO - Remote", location="", url="https://linkedin.com/jobs/san-francisco")
    assert not jr.is_onsite_non_local(j)


def test_onsite_sf_but_remote_in_location():
    j = Job(title="PO", location="San Francisco or Remote",
            url="https://linkedin.com/jobs/san-francisco")
    assert not jr.is_onsite_non_local(j)


def test_onsite_location_field_non_local():
    j = Job(title="PO", location="Chicago, IL")
    assert jr.is_onsite_non_local(j)


def test_onsite_location_field_but_remote_desc():
    j = Job(title="PO", location="Chicago, IL",
            description="This is a fully remote position open to US candidates.")
    assert not jr.is_onsite_non_local(j)


def test_remote_job_passes():
    j = Job(title="PO", location="Remote", url="https://example.com/job/1")
    assert not jr.is_onsite_non_local(j)


# ── is_bad_scrape ────────────────────────────────────────────────────────────


def test_bad_scrape_json():
    j = Job(title="PO", description='{"error": "not found"}')
    assert jr.is_bad_scrape(j)


def test_bad_scrape_css():
    j = Job(title="PO", description='color: var(--primary); background: var(--bg)')
    assert jr.is_bad_scrape(j)


def test_bad_scrape_normal():
    j = Job(title="PO", description="We are looking for a Product Owner.")
    assert not jr.is_bad_scrape(j)


# ── Wrong title filter ───────────────────────────────────────────────────────


def test_wrong_title_data_analyst():
    assert jr._WRONG_TITLE_RE.search("Senior Data Analyst")


def test_wrong_title_sales():
    assert jr._WRONG_TITLE_RE.search("Sales Manager — Enterprise")


def test_wrong_title_product_owner_ok():
    assert not jr._WRONG_TITLE_RE.search("Product Owner — Payments Platform")


def test_wrong_title_product_manager_ok():
    assert not jr._WRONG_TITLE_RE.search("Senior Product Manager")
