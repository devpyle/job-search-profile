#!/usr/bin/env python3
"""
Job Search System — Interactive Setup
Run once after cloning: python setup.py
Works on Linux, macOS, and Windows.
"""

import os
import platform
import re
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
        "requests", "beautifulsoup4", "python-dotenv", "markdown", "pypdf",
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
    ("ADZUNA_APP_KEY",     "Adzuna API key", "", True),
    ("BRAVE_API_KEY",      "Brave Search API key (paid — optional, skip if you don't have one)",
     "https://api.search.brave.com/", False),
    ("TAVILY_API_KEY",     "Tavily API key (free tier available)",
     "https://tavily.com/", True),
    ("GMAIL_FROM",         "Gmail address to send reports from (optional — skip to use dashboard only)",
     "", False),
    ("GMAIL_TO",           "Gmail address to receive reports (optional)", "", False),
    ("GMAIL_APP_PW",       "Gmail App Password (optional — needed only if using email delivery)",
     "https://myaccount.google.com/apppasswords", False),
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
    return existing  # return so profile setup can use the API key

def load_env_key():
    """Read ANTHROPIC_API_KEY from .env without importing dotenv."""
    env_path = REPO / ".env"
    if not env_path.exists():
        return os.environ.get("ANTHROPIC_API_KEY", "")
    for line in env_path.read_text().splitlines():
        if line.startswith("ANTHROPIC_API_KEY="):
            return line.partition("=")[2].strip()
    return os.environ.get("ANTHROPIC_API_KEY", "")

# ── RESUME EXTRACTION ─────────────────────────────────────────────────────────

def extract_docx(path: Path) -> str:
    from docx import Document
    doc = Document(str(path))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())

def extract_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        err("pypdf not installed. Run: pip install pypdf")
        return ""
    reader = PdfReader(str(path))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(pages)

def extract_resume(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return extract_docx(path)
    elif suffix == ".pdf":
        return extract_pdf(path)
    elif suffix in (".txt", ".md"):
        return path.read_text(encoding="utf-8", errors="ignore")
    else:
        warn(f"Unsupported file type: {suffix}. Supported: .docx, .pdf, .txt, .md")
        return ""

# ── PROFILE QUESTIONS ─────────────────────────────────────────────────────────

def gather_preferences() -> dict:
    """Ask the user targeted questions to supplement the resume."""
    banner("Your job search preferences")
    info("These are used to configure your search queries and Claude rating prompt.")
    info("Press Enter to skip any field — you can fill it in config.py later.\n")

    prefs = {}

    prefs["target_titles"] = ask(
        "Target job titles (comma-separated)",
        default="Product Owner, Product Manager, Business Analyst"
    )
    prefs["industries"] = ask(
        "Industries you're open to (comma-separated)",
        default="fintech, banking, SaaS, enterprise software, healthcare"
    )
    prefs["city"]  = ask("Your city", default="")
    prefs["state"] = ask("Your state (2-letter abbreviation)", default="")
    prefs["metro_terms"] = ask(
        "Local metro area search terms (comma-separated — cities/regions near you)",
        default=""
    )
    prefs["remote"] = ask(
        "Work preference",
        default="remote preferred, open to hybrid"
    )
    prefs["salary"] = ask("Salary floor (numbers only, e.g. 120000)", default="100000")
    prefs["linkedin"] = ask("Your LinkedIn URL (optional)", default="")
    prefs["email"]    = ask("Your email address (optional)", default="")
    prefs["phone"]    = ask("Your phone number (optional)", default="")
    prefs["specialty"] = ask(
        "One-line specialty / differentiator (e.g. 'API platform strategy in regulated finance')",
        default=""
    )

    return prefs

# ── CLAUDE PROFILE GENERATION ─────────────────────────────────────────────────

TEMPLATES = {
    "personal-info.md": (REPO / "docs" / "templates" / "personal-info.md"),
    "education.md":     (REPO / "docs" / "templates" / "education.md"),
    "technical-skills.md": (REPO / "docs" / "templates" / "technical-skills.md"),
    "YYYY-YYYY-company-title.md": (REPO / "docs" / "templates" / "YYYY-YYYY-company-title.md"),
}

def read_template(name: str) -> str:
    p = TEMPLATES.get(name)
    if p and p.exists():
        return p.read_text(encoding="utf-8")
    return ""

def build_prompt(resume_text: str, prefs: dict) -> str:
    job_template    = read_template("YYYY-YYYY-company-title.md")
    info_template   = read_template("personal-info.md")
    skills_template = read_template("technical-skills.md")
    edu_template    = read_template("education.md")

    return f"""You are setting up a job search profile system. Given a resume and some preferences, generate structured profile documents that will be used to create tailored resumes and cover letters with AI.

## Resume
{resume_text}

## Preferences provided by the user
- Target job titles: {prefs.get('target_titles', 'not specified')}
- Industries open to: {prefs.get('industries', 'not specified')}
- Location: {prefs.get('city', '')}, {prefs.get('state', '')}
- Work preference: {prefs.get('remote', 'remote preferred')}
- Salary floor: ${prefs.get('salary', '100000')}
- Specialty/differentiator: {prefs.get('specialty', 'not specified')}
- Email: {prefs.get('email', 'not provided')}
- Phone: {prefs.get('phone', 'not provided')}
- LinkedIn: {prefs.get('linkedin', 'not provided')}

## Your task
Generate the following files. Use the templates as your exact structure and formatting guide — follow the frontmatter schema and section headings precisely. Fill in real content from the resume; do not leave template placeholder text. Where information is not available, write a reasonable placeholder in brackets like [add here].

Output each file wrapped in XML tags exactly like this:
<file name="personal-info.md">
...file content...
</file>

### Files to generate:

**1. personal-info.md** — contact info, headline, summary, industry openness
Template:
{info_template}

**2. education.md** — degrees and formatting guidance
Template:
{edu_template}

**3. technical-skills.md** — master skills list grouped by category
Template:
{skills_template}

**4. One job file per role** — newest to oldest. Name each file YYYY-YYYY-company-slugified-title.md (e.g. 2021-2024-acme-product-owner.md). For current role use present instead of end year.
Template for each job file:
{job_template}

Important:
- Key achievements bullets must be resume-ready: past tense, strong verb, metric where available
- Extract real metrics and outcomes from the resume wherever possible
- The 30-second summary should be narrative, not bullet points
- Signature story should be the strongest STAR story you can construct from the resume
- technical-skills.md should consolidate ALL skills across all roles
- personal-info.md Summary Blurb should be 2-3 polished sentences suitable for a cover letter opening
"""

def parse_files(response: str) -> dict[str, str]:
    files = {}
    for match in re.finditer(r'<file name="([^"]+)">(.*?)</file>', response, re.DOTALL):
        files[match.group(1).strip()] = match.group(2).strip()
    return files

def generate_profile(resume_text: str, prefs: dict, api_key: str) -> dict[str, str]:
    """Generate profile docs via claude -p (Pro/Max subscription) or API fallback."""
    prompt = build_prompt(resume_text, prefs)
    print()

    # Prefer claude -p — uses the user's Pro/Max subscription, better model, no API cost
    if shutil.which("claude"):
        info("Generating profile documents via Claude Code (claude -p)…")
        result = subprocess.run(
            ["claude", "-p", prompt],
            capture_output=True, text=True, timeout=180,
        )
        if result.returncode == 0 and result.stdout.strip():
            return parse_files(result.stdout)
        warn(f"claude -p failed ({result.stderr[:200].strip()}) — falling back to API…")

    # Fallback: Anthropic API
    if not api_key:
        err("No ANTHROPIC_API_KEY found and Claude Code is not available.")
        return {}

    info("Generating profile documents via Anthropic API (claude-sonnet-4-6)…")
    import anthropic
    client  = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8000,
        messages=[{"role": "user", "content": prompt}],
    )
    return parse_files(message.content[0].text)

def write_profile_files(files: dict[str, str]) -> list[str]:
    """Write generated files to docs/ and return list of job doc filenames."""
    docs_dir = REPO / "docs"
    docs_dir.mkdir(exist_ok=True)

    job_docs = []
    for filename, content in files.items():
        dest = docs_dir / filename
        dest.write_text(content + "\n", encoding="utf-8")
        ok(f"Created docs/{filename}")
        if re.match(r'^\d{4}', filename):
            job_docs.append(filename)

    # Sort job docs newest → oldest
    job_docs.sort(reverse=True)
    return job_docs

def setup_profile():
    banner("Build your profile from your resume (optional)")
    info("Upload your resume and Claude will generate your docs/ profile files automatically.")
    info("Supports: .docx, .pdf, .txt, .md")
    info("Skip this step if you prefer to fill in the docs/ templates manually.\n")

    if not ask_yn("Import your resume now?", default=True):
        return []

    # Get resume path
    while True:
        raw = ask("Path to your resume file").strip().strip('"').strip("'")
        if not raw:
            info("Skipping resume import.")
            return []
        path = Path(raw).expanduser()
        if path.exists():
            break
        err(f"File not found: {path}")
        if not ask_yn("Try again?", default=True):
            return []

    resume_text = extract_resume(path)
    if not resume_text.strip():
        warn("Could not extract text from the resume. Skipping profile generation.")
        return []
    ok(f"Extracted {len(resume_text.split())} words from {path.name}")

    prefs = gather_preferences()

    api_key = load_env_key()
    if not api_key:
        warn("ANTHROPIC_API_KEY not found — cannot call Claude.")
        warn("Add it to .env and re-run setup.py, or fill in docs/ manually.")
        return []

    try:
        files = generate_profile(resume_text, prefs, api_key)
    except Exception as e:
        err(f"Claude API call failed: {e}")
        warn("You can fill in the docs/ template files manually.")
        return []

    if not files:
        warn("Claude returned no files. The docs/ templates are available to fill in manually.")
        return []

    ok(f"Claude generated {len(files)} profile files")
    job_docs = write_profile_files(files)
    return job_docs, prefs

# ── config.py ─────────────────────────────────────────────────────────────────

def create_config(job_docs: list[str] | None = None, prefs: dict | None = None):
    banner("Setting up config.py")
    config_path = REPO / "config.py"
    example     = REPO / "config.example.py"

    if not config_path.exists():
        shutil.copy(example, config_path)
        ok("Copied config.example.py → config.py")

    if not prefs and not job_docs:
        info("Open config.py and fill in your personal settings.")
        return

    # Patch config.py with values we have
    text = config_path.read_text(encoding="utf-8")
    changes = []

    p = prefs or {}

    name = ""
    # Try to extract name from generated personal-info.md
    pi = REPO / "docs" / "personal-info.md"
    if pi.exists():
        m = re.search(r'\*\*Name:\*\*\s*(.+)', pi.read_text())
        if m:
            name = m.group(1).strip()

    if name and "Your Name" in text:
        text = text.replace('"Your Name"', f'"{name}"')
        changes.append(f"CANDIDATE_NAME = {name!r}")

    if p.get("city") and "Your City" in text:
        text = text.replace('"Your City"', f'"{p["city"]}"')
        changes.append(f"HOME_CITY = {p['city']!r}")

    if p.get("state") and '"NC"' in text:
        text = text.replace('"NC"', f'"{p["state"].upper()}"')
        changes.append(f"HOME_STATE = {p['state'].upper()!r}")

    if p.get("salary"):
        try:
            salary_int = int(re.sub(r'[^0-9]', '', p["salary"]))
            text = re.sub(r'MIN_SALARY\s*=\s*[\d_]+', f'MIN_SALARY = {salary_int:_}', text)
            changes.append(f"MIN_SALARY = {salary_int:,}")
        except ValueError:
            pass

    if p.get("metro_terms"):
        terms = [t.strip().lower() for t in p["metro_terms"].split(",") if t.strip()]
        if terms:
            terms_repr = "\n    " + ",\n    ".join(f'"{t}"' for t in terms) + ",\n"
            text = re.sub(
                r'HOME_METRO_TERMS\s*=\s*\[.*?\]',
                f'HOME_METRO_TERMS = [{terms_repr}]',
                text, flags=re.DOTALL
            )
            changes.append(f"HOME_METRO_TERMS = {terms}")

    if job_docs:
        docs_repr = "\n    " + ",\n    ".join(f'"{d}"' for d in job_docs) + ",\n"
        text = re.sub(
            r'JOB_DOCS\s*=\s*\[.*?\]',
            f'JOB_DOCS = [{docs_repr}]',
            text, flags=re.DOTALL
        )
        changes.append(f"JOB_DOCS = {job_docs}")

    config_path.write_text(text, encoding="utf-8")

    if changes:
        ok("Patched config.py with your settings:")
        for c in changes:
            info(f"  {c}")
    info("Review config.py and fill in CANDIDATE_BACKGROUND, search queries, and anything else marked with [brackets].")

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

    script   = REPO / "scripts" / "job_radar.py"
    repo_str = str(REPO)

    if IS_WINDOWS:
        info("On Windows, use Task Scheduler:")
        info(f'  Action: "{PY}" "{script}"')
        info(f'  Start in: "{repo_str}"')
        info("  Trigger: Daily — create two triggers at 9:00 and 16:00")
        info("  Run whether user is logged on or not")
        if ask_yn("Open Task Scheduler now?", default=False):
            os.startfile("taskschd.msc")
        return

    cron_line = f'0 9,16 * * 1-5 cd "{repo_str}" && "{PY}" scripts/job_radar.py >> output/job-radar/cron.log 2>&1'
    info("Proposed cron entry (weekdays, 9am and 4pm):")
    print(f"\n     {cron_line}\n")

    if ask_yn("Add this to your crontab now?", default=True):
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        existing_cron = result.stdout if result.returncode == 0 else ""
        if "job_radar.py" in existing_cron:
            warn("A job_radar.py entry already exists — not adding a duplicate")
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
    info("Start manually: python scripts/dashboard.py")
    if IS_MAC:
        info("On macOS, add it as a Login Item or a launchd plist.")
    elif IS_LINUX:
        info("On Linux, add it to startup applications or a systemd user service.")
    elif IS_WINDOWS:
        info("On Windows, add a shortcut to the Startup folder, or use Task Scheduler.")
    info("See README for details.")

# ── SUMMARY ───────────────────────────────────────────────────────────────────

def summary(profile_generated: bool):
    banner("Setup complete!")

    step2 = (
        "  2. Review docs/ — Claude has pre-filled your profile files from your resume.\n"
        "     Check each file, fill in any [brackets], and add/edit as needed."
    ) if profile_generated else (
        "  2. Fill in your docs/ files — use docs/templates/ as a guide.\n"
        "     One file per role (YYYY-YYYY-company-title.md), plus personal-info,\n"
        "     education, and technical-skills."
    )

    print(f"""
  Next steps:

  1. Review config.py — check CANDIDATE_BACKGROUND, search queries,
     and any settings still showing placeholder text.

{step2}

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
    create_dirs()

    # Profile import — do before config so we can patch config with real values
    result     = setup_profile()
    job_docs   = []
    prefs      = {}
    profile_generated = False
    if result:
        job_docs, prefs = result
        profile_generated = bool(job_docs)

    create_config(job_docs=job_docs or None, prefs=prefs or None)

    if ask_yn("\n  Set up the job radar schedule (cron / Task Scheduler)?", default=True):
        setup_scheduler()

    setup_dashboard()
    summary(profile_generated)


if __name__ == "__main__":
    main()
