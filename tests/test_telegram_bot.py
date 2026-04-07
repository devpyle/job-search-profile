"""Tests for telegram_bot.py — token redaction and lazy client initialization."""

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure mock config is available
import tests.conftest  # noqa: F401


# Patch env before importing telegram_bot (it reads env at import time)
@patch.dict(os.environ, {
    "TELEGRAM_BOT_TOKEN": "123456:ABC-fake-token-for-testing",
    "TELEGRAM_USER_ID": "99999",
    "ANTHROPIC_API_KEY": "sk-ant-test-key",
}, clear=False)
def _import_telegram_bot():
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    import telegram_bot
    return telegram_bot


tb = _import_telegram_bot()


# ── Token redaction ──────────────────────────────────────────────────────────


def test_token_redacted_from_error(capsys):
    """The main loop's error handler should redact the bot token."""
    token = tb.TOKEN
    assert token  # confirm TOKEN was loaded

    # Simulate what the main loop does
    error_msg = f"Connection error: https://api.telegram.org/bot{token}/getUpdates"
    redacted = str(error_msg).replace(token, "BOT_TOKEN_REDACTED")
    assert token not in redacted
    assert "BOT_TOKEN_REDACTED" in redacted


def test_api_url_contains_token():
    """API URL embeds the token — confirms redaction is needed."""
    assert tb.TOKEN in tb.API


# ── Lazy client initialization ───────────────────────────────────────────────


def test_get_client_missing_openai_key():
    """Requesting OpenAI client without OPENAI_API_KEY should raise."""
    # Clear cached clients
    tb._clients.clear()
    with patch.dict(os.environ, {}, clear=False):
        # Remove OPENAI_API_KEY if present
        os.environ.pop("OPENAI_API_KEY", None)
        with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
            tb._get_client("openai")


def test_get_client_missing_nvidia_key():
    """Requesting Nvidia client without keys should raise."""
    tb._clients.clear()
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("NVIDIA_API_KEY", None)
        os.environ.pop("NVIDIA_BASE_URL", None)
        with pytest.raises(RuntimeError, match="NVIDIA"):
            tb._get_client("nvidia")


def test_get_client_missing_google_key():
    """Requesting Google client without GOOGLE_API_KEY should raise."""
    tb._clients.clear()
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("GOOGLE_API_KEY", None)
        with pytest.raises(RuntimeError, match="GOOGLE_API_KEY"):
            tb._get_client("google")


def test_get_client_missing_moonshot_key():
    tb._clients.clear()
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("MOONSHOT_API_KEY", None)
        os.environ.pop("MOONSHOT_BASE_URL", None)
        with pytest.raises(RuntimeError, match="MOONSHOT"):
            tb._get_client("moonshot")


def test_get_client_missing_openrouter_key():
    tb._clients.clear()
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("OPENROUTER_API_KEY", None)
        os.environ.pop("OPENROUTER_BASE_URL", None)
        with pytest.raises(RuntimeError, match="OPENROUTER"):
            tb._get_client("openrouter")


def test_get_client_unknown_provider():
    with pytest.raises(RuntimeError, match="Unknown provider"):
        tb._get_client("nonexistent")


def test_get_client_anthropic_works():
    """Anthropic client should init successfully with the test key."""
    tb._clients.clear()
    client = tb._get_client("anthropic")
    assert client is not None
    # Second call should return cached instance
    assert tb._get_client("anthropic") is client


# ── Model registry ───────────────────────────────────────────────────────────


def test_default_model_in_registry():
    assert tb.DEFAULT_MODEL in tb.MODELS


def test_all_models_have_provider_and_id():
    for alias, (provider, model_id) in tb.MODELS.items():
        assert provider, f"{alias} has empty provider"
        assert model_id, f"{alias} has empty model_id"


# ── State management ─────────────────────────────────────────────────────────


def test_load_state_default(tmp_path):
    """load_state returns default when no state file exists."""
    original = tb.STATE_FILE
    tb.STATE_FILE = tmp_path / "nonexistent.json"
    state = tb.load_state()
    assert state["model"] == tb.DEFAULT_MODEL
    tb.STATE_FILE = original


def test_save_and_load_state(tmp_path):
    original = tb.STATE_FILE
    tb.STATE_FILE = tmp_path / "state.json"
    tb.save_state({"model": "sonnet"})
    state = tb.load_state()
    assert state["model"] == "sonnet"
    tb.STATE_FILE = original
