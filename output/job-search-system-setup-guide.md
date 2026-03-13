# Job Search & Resume System — Setup Guide

A Claude Code-powered job search system that runs automated daily searches across multiple job APIs, emails you results twice a day, and generates tailored resumes and cover letters on demand. Here's everything you need to build your own.

---

## What This System Does

**Automated Job Radar**
- Queries Adzuna, Brave Search, and Tavily twice a day (9am and 4pm)
- Deduplicates results across runs so you only see new postings
- Rates each job 1–5 stars based on keyword match to your target roles
- Saves a dated report to your output folder
- Emails the report to your inbox automatically

**Resume & Cover Letter Generation (on demand)**
- Claude reads your full career profile from structured docs
- Runs a fit assessment before writing anything — tells you Apply or Don't Apply with honest reasoning
- Extracts keywords from the job description and maps them to your real experience
- Writes tailored, ATS-friendly resumes in HTML format
- Follows strict voice rules to avoid template-sounding output

---

## Prerequisites

1. **Claude Code** installed — [claude.ai/code](https://claude.ai/code)
2. **Python 3.10+** with pip
3. **Git** and a GitHub account
4. API keys for three services (all have free tiers):
   - [Adzuna](https://developer.adzuna.com/) — structured job listings with salary data
   - [Brave Search API](https://api.search.brave.com/) — web search for job postings
   - [Tavily](https://tavily.com/) — AI-optimized search
5. A **Gmail account** with an App Password for email delivery

---

## Step 1 — Create Your Repo

```
mkdir job-search-profile
cd job-search-profile
git init
mkdir -p docs input/job-postings input/old-resumes input/raw-notes
mkdir -p output/resumes output/cover-letters output/job-radar
touch output/resumes/.gitkeep output/cover-letters/.gitkeep output/job-radar/.gitkeep
```

Create a `.gitignore`:
```
.env
*.log
__pycache__/
*.pyc
.DS_Store
```

---

## Step 2 — Install Python Dependencies

```bash
pip install requests python-dotenv fastmcp
```

---

## Step 3 — Set Up Your API Keys

Create a `.env` file in the repo root (never commit this):

```
ADZUNA_APP_ID=your_adzuna_app_id
ADZUNA_APP_KEY=your_adzuna_app_key
BRAVE_API_KEY=your_brave_api_key
TAVILY_API_KEY=your_tavily_api_key
GMAIL_APP_PW=your_gmail_app_password
```

**Getting a Gmail App Password:**
1. Go to myaccount.google.com → Security → 2-Step Verification (must be enabled)
2. Search for "App Passwords" at the bottom of the Security page
3. Create one for "Mail" — paste the 16-character password into `.env`

**Test email delivery before going further:**
```python
python3 -c "
import smtplib, os
from dotenv import load_dotenv
from email.message import EmailMessage
load_dotenv()
msg = EmailMessage()
msg['Subject'] = 'Test'
msg['From'] = msg['To'] = 'your@gmail.com'
msg.set_content('It works.')
with smtplib.SMTP_SSL('smtp.gmail.com', 465) as s:
    s.login('your@gmail.com', os.environ['GMAIL_APP_PW'])
    s.send_message(msg)
print('Sent.')
"
```

---

## Step 4 — Build Your Profile Docs

This is the most important part. Claude uses these files to generate resumes. Create one markdown file per job in `docs/`, plus supporting files.

**File naming:** `YYYY-YYYY-company-title.md`

**Required files:**
- `docs/personal-info.md` — contact info, headline, summary blurb, industry openness
- `docs/technical-skills.md` — master skills list organized by category
- `docs/education.md` — degrees with formatting guidance
- One `docs/YYYY-YYYY-company-title.md` per role

**Job file structure** (use this template for each role):

```markdown
---
type: job
company: "Company Name"
title: "Your Title"
location: "City, ST"
start: "YYYY-MM"
end: "YYYY-MM"  # or "present"
domain: "industry"
keywords: ["keyword1", "keyword2"]
---

## 30-Second Summary
[2-3 sentence narrative of what you did and why it mattered]

## What I Owned
- Responsibility 1
- Responsibility 2

## Key Achievements
- **Bold the metric.** Context of what was broken, what you did, result with number.
- **Another metric.** Same pattern.

## Signature Story (STAR)
**Situation:** ...
**Task:** ...
**Action:** ...
**Result:** ...

## Technical Skills Used
- Tool 1, Tool 2, Tool 3
```

**Tips for writing Key Achievements:**
- Every bullet needs a metric or concrete outcome
- Format: situation → what you did → measurable result
- These get pulled directly into resumes, so make them resume-ready now
- Mine your old resumes and LinkedIn for numbers you may have forgotten

---

## Step 5 — Create CLAUDE.md

This file tells Claude how to behave in your repo. Create `CLAUDE.md` in the repo root:

```markdown
# CLAUDE.md

## What This Repository Is
A structured job search profile for [Your Name]. The docs/ folder is a personal
source of truth used to generate resumes, cover letters, and other application
artifacts on demand.

## Resume and Cover Letter Generation
Always read docs/resume-generation-rules.md first and follow those rules exactly
before generating any resume or cover letter.

## Key Facts
- Target roles: [your target titles]
- Industries: [your target industries]
- Location: [your city] — remote preferred / open to hybrid
- Core differentiator: [what makes you stand out]

## Generating Artifacts
1. Pull contact/headline from personal-info.md
2. Pull bullets verbatim from Key Achievements sections
3. Tailor framing to the target industry
4. Filter technical-skills.md to relevant skills only
```

---

## Step 6 — Create Resume Generation Rules

Create `docs/resume-generation-rules.md` — this is the instruction set Claude follows when writing resumes. Key sections to include:

- **Rule 0 — Fit Assessment:** Claude evaluates the job first and gives you Apply/Don't Apply before writing anything
- **Keyword Extraction:** Pull all relevant terms from the JD
- **Keyword Mapping:** Match JD requirements to your actual experience — never invent skills
- **Writing Rules:** SOAR bullets (Situation, Obstacle, Action, Result), bold metrics, no buzzwords
- **Voice Rules:** Plain English, no "results-driven", no "passionate about", no em dashes
- **Formatting Rules:** ATS-friendly HTML output, no tables or icons

You can use the one from this repo as a starting point — it's at `docs/resume-generation-rules.md`.

---

## Step 7 — Set Up the Job Radar Script

Create `scripts/job_radar.py`. The script should:

1. Load API keys from `.env`
2. Run search queries against Adzuna, Brave, and Tavily
3. Deduplicate results against a `.seen.json` file
4. Rate each job (1–5 stars) based on keyword match to your target roles
5. Save a formatted markdown report to `output/job-radar/YYYY-MM-DD-[am|pm].md`
6. Email the report via Gmail SMTP

You can copy `scripts/job_radar.py` from this repo and update:
- `EMAIL` constant to your Gmail address
- Search queries in `search_adzuna()`, `search_brave()`, and `search_tavily()` to match your target roles, locations, and industries
- The `rate()` function keywords to match your specific titles and domains

**Key note on Adzuna:** The US API doesn't support `where=remote`. For remote searches, omit the `where` parameter and add "remote" to your `what` keywords instead.

---

## Step 8 — Schedule with Cron

```bash
# Open crontab
crontab -e

# Add these two lines (adjust path to your repo)
0 9  * * *  cd /path/to/job-search-profile && /usr/bin/python3 scripts/job_radar.py >> output/job-radar/cron.log 2>&1
0 16 * * *  cd /path/to/job-search-profile && /usr/bin/python3 scripts/job_radar.py >> output/job-radar/cron.log 2>&1
```

This fires at 9am and 4pm every day. Adjust times to your preference. Cron log goes to `output/job-radar/cron.log` for debugging.

**Note:** Cron uses a minimal environment — it won't inherit your shell's PATH or conda/pyenv setup. If you use a virtual environment, use the full path to its Python binary instead of `/usr/bin/python3`.

---

## Daily Workflow

**Job radar runs automatically.** Check your email at 9am and 4pm for new postings. 5-star jobs go to the top — those are your priority applications.

**To generate a resume:**
1. Save the job description to `input/job-postings/company-title.txt`
2. Open Claude Code in the repo
3. Run: `generate resume for input/job-postings/company-title.txt`
4. Claude will assess the fit and tell you Apply or Don't Apply
5. If Apply — confirm and Claude builds the resume to `output/resumes/company-title-YYYY-MM-DD.html`
6. Open the HTML in a browser, copy-paste into Google Docs, adjust formatting

**To generate a cover letter:**
- Same flow — drop the JD in `input/job-postings/`, ask Claude for a cover letter
- Claude reads your signature stories and matches your top 2-3 experiences to the role

---

## Repo Structure (final)

```
job-search-profile/
├── CLAUDE.md                          # Claude Code instructions
├── .env                               # API keys (never commit)
├── .gitignore
├── docs/
│   ├── personal-info.md
│   ├── technical-skills.md
│   ├── education.md
│   ├── resume-generation-rules.md
│   ├── YYYY-YYYY-company-title.md     # one per role
│   └── ...
├── input/
│   ├── job-postings/                  # drop JDs here before generating
│   ├── old-resumes/                   # source material for backfilling docs
│   └── raw-notes/                     # informal role notes to clean up
├── output/
│   ├── resumes/                       # generated HTML resumes
│   ├── cover-letters/                 # generated cover letters
│   └── job-radar/                     # daily search reports + .seen.json
└── scripts/
    └── job_radar.py                   # automated search + email script
```

---

## Rough Time to Set Up

- API keys and .env: 20 minutes
- Writing your profile docs: 2–4 hours (this is the real work — do it right)
- Copying and customizing the scripts: 30 minutes
- Cron setup and email test: 15 minutes

The profile docs are the investment. Once they're solid, Claude can generate a tailored resume in under 2 minutes.
