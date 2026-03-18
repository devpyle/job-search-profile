# Claude Code Job Search System

A Claude Code-powered job search system that runs automated daily searches across multiple job APIs, emails you results twice a day, and generates tailored resumes and cover letters on demand.

Built and maintained using [Claude Code](https://claude.ai/code).

---

## What It Does

**Automated Job Radar**
- Queries Adzuna, Brave Search, Tavily, and LinkedIn twice a day (9am and 4pm via cron)
- Deduplicates results across runs so you only see new postings
- Rates each job with Claude Haiku — `Apply Now / Worth a Look / Weak Match / Skip` — with a one-sentence reason
- Saves a dated markdown report to `output/job-radar/`
- Emails the report with priority jobs at the top and a filtered appendix at the bottom

**Telegram Bot (optional)**
- `/radar` — trigger a job search from your phone
- `/latest` — pull up the most recent report
- `/status` — last run summary
- Chat with any supported AI model using your full career profile as context
- Supports Claude, GPT-4o, Gemini, Kimi K2, DeepSeek, and any OpenRouter or Nvidia NIM model

**Resume & Cover Letter Generation (on demand)**
- Claude reads your full career profile from structured docs in `docs/`
- Runs a fit assessment before writing anything — gives you Apply or Don't Apply with honest reasoning
- Extracts keywords from the job description and maps them to your real experience
- Writes tailored, ATS-friendly resumes in HTML format
- Follows strict voice rules to avoid generic template-sounding output

---

## Repo Structure

```
job-search-profile/
├── CLAUDE.md                          # Claude Code instructions
├── .env                               # API keys (never commit)
├── docs/
│   ├── personal-info.md               # contact, headline, summary
│   ├── technical-skills.md            # master skills list
│   ├── education.md                   # degrees and formatting
│   ├── resume-generation-rules.md     # rules Claude follows for resume/cover letter work
│   └── YYYY-YYYY-company-title.md     # one file per role
├── input/
│   ├── job-postings/                  # drop JDs here before generating a resume
│   ├── old-resumes/                   # source material for backfilling docs
│   └── raw-notes/                     # informal role notes to clean up
├── output/
│   ├── resumes/                       # generated HTML resumes
│   ├── cover-letters/                 # generated cover letters
│   └── job-radar/                     # daily search reports + dedup state
└── scripts/
    ├── job_radar.py                   # automated search + email script
    ├── telegram_bot.py                # Telegram bot with multi-model AI chat
    └── test_linkedin.py               # LinkedIn scraper test
```

---

## Daily Workflow

**Job radar runs automatically.** Check your email at 9am and 4pm. Apply Now jobs are at the top — those are priority applications.

**To generate a resume:**
1. Save the job description to `input/job-postings/company-title.txt`
2. Open Claude Code in the repo
3. Say: `generate resume for input/job-postings/company-title.txt`
4. Claude assesses fit first — Apply or Don't Apply
5. Confirm to proceed; resume saves to `output/resumes/company-title-YYYY-MM-DD.html`
6. Open in browser, copy-paste into Google Docs, adjust formatting

**To generate a cover letter:** same flow, just ask for a cover letter instead.

---

## Want to Build Your Own?

A full setup guide is in [`output/job-search-system-setup-guide.md`](output/job-search-system-setup-guide.md). It covers everything: API keys, profile doc templates, CLAUDE.md setup, script customization, cron scheduling, and Gmail delivery.

**Prerequisites:**
- [Claude Code](https://claude.ai/code)
- Python 3.10+
- [Anthropic API key](https://console.anthropic.com/) — used for Claude Haiku job rating
- Free API keys: [Adzuna](https://developer.adzuna.com/) · [Brave Search](https://api.search.brave.com/) · [Tavily](https://tavily.com/)
- Gmail account with an [App Password](https://myaccount.google.com/apppasswords)
- (Optional) Telegram bot token for mobile access

**Time to set up:** ~3–5 hours, most of which is writing your profile docs. Once those are solid, Claude can generate a tailored resume in under 2 minutes.
