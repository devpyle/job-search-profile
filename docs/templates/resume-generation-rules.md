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
- Most relevant experience at the top
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
