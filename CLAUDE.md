# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Repository Is

A structured job search profile — the `docs/` folder is a personal "source of truth" used to generate resumes, cover letters, LinkedIn summaries, and other application artifacts on demand. There is no build system, test runner, or CI pipeline.

## File Structure & Conventions

Each file in `docs/` is a markdown document with YAML frontmatter. The frontmatter `type` field classifies the document:

- `type: personal_info` — contact details, industry preferences, professional headline variants (`personal-info.md`)
- `type: job` — one file per role, with structured sections for achievements, STAR stories, and tech used
- `type: skills` — master skills list organized by category (`technical-skills.md`)
- `type: education` — degrees, formatting guidance for resumes and cover letters (`education.md`)

Job files follow the naming pattern `YYYY-YYYY-company-title.md`.

## How Content Is Organized Within Job Files

Each job file contains these sections (used selectively when generating artifacts):
- **30-second summary** — narrative overview
- **What I owned** — responsibilities list
- **Key achievements** — resume-ready bullet points (copy directly)
- **Signature story** — STAR format for interviews or cover letters
- **Technical skills used** — role-specific tools/technologies

## Key Facts (populate from your docs)

These come from your `docs/personal-info.md` and job files — not hardcoded here. See `docs/templates/` for the expected structure.

## Resume and Cover Letter Generation

**Always read `docs/resume-generation-rules.md` first and follow those rules exactly before generating any resume or cover letter.** This includes the fit assessment in Rule 0, which must run before any writing begins.

## Generating Artifacts

When generating a resume, cover letter, or other output:
1. Pull contact/headline from `personal-info.md`
2. Pull bullets verbatim from the "Key achievements" sections in job files — these are already resume-ready
3. Tailor industry framing using the "Industry Openness" and tone variant sections in `personal-info.md`
4. Use `education.md`'s "How to reference in resumes" section for degree formatting
5. Filter `technical-skills.md` to skills relevant to the target role/industry

## Adding New Content

New job entries should follow the existing frontmatter schema (`type`, `company`, `title`, `location`, `start`, `end`, `domain`, `keywords`) and include all standard sections. Update `technical-skills.md` if new tools were used.

## Memory

Two layers, both in use:
- File-based memory under `~/.claude/projects/-home-david-claude-job-search-profile/memory/` (indexed by `MEMORY.md`) auto-loads into context each session.
- The **clude** MCP holds the same memories (searchable) plus is the place for richer recall. At the start of a substantive task, `recall_memories` with `tags: ["job-search-profile"]` to pull relevant guardrails/state. Mirrored memories carry `source: job-search-profile/memory` and a `source_id` matching the filename.

When saving a NEW memory, write it to BOTH: the file (so it keeps auto-loading via `MEMORY.md`) and clude (tag it `job-search-profile`, set `source_id` to the filename), so the two stay in sync.

## Input Directory (`input/`)

Staging area for raw materials — nothing here goes into output directly. Three subfolders:

- **`input/job-postings/`** — job descriptions for roles you are targeting. Read these to tailor resumes and cover letters: extract required skills, keywords, and role framing to match against `docs/`.
- **`input/old-resumes/`** — previous resume files. Mine these for achievements, metrics, or role details not yet captured in `docs/` and backfill into the appropriate job markdown files.
- **`input/raw-notes/`** — informal notes about past roles. Treat as unstructured input to be cleaned up and merged into the relevant `docs/` job files using the standard section format.
