# Claude Code Job Search System

A Claude Code-powered job search system that runs automated daily searches across multiple job APIs, emails you results twice a day, and provides a full web dashboard for tracking applications and generating tailored resumes and cover letters.

Built and maintained using [Claude Code](https://claude.ai/code).

---

## What It Does

**Automated Job Radar**
- Queries Adzuna, Brave Search, Tavily, LinkedIn, Remotive, WeWorkRemotely, Himalayas, RemoteOK, Jobicy, JSearch, Greenhouse, Lever, and Ashby ATS twice a day (9am and 4pm via cron)
- Deduplicates results across runs using multi-key dedup (company+title and URL) so you only see new postings
- Filters out wrong titles, non-US locations, onsite/hybrid roles outside your area, staffing agencies, closed listings, broken URLs, salary below floor, and aggregate/category pages
- Rates each job with Claude Haiku — `Apply Now / Worth a Look / Weak Match / Skip` — with a one-sentence reason
- Saves a dated markdown report to `output/job-radar/`
- Emails the full report in the email body and attaches the `.md` file

**Web Dashboard** (`scripts/dashboard.py`)
- Local Flask app — run it on your always-on machine, open at `http://localhost:5000`
- **Kanban board** — drag jobs through: New → Reviewing → Drafting → Ready → Applied → Phone Screen → Interview → Offer → Accepted / Rejected / Passed
- **Radar view** — browse reports in-browser, save jobs to the board with one click
  - Comment box on every card to note why a job isn't a fit or flag search tweaks
  - Dismiss jobs you've reviewed — stays hidden on future visits, toggle to show dismissed
  - Mark entire reports as reviewed — ✓ appears in the report dropdown
- **Job detail** — full description, timestamped notes, status changes
- **Document generation** — generates tailored resume + cover letter via Claude (uses your Pro subscription via `claude -p`, no API cost)
- **Two-panel editor** — edit resume and cover letter side by side, regenerate with custom instructions, version history, mark final
- **DOCX export** — download resume or cover letter as a Word file
- **SQLite database** — all jobs, notes, documents, comments, and dismissed state persist locally

**Telegram Bot** (`scripts/telegram_bot.py`, optional)
- `/radar` — trigger a job search from your phone
- `/latest` — pull up the most recent report
- `/status` — last run summary
- Chat with any supported AI model using your full career profile as context
- Supports Claude, GPT-4o, Gemini, Kimi K2, DeepSeek, and any OpenRouter or Nvidia NIM model

---

## Repo Structure

```
job-search-profile/
├── CLAUDE.md                          # Claude Code instructions
├── .env                               # API keys (never commit)
├── docs/                              # personal profile docs — local only, not in git
│   ├── personal-info.md               # contact, headline, summary
│   ├── technical-skills.md            # master skills list
│   ├── education.md                   # degrees and formatting
│   ├── resume-generation-rules.md     # rules Claude follows for resume/cover letter work
│   ├── YYYY-YYYY-company-title.md     # one file per role
│   └── templates/                     # starter templates for each doc type
├── input/
│   ├── job-postings/                  # drop JDs here before generating a resume
│   ├── old-resumes/                   # source material for backfilling docs
│   └── raw-notes/                     # informal role notes to clean up
├── output/
│   ├── documents/                     # DOCX resume/cover letter exports
│   └── job-radar/                     # daily search reports + dedup state
├── dashboard/
│   ├── templates/                     # Jinja2 HTML templates
│   │   ├── base.html
│   │   ├── board.html
│   │   ├── radar.html
│   │   ├── job_detail.html
│   │   ├── draft.html
│   │   └── _card.html
│   └── static/
│       ├── style.css                  # dark mode UI
│       └── app.js
└── scripts/
    ├── job_radar.py                   # automated search, filter, rate, email
    ├── dashboard.py                   # Flask dashboard — kanban, radar, doc gen
    └── telegram_bot.py                # Telegram bot with multi-model AI chat
```

---

## Daily Workflow

**Job radar runs automatically.** Check your email at 9am and 4pm.

**Reviewing the radar:**
1. Open the dashboard at `http://localhost:5000` and go to **Radar**
2. Review each job — save promising ones to the board with **+ Save**, dismiss the rest with **✕**
3. Add comments to any job to note why it's not a fit (helps tune the search over time)
4. Click **Mark Reviewed** when done with the report

**Working a saved job:**
1. Go to **Board** — saved jobs land in the New column
2. Drag the card to **Reviewing** as you look it over
3. When ready to apply, click **View** → **Generate Resume + Cover Letter**
4. Edit in the two-panel editor, add regeneration instructions if needed
5. Download DOCX, **Mark Final**, card moves to Ready
6. Move through Applied → Phone Screen → Interview → Offer as you progress

**To generate a resume without the dashboard:**
1. Save the job description to `input/job-postings/company-title.txt`
2. Open Claude Code in the repo and say: `generate resume for input/job-postings/company-title.txt`

---

## Setup

**Prerequisites:**
- [Claude Code](https://claude.ai/code) with a Pro or Max subscription
- Python 3.10+
- Free API keys: [Adzuna](https://developer.adzuna.com/) · [Brave Search](https://api.search.brave.com/) · [Tavily](https://tavily.com/)
- [Anthropic API key](https://console.anthropic.com/) — used for Claude Haiku job rating in `job_radar.py`
- Gmail account with an [App Password](https://myaccount.google.com/apppasswords)
- (Optional) Telegram bot token for mobile access

**Install dependencies:**
```bash
pip install flask python-docx anthropic requests python-dotenv
```

**Run the dashboard:**
```bash
cd job-search-profile
python scripts/dashboard.py
# Open http://localhost:5000
```

**Schedule the radar (cron):**
```
0 9,16 * * 1-5 cd /path/to/job-search-profile && python scripts/job_radar.py
```

**Customizing for yourself:**
- Edit the `USER CONFIG` block at the top of `scripts/dashboard.py` — swap in your name and your `docs/` filenames
- Update `CANDIDATE_NAME`, `JOB_DOCS`, and `CRYPTO_DOC` to match your profile
- Add companies to `BLOCKED_COMPANIES` in `job_radar.py` as you find ones that keep slipping through filters
- Add domains to `DOMAIN_COMPANY_MAP` for better company name extraction from Workday/ATS URLs

**Profile docs:**
Most setup time is writing your `docs/` files. Template files showing the expected structure for each doc type are in `docs/templates/`. Once those are solid, Claude can generate a tailored resume in under 2 minutes.
