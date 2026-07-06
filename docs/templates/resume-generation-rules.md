---
type: rules
name: "Resume Generation Rules"
---

# Resume Generation Rules

## Rule 0 — Fit Assessment First (Always)
Before any resume work, evaluate the job description against the candidate's background and return:

- **Verdict:** Apply or Don't Apply (one clear recommendation)
- **Why:** 3-5 sentences explaining the match or gap
- **Key Strengths:** Where the candidate's background directly maps to requirements
- **Key Gaps:** Hard requirements missing that would likely disqualify at screening

If verdict is **Don't Apply** — stop. Do not build a resume. Explain why clearly.
If verdict is **Apply** — state why it's worth it, then wait for the candidate to confirm before building. Do not start the resume until they say go.

Be direct. Do not soften gaps. If a job requires 10 years in a specific industry the candidate hasn't worked in, say so plainly.

---

## Rule 1 — Grounding: Every Bullet Must Trace to a Documented Fact (NO FABRICATION)

The most important rule. Every bullet, and every clause inside a bullet, must trace to a specific documented achievement or metric in the candidate's docs/ job files. If it is not written down, it does not go on the resume.

- START from the "Key achievements" and "Metrics" sections of each job doc. Select and lightly rephrase those. Do NOT write net-new accomplishments.
- When the JD asks for something not in the docs: map it to a REAL documented fact, or omit it. Never invent a bullet to cover a keyword.
- BANNED vague filler (these signal fabrication): "drove adoption/alignment/consensus", "championed", "fostered", "brought structure", "consistent communication", "stakeholder buy-in", "seamless", "synergy".
- **Mandatory self-audit:** before finalizing, re-read every bullet and name the documented fact behind it. If there is no source fact, cut the bullet.

---

## Rule 1.5 — Framing Honesty: No Exaggeration in Summaries, Cover Letters, or Phrasing

Rule 1 keeps the facts honest; this rule keeps the framing honest. Summaries and cover letters are held to the SAME grounding standard as bullets — exaggeration hides in phrasing even when every bullet traces to a real fact.

- **Verb strength must match the docs.** "Owned" / "ran" / "led" / "built" / "implemented" / "supported" are different claims. Use the verb the source doc uses, or weaker — never stronger.
- **Do the arithmetic on duration claims.** Any "N years of X" must be computable from the start/end dates of the roles that actually involved X. Don't stretch a partial-career domain across the whole career.
- **No domain relabeling.** Never re-badge documented work into the JD's domain vocabulary when the substance differs. Renaming to a genuine synonym is fine; changing what the work WAS is not.
- **No self-granted titles.** Role labels in summaries must match documented titles or explicit dual roles. Otherwise describe the work, not a title.
- **Present tense = current role only.** If the evidence comes from past roles, use past or career framing.
- **Strict reverse-chronological experience order, always.** Never reorder roles to foreground a relevant one or bury a weak one — it reads as doctored and breaks ATS parsing. Emphasis belongs in the summary and cover letter, not the ordering.
- **Verify real-world facts before asserting them.** Geography, commute distance, availability, relocation: check first, or phrase as open to discussion.

**Mandatory framing self-audit:** after the Rule 1 bullet audit, re-read the summary and the entire cover letter sentence-by-sentence. The probe test for each claim: would the candidate survive an interviewer pressing on this exact sentence? Fix or cut anything that fails.

---

## Step 1 — Keyword Extraction
Extract ALL relevant keywords from the job description:
- Job title variants
- Required and preferred skills
- Responsibilities and duties
- Tools and technologies
- Soft skills
- Domain and industry terms

Also identify the JD pain points — what's broken, messy, or missing that this hire is meant to fix. Use this framing in the resume.

---

## Step 2 — Keyword Mapping
For every relevant keyword from the JD, compare against the candidate's profile files in docs/:

- Exists in profile → rewrite and emphasize it
- Exists but weak → strengthen, move higher, highlight impact
- Missing but similar experience exists → add a truthful sentence
- Missing and cannot be assumed → DO NOT invent it

Do not keyword stuff. Every skill listed must be backed by real experience.

---

## Step 3 — Writing Rules

### Bullets
- Use SOAR structure: Situation, Obstacle, Action, Result
- Every bullet must have context, what the candidate did, and a measurable outcome
- Bold the metrics and impact in each bullet
- Vary sentence structure to avoid robotic tone
- Mirror the JD's language and pain point framing, not generic PM language
- Soft skills should appear inside job bullets, not as a separate list

### Summary
- First person, 4 sentences max
- Short and punchy
- Customize with a line that highlights the candidate's unique career arc or cross-functional depth
- Use JD keywords naturally
- No buzzwords

### Skills Section
- 20 skills maximum
- Tailored to the target role — not a laundry list
- Relevant keywords and proven strengths only

### Structure
- Experience in strict reverse-chronological order (see Rule 1.5) — emphasize relevance through the summary and bullet selection, never by reordering roles
- Strong tailored summary at the beginning
- Strengthen achievements with measurable impact wherever possible
- Match responsibilities to JD phrasing without copying word-for-word

---

## Step 4 — Voice Rules

### Always
- Plain English
- Contractions are fine: "I've", "I'm", "didn't"
- First person on resumes and summaries
- Short punchy sentences over long complex ones
- Warm but direct — confident without being arrogant
- Mirror the JD's language, not generic PM language

### Never Write
- "Results-driven product manager"
- "Proven track record of..."
- "Dynamic and innovative..."
- "Passionate about..."
- "Leveraging synergies..."
- Em dashes — ever
- Anything that sounds like it came from a resume template
- AI-sounding phrases or jargon

---

## Step 5 — Formatting Rules

### ATS-Friendly
- No icons
- No tables
- No images
- Standard resume structure

### Output Format
- Markdown format, clean and ready to convert to DOCX or paste into a document editor
- Keep it concise, professional, and keyword-rich

---

## How to Trigger This Workflow

1. Drop the job description into input/job-postings/filename.txt
2. Run: "generate resume for input/job-postings/filename.txt"
3. Claude will run fit assessment first and wait for confirmation
4. On confirmation, generate resume to output/resumes/company-title-date.md

Then commit the output to git for tracking.
