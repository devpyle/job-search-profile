# Proposed Changes from Old Resumes

Analysis of all 21 resume files in `input/old-resumes/`. Changes are organized by target file. Nothing has been updated yet — this is for your review.

---

## 1. `docs/2021-2024-broadridge-product-owner-scrum-master.md`

### Add to Key Achievements
These bullets appear across multiple resumes but are missing from the current doc:

- **80% sprint velocity**: "Maintained an 80% velocity rate throughout Agile sprints, ensuring consistent progress and timely delivery of project milestones."
- **UI upgrade project**: "Led a cross-functional team through a multi-year project to upgrade the user interface (UI) for the trust business, enhancing usability and client satisfaction."
- **PO backlog ownership** (from Relias version): "Acted as Product Owner for multiple initiatives, defining and prioritizing backlogs based on business value and stakeholder feedback."
- **Requirements workshops** (from Relias version): "Facilitated requirements workshops and collaborated with stakeholders across departments to gather and document business requirements."

### Note on a disputed metric
One resume (Pendo version) says "30% increase in customer satisfaction" instead of "30% increase in delivery efficiency." The more common and credible version across all other resumes is **delivery efficiency**. Flagging for awareness — do not change this.

---

## 2. `docs/2019-2021-first-citizens-business-analyst.md`

### Add to Key Achievements
- **Credit card app metric** (appears in 8+ resumes, strong metric not in current doc): "Designed and implemented new credit card online application, **tripling customer volumes**."
- **Loan processing integration** (appears in later versions): "Integrated new credit card app with existing loan processing system."

### Note on Q2 integration
Some resumes describe Q2 at a higher level ("reduced application completion time by 50%") while others don't. The current doc already has the 50% reduction bullet — keep it. The "tripling customer volumes" metric is for the credit card app specifically and is additive.

---

## 3. `docs/2011-2015-deutsche-bank-avp-associate-ba.md`

### Expand role progression
The current doc shows 2 roles. The resumes reveal 5 stages of progression at Deutsche Bank Jacksonville that should be documented:

| Title | Dates |
|-------|-------|
| Consultant | March 2011 – May 2011 |
| Senior Operation Analyst | May 2011 – November 2011 |
| Associate – Tax Operations Team Manager | November 2011 – May 2012 |
| Associate – IGT – Business Analyst | May 2012 – January 2014 |
| AVP – IGT – Lead Business Analyst | January 2014 – September 2015 |

### Add to Key Achievements
These bullets appear in older resumes but are missing from the current doc:

- **SME on Global Debt Manager**: "Assisted as SME on Global Debt Manager project for Trust and Agency Business."
- **Industry working group leadership**: "Initiated and co-chaired an industry-wide working group on prime brokerage cost basis issues and resolution."
- **Client liaison**: "Liaised with Tier 1 prime brokerage and hedge fund clients for cost basis issue resolution."
- **Team management**: "Managed a team of 8 in cost basis reporting operations; trained and developed staff in less than 6 months."
- **KPI/KRI creation**: "Created KPIs and KRIs for cost basis processes."
- **Early consultant work** (if you want to include it): Position break reconciliation between Broadridge and Maxit, DTCC CBRS application oversight.

### Note on start date
Current frontmatter has `start: 2011-03` (Consultant start). The "Associate" title didn't begin until November 2011. Recommend keeping 2011-03 as the start since this was all at Deutsche Bank — just clarifying the progression internally.

---

## 4. `docs/technical-skills.md`

### Add to existing categories

**Technical Tools** — tools that appear consistently across resumes but are missing:
- Bitbucket
- TeamCity
- Splunk (appears in Relias-targeted resume)
- VBA (Excel VBA — appears in one resume, lower confidence it's a real skill to highlight)
- Oracle Exadata
- Unix/Linux
- Microsoft SQL Server (more specific than just "SQL (intermediate)")

**Regulatory / Compliance** — domain knowledge from resumes:
- FATCA
- Reg B
- FCRA

**Note on CPQ, Oracle, SAP**: These appear in one tailored resume (BSA role) and don't reflect actual hands-on experience based on the rest of the profile. Recommend **not** adding these.

---

## 5. `docs/education.md`

### Add academic honors and details (currently missing)
- **MBA GPA**: 3.54, Cum Laude, Dean's List
- **Undergraduate**: Dean's List, Bright Futures Scholarship Recipient
- **Clubs**: International Business Society (UNF), Alpha Sigma Pi

These are low-priority for a 10+ year career but worth having in the file for completeness.

---

## 6. NEW FILE: `docs/pre-2011-early-career.md`

The following roles appear in older resumes but have **no corresponding docs file**:

| Role | Company | Dates |
|------|---------|-------|
| Staff Accountant | BayGardens Inc. (Seffner, FL) | Jan 2008 – Feb 2009 |
| Consultant | Raymond James Financial Services (Lakewood Ranch, FL) | Feb 2009 – Aug 2009 |

**Raymond James bullets from resumes:**
- Analyzed and examined financial products
- Developed campaigns for recruiting potential clients
- Developed strategic plan for recruitment of financial advisors and professional partnerships
- Coordinated the transfer of client accounts to Raymond James
- Implemented Gorilla CRM system and QuickBooks

**BayGardens bullets from resumes:**
- Prepared and managed invoicing, payroll and customer accounts
- Analyzed cash flows and budget
- Developed production schedules for agriculture products

**Recommendation:** Create this file mainly for completeness and ATS date coverage. These roles are rarely if ever included in current resume versions and wouldn't be in standard output artifacts unless specifically requested.

---

## 7. ThugDAO (optional / special-case)

One resume (`davidmyersjune2024web3.docx`) includes a **DAO Council Leader** role at ThugDAO (May 2022 – Present), covering:
- Led NFT/DAO project transition from original owner
- Managed Thugbirdz NFT + Ordinals collections
- Managed validator, treasury, and partnerships (Jito, Sentries, Sanctum)
- First OG Solana project to be fully inscribed

This is not in any current docs file. It's a non-standard entry that could be useful for Web3-adjacent roles but would be omitted for mainstream fintech/banking applications.

**Recommendation:** Create an optional `docs/thugdao-dao-council.md` only if you want it available for tailoring. Flag it as Web3/optional so it's never included in default resume outputs.

---

## Summary of Changes

| File | Action | Priority |
|------|--------|---------|
| `docs/2021-2024-broadridge-product-owner-scrum-master.md` | Add 3–4 bullets | High |
| `docs/2019-2021-first-citizens-business-analyst.md` | Add 2 bullets | High |
| `docs/2011-2015-deutsche-bank-avp-associate-ba.md` | Expand role progression + add 5–6 bullets | Medium |
| `docs/technical-skills.md` | Add ~8 tools/skills | Medium |
| `docs/education.md` | Add GPA, honors, clubs | Low |
| `docs/pre-2011-early-career.md` | Create new file | Low |
| `docs/thugdao-dao-council.md` | Create new file (optional) | Optional |
