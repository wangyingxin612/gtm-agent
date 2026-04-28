# GTM AI Agent (Lead Research) — Product Requirements Document (MVP)

**Document Type:** Product Requirements Document (Internal)  
**Audience:** Product, Engineering, Leadership  
**Internal Name:** GTM AI Agent (Lead Research)  
**Scope of This PRD:** The "Lead / Company Research" step inside the GTM workflow  
**Version:** 2.0  
**Last Updated:** 2026-04

---

## 1. Product Positioning (MVP Truth)

GTM AI Agent (Lead Research) is a human-in-the-loop AI assistant that helps users:

- Find companies that are worth attention
- Decide whether now is the right time
- Eliminate fragmented, repetitive manual research

The core goal is:

> Hand the messy, manual, scattered research work to AI, so humans only make judgments.

---

## 2. Target Users

**Primary User:** SDR / BDR  
**Secondary Stakeholders:** Founders / Early GTM, Growth / Marketing

**Reference User Profile (MVP Validation):** An SDR at a company like [Fluency](https://usefluency.com) — a B2B SaaS tool selling to enterprise operations and compliance teams. They need to find mid-market companies in financial services, insurance, and manufacturing that are scaling fast and haven't yet standardized their process documentation. They currently do this research manually across LinkedIn, Crunchbase, and Google.

In this PRD, we refer to them simply as "the user."

---

## 3. Product Goals & Non-Goals

### 3.1 Goals (MVP)

- Ship an end-to-end flow: user input → ranked company list with contacts
- Make users feel "this list looks right" at first glance
- Allow users to review, correct, and influence system decisions
- Establish a strong human-in-the-loop experience

### 3.2 Non-Goals (MVP)

- No frontend UI (MVP is backend-only; output delivered via Jupyter Notebook or CLI + CSV/JSON)
- No outreach or sequencing
- No message or personalization generation
- No guarantee of deal outcomes or uplift
- No full GTM automation
- No attempt to replace human decision-making

> **MVP Validation Strategy:** The first version will be a backend pipeline that a human operator runs on behalf of users. The goal is to validate the output quality — "does this list look right?" — before building any UI. A simple Streamlit wrapper may be added for user testing once the core logic is validated.

---

## 4. Core User Journey (MVP)

1. User describes what they sell and who they want to sell to
2. System interprets and enriches user input
3. User confirms the system's understanding
4. System generates a ranked company list
5. User takes quick actions (keep / remove / revisit)
6. User drills down only when needed to see reasoning
7. User confirms the final company list
8. System performs contact research
9. System attaches contacts inline to the list

Contact research is only triggered after the user confirms the company list, to control cost and ensure relevance.

---

## 5. User Inputs

### 5.1 Company Information (Required)

**User provides:**

- Their company website (required)
- Optional documents (product docs, pitch deck, case studies)
- Optional: list of existing customers

**User expectation:**

> I shouldn't have to explain my product more than once.

---

### 5.2 Target Customer Description (Strongly Encouraged)

**Format:** Free-form natural language

**Examples:**

- "North American financial services companies with 200-2000 employees that are growing fast"
- "Mid-market insurance companies replacing manual compliance documentation"

**Behavior:**

- Users may skip this step
- The system will warn that skipping may significantly reduce accuracy

**User expectation:**

> I want to describe my target like I talk to a teammate, not fill 20 fields.

---

### 5.3 Existing Lead List (Optional)

**Purpose:** Provide a candidate list for ranking (mode 2: rank-only, instead of full discovery)

**Format:** CSV (company name + website preferred)

---

### 5.4 Competitor Info (Optional)

**User provides:** Competitor website URLs

**User expectation:**

> I know who I compete with — the system should learn from that.

---

## 6. Input Enrichment & Confirmation

### 6.1 System Interpretation

The system will:

- Interpret user intent
- Convert it into structured ICP fields
- Detect obvious conflicts or high-risk misunderstandings

### 6.2 User Confirmation (Required Step)

The system shows:

> "This is our structured understanding of your input."

Form is structured and editable, but heavy editing is discouraged.

User can:

- Confirm directly
- Edit text → system re-parses → user confirms again

Only after confirmation does the system proceed to data fetching and ranking.

### 6.3 Warn, Not Override

When detecting conflicts or risky directions, the system only warns:

> "We think X may work better than Y — do you still want to proceed?"

Final decision always belongs to the user.

---

## 7. Primary Output: Ranked Company List

### 7.1 List Configuration

- Top 10 / 20 / 50 / 100 (default: 10)
- MVP maximum: 100 companies

### 7.2 Per-Company Row

Each row shows:

- Company name + domain
- Industry, size, location
- Tier (Tier 1 / 2 / 3)
- 1–2 sentence reasoning summary ("Why Now")
- Inline contacts (if available)
- Quick actions: Keep / Remove / Revisit

Timing is not shown as a separate label. It is reflected in tier and ranking.

---

## 8. Drilldown (Explainability)

Clicking (or selecting) a company shows:

- Why it is in the list
- Why it ranks where it does
- Which signals mattered most (ICP fit, timing, tech, growth, etc.)

Purpose: build trust and support review — not to expose complex models.

**Example output:**

```
Company X — ICP Score: 87 (Tier 1)

Reasoning: Financial services firm undergoing rapid growth, similar to existing
customers. High operational complexity with manual processes.

Score Breakdown:
  Firmographic Match:   +25  (400 employees; ideal range 200–1000; FinServ)
  Keyword Relevance:    +22  (compliance, operations, process documentation)
  Growth Signals:       +18  (hiring +40% YoY, expanding to new markets)
  Timing Indicators:    +13  (recent funding round, new office opened)
  Lookalike Similarity: +9   (limited existing customers; firmographic mode)
```

Scores are heuristic and directional; small deltas are not meaningful.

---

## 9. Contact Discovery (Minimal MVP)

Principle: finding the right companies matters more than finding every contact.

MVP behavior:

- High confidence: show 1–2 specific people with verified contact info
- Low confidence: show role-level suggestion + explanation

Contacts appear inline in the list.

**MVP constraint:** Email addresses are only shown when publicly verifiable. We never guess or generate emails.

---

## 10. Override & Revisit

### 10.1 Quick Actions

Each company supports:

- Remove with reason
- Revisit later (Timing is not right)
- Rerank (Priority feels wrong)

### 10.2 Revisit Semantics

- No separate workflow
- Companies marked "Revisit" will rank slightly higher next time
- Serves as a reminder, not a guarantee

---

## 11. MVP Success Criteria

First goal: validate the flow, not perfect accuracy.

**Success means:**

- Users can smoothly go from input → list
- Users understand what the system is doing

**Strong qualitative signals:**

- "This list looks right at first glance."
- "I don't want to do manual research anymore."

**Quantitative proxy (backend MVP):**

- Keep rate > 60% on Tier 1 companies (user keeps without removing)
- Time to produce a 20-company ranked list with contacts < 5 minutes

Serious accuracy evaluation happens only after integrating real customer data and running with multiple users.

---

## Appendix: Glossary

| Term | Definition |
|------|------------|
| ICP | Ideal Customer Profile — characteristics of companies most likely to buy |
| SDR | Sales Development Representative — focuses on outbound prospecting |
| BDR | Business Development Representative — focuses on inbound lead qualification |
| GTM | Go-To-Market — strategy for launching and selling products |
| Tier | Company priority classification (Tier 1 = highest priority) |
| Lookalike | Similarity score comparing prospect to existing customers |
| Firmographic | Company demographic data (size, industry, location) |
| Pain Point | Business problem that creates urgency to buy |
| Decision Chain | Hierarchy of people involved in purchasing decisions |
| Backend MVP | A version with no user-facing UI; operated via Jupyter Notebook or CLI |

---

**End of PRD v2.0 (MVP, Lead Research)**
