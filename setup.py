#!/usr/bin/env python3
"""
Job Search System — Interactive Setup
Run once after cloning: python setup.py
Works on Linux, macOS, and Windows.
"""

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).parent
IS_WINDOWS = platform.system() == "Windows"
IS_MAC     = platform.system() == "Darwin"
IS_LINUX   = platform.system() == "Linux"
PY         = sys.executable

# ── HELPERS ───────────────────────────────────────────────────────────────────

def banner(text):
    print(f"\n{'─' * 60}")
    print(f"  {text}")
    print('─' * 60)

def ok(text):   print(f"  ✓  {text}")
def info(text): print(f"  →  {text}")
def warn(text): print(f"  ⚠  {text}")
def err(text):  print(f"  ✗  {text}")

def ask(prompt, default=""):
    suffix = f" [{default}]" if default else ""
    val = input(f"     {prompt}{suffix}: ").strip()
    return val or default

def ask_yn(prompt, default=True):
    suffix = "Y/n" if default else "y/N"
    val = input(f"     {prompt} ({suffix}): ").strip().lower()
    if not val:
        return default
    return val.startswith("y")

# ── CHECKS ────────────────────────────────────────────────────────────────────

def check_python():
    banner("Checking Python version")
    v = sys.version_info
    if v < (3, 10):
        err(f"Python 3.10+ required. You have {v.major}.{v.minor}.")
        err("Download from https://python.org")
        sys.exit(1)
    ok(f"Python {v.major}.{v.minor}.{v.micro}")

def check_claude():
    banner("Checking Claude Code")
    if shutil.which("claude"):
        ok("Claude Code found")
    else:
        warn("Claude Code not found in PATH.")
        info("Dashboard doc generation uses 'claude -p' (your Pro/Max subscription).")
        info("Install from: https://claude.ai/code")
        info("If you're on Claude Desktop (Mac/Windows), the dashboard gen won't work,")
        info("but job radar, Telegram bot, and manual resume generation still will.")
        if not ask_yn("Continue without Claude Code?", default=True):
            sys.exit(0)

# ── DEPENDENCIES ──────────────────────────────────────────────────────────────

def install_deps():
    banner("Installing Python dependencies")
    packages = [
        "flask", "python-docx", "anthropic", "openai", "google-genai",
        "requests", "beautifulsoup4", "python-dotenv", "markdown",
    ]
    info(f"Running: pip install {' '.join(packages)}")
    result = subprocess.run(
        [PY, "-m", "pip", "install", "--quiet", *packages],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        err("pip install failed:")
        print(result.stderr)
        sys.exit(1)
    ok("All dependencies installed")

# ── .env ──────────────────────────────────────────────────────────────────────

ENV_VARS = [
    ("ANTHROPIC_API_KEY",  "Anthropic API key (required for job rating)",
     "https://console.anthropic.com/", True),
    ("ADZUNA_APP_ID",      "Adzuna App ID (free — job search API)",
     "https://developer.adzuna.com/", True),
    ("ADZUNA_API_KEY",     "Adzuna API key", "", True),
    ("BRAVE_API_KEY",      "Brave Search API key (free tier available)",
     "https://api.search.brave.com/", True),
    ("TAVILY_API_KEY",     "Tavily API key (free tier available)",
     "https://tavily.com/", True),
    ("GMAIL_FROM",         "Gmail address to send reports from", "", True),
    ("GMAIL_TO",           "Gmail address to send reports to", "", True),
    ("GMAIL_APP_PW",       "Gmail App Password (not your login password)",
     "https://myaccount.google.com/apppasswords", True),
    ("JSEARCH_API_KEY",    "JSearch API key (optional — RapidAPI)",
     "https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch", False),
    ("OPENAI_API_KEY",     "OpenAI API key (optional — GPT-4o in Telegram bot)", "", False),
    ("GOOGLE_API_KEY",     "Google API key (optional — Gemini in Telegram bot)", "", False),
    ("OPENROUTER_API_KEY", "OpenRouter API key (optional)", "", False),
    ("OPENROUTER_BASE_URL","OpenRouter base URL (optional)", "https://openrouter.ai/api/v1", False),
    ("NVIDIA_API_KEY",     "Nvidia NIM API key (optional)", "", False),
    ("NVIDIA_BASE_URL",    "Nvidia NIM base URL (optional)", "", False),
    ("MOONSHOT_API_KEY",   "Moonshot API key (optional — Kimi K2)", "", False),
    ("MOONSHOT_BASE_URL",  "Moonshot base URL (optional)", "", False),
    ("TELEGRAM_BOT_TOKEN", "Telegram bot token (optional)", "", False),
    ("TELEGRAM_USER_ID",   "Your Telegram user ID (optional)", "", False),
]

def create_env():
    banner("Setting up .env (API keys)")
    env_path = REPO / ".env"

    existing = {}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                existing[k.strip()] = v.strip()
        info(f".env already exists with {len(existing)} entries — will update missing keys only")

    lines = []
    skipped = []

    print()
    for key, label, url, required in ENV_VARS:
        if key in existing and existing[key]:
            ok(f"{key} already set")
            lines.append(f"{key}={existing[key]}")
            continue

        tag = "required" if required else "optional — press Enter to skip"
        if url:
            info(f"Get it at: {url}")
        val = ask(f"{label} ({tag})", default=existing.get(key, ""))
        if val:
            lines.append(f"{key}={val}")
        else:
            lines.append(f"# {key}=")
            if required:
                warn(f"{key} not set — job radar may not work until this is added")
        print()

    env_path.write_text("\n".join(lines) + "\n")
    ok(f".env written to {env_path}")

# ── config.py ─────────────────────────────────────────────────────────────────

def create_config():
    banner("Setting up config.py")
    config_path = REPO / "config.py"
    example     = REPO / "config.example.py"

    if config_path.exists():
        ok("config.py already exists — skipping (edit it manually to change settings)")
        return

    shutil.copy(example, config_path)
    ok(f"Copied config.example.py → config.py")
    info("Open config.py and fill in:")
    info("  • CANDIDATE_NAME, CANDIDATE_BACKGROUND — your name and career summary")
    info("  • HOME_CITY, HOME_STATE, HOME_METRO_TERMS — your location")
    info("  • MIN_SALARY — your salary floor")
    info("  • Search query lists — tailor to your target roles")
    info("  • JOB_DOCS — list your docs/ job files once you've written them")

# ── docs/ ─────────────────────────────────────────────────────────────────────

def create_docs():
    banner("Setting up docs/")
    docs_dir      = REPO / "docs"
    templates_dir = REPO / "docs" / "templates"
    docs_dir.mkdir(exist_ok=True)

    if not templates_dir.exists():
        warn("docs/templates/ not found — skipping doc setup")
        return

    templates = list(templates_dir.glob("*.md"))
    if not templates:
        warn("No templates found in docs/templates/")
        return

    copied = []
    for t in templates:
        if t.name.startswith("YYYY"):
            # Don't copy the job file template to root — leave it as a reference
            continue
        dest = docs_dir / t.name
        if not dest.exists():
            shutil.copy(t, dest)
            copied.append(t.name)

    if copied:
        ok(f"Copied templates to docs/: {', '.join(copied)}")
    else:
        ok("docs/ already populated")

    info("Edit each file in docs/ with your personal information.")
    info("Add one YYYY-YYYY-company-title.md per role, using docs/templates/YYYY-YYYY-company-title.md as a guide.")

# ── DIRECTORIES ───────────────────────────────────────────────────────────────

def create_dirs():
    banner("Creating output directories")
    dirs = [
        REPO / "input" / "job-postings",
        REPO / "input" / "raw-notes",
        REPO / "output" / "job-radar",
        REPO / "output" / "documents",
        REPO / "dashboard" / "data",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
        ok(str(d.relative_to(REPO)))

# ── CRON / SCHEDULER ──────────────────────────────────────────────────────────

def setup_scheduler():
    banner("Scheduling the job radar (twice daily at 9am and 4pm)")

    script  = REPO / "scripts" / "job_radar.py"
    repo_str = str(REPO)

    if IS_WINDOWS:
        info("On Windows, use Task Scheduler:")
        info(f'  Action: "{PY}" "{script}"')
        info(f'  Start in: "{repo_str}"')
        info("  Trigger: Daily, repeat every 7 hours (or create two triggers: 9:00 and 16:00)")
        info("  Run whether user is logged on or not")
        if ask_yn("Open Task Scheduler now?", default=False):
            os.startfile("taskschd.msc")
        return

    # Linux / macOS — cron
    cron_line = f"0 9,16 * * 1-5 cd \"{repo_str}\" && \"{PY}\" scripts/job_radar.py >> output/job-radar/cron.log 2>&1"
    info("Proposed cron entry (weekdays, 9am and 4pm):")
    print(f"\n     {cron_line}\n")

    if ask_yn("Add this to your crontab now?", default=True):
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        existing_cron = result.stdout if result.returncode == 0 else ""
        if "job_radar.py" in existing_cron:
            warn("A job_radar.py cron entry already exists — not adding a duplicate")
            info("Run 'crontab -e' to edit manually")
        else:
            new_cron = existing_cron.rstrip("\n") + "\n" + cron_line + "\n"
            proc = subprocess.run(["crontab", "-"], input=new_cron, text=True)
            if proc.returncode == 0:
                ok("Cron entry added")
            else:
                warn("Failed to write crontab — add it manually with: crontab -e")
    else:
        info("Add it manually with: crontab -e")

# ── DASHBOARD AUTOSTART ───────────────────────────────────────────────────────

def setup_dashboard():
    banner("Dashboard autostart (optional)")
    info("The dashboard runs at http://localhost:5000")
    info(f"Start manually: python scripts/dashboard.py")

    if IS_MAC:
        info("On macOS, you can add it as a Login Item or a launchd plist.")
    elif IS_LINUX:
        info("On Linux, add it to your startup applications or a systemd user service.")
    elif IS_WINDOWS:
        info("On Windows, add a shortcut to the Startup folder, or use Task Scheduler.")

    info("See README for details.")

# ── SUMMARY ───────────────────────────────────────────────────────────────────

def summary():
    banner("Setup complete!")
    print("""
  Next steps:

  1. Edit config.py — fill in your name, background, location, salary floor,
     and search queries tailored to your target roles.

  2. Edit your docs/ files — fill in your career history, skills, and education.
     These are used by Claude to generate tailored resumes and cover letters.

  3. Run a test search:
       python scripts/job_radar.py

  4. Start the dashboard:
       python scripts/dashboard.py
       Open http://localhost:5000

  5. (Optional) Set up the Telegram bot:
       python scripts/telegram_bot.py

  Full setup guide: README.md
    """)

# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    print()
    print("  Job Search System — Setup")
    print(f"  Platform: {platform.system()} {platform.release()}")
    print(f"  Repo:     {REPO}")

    check_python()
    check_claude()

    if ask_yn("\n  Install Python dependencies now?", default=True):
        install_deps()

    create_env()
    create_config()
    create_docs()
    create_dirs()

    if ask_yn("\n  Set up the job radar schedule (cron / Task Scheduler)?", default=True):
        setup_scheduler()

    setup_dashboard()
    summary()


if __name__ == "__main__":
    main()
