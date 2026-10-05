"""Tests for run_cli: retrying the claude CLI through self-update windows."""

import errno
from unittest.mock import patch

import pytest

import tests.conftest  # noqa: F401

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import claude_cli
from claude_cli import run_cli


def _oserr(code):
    return OSError(code, "simulated")


@patch("claude_cli.time.sleep")
@patch("claude_cli.subprocess.run")
def test_retries_while_binary_missing(mock_run, mock_sleep):
    mock_run.side_effect = [_oserr(errno.ENOENT), _oserr(errno.EACCES), "ok"]
    assert run_cli(["claude", "-p", "x"]) == "ok"
    assert mock_run.call_count == 3
    assert mock_sleep.call_count == 2


@patch("claude_cli.time.sleep")
@patch("claude_cli.subprocess.run")
def test_gives_up_after_backoff(mock_run, mock_sleep):
    mock_run.side_effect = _oserr(errno.ENOENT)
    with pytest.raises(OSError):
        run_cli(["claude"])
    assert mock_run.call_count == len(claude_cli._BACKOFF) + 1


@patch("claude_cli.time.sleep")
@patch("claude_cli.subprocess.run")
def test_other_errors_raise_immediately(mock_run, mock_sleep):
    mock_run.side_effect = _oserr(errno.ENOMEM)
    with pytest.raises(OSError):
        run_cli(["claude"])
    assert mock_run.call_count == 1
    mock_sleep.assert_not_called()


@patch("claude_cli.subprocess.run", return_value="done")
def test_passes_kwargs_through(mock_run):
    assert run_cli(["claude"], capture_output=True, timeout=5) == "done"
    mock_run.assert_called_once_with(["claude"], capture_output=True, timeout=5)
