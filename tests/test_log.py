"""Tests for the log helper module."""

import scripts.log as log_mod


def test_verbose_message_suppressed_by_default(capsys):
    log_mod.VERBOSE = False
    log_mod.log("secret detail", verbose=True)
    assert capsys.readouterr().out == ""


def test_verbose_message_shown_when_enabled(capsys):
    log_mod.VERBOSE = True
    log_mod.log("secret detail", verbose=True)
    assert "secret detail" in capsys.readouterr().out
    log_mod.VERBOSE = False


def test_normal_message_always_shown(capsys):
    log_mod.VERBOSE = False
    log_mod.log("always visible")
    assert "always visible" in capsys.readouterr().out


def test_source_prefix(capsys):
    log_mod.log("found 5 results", source="Adzuna")
    out = capsys.readouterr().out
    assert "[Adzuna]" in out
    assert "found 5 results" in out


def test_no_source_prefix(capsys):
    log_mod.log("plain message")
    out = capsys.readouterr().out
    assert "[" not in out
    assert "plain message" in out


def test_init_sets_verbose():
    log_mod.init(["script.py", "--verbose"])
    assert log_mod.VERBOSE is True
    log_mod.init(["script.py"])
    assert log_mod.VERBOSE is False


def test_init_defaults_to_sys_argv():
    log_mod.init()
    assert log_mod.VERBOSE is False
