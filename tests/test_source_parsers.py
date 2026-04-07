"""Fixture-based tests for source parsers — verifies field extraction from API responses."""

import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

import tests.conftest  # noqa: F401

FIXTURES = Path(__file__).parent / "fixtures"


def _load_json(name):
    return json.loads((FIXTURES / name).read_text())


def _load_text(name):
    return (FIXTURES / name).read_text()


def _load_bytes(name):
    return (FIXTURES / name).read_bytes()


# Import job_radar with patched env
@patch.dict(os.environ, {
    "ADZUNA_APP_ID": "test", "ADZUNA_APP_KEY": "test",
    "TAVILY_API_KEY": "test", "ANTHROPIC_API_KEY": "test",
})
def _import():
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    import job_radar
    return job_radar


jr = _import()


def _mock_response(json_data=None, content=None, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    if json_data is not None:
        resp.json.return_value = json_data
    if content is not None:
        resp.content = content
    return resp


# ── Adzuna ───────────────────────────────────────────────────────────────────


class TestAdzuna:
    @patch("sources.adzuna.ADZUNA_QUERIES", [{"what": "product owner", "sort_by": "date", "max_days_old": 7}])
    @patch("sources.adzuna.requests.get")
    def test_parses_jobs(self, mock_get):
        mock_get.return_value = _mock_response(json_data=_load_json("adzuna.json"))
        jobs = jr.search_adzuna()
        assert len(jobs) == 2
        assert jobs[0].source == "Adzuna"
        assert jobs[0].title == "Product Owner - Payments Platform"
        assert jobs[0].company == "Acme Corp"
        assert jobs[0].salary_min == 130000
        assert jobs[0].url == "https://example.com/adzuna/job/101"
        # Predicted salary should be None
        assert jobs[1].salary_min is None

    @patch("sources.adzuna.ADZUNA_QUERIES", [{"what": "test", "sort_by": "date", "max_days_old": 7}])
    @patch("sources.adzuna.requests.get")
    def test_handles_error(self, mock_get):
        mock_get.side_effect = Exception("Connection timeout")
        jobs = jr.search_adzuna()
        assert jobs == []


# ── Brave ────────────────────────────────────────────────────────────────────


class TestBrave:
    @patch("sources.brave.BRAVE_QUERIES", ["product owner remote"])
    @patch("sources.brave.requests.get")
    @patch("sources.brave.time.sleep")
    def test_parses_jobs(self, mock_sleep, mock_get):
        mock_get.return_value = _mock_response(json_data=_load_json("brave.json"))
        jobs = jr.search_brave()
        assert len(jobs) == 2
        assert jobs[0].source == "Brave"
        assert "API Platform" in jobs[0].title
        assert jobs[0].url.startswith("https://")

    @patch("sources.brave.BRAVE_QUERIES", ["test"])
    @patch("sources.brave.requests.get")
    @patch("sources.brave.time.sleep")
    def test_handles_error(self, mock_sleep, mock_get):
        mock_get.side_effect = Exception("API error")
        jobs = jr.search_brave()
        assert jobs == []


# ── Tavily ───────────────────────────────────────────────────────────────────


class TestTavily:
    @patch("sources.tavily.TAVILY_QUERIES", ["product owner remote"])
    @patch("sources.tavily.requests.post")
    def test_parses_jobs(self, mock_post):
        mock_post.return_value = _mock_response(json_data=_load_json("tavily.json"))
        jobs = jr.search_tavily()
        assert len(jobs) == 2
        assert jobs[0].source == "Tavily"
        assert "Cloud Platform" in jobs[0].title

    @patch("sources.tavily.TAVILY_QUERIES", ["test"])
    @patch("sources.tavily.requests.post")
    def test_handles_error(self, mock_post):
        mock_post.side_effect = Exception("API error")
        jobs = jr.search_tavily()
        assert jobs == []


# ── LinkedIn ─────────────────────────────────────────────────────────────────


class TestLinkedIn:
    def test_parse_cards_remote(self):
        from bs4 import BeautifulSoup
        html = _load_text("linkedin_cards.html")
        soup = BeautifulSoup(html, "html.parser")
        from sources.linkedin import _li_parse_cards
        jobs = _li_parse_cards(soup, remote=True)
        assert len(jobs) == 2
        assert jobs[0].source == "LinkedIn"
        assert jobs[0].title == "Product Owner — Payments"
        assert jobs[0].company == "Acme Corp"
        assert "501" in jobs[0].url

    def test_parse_cards_local_filters(self):
        from bs4 import BeautifulSoup
        html = _load_text("linkedin_cards.html")
        soup = BeautifulSoup(html, "html.parser")
        from sources.linkedin import _li_parse_cards
        # Local mode filters for LI_NC_LOCATIONS — these fixtures don't have Raleigh
        jobs = _li_parse_cards(soup, remote=False)
        assert len(jobs) == 0


# ── Remotive ─────────────────────────────────────────────────────────────────


class TestRemotive:
    @patch("sources.remote_boards.requests.get")
    @patch("sources.remote_boards.time.sleep")
    def test_parses_jobs(self, mock_sleep, mock_get):
        mock_get.return_value = _mock_response(json_data=_load_json("remotive.json"))
        jobs = jr.search_remotive()
        assert len(jobs) >= 1
        assert jobs[0].source == "Remotive"
        assert jobs[0].company == "Acme Corp"
        assert jobs[0].salary_text == "$120K-$150K"

    @patch("sources.remote_boards.requests.get")
    @patch("sources.remote_boards.time.sleep")
    def test_handles_error(self, mock_sleep, mock_get):
        mock_get.side_effect = Exception("API error")
        jobs = jr.search_remotive()
        assert jobs == []


# ── WeWorkRemotely ───────────────────────────────────────────────────────────


class TestWeWorkRemotely:
    @patch("sources.remote_boards.requests.get")
    def test_parses_xml_feed(self, mock_get):
        mock_resp = _mock_response()
        mock_resp.content = _load_bytes("weworkremotely.xml")
        mock_get.return_value = mock_resp
        jobs = jr.search_weworkremotely()
        # 2 feeds × 2 items each = 4 (same fixture for both feeds)
        assert len(jobs) == 4
        assert jobs[0].source == "WeWorkRemotely"
        assert jobs[0].title == "Product Owner"  # " at Acme Corp" stripped
        assert "501" in jobs[0].url

    @patch("sources.remote_boards.requests.get")
    def test_handles_error(self, mock_get):
        mock_get.side_effect = Exception("Network error")
        jobs = jr.search_weworkremotely()
        assert jobs == []


# ── Himalayas ────────────────────────────────────────────────────────────────


class TestHimalayas:
    @patch("sources.remote_boards.requests.get")
    @patch("sources.remote_boards.time.sleep")
    def test_parses_jobs(self, mock_sleep, mock_get):
        mock_resp = _mock_response()
        mock_resp.json.return_value = _load_json("himalayas.json")
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp
        jobs = jr.search_himalayas()
        assert len(jobs) >= 1
        assert jobs[0].source == "Himalayas"
        assert jobs[0].company == "Acme Corp"
        assert "$125,000" in jobs[0].salary_text

    @patch("sources.remote_boards.requests.get")
    @patch("sources.remote_boards.time.sleep")
    def test_handles_error(self, mock_sleep, mock_get):
        mock_get.side_effect = Exception("API error")
        jobs = jr.search_himalayas()
        assert jobs == []


# ── RemoteOK ─────────────────────────────────────────────────────────────────


class TestRemoteOK:
    @patch("sources.remote_boards.requests.get")
    def test_parses_jobs(self, mock_get):
        mock_get.return_value = _mock_response(json_data=_load_json("remoteok.json"))
        jobs = jr.search_remoteok()
        assert len(jobs) == 2
        assert jobs[0].source == "RemoteOK"
        assert "Payments" in jobs[0].title
        assert "$130,000" in jobs[0].salary_text

    @patch("sources.remote_boards.requests.get")
    def test_handles_http_error(self, mock_get):
        mock_get.return_value = _mock_response(status_code=500)
        jobs = jr.search_remoteok()
        assert jobs == []


# ── Jobicy ───────────────────────────────────────────────────────────────────


class TestJobicy:
    @patch("sources.remote_boards.requests.get")
    @patch("sources.remote_boards.time.sleep")
    def test_parses_jobs(self, mock_sleep, mock_get):
        mock_get.return_value = _mock_response(json_data=_load_json("jobicy.json"))
        jobs = jr.search_jobicy()
        assert len(jobs) >= 1
        assert jobs[0].source == "Jobicy"
        assert "$120,000" in jobs[0].salary_text

    @patch("sources.remote_boards.requests.get")
    @patch("sources.remote_boards.time.sleep")
    def test_handles_error(self, mock_sleep, mock_get):
        mock_get.side_effect = Exception("API error")
        jobs = jr.search_jobicy()
        assert jobs == []


# ── JSearch ──────────────────────────────────────────────────────────────────


class TestJSearch:
    @patch("sources.jsearch.JSEARCH_REMOTE_QUERIES", ["Product Owner remote"])
    @patch("sources.jsearch.JSEARCH_LOCAL_QUERIES", [])
    @patch("sources.jsearch.JSEARCH_API_KEY", "test-key")
    @patch("sources.jsearch.requests.get")
    def test_parses_jobs(self, mock_get):
        mock_get.return_value = _mock_response(json_data=_load_json("jsearch.json"))
        jobs = jr.search_jsearch()
        assert len(jobs) >= 1
        assert jobs[0].source == "JSearch"
        assert jobs[0].salary_min == 130000

    @patch("sources.jsearch.JSEARCH_API_KEY", "")
    def test_skips_without_key(self):
        jobs = jr.search_jsearch()
        assert jobs == []

    @patch("sources.jsearch.JSEARCH_REMOTE_QUERIES", ["test"])
    @patch("sources.jsearch.JSEARCH_LOCAL_QUERIES", [])
    @patch("sources.jsearch.JSEARCH_API_KEY", "test-key")
    @patch("sources.jsearch.requests.get")
    def test_handles_timeout_retry(self, mock_get):
        import requests as req
        mock_get.side_effect = [
            req.exceptions.Timeout("timeout"),
            req.exceptions.Timeout("timeout"),
            req.exceptions.Timeout("timeout"),
        ]
        jobs = jr.search_jsearch()
        assert jobs == []
        assert mock_get.call_count == 3


# ── ATS (Greenhouse / Lever / Ashby) ─────────────────────────────────────────


class TestATS:
    @patch("sources.ats.PORTAL_COMPANIES", ["testco"])
    @patch("sources.ats.time.sleep")
    @patch("sources.ats.requests.get")
    def test_greenhouse_parses_matching_titles(self, mock_get, mock_sleep):
        def side_effect(url, **kwargs):
            if "greenhouse" in url:
                return _mock_response(json_data=_load_json("greenhouse.json"))
            return _mock_response(status_code=404)

        mock_get.side_effect = side_effect
        jobs = jr.search_ats_companies()
        # Should find "Product Owner — Payments" but not "Software Engineer"
        po_jobs = [j for j in jobs if "Product Owner" in j.title]
        assert len(po_jobs) == 1
        assert po_jobs[0].source == "Greenhouse"
        assert po_jobs[0].company == "Testco"

    @patch("sources.ats.PORTAL_COMPANIES", ["testco"])
    @patch("sources.ats.time.sleep")
    @patch("sources.ats.requests.get")
    def test_lever_parses_matching_titles(self, mock_get, mock_sleep):
        def side_effect(url, **kwargs):
            if "lever" in url:
                resp = _mock_response()
                resp.json.return_value = _load_json("lever.json")
                return resp
            return _mock_response(status_code=404)

        mock_get.side_effect = side_effect
        jobs = jr.search_ats_companies()
        po_jobs = [j for j in jobs if "Product Owner" in j.title]
        assert len(po_jobs) == 1
        assert po_jobs[0].source == "Lever"

    @patch("sources.ats.PORTAL_COMPANIES", ["testco"])
    @patch("sources.ats.time.sleep")
    @patch("sources.ats.requests.get")
    def test_ashby_parses_matching_titles(self, mock_get, mock_sleep):
        def side_effect(url, **kwargs):
            if "ashby" in url:
                return _mock_response(json_data=_load_json("ashby.json"))
            return _mock_response(status_code=404)

        mock_get.side_effect = side_effect
        jobs = jr.search_ats_companies()
        po_jobs = [j for j in jobs if "Product Owner" in j.title]
        assert len(po_jobs) == 1
        assert po_jobs[0].source == "Ashby"

    @patch("sources.ats.PORTAL_COMPANIES", ["testco"])
    @patch("sources.ats.time.sleep")
    @patch("sources.ats.requests.get")
    def test_all_three_combined(self, mock_get, mock_sleep):
        def side_effect(url, **kwargs):
            if "greenhouse" in url:
                return _mock_response(json_data=_load_json("greenhouse.json"))
            elif "lever" in url:
                resp = _mock_response()
                resp.json.return_value = _load_json("lever.json")
                return resp
            elif "ashby" in url:
                return _mock_response(json_data=_load_json("ashby.json"))
            return _mock_response(status_code=404)

        mock_get.side_effect = side_effect
        jobs = jr.search_ats_companies()
        sources = {j.source for j in jobs}
        assert "Greenhouse" in sources
        assert "Lever" in sources
        assert "Ashby" in sources

    @patch("sources.ats.PORTAL_COMPANIES", ["testco"])
    @patch("sources.ats.time.sleep")
    @patch("sources.ats.requests.get")
    def test_handles_all_errors(self, mock_get, mock_sleep):
        mock_get.side_effect = Exception("Network error")
        jobs = jr.search_ats_companies()
        assert jobs == []
