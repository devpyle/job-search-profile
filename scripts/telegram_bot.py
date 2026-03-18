#!/usr/bin/env python3
"""Telegram bot for job search system — multi-model, authorized user only."""

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

import anthropic
import google.genai as genai
import requests
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
AUTHORIZED_USER = int(os.environ["TELEGRAM_USER_ID"])
REPO_ROOT = Path(__file__).parent.parent
OUTPUT_DIR = REPO_ROOT / "output" / "job-radar"
DOCS_DIR = REPO_ROOT / "docs"
API = f"https://api.telegram.org/bot{TOKEN}"
STATE_FILE = REPO_ROOT / "output" / ".bot_state.json"

# ── Provider clients ──────────────────────────────────────────────────────────

claude_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

openai_client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

nvidia_client = OpenAI(
    api_key=os.environ["NVIDIA_API_KEY"],
    base_url=os.environ["NVIDIA_BASE_URL"],
)

moonshot_client = OpenAI(
    api_key=os.environ["MOONSHOT_API_KEY"],
    base_url=os.environ["MOONSHOT_BASE_URL"],
)

openrouter_client = OpenAI(
    api_key=os.environ["OPENROUTER_API_KEY"],
    base_url=os.environ["OPENROUTER_BASE_URL"],
)

google_client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])

# ── Model registry ────────────────────────────────────────────────────────────
# alias -> (provider, model_id)
MODELS = {
    # Anthropic
    "haiku":              ("anthropic", "claude-haiku-4-5-20251001"),
    "sonnet":             ("anthropic", "claude-sonnet-4-6"),
    "opus":               ("anthropic", "claude-opus-4-6"),
    # OpenAI
    "gpt-4o":             ("openai", "gpt-4o"),
    "gpt-4o-mini":        ("openai", "gpt-4o-mini"),
    # Google (cheaper flash models)
    "gemini":             ("google", "gemini-2.0-flash"),
    "gemini-pro":         ("google", "gemini-2.5-pro-exp-03-25"),
    # Moonshot API (api.moonshot.cn) — Kimi K2.5 series
    "kimi":               ("moonshot", "kimi-k2.5"),
    "kimi-thinking":      ("moonshot", "kimi-k2-thinking-turbo"),
    # Nvidia NIM — reasoning catalog
    "nvidia-kimi":        ("nvidia", "moonshotai/kimi-k2.5"),
    "nvidia-kimi-think":  ("nvidia", "moonshotai/kimi-k2-thinking"),
    "glm":                ("nvidia", "z-ai/glm-4.7"),
    "deepseek":           ("nvidia", "deepseek-ai/deepseek-v3.1"),
    "deepseek-v3":        ("nvidia", "deepseek-ai/deepseek-v3.2"),
    "nemotron":           ("nvidia", "nvidia/nemotron-3-nano-30b-a3b"),
    "devstral":           ("nvidia", "mistralai/devstral-2-123b-instruct-2512"),
    "qwq":                ("nvidia", "qwen/qwq-32b"),
    # OpenRouter
    "or-minimax":         ("openrouter", "minimax/minimax-m2.5"),
    "or-deepseek":        ("openrouter", "deepseek/deepseek-chat"),
    "or-grok":            ("openrouter", "x-ai/grok-3-beta"),
    "or-llama":           ("openrouter", "meta-llama/llama-3.3-70b-instruct"),
    "or-gemini":          ("openrouter", "google/gemini-flash-1.5"),
    # OpenRouter free tier — use /free to see current list, or /model or/model-id
}

DEFAULT_MODEL = "haiku"


# ── State (active model) ──────────────────────────────────────────────────────

def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"model": DEFAULT_MODEL}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state))


# ── Profile context ───────────────────────────────────────────────────────────

def build_system_prompt() -> str:
    sections = [
        "You are a job search assistant. "
        "You have full context of the user's career profile, target roles, and active job search. "
        "Be direct, concise, and practical. No fluff.\n"
    ]
    for filename in ["personal-info.md", "technical-skills.md", "resume-generation-rules.md"]:
        path = DOCS_DIR / filename
        if path.exists():
            sections.append(f"--- {filename} ---\n{path.read_text()}\n")
    for path in sorted(DOCS_DIR.glob("????-????-*.md")):
        sections.append(f"--- {path.name} ---\n{path.read_text()}\n")
    reports = sorted(OUTPUT_DIR.glob("*.md"), reverse=True)
    if reports:
        sections.append(f"--- Latest Job Radar ({reports[0].name}) ---\n{reports[0].read_text()}\n")
    return "\n".join(sections)


# ── Claude router ─────────────────────────────────────────────────────────────

def ask_claude(model_id: str, system: str, message: str) -> str:
    response = claude_client.messages.create(
        model=model_id,
        max_tokens=1024,
        system=system,
        messages=[{"role": "user", "content": message}],
    )
    return response.content[0].text


def ask_openai_compat(client: OpenAI, model_id: str, system: str, message: str) -> str:
    response = client.chat.completions.create(
        model=model_id,
        max_tokens=1024,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": message},
        ],
    )
    return response.choices[0].message.content


def ask_google(model_id: str, system: str, message: str) -> str:
    response = google_client.models.generate_content(
        model=model_id,
        contents=f"{system}\n\nUser: {message}",
    )
    return response.text


def ask(message: str) -> tuple[str, str]:
    """Route message to active model. Returns (reply, model_alias)."""
    state = load_state()
    alias = state.get("model", DEFAULT_MODEL)
    system = build_system_prompt()

    # Arbitrary OpenRouter model via "or/..." syntax
    if alias.startswith("or/"):
        model_id = state.get("_or_custom", alias[3:])
        reply = ask_openai_compat(openrouter_client, model_id, system, message)
        return reply, model_id

    # Arbitrary Nvidia NIM model via "nv/..." syntax
    if alias.startswith("nv/"):
        model_id = state.get("_nv_custom", alias[3:])
        reply = ask_openai_compat(nvidia_client, model_id, system, message)
        return reply, model_id

    provider, model_id = MODELS.get(alias, MODELS[DEFAULT_MODEL])

    if provider == "anthropic":
        reply = ask_claude(model_id, system, message)
    elif provider == "google":
        reply = ask_google(model_id, system, message)
    elif provider == "openai":
        reply = ask_openai_compat(openai_client, model_id, system, message)
    elif provider == "nvidia":
        reply = ask_openai_compat(nvidia_client, model_id, system, message)
    elif provider == "moonshot":
        reply = ask_openai_compat(moonshot_client, model_id, system, message)
    elif provider == "openrouter":
        reply = ask_openai_compat(openrouter_client, model_id, system, message)
    else:
        reply = f"Unknown provider: {provider}"

    return reply, alias


# ── Telegram helpers ──────────────────────────────────────────────────────────

def send(chat_id: int, text: str):
    while text:
        chunk, text = text[:4000], text[4000:]
        requests.post(f"{API}/sendMessage", json={
            "chat_id": chat_id,
            "text": chunk,
            "parse_mode": "Markdown",
        }, timeout=10)


def get_updates(offset: int) -> list:
    r = requests.get(f"{API}/getUpdates", params={"offset": offset, "timeout": 30}, timeout=40)
    r.raise_for_status()
    return r.json().get("result", [])


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_radar(chat_id: int):
    send(chat_id, "Running job radar... (~30 seconds)")
    result = subprocess.run(
        ["python3", "scripts/job_radar.py"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=120,
    )
    if result.returncode == 0:
        send(chat_id, "Done. Check your email for the full report.")
    else:
        send(chat_id, f"Run failed:\n```\n{result.stderr[-500:]}\n```")


def cmd_latest(chat_id: int):
    reports = sorted(OUTPUT_DIR.glob("*.md"), reverse=True)
    if not reports:
        send(chat_id, "No reports yet. Try /radar.")
        return
    send(chat_id, reports[0].read_text())


def cmd_status(chat_id: int):
    reports = sorted(OUTPUT_DIR.glob("*.md"), reverse=True)
    if not reports:
        send(chat_id, "No runs yet. Send /radar to trigger one.")
        return
    latest = reports[0]
    header = "\n".join(latest.read_text().splitlines()[:2])
    mtime = datetime.fromtimestamp(latest.stat().st_mtime)
    state = load_state()
    send(chat_id, (
        f"Last run: {mtime.strftime('%a %b %-d at %-I:%M %p')}\n"
        f"Active model: *{state.get('model', DEFAULT_MODEL)}*\n\n"
        f"{header}"
    ))


def fetch_free_models() -> list[dict]:
    """Fetch current free models from OpenRouter API."""
    r = requests.get(
        "https://openrouter.ai/api/v1/models",
        headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"},
        timeout=10,
    )
    r.raise_for_status()
    models = r.json().get("data", [])
    return [
        m for m in models
        if str(m.get("pricing", {}).get("prompt", "1")) == "0"
        or m.get("id", "").endswith(":free")
    ]


def cmd_nvidia(chat_id: int):
    send(chat_id, "_Fetching current Nvidia NIM models..._")
    try:
        r = requests.get(
            f"{os.environ['NVIDIA_BASE_URL']}/models",
            headers={"Authorization": f"Bearer {os.environ['NVIDIA_API_KEY']}"},
            timeout=10,
        )
        r.raise_for_status()
        models = r.json().get("data", [])
        if not models:
            send(chat_id, "No models returned from Nvidia API.")
            return
        lines = [f"*Nvidia NIM — {len(models)} available models:*\n"]
        for m in sorted(models, key=lambda x: x.get("id", "")):
            lines.append(f"`{m.get('id')}`")
        lines.append("\nTo use one: `/model nv/org/model-name`")
        send(chat_id, "\n".join(lines))
    except Exception as e:
        send(chat_id, f"Error fetching Nvidia models: {e}")


def cmd_free(chat_id: int):
    send(chat_id, "_Fetching current free models from OpenRouter..._")
    try:
        free = fetch_free_models()
        if not free:
            send(chat_id, "No free models found right now.")
            return
        lines = ["*Free OpenRouter models right now:*\n"]
        for m in sorted(free, key=lambda x: x.get("id", "")):
            name = m.get("name") or m.get("id")
            mid = m.get("id")
            ctx = m.get("context_length", "")
            ctx_str = f" ({ctx//1000}k ctx)" if ctx else ""
            lines.append(f"`{mid}`{ctx_str}")
        lines.append("\nTo use one: `/model or/model-id`")
        send(chat_id, "\n".join(lines))
    except Exception as e:
        send(chat_id, f"Error fetching free models: {e}")


def cmd_model(chat_id: int, args: str):
    alias = args.strip().lower()
    if not alias:
        state = load_state()
        current = state.get("model", DEFAULT_MODEL)
        model_list = "\n".join(f"  `{k}` — {v[1]}" for k, v in sorted(MODELS.items()))
        send(chat_id, (
            f"Current model: *{current}*\n\n"
            f"Named aliases:\n{model_list}\n\n"
            "Use any OpenRouter model directly: `/model or/google/gemini-2.0-flash-exp:free`\n"
            "See free models: `/free`"
        ))
        return

    # Support arbitrary OpenRouter models via "or/org/model-name" syntax
    if alias.startswith("or/"):
        model_id = alias[3:]
        state = load_state()
        state["model"] = alias
        state["_or_custom"] = model_id
        save_state(state)
        send(chat_id, f"Switched to OpenRouter model `{model_id}`")
        return

    # Support arbitrary Nvidia NIM models via "nv/org/model-name" syntax
    if alias.startswith("nv/"):
        model_id = alias[3:]
        state = load_state()
        state["model"] = alias
        state["_nv_custom"] = model_id
        save_state(state)
        send(chat_id, f"Switched to Nvidia NIM model `{model_id}`")
        return

    if alias not in MODELS:
        send(chat_id, f"Unknown model `{alias}`. Send `/model` to see options, or use `or/model-id` for any OpenRouter model.")
        return
    state = load_state()
    state["model"] = alias
    state.pop("_or_custom", None)
    save_state(state)
    _, model_id = MODELS[alias]
    send(chat_id, f"Switched to *{alias}* (`{model_id}`)")


def cmd_help(chat_id: int):
    state = load_state()
    current = state.get("model", DEFAULT_MODEL)
    send(chat_id, (
        "*Job Search Bot*\n\n"
        "/radar — run a job search now\n"
        "/latest — most recent report\n"
        "/status — last run summary\n"
        "/model — list or switch models\n"
        "/nvidia — list all current Nvidia NIM models\n"
        "/free — show current free OpenRouter models\n"
        "/help — this message\n\n"
        f"Active model: *{current}*\n\n"
        "Or just type anything to chat."
    ))


# ── Message handler ───────────────────────────────────────────────────────────

def handle(message: dict):
    chat_id = message.get("chat", {}).get("id")
    user_id = message.get("from", {}).get("id")
    text = message.get("text", "").strip()

    if user_id != AUTHORIZED_USER:
        send(chat_id, "Unauthorized.")
        return

    if text.startswith("/radar"):
        cmd_radar(chat_id)
    elif text.startswith("/latest"):
        cmd_latest(chat_id)
    elif text.startswith("/status"):
        cmd_status(chat_id)
    elif text.startswith("/nvidia"):
        cmd_nvidia(chat_id)
    elif text.startswith("/free"):
        cmd_free(chat_id)
    elif text.startswith("/model"):
        cmd_model(chat_id, text[6:])
    elif text.startswith("/help") or text.startswith("/start"):
        cmd_help(chat_id)
    else:
        send(chat_id, "_Thinking..._")
        try:
            reply, alias = ask(text)
            send(chat_id, f"{reply}\n\n_— {alias}_")
        except Exception as e:
            send(chat_id, f"Error: {e}")


# ── Main loop ─────────────────────────────────────────────────────────────────

def main():
    print("Bot started. Listening for messages...")
    offset = 0
    while True:
        try:
            updates = get_updates(offset)
            for update in updates:
                offset = update["update_id"] + 1
                if "message" in update:
                    handle(update["message"])
        except requests.exceptions.Timeout:
            pass
        except Exception as e:
            print(f"Error: {e}")


if __name__ == "__main__":
    main()
