# GTM AI Agent (Lead Research) — Detailed Technical Specification

**Document Type:** Detailed Technical Specification (Internal)  
**Audience:** Product, Engineering, Architecture  
**Internal Name:** GTM AI Agent (Lead Research)  
**Scope:** Complete technical requirements for the "Lead / Company Research" MVP  
**Base Document:** PRD-v2.md  
**Version:** 3.1  
**Last Updated:** 2026-04

**Changelog from v3.0:**
- Added Section 1.5: System Objective (what the system is actually optimizing)
- Added Section 3.4: Agent Architecture (MVP agents + post-MVP Timing Agent)
- Updated Section 7.2: CompanyProfile now declared as Canonical Context; added `agent_contributions` and `signal_history` fields
- Updated Section 8: Scoring weights externalized to `scoring_config.json`; no longer hardcoded
- Updated Section 9: Contact Discovery restructured as encapsulated Agent class
- Updated Section 10.1: Override schema promoted to first-class structured type (`OverrideEvent`)
- Updated Section 10.2: Revisit boost now has explicit decay formula
- Added Section 11.5: Evaluation Framework (engineering metrics, separate from product metrics)
- Updated Section 20: Full rewrite — Signal Snapshot (minimal signal store), Phase 2 training pipeline structure, trigger condition at 80 labeled samples
- Added Appendix F: Scoring Config reference

**Changelog from v2.1:**
- Replaced Apollo.io with Hunter.io as primary data provider
- Added Section 6.4: Company Discovery Mechanism (previously missing)
- Fixed scoring multiplier cap bug (scores could exceed 100)
- Fixed cold-start weight redistribution (incomplete in v2.1)
- Replaced deprecated Clearbit fallback with PDL (People Data Labs)
- Fixed Google News API rate limit (100 req/day insufficient)
- Updated LLM stack: Claude as primary (was GPT-4o)
- Resolved all Appendix B open questions
- Scoped MVP to backend-only (no frontend)

---

## 1. Product Positioning (MVP Truth)

GTM AI Agent (Lead Research) is a human-in-the-loop AI assistant that helps users:

- Find companies that are worth attention
- Decide whether now is the right time
- Eliminate fragmented, repetitive manual research

The core goal is:

> Hand the messy, manual, scattered research work to AI, so humans only make judgments.

### 1.5 System Objective *(Added in v3.1)*

The system optimizes for:

> **The expected value of reaching out to a company at a given point in time.**

This is not the same as "ICP fit." A company can be a perfect ICP fit but terrible timing (just signed a competitor, no budget cycle for 9 months). The system must evaluate both dimensions together.

The objective is approximated using three factors:

```
Expected Outreach Value = f(ICP Fit, Timing, Signal Confidence)
```

| Factor | What It Measures | Primary Signals |
|---|---|---|
| ICP Fit | How relevant this company is structurally | Industry, size, location, tech stack, pain point keywords |
| Timing | How appropriate it is to engage *now* | Funding recency, hiring growth, company age, revenue stage |
| Signal Confidence | How reliable the evidence is | Data source quality, enrichment completeness, recency |

**Important clarifications:**
- Scores are **heuristic prioritization signals**, not predictions of conversion probability
- Small score differences (< 5 points) are not meaningful
- Ranking exists to **reduce search space**, not determine outcomes
- The system can say "this company fits"; only the human can say "this is the right time to call"

**What this means for engineering:**
Every scoring component, signal weight, and tier threshold should be evaluated against this objective: does it improve the system's ability to surface companies where reaching out *now* is likely to be valuable?

---

## 2. Target Users

**Primary User:** SDR / BDR  
**Secondary Stakeholders:** Founders / Early GTM, Growth / Marketing

**Reference Implementation:** The MVP is validated against the ICP of a company like [Fluency](https://usefluency.com) — a B2B SaaS work-intelligence platform targeting enterprise operations/compliance teams in financial services, insurance, and manufacturing.

---

## 3. MVP Scope & Architecture Boundary

### 3.1 MVP is Backend-Only

The MVP has no user-facing frontend. It runs as:

- A Python CLI script, or
- A Jupyter Notebook (primary interface for operator/tester)

Output is delivered as structured JSON + CSV files. A lightweight Streamlit wrapper may be added for user testing, but is not part of the core MVP.

### 3.2 Goals (MVP)

- Ship an end-to-end flow: user input → ranked company list with contacts
- Make outputs feel accurate ("this list looks right")
- Allow operators to review and correct system decisions
- Establish a strong human-in-the-loop experience

### 3.3 Non-Goals (MVP)

- No frontend UI
- No outreach or sequencing
- No message or personalization generation
- No full GTM automation
- No multi-user / multi-tenant isolation (single operator mode)
- **No fully automated decision-making without human confirmation at each major step**

### 3.4 Agent Architecture *(Added in v3.1)*

The system is internally structured as a set of specialized agents, each responsible for a distinct decision layer. In MVP, all agents run synchronously within a single pipeline. The agent boundaries exist now so that each component can be independently modified, tested, and eventually deployed separately.

**MVP Agent Map:**

```
┌─────────────────────────────────────────────────────────┐
│                  GTM Lead Research Pipeline              │
│                                                         │
│  ┌──────────────────┐    ┌──────────────────────────┐  │
│  │  ICP Interpreter │    │   Company Discoverer     │  │
│  │  (LLM-based)     │───▶│   (Hunter Discover API)  │  │
│  └──────────────────┘    └──────────────────────────┘  │
│                                       │                 │
│                                       ▼                 │
│  ┌──────────────────────────────────────────────────┐  │
│  │              Scoring Engine                       │  │
│  │  Firmographic + Keyword + Growth + Timing +       │  │
│  │  Lookalike  →  scoring_config.json weights        │  │
│  └──────────────────────────────────────────────────┘  │
│                                       │                 │
│                          [User confirms company list]   │
│                                       │                 │
│                                       ▼                 │
│  ┌──────────────────────────────────────────────────┐  │
│  │           Contact Discovery Agent                 │  │
│  │  (Hunter Domain Search → ranked contacts)         │  │
│  └──────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
                                        │
                                        ▼
                           Signal Snapshot → SQLite
                           Override Events → SQLite
```

**Agent Encapsulation Rule:** Each agent is a Python class with:
- Its own `__init__` accepting config and API clients
- A single primary async method (`run`, `discover`, `score`, `find_contacts`)
- Its own error handling and fallback logic
- No direct knowledge of other agents' internals

This means changing the Contact Discovery provider (e.g., Hunter → PDL) requires only modifying `ContactDiscoveryAgent`, not touching `ScoringEngine` or `ICPInterpreter`.

**Post-MVP: Timing Agent (Mode B)**

The current pipeline includes timing signals as a *scoring component* (Mode A — synchronous, per-session). Post-MVP, a separate Timing Agent will run asynchronously to monitor companies already in a user's list:

```
Timing Agent (async, post-MVP):
  Input:  List of company_ids in user's confirmed lists
  Action: Poll for new signals (funding, leadership changes, hiring spikes)
  Output: Writes SignalEvent to Signal Store → notifies user

Interface (defined now, implemented post-MVP):
  class TimingAgent:
      async def watch(self, company_ids: List[str]) -> None: ...
      async def poll_signals(self, company_id: str) -> List[SignalEvent]: ...
      async def write_signal(self, event: SignalEvent) -> None: ...
```

The `signal_history` field in `CompanyProfile` (see Section 7.2) is designed to receive writes from this agent.

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

#### 5.1.1 Website Analysis Specification

**Website Content Extraction:**

| Parameter | Value |
|---|---|
| Scraping service | Firecrawl API (headless browser, JS rendering) |
| Content sections | About, Products/Services, Pricing, Use Cases, Customers, Blog |
| Max crawl depth | 3 levels from homepage |
| Rate limiting | 1 req/sec per domain |
| Compliance | Respect robots.txt; no login-required content |

**Document Parsing:**

| Parameter | Value |
|---|---|
| Supported formats | PDF, DOCX, PPTX, TXT, MD |
| Max file size | 10MB per document |
| Max documents | 5 per session |
| Parsing library | Unstructured.io |
| Strategy | Extract text → preserve structure → LLM summarize |

#### 5.1.2 Existing Customer List Specification

| Parameter | Value |
|---|---|
| Required fields | `company_name` OR `website` (at least one) |
| Optional fields | `industry`, `employee_count`, `contract_value`, `deal_date` |
| Max customers | 100 |
| Deduplication | Match by normalized domain; merge records |
| Validation | Valid URL format; non-empty company name |

---

### 5.2 Target Customer Description (Strongly Encouraged)

**Format:** Free-form natural language

**Examples:**
- "Financial services companies in North America with 200-2000 employees that are growing fast"
- "Mid-market insurance companies struggling with manual compliance documentation"

**Behavior:**
- Users may skip this step
- System warns if skipped: "Without a target description, accuracy may be significantly reduced."

---

### 5.3 Existing Lead List (Optional)

**Purpose:** Candidate list for rank-only mode (skip discovery, go straight to scoring)

**CSV Format Requirements:**

| Parameter | Value |
|---|---|
| Required columns | `company_name` OR `website` (at least one) |
| Optional columns | `industry`, `size`, `location`, `notes` |
| Max rows | 1,000 |
| Encoding | UTF-8 |
| Header row | Required |
| Duplicate handling | Merge by domain; keep first occurrence |
| Invalid rows | Skip with warning; continue |

---

### 5.4 Competitor Info (Optional)

**User provides:** Competitor website URLs (max 10)

**Usage:**
- Auto-exclude competitors and their known customers from results
- Use competitor customer base to refine ICP (if public info available)

---

## 6. Input Enrichment & Confirmation

### 6.1 System Interpretation

The system will:
- Interpret user intent
- Convert it into structured ICP fields
- Detect obvious conflicts or high-risk misunderstandings

#### 6.1.1 Structured ICP Schema

```python
from pydantic import BaseModel
from typing import Optional, List

class ICPDefinition(BaseModel):
    # Core Fields (Required)
    industries: List[str]               # e.g., ["Financial Services", "Insurance"]
    company_size_min: int = 10          # Minimum employees
    company_size_max: int = 5000        # Maximum employees
    locations: List[str]                # ISO country or "City, Country"

    # Optional Fields
    keywords: Optional[List[str]]       # e.g., ["compliance", "operations", "SOP"]
    growth_stages: Optional[List[str]]  # e.g., ["Series A", "Series B"]
    revenue_min: Optional[int]          # Minimum ARR in USD
    revenue_max: Optional[int]          # Maximum ARR in USD

    # Pain Point Indicators
    pain_points: Optional[List[str]]    # e.g., ["manual documentation", "compliance risk"]

    # Exclusions
    exclude_industries: Optional[List[str]]
    exclude_companies: Optional[List[str]]  # Competitors + existing customers

    # Timing Preferences
    recent_funding: Optional[bool] = False
    recent_funding_months: Optional[int] = 6
    hiring_growth: Optional[bool] = False

    # Deal Probability Factors
    prefer_short_decision_chain: bool = True  # Prefer companies <500 where founder/exec still decides
    prefer_not_enterprise: bool = True        # Avoid 1000+ employee companies for MVP

    # Metadata
    interpretation_confidence: float    # 0.0 - 1.0
    warnings: List[str]                 # Interpretation warnings
```

**Field Validation Rules:**

| Field | Rule |
|---|---|
| `industries` | Min 1, Max 10 |
| `company_size` | Min 1, Max 100,000; min must be < max |
| `locations` | ISO country codes or "City, Country" format |
| `keywords` | Free-form; max 20 |

**Size Category Mapping:**

| Category | Size Range | Decision Speed | MVP Priority |
|---|---|---|---|
| Startup | 1–50 | Very Fast (founder decides) | ⭐⭐⭐ Primary |
| SMB | 51–200 | Fast (small leadership team) | ⭐⭐⭐ Primary |
| Mid-market | 201–1000 | Moderate (procurement involved) | ⭐⭐ Secondary |
| Scale-up | 1001–5000 | Slow (procurement process) | ⭐ Tertiary |
| Enterprise | 5000+ | Very Slow (RFP required) | Deprioritize |

#### 6.1.2 NL-to-Structured Interpretation Rules

**Confidence Thresholds:**

| User Input Pattern | Extracted Field | Confidence |
|---|---|---|
| "companies with X employees" | `company_size_min/max` | 0.90 |
| "in [location]" | `locations` | 0.95 |
| "[industry] companies" | `industries` | 0.90 |
| "recently raised funding" | `recent_funding = True` | 0.95 |
| "mid-market" | `size_min=200, max=1000` | 0.90 |
| "enterprise" | `size_min=1000` | 0.90 |
| "SMB / small companies" | `size_max=200` | 0.90 |
| "startups" | `size_max=50, growth_stages=["Seed","Series A"]` | 0.85 |
| "compliance", "SOP", "documentation" | `keywords`, `pain_points` | 0.85 |

**Ambiguity Resolution:**
- When multiple interpretations: present top 2 options to user
- Auto-extraction threshold: confidence ≥ 0.85 (below this, ask user)
- Required clarification triggers: missing `industries` OR missing size range

#### 6.1.3 ICP Refinement Rules

**Deprioritization Triggers:**

| Signal | Detection Method | Action |
|---|---|---|
| Enterprise-scale (>5000 employees) | Firmographic data | Suggest smaller alternatives |
| Already using competitor | Keyword/news analysis | Exclude or flag |
| Deep hyperscaler lock-in | News + tech stack analysis | Lower priority tier |

**Refinement Feedback Categories:**

| User Feedback | System Response |
|---|---|
| "Too big / too complex" | Reduce `company_size_max`; set `prefer_short_decision_chain=True` |
| "Not our ICP" | Remove industry; request clarification |
| "Good but timing wrong" | Mark as revisit; note timing concern |

---

### 6.2 User Confirmation (Required Step)

**Confirmation State Machine:**

```
States: [DRAFT, PENDING_CONFIRMATION, CONFIRMED, EDITING]

DRAFT → PENDING_CONFIRMATION     : on interpretation complete
PENDING_CONFIRMATION → CONFIRMED : on user confirm
PENDING_CONFIRMATION → EDITING   : on user edit
EDITING → PENDING_CONFIRMATION   : on re-parse complete
CONFIRMED → EDITING              : on user request change
```

**Re-parse Trigger Rules:**
- Which changes trigger re-parse: `industries`, `company_size_min/max`, `locations`
- "Major change" = modifying >50% of values in any array field
- Max re-parse iterations before warning: 3

---

### 6.3 Warn, Not Override

**Warning Severity Levels:**

| Level | Trigger | Message Pattern |
|---|---|---|
| INFO | Suggestions only | "Consider also targeting..." |
| WARNING | Accuracy risk | "This may reduce accuracy..." |
| CRITICAL | Conflicting criteria | "Your criteria conflict..." (must resolve) |

**Detectable Conflicts:**

| Conflict Type | Detection Logic | Warning |
|---|---|---|
| Too broad ICP | Estimated result > 10,000 | "Your criteria may return 10,000+ companies. Narrow by industry or size." |
| Too narrow ICP | Estimated result < 10 | "Only ~N companies found. Consider broadening." |
| Contradictory filters | `size_min > size_max` | "Min size {X} conflicts with max size {Y}." |
| Missing key criteria | No industries specified | "Without industry filters, accuracy may be significantly reduced." |
| Targeting giants | Top results are >5000 employees | "These companies may have complex procurement. Consider targeting mid-sized companies." |

---

### 6.4 Company Discovery Mechanism *(Section added in v3.0)*

This section defines how the system translates a confirmed ICP into an actual candidate company list. This was the primary gap in v2.1.

#### 6.4.1 Discovery Architecture

The system operates in two modes depending on whether the user provided a lead list:

**Mode A — Full Discovery (no lead list provided):**
```
ICPDefinition → Hunter Discover API → Candidate Pool (≤100 companies)
                                    → Score & Rank → Top N results
```

**Mode B — Rank-Only (lead list provided):**
```
User Lead List → Hunter Company Enrichment (per domain) → Score & Rank → Top N results
```

Mode B is cheaper (fewer API calls) and more deterministic, but depends on the quality of the user's list.

#### 6.4.2 ICP → Hunter Discover API Parameter Mapping

**Primary Endpoint:** `GET https://api.hunter.io/v2/discover`  
**Cost:** Free (no credits consumed)  
**Max results per call:** 100 companies (pagination requires premium)

| ICP Field | Hunter Parameter | Transformation |
|---|---|---|
| `industries` | `industry.include[]` | Map to Hunter industry taxonomy (see 6.4.3) |
| `exclude_industries` | `industry.exclude[]` | Direct mapping |
| `company_size_min/max` | `headcount[]` | Map to Hunter size buckets (see 6.4.4) |
| `locations` | `headquarters_location.include[]` | Map to ISO country code + optional city |
| `exclude_companies` (domains) | `organization.domain` exclusion | Post-process filter (Hunter doesn't support domain blacklist natively) |
| `keywords` | `keywords.include[]`, `match: "any"` | Direct list |
| `pain_points` | `keywords.include[]` | Merge with `keywords` field |
| `recent_funding` | `funding.series[]` | Premium only; skip on free tier |
| `company_type` | `company_type.include[]` | Default: `["privately held", "public company"]` |

**Natural Language Fallback:**

When structured mapping produces a very narrow ICP (<10 expected results), fall back to the `query` parameter:

```python
query = f"{', '.join(icp.industries)} companies in {', '.join(icp.locations)} with {icp.company_size_min}-{icp.company_size_max} employees focused on {', '.join(icp.keywords or [])}"
```

Hunter's AI assistant will interpret this and apply filters automatically.

**Example Request (Fluency ICP):**

```json
{
  "industry": {
    "include": ["Financial Services", "Insurance", "Manufacturing"]
  },
  "headcount": ["51-200", "201-500", "501-1000"],
  "headquarters_location": {
    "include": [
      {"country": "US"},
      {"country": "AU"},
      {"country": "GB"}
    ]
  },
  "keywords": {
    "include": ["compliance", "operations", "process", "documentation"],
    "match": "any"
  },
  "company_type": {
    "include": ["privately held", "public company"]
  },
  "limit": 100
}
```

#### 6.4.3 Industry Taxonomy Mapping

Hunter uses a different industry classification from the ICP. This mapping must be maintained:

| ICP Industry | Hunter Industry Values |
|---|---|
| Financial Services | "Financial Services", "Banking", "Capital Markets" |
| Insurance | "Insurance" |
| Manufacturing | "Industrial Machinery", "Automotive", "Consumer Goods" |
| Healthcare | "Hospital & Health Care", "Medical Devices", "Pharmaceuticals" |
| Professional Services | "Management Consulting", "Accounting", "Legal Services" |
| Technology / SaaS | "Computer Software", "Information Technology and Services" |
| AI / ML | "Artificial Intelligence", "Computer Software" |

> Full mapping table: maintained in `/src/config/industry_mapping.json`

#### 6.4.4 Headcount Bucket Mapping

Hunter uses fixed size buckets, not arbitrary ranges. Map ICP min/max to bucket set:

```python
HUNTER_BUCKETS = ["1-10", "11-50", "51-200", "201-500", "501-1000", "1001-5000", "5001-10000", "10001+"]

def map_size_to_buckets(size_min: int, size_max: int) -> list[str]:
    bucket_ranges = [(1,10), (11,50), (51,200), (201,500), (501,1000), (1001,5000), (5001,10000), (10001, 9999999)]
    result = []
    for i, (lo, hi) in enumerate(bucket_ranges):
        # Include bucket if it overlaps with [size_min, size_max]
        if lo <= size_max and hi >= size_min:
            result.append(HUNTER_BUCKETS[i])
    return result
```

#### 6.4.5 Candidate Pool Size Strategy

| Target List Size | Candidates to Fetch | Rationale |
|---|---|---|
| Top 10 | 50 | 5x buffer; enough for scoring variance |
| Top 20 | 100 | 5x buffer; Hunter max per call |
| Top 50 | 100 + enrichment filter | Use enrichment to narrow before scoring |
| Top 100 | 100 | Hunter free tier max; no buffer |

**Over-fetch rationale:** Hunter returns companies that match filters but may have limited data. Fetching more than needed allows the scoring engine to filter out low-quality candidates (missing industry data, no description, etc.).

#### 6.4.6 Data Returned by Hunter Discover

Each company in the Discover response includes:

```json
{
  "domain": "example.com",
  "name": "Example Corp",
  "headcount": "201-500",
  "industry": "Financial Services",
  "country": "US",
  "city": "New York",
  "description": "Short company description",
  "linkedin_handle": "company/example-corp",
  "founded_year": 2012,
  "tags": ["fintech", "compliance", "SaaS"]
}
```

**What Hunter Discover does NOT return (must enrich separately):**
- Tech stack
- Funding details (series, amount, date)
- Employee count (exact number; only bucket)
- Revenue estimates
- Recent news / signals

#### 6.4.7 Company Enrichment for Scoring

After the candidate pool is fetched, enrich each company via Hunter Company Enrichment:

**Endpoint:** `GET https://api.hunter.io/v2/companies/enrich?domain={domain}`  
**Cost:** 0.2 credits per company (charged only if data found)

Additional fields returned by enrichment:

```json
{
  "phone_numbers": [...],
  "email_addresses": [...],
  "tech_stack": ["Salesforce", "Workday", "ServiceNow"],
  "funding": {
    "series": "Series B",
    "amount": 25000000,
    "date": "2023-06-15"
  },
  "revenue": "$10M-$50M",
  "employee_count": 320,
  "social_media": {...}
}
```

> **Cost estimate:** 100 companies × 0.2 credits = 20 credits per session. On Hunter Starter ($34/month), this is negligible.

#### 6.4.8 Supplemental Signals: Website Scraping

For Tier 1 candidates only (after initial scoring), optionally scrape company website via Firecrawl to extract:
- Current job postings (hiring signals)
- Product/customer page keywords
- Recent blog posts or press releases

This is optional and controlled by a `deep_enrich: bool` flag. Default: `False` (to control cost and latency).

---

## 7. Primary Output: Ranked Company List

### 7.1 List Configuration

- Top 10 / 20 / 50 / 100 (default: 10)
- MVP maximum: 100 companies

### 7.2 Per-Company Data Schema

> **Canonical Context Declaration *(v3.1)*:** `CompanyProfile` is the **canonical context** for all agents in this system. Every agent reads from and writes to this structure. No agent maintains its own parallel representation of a company. When the Timing Agent is implemented post-MVP, it writes to `signal_history`. When additional agents are added (Outreach Prep, Pipeline Monitor), they add entries to `agent_contributions`. The schema is designed to be additive — new agents add new contribution keys, not new top-level fields.

```python
class AgentContribution(BaseModel):
    """Records what a specific agent contributed to this company's context."""
    agent_id: str                   # e.g., "lead_research_v1", "timing_monitor_v1"
    agent_version: str
    signals_added: List[str]        # Field names this agent populated
    confidence: float               # 0.0 - 1.0
    timestamp: datetime
    source_urls: Optional[List[str]]  # Evidence sources

class SignalEvent(BaseModel):
    """An observed change in a company signal over time."""
    signal_type: str                # "funding", "headcount", "leadership", "job_postings"
    old_value: Optional[Any]
    new_value: Any
    detected_at: datetime
    source_agent: str               # Which agent detected this
    confidence: float
    source_url: Optional[str]

class CompanyProfile(BaseModel):
    # Identifiers
    id: str                             # Internal UUID
    name: str
    domain: str
    linkedin_url: Optional[str]

    # Firmographics
    industry: Optional[str]
    sub_industry: Optional[str]
    employee_count: Optional[int]       # Exact if available; else midpoint of bucket
    employee_range: Optional[str]       # Hunter bucket e.g. "201-500"
    hq_location: Optional[str]
    hq_country: Optional[str]
    founded_year: Optional[int]
    company_type: Optional[str]

    # Signals
    tech_stack: Optional[List[str]]     # From Hunter enrichment
    funding_series: Optional[str]       # "Series A", "Series B", etc.
    funding_amount: Optional[int]       # USD
    funding_date: Optional[date]
    revenue_range: Optional[str]        # e.g. "$10M-$50M"
    description: Optional[str]

    # Canonical Context Fields (v3.1)
    agent_contributions: Dict[str, AgentContribution] = {}
    # Maps agent_id → what that agent contributed.
    # MVP: only "lead_research_v1" writes here.
    # Post-MVP: "timing_monitor_v1", "outreach_prep_v1" add their own keys.

    signal_history: List[SignalEvent] = []
    # Ordered list of observed signal changes, oldest first.
    # MVP: populated once during Lead Research with initial values.
    # Post-MVP: Timing Agent appends new events as signals change.

    # Metadata
    data_source: str = "hunter"
    last_enriched: datetime
    enrichment_confidence: float        # 0.0 - 1.0
    data_quality: str = "full"          # "full" | "partial" | "limited"
```

```python
class RankedCompany(BaseModel):
    company: CompanyProfile

    # Scoring
    total_score: float                  # 0-100 (hard capped)
    tier: Literal["Tier 1", "Tier 2", "Tier 3"]
    score_breakdown: ScoreBreakdown

    # Explanation
    reasoning_summary: str              # 1-2 sentences ("Why Now")

    # Contacts (populated after contact discovery)
    contacts: Optional[List[Contact]]
    contact_confidence: Optional[str]   # "high" | "low"

    # User Actions
    user_action: Optional[str]          # "keep" | "remove" | "revisit"
    user_action_reason: Optional[str]
    user_action_timestamp: Optional[datetime]
```

---

## 8. Scoring & Ranking

### 8.0 Scoring Configuration *(Added in v3.1)*

**Scoring weights are not hardcoded.** They live in `scoring_config.json` at the project root. This enables weight tuning without code changes, A/B testing between configs, and eventually per-customer configuration.

```json
// scoring_config.json
{
  "version": "1.0",
  "weights": {
    "firmographic": 30,
    "keyword_relevance": 25,
    "growth_signals": 20,
    "timing_indicators": 15,
    "lookalike_similarity": 10
  },
  "cold_start_weights": {
    "firmographic": 38,
    "keyword_relevance": 30,
    "growth_signals": 20,
    "timing_indicators": 17,
    "lookalike_similarity": 0,
    "cold_start_floor": 5
  },
  "modifiers": {
    "founder_led_bonus": 5,
    "small_team_bonus": 3,
    "enterprise_penalty": -5,
    "explicit_enterprise_penalty": -8,
    "recent_rejection_penalty": -100,
    "revisit_boost": 10,
    "revisit_decay_half_life_days": 30
  },
  "tiers": {
    "tier_1_min": 70,
    "tier_2_min": 45,
    "tier_3_min": 20
  }
}
```

**Loading pattern:**

```python
import json
from functools import lru_cache

@lru_cache(maxsize=1)
def load_scoring_config(path: str = "scoring_config.json") -> dict:
    with open(path) as f:
        return json.load(f)

# Usage in scoring functions:
config = load_scoring_config()
WEIGHTS = config["weights"]
MODIFIERS = config["modifiers"]
TIERS = config["tiers"]
```

**Config versioning:** When weights are updated (e.g., after Phase 2 model output), bump `version`. Store the previous config in `scoring_config_history/` with a timestamp. This creates an audit trail of weight changes.

### 8.1 Scoring Algorithm

**Score Components:**

| Component | Max Points | Weight | Calculation |
|---|---|---|---|
| Firmographic Match | 30 | 30% | Industry + size + location match against ICP |
| Keyword Relevance | 25 | 25% | Description + tags vs ICP keywords/pain_points |
| Growth Signals | 20 | 20% | Funding recency + hiring signals + expansion |
| Timing Indicators | 15 | 15% | Pain point urgency signals |
| Lookalike Similarity | 10 | 10% | Similarity to existing customers (boosted when customers available) |
| **Total** | **100** | **100%** | |

> **v3.0 fix:** Scores are now hard-capped at 100.0 after all modifier calculations. Previous versions used multipliers that could push scores above 100.

#### 8.1.1 Firmographic Match (0–30)

```python
def score_firmographic(company: CompanyProfile, icp: ICPDefinition) -> float:
    score = 0.0

    # Industry match (0-12)
    if company.industry in icp.industries:
        score += 12
    elif is_related_industry(company.industry, icp.industries):
        score += 6

    # Company size (0-12)
    emp = company.employee_count or midpoint(company.employee_range)
    if icp.company_size_min <= emp <= icp.company_size_max:
        score += 12
    elif icp.company_size_min * 0.5 <= emp <= icp.company_size_max * 2:
        score += 5

    # Location (0-6)
    if company.hq_country in icp.locations or company.hq_location in icp.locations:
        score += 6
    elif is_same_region(company.hq_country, icp.locations):
        score += 3

    return score  # max 30
```

#### 8.1.2 Keyword Relevance (0–25)

Match ICP `keywords` and `pain_points` against company `description` + `tags` using TF-IDF cosine similarity or simple overlap:

```python
def score_keyword_relevance(company: CompanyProfile, icp: ICPDefinition) -> float:
    target_keywords = (icp.keywords or []) + (icp.pain_points or [])
    if not target_keywords:
        return 12.5  # Neutral when no keywords defined (half credit)

    company_text = f"{company.description or ''} {' '.join(company.tech_stack or [])} {' '.join([company.industry or ''])}"
    company_text = company_text.lower()

    matched = sum(1 for kw in target_keywords if kw.lower() in company_text)
    ratio = matched / len(target_keywords)

    return min(25.0, 25.0 * ratio)
```

#### 8.1.3 Growth Signals (0–20)

```python
def score_growth_signals(company: CompanyProfile) -> float:
    score = 0.0

    # Recent funding (0-8)
    if company.funding_date:
        months_ago = (date.today() - company.funding_date).days / 30
        if months_ago <= 6:
            score += 8
        elif months_ago <= 12:
            score += 5
        elif months_ago <= 24:
            score += 2

    # Funding stage bonus (0-6)
    stage_scores = {
        "Seed": 3, "Pre-Seed": 2,
        "Series A": 6, "Series B": 5, "Series C": 4,
        "Series C+": 3, "IPO": 2
    }
    score += stage_scores.get(company.funding_series or "", 0)

    # Hiring activity (0-6) — approximated from job board signals (if available)
    # Placeholder: awarded if hiring_growth signal is detected
    # TODO: integrate hiring data post-MVP

    return min(20.0, score)
```

#### 8.1.4 Timing Indicators (0–15)

```python
def score_timing(company: CompanyProfile, icp: ICPDefinition) -> float:
    score = 0.0

    # Pain point urgency (0-8)
    # Check if company signals align with known urgent pain points
    urgency_keywords = icp.pain_points or []
    if any(kw.lower() in (company.description or "").lower() for kw in urgency_keywords):
        score += 8

    # Founding year proximity (0-4)
    # Companies 3-10 years old are often in active scaling mode
    if company.founded_year:
        age = date.today().year - company.founded_year
        if 3 <= age <= 10:
            score += 4
        elif age < 3:
            score += 2

    # Revenue stage match (0-3)
    # Mid-revenue companies ($1M-$50M) are often in the sweet spot
    revenue_stage_map = {"$1M-$10M": 3, "$10M-$50M": 3, "$50M-$100M": 2, "<$1M": 1, ">$100M": 1}
    score += revenue_stage_map.get(company.revenue_range or "", 0)

    return min(15.0, score)
```

#### 8.1.5 Lookalike Similarity (0–10)

When existing customers are provided, compute embedding similarity. When fewer than 3 customers exist, use a simplified version:

```python
def score_lookalike(company: CompanyProfile, existing_customers: List[CompanyProfile]) -> float:
    if len(existing_customers) == 0:
        return 5.0  # Neutral: no data to compare

    if len(existing_customers) < 3:
        # Simple overlap: check industry + size alignment
        same_industry = sum(1 for c in existing_customers if c.industry == company.industry)
        in_size_range = sum(1 for c in existing_customers
                           if c.employee_count and
                           abs(c.employee_count - (company.employee_count or 0)) < 200)
        ratio = (same_industry + in_size_range) / (2 * len(existing_customers))
        return round(10.0 * ratio, 2)

    # Full embedding similarity (3+ customers)
    avg_embedding = average_embeddings([embed(c) for c in existing_customers])
    similarity = cosine_similarity(embed(company), avg_embedding)
    return round(10.0 * max(0, similarity), 2)
```

#### 8.1.6 Cold-Start Weight Redistribution *(v3.0 fix)*

When no existing customers are provided (`len(existing_customers) == 0`), redistribute the Lookalike component's weight across other components:

| Component | Normal Weight | Cold-Start Weight (no customers) |
|---|---|---|
| Firmographic Match | 30% | 38% (+8) |
| Keyword Relevance | 25% | 30% (+5) |
| Growth Signals | 20% | 20% (unchanged) |
| Timing Indicators | 15% | 17% (+2) |
| Lookalike Similarity | 10% | 0% → replaced by Firmographic/Keyword |

Implementation:

```python
def calculate_total_score(company, icp, existing_customers) -> float:
    config = load_scoring_config()
    w = config["weights"]
    cw = config["cold_start_weights"]

    s_firm = score_firmographic(company, icp)
    s_kw   = score_keyword_relevance(company, icp)
    s_grow = score_growth_signals(company)
    s_time = score_timing(company, icp)
    s_like = score_lookalike(company, existing_customers)

    if len(existing_customers) == 0:
        total = (
            (s_firm / 30 * cw["firmographic"]) +
            (s_kw   / 25 * cw["keyword_relevance"]) +
            (s_grow / 20 * cw["growth_signals"]) +
            (s_time / 15 * cw["timing_indicators"]) +
            cw["cold_start_floor"]
        )
    else:
        total = (
            (s_firm / 30 * w["firmographic"]) +
            (s_kw   / 25 * w["keyword_relevance"]) +
            (s_grow / 20 * w["growth_signals"]) +
            (s_time / 15 * w["timing_indicators"]) +
            (s_like / 10 * w["lookalike_similarity"])
        )

    return min(100.0, round(total, 2))  # Hard cap at 100
```

#### 8.1.7 Deal Probability Modifier

Applied as a final adjustment (not a multiplier, to prevent cap violation):

```python
def apply_deal_modifier(score: float, company: CompanyProfile, icp: ICPDefinition) -> float:
    config = load_scoring_config()
    m = config["modifiers"]
    adjustment = 0.0

    emp = company.employee_count or midpoint(company.employee_range)

    if emp <= 50:    adjustment += m["founder_led_bonus"]
    elif emp <= 200: adjustment += m["small_team_bonus"]
    elif emp >= 1000: adjustment += m["enterprise_penalty"]

    if icp.prefer_not_enterprise and emp >= 1000:
        adjustment += m["explicit_enterprise_penalty"]

    return min(100.0, max(0.0, score + adjustment))
```

### 8.2 Tier Assignment

| Tier | Score Range | Description |
|---|---|---|
| Tier 1 | 70–100 | Highest priority; strong ICP + timing fit |
| Tier 2 | 45–69 | Good fit; worth pursuing |
| Tier 3 | 20–44 | Lower priority; timing may not be right |
| Excluded | 0–19 | Not recommended; omitted from output |

> **Why thresholds changed from v2.1:** The original thresholds (75/50/25) were designed for a 5-component score where each component had different max values. In v3.0, with cold-start redistribution, real scores cluster around 35–75. Thresholds adjusted down to maintain a useful Tier 1 cohort.

**Tier distribution target:** ~20% Tier 1, ~40% Tier 2, ~40% Tier 3. If Tier 1 > 40% of results, tighten thresholds. If Tier 1 < 10%, loosen.

### 8.3 Explanation Generation

**"Why Now" LLM Prompt:**

```
System: You are a B2B sales assistant. Generate a brief, direct "Why Now"
explanation for why this company is a good prospect. Focus on their
specific situation and timing. No marketing language.

Rules:
1. Lead with a specific pain point or observable signal
2. Connect to timing (funding, growth, new hire, product launch)
3. 1-2 sentences only
4. Be specific — avoid generic phrases like "growing company"
5. Focus on WHY NOW, not just WHY

Bad: "Great company with strong growth potential."
Good: "Operations team scaling rapidly post-Series B; compliance documentation
still manual, creating audit risk."

Input:
- Company: {name}, {industry}, {employee_count} employees
- Location: {location}
- Description: {description}
- Signals: {top_signals}
- User's product solves: {pain_points}

Output: 1-2 sentence "Why Now" explanation.
```

**LLM Settings:**

| Parameter | Value |
|---|---|
| Model | `claude-haiku-4-5` (fast, cost-optimized) |
| Max tokens | 150 |
| Temperature | 0.3 |
| Timeout | 8s |

---

## 9. Contact Discovery Agent *(Restructured in v3.1)*

Principle: finding the right companies matters more than finding every contact.

Contact Discovery is encapsulated as a standalone agent class. It runs synchronously in MVP (triggered after user confirms the company list), but is fully isolated from the Scoring Engine and ICP Interpreter. Changing the contact data source (e.g., Hunter → PDL or LinkedIn API) requires only modifying this class.

```python
class ContactDiscoveryAgent:
    """
    Finds and ranks contacts at a given company domain.
    Isolated agent: no knowledge of ICP, scoring, or session state.
    Receives company domains; returns ranked Contact lists.
    """

    def __init__(self, hunter_api_key: str, config: dict):
        self.api_key = hunter_api_key
        self.config = config  # target seniorities, departments, max contacts

    async def run(self, companies: List[RankedCompany]) -> List[RankedCompany]:
        """Entry point: enrich a list of ranked companies with contacts."""
        results = await asyncio.gather(*[
            self._find_contacts_for_company(rc)
            for rc in companies
            if rc.tier in ["Tier 1", "Tier 2"]  # Only search for Tier 1/2
        ])
        # Merge contacts back into company objects
        ...

    async def _find_contacts_for_company(self, rc: RankedCompany) -> RankedCompany:
        """Core logic: Hunter Domain Search → filter → rank → return top 3."""
        ...

    def _rank_contacts(self, contacts: List[Contact]) -> List[Contact]:
        """Rank by: seniority match > department match > email confidence."""
        ...

    def _make_role_suggestion(self, company: CompanyProfile) -> Contact:
        """Fallback: generate a role-level suggestion when no contact found."""
        ...
```

**Failure isolation:** If `ContactDiscoveryAgent` fails entirely (Hunter API down), the pipeline returns ranked companies without contacts. Companies are never dropped because contact discovery failed.

### 9.1 Contact Schema

```python
class Contact(BaseModel):
    id: str
    first_name: str
    last_name: str
    full_name: str

    # Professional Info
    title: str
    seniority: str              # "C-Level", "VP", "Director", "Manager"
    department: str

    # Contact Info
    email: Optional[str]                 # Only if publicly verifiable
    email_confidence: Optional[str]      # "verified" | "likely" | None
    linkedin_url: Optional[str]
    phone: Optional[str]                 # Rarely available

    # Metadata
    data_source: str                     # "hunter_domain_search", "public_page"
    last_verified: Optional[datetime]

    # Role-level fallback
    is_role_suggestion: bool = False
    role_suggestion_reason: Optional[str]
```

**Critical Email Rule:** Never display guessed or generated emails. Only show emails that are verifiably public. Marking an uncertain email as "N/A" is better than a wrong address.

### 9.2 Hunter Domain Search for Contacts

**Primary Endpoint:** `GET https://api.hunter.io/v2/domain-search?domain={domain}`  
**Cost:** 1 credit per 10 emails returned  
**Free tier:** 50 credits/month → 500 contacts/month

**Request:**

```
GET https://api.hunter.io/v2/domain-search
  ?domain=example.com
  &type=personal          # Exclude generic role emails (info@, contact@)
  &seniority=executive,director,vp   # Filter by seniority
  &department=management,it,operations
  &api_key=YOUR_KEY
```

**Response fields used:**

```json
{
  "data": {
    "emails": [
      {
        "value": "jane@example.com",
        "type": "personal",
        "confidence": 88,
        "first_name": "Jane",
        "last_name": "Smith",
        "position": "VP of Operations",
        "seniority": "director",
        "department": "management",
        "linkedin": "https://linkedin.com/in/janesmith",
        "verification": { "status": "valid" }
      }
    ]
  }
}
```

### 9.3 Buyer Persona Targeting

**Default seniority filter by product type:**

| Product Category | Target Seniorities | Target Departments |
|---|---|---|
| Process/Ops SaaS (e.g. Fluency) | `c_suite, vp, director` | `operations, management, legal` |
| Sales SaaS | `vp, director, manager` | `sales, business_development` |
| Engineering SaaS | `c_suite, vp, director` | `engineering, it` |
| Marketing SaaS | `c_suite, vp, director` | `marketing, growth` |

**Decision Chain Priority (inferred from product):**

1. CEO / Co-founder — strategic and budget decisions
2. Head of Operations / COO — primary champion
3. Head of Compliance / Risk — secondary champion
4. Director of IT / Digital — technical evaluator

### 9.4 Contact Confidence Scoring

**High Confidence (show specific person):**
- `email_confidence == "verified"` OR `linkedin_url` is available
- `seniority` matches target personas
- Source is `hunter_domain_search` with `confidence >= 70`

**Low Confidence (show role suggestion):**
- Name found but email not verified
- No email available; LinkedIn only
- Role inferred from domain search with low confidence

**Output format:**

```
HIGH CONFIDENCE:
  Jane Smith — VP of Operations
  LinkedIn: linkedin.com/in/janesmith
  Email: jane@example.com (verified)
  Source: Hunter Domain Search

LOW CONFIDENCE:
  Role: Head of Operations / Chief of Staff
  Why: Directly responsible for process documentation and compliance
  Note: Specific name not publicly available. Search LinkedIn using role.
```

### 9.5 Contact Discovery Limits

| Limit | Value | Rationale |
|---|---|---|
| Max contacts returned per company | 3 | Enough for outreach; avoids overwhelm |
| Max contacts searched per company | 10 | Internal limit; return best 3 |
| Max total contacts per session | 300 | 100 companies × 3 contacts |
| Credits used (Hunter) per session | ~10 credits | 100 domains × 0.1 avg |
| Hunter free tier per month | 50 credits | Sufficient for ~500 contacts |

### 9.6 Contact Output Positioning

This distinction must be clear in all documentation and output:

| What We Promise | What We Don't Promise |
|---|---|
| "Who to contact" (directional) | "Verified current employee database" |
| "Decision-relevant roles" | "100% accurate contact data" |
| "Narrow your search significantly" | "Complete contact coverage" |

---

*[Continued in Part 2: Sections 10–20 and Appendices]*
# GTM AI Agent — Tech Spec v3.0 (Part 2: Sections 10–20 + Appendices)

---

## 10. Override & Revisit

### 10.1 Quick Actions

Each company supports:

| Action | Required Input | Effect | Reversible |
|---|---|---|---|
| Keep | None | Mark as confirmed | Yes |
| Remove | Reason (optional) | Hide from list | Yes |
| Revisit | None | Flag for future | Yes |
| Rerank | Direction (up/down) | Adjust score ±5 | Yes |

**Remove Reasons (Predefined):**
- "Already a customer"
- "Competitor"
- "Wrong industry"
- "Too large / complex"
- "Recently contacted (no response)"
- "Timing not right"
- "Other" (free text)

**Override as a First-Class Structured Event *(v3.1)*:**

Override is not just a UI interaction. It is the most valuable ground-truth signal in the system. Every override is stored as a structured `OverrideEvent` in SQLite immediately when it occurs.

```python
class OverrideEvent(BaseModel):
    """
    Structured record of a user's deliberate action on a ranked company.
    This is the primary ground truth label for the learning system.
    """
    id: str                         # UUID
    session_id: str
    company_id: str
    company_domain: str             # Denormalized for easier querying

    # The action
    action: Literal["keep", "remove", "revisit", "rerank"]
    remove_reason: Optional[str]    # Predefined category
    remove_reason_text: Optional[str]  # Free text if "Other"
    rerank_direction: Optional[Literal["up", "down"]]

    # Context at time of override (critical for learning)
    score_at_override: float
    tier_at_override: str
    score_breakdown_at_override: dict  # Full ScoreBreakdown snapshot

    # Metadata
    timestamp: datetime
    user_id: str = "operator"       # Single user in MVP; multi-user post-MVP

    # Filled post-hoc by learning pipeline
    was_correct: Optional[bool] = None  # Human-labeled correctness (post-MVP)
```

**Why `score_breakdown_at_override` matters:** When a user removes a company that scored 72 (Tier 1), we need to know *which signals* contributed to that score to understand what went wrong. Storing the full breakdown at the time of action is what makes the learning pipeline possible. Without it, we'd only know the outcome, not the cause.

**SQLite table:**
```sql
CREATE TABLE override_events (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    company_id TEXT NOT NULL,
    company_domain TEXT NOT NULL,
    action TEXT NOT NULL,
    remove_reason TEXT,
    remove_reason_text TEXT,
    rerank_direction TEXT,
    score_at_override REAL NOT NULL,
    tier_at_override TEXT NOT NULL,
    score_breakdown_at_override TEXT NOT NULL,  -- JSON
    timestamp TEXT NOT NULL,
    user_id TEXT NOT NULL DEFAULT 'operator',
    was_correct INTEGER                          -- NULL until labeled
);
CREATE INDEX idx_override_company ON override_events(company_domain);
CREATE INDEX idx_override_action ON override_events(action);
```

### 10.2 Revisit Semantics

Companies marked "Revisit" receive a score boost in future sessions. The boost decays over time so stale revisits don't permanently pollute rankings.

```python
def calculate_revisit_boost(revisit_timestamp: datetime) -> float:
    """
    Boost decays from full value to zero over ~60 days.
    Half-life: 30 days (configurable in scoring_config.json).
    """
    config = load_scoring_config()
    base_boost = config["modifiers"]["revisit_boost"]          # default: 10
    half_life = config["modifiers"]["revisit_decay_half_life_days"]  # default: 30

    days_elapsed = (datetime.utcnow() - revisit_timestamp).days
    decay_factor = 0.5 ** (days_elapsed / half_life)

    return round(base_boost * decay_factor, 2)

# Examples:
# Day 0 (just marked):  boost = 10.0
# Day 30:               boost = 5.0
# Day 60:               boost = 2.5
# Day 90:               boost = 1.25  (effectively negligible)
```

**Revisit does not guarantee re-appearance.** If the company no longer appears in Hunter Discover results (e.g., ICP criteria changed), the boost has nothing to apply to.

---

## 11. MVP Success Criteria

First goal: validate the flow, not perfect accuracy.

**Success means:**
- Users can go from input → ranked list in under 5 minutes
- Users understand what the system is doing and why

**Strong qualitative signals:**
- "This list looks right at first glance."
- "I don't want to do manual research anymore."

**Quantitative proxy:**
- Keep rate > 60% on Tier 1 companies
- Contact find rate > 50% per Tier 1 company (LinkedIn URL or email)
- End-to-end pipeline time < 5 min for 20 companies

Serious accuracy evaluation happens only after multiple real user sessions.

---

## 11.5 Evaluation Framework *(Added in v3.1)*

Success criteria in Section 11 are **product metrics** — they tell us if users are happy. This section defines **engineering metrics** — they tell us if the system is working correctly and how to improve it.

### 11.5.1 Offline Metrics (Run after each batch of sessions)

These are computed from `signal_snapshots` and `override_events` in SQLite. Run as a weekly Jupyter notebook.

| Metric | Definition | Target | Alert If |
|---|---|---|---|
| **Tier 1 Precision** | % of Tier 1 companies that user kept | > 70% | < 50% |
| **Tier 1 Recall** | % of kept companies that were Tier 1 | > 60% | < 40% |
| **Override Rate by Tier** | % of each tier that user overrode | Tier 1 < 30%, Tier 2 < 50% | Tier 1 > 50% |
| **Remove Reason Distribution** | Breakdown of why companies were removed | — | "Wrong industry" > 30% (ICP parsing problem) |
| **Ranking Consistency** | % of sessions where top 3 are kept | > 50% | < 30% |
| **Signal Coverage** | % of companies with complete enrichment | > 80% | < 60% |

**Computing Tier 1 Precision:**
```python
import sqlite3
import pandas as pd

conn = sqlite3.connect("data/gtm_agent.db")

df = pd.read_sql("""
    SELECT s.company_id, s.tier_assigned, s.total_score,
           o.action, o.remove_reason
    FROM signal_snapshots s
    LEFT JOIN override_events o ON s.company_id = o.company_id
                                AND s.session_id = o.session_id
    WHERE s.tier_assigned = 'Tier 1'
""", conn)

precision = len(df[df.action == "keep"]) / len(df)
print(f"Tier 1 Precision: {precision:.1%}")
```

### 11.5.2 Signal Contribution Analysis

Which signals actually predict user keep/remove decisions?

```python
# For each signal field in score_breakdown_at_override,
# compute correlation with action == "keep"

df = pd.read_sql("""
    SELECT json_extract(score_breakdown_at_override, '$.firmographic_score') as firm,
           json_extract(score_breakdown_at_override, '$.keyword_score') as kw,
           json_extract(score_breakdown_at_override, '$.growth_score') as growth,
           json_extract(score_breakdown_at_override, '$.timing_score') as timing,
           CASE WHEN action = 'keep' THEN 1 ELSE 0 END as kept
    FROM override_events
""", conn)

print(df.corr()["kept"].sort_values(ascending=False))
# Output tells you: which signals have the highest correlation with user keeping a company
```

This is the direct input to Phase 2 weight retraining.

### 11.5.3 Online Proxy Metrics (Per Session)

Logged automatically at end of each pipeline run:

| Metric | How Computed | What It Indicates |
|---|---|---|
| Keep rate by tier | `kept / total` per tier | Ranking quality |
| Override rate | `overrides / companies_shown` | Ranking accuracy |
| Drilldown rate | Future metric (when UI exists) | Trust level |
| Contact find rate | `contacts_found / companies_contacted` | Hunter coverage |
| Session duration | `end_time - start_time` | Workflow efficiency |

### 11.5.4 Evaluation Cadence

| Frequency | Activity |
|---|---|
| After every session | Log online proxy metrics to session summary |
| Weekly (≥ 3 sessions) | Run offline analysis notebook; review signal contribution |
| When labeled samples ≥ 80 | Trigger Phase 2 training pipeline (see Section 20) |
| After weight update | Compare keep rate before/after; roll back if degraded |

---

## 12. Data Source & Integration Specifications *(Fully revised in v3.0)*

### 12.1 Primary Data Provider: Hunter.io

**Plan required:** Starter ($34/month)  
**Why:** Free plan (50 credits/month) is sufficient for initial testing. Starter provides 500 credits/month — enough for ~5 full sessions per month with 100 companies each.

#### 12.1.1 Hunter.io Endpoints Used

| Endpoint | URL | Cost | Purpose |
|---|---|---|---|
| Discover | `GET /v2/discover` | Free | Company discovery (ICP → candidate list) |
| Company Enrichment | `GET /v2/companies/enrich` | 0.2 credits/call | Enrich company with tech, funding, revenue |
| Domain Search | `GET /v2/domain-search` | 1 credit per 10 emails | Find contacts at a domain |
| Email Finder | `GET /v2/email-finder` | 1 credit/call | Find email for a specific name + domain |
| Email Verifier | `GET /v2/email-verifier` | 0.5 credits/call | Verify deliverability of an email |
| Account Info | `GET /v2/account` | Free | Check remaining credits |

**Authentication:** API key via `X-API-KEY` header or `?api_key=` query param.

**Rate Limits:**
- Domain Search: 15 req/sec, 500 req/min
- Other endpoints: standard rate limits apply (generous for our volume)

#### 12.1.2 Session Credit Budget

| Operation | Volume | Credits Used |
|---|---|---|
| Company Discover | 1 call | 0 (free) |
| Company Enrichment | 100 companies × 0.2 | 20 credits |
| Domain Search (contacts) | 50 domains × 0.1 avg | 5 credits |
| Email Verification (top contacts) | 30 emails × 0.5 | 15 credits |
| **Total per session** | | **~40 credits** |

With Starter's 500 credits/month: **~12 full sessions per month.**

### 12.2 Supplemental Data Sources

**Company Website Scraping:**

| Parameter | Value |
|---|---|
| Service | Firecrawl |
| Usage | Tier 1 companies only (optional; `deep_enrich=True`) |
| Rate limit | 1 req/sec per domain |
| Free tier | 500 pages/month (sufficient for MVP) |
| Purpose | Extract job postings, blog signals, recent news |

**News & Signals:**

> **v3.0 fix:** Google News API free tier (100 req/day) is insufficient for production use. Removed.

Alternative for MVP: Use company website scraping (Firecrawl) to find blog/news sections. Post-MVP: evaluate NewsAPI.org ($149/month) or Exa.ai for semantic news search.

For MVP, news signals are derived from:
1. Company website blog/news section (via Firecrawl)
2. Hunter Company Enrichment `funding` field (recent funding = built-in signal)
3. Hunter `description` field keyword analysis

**Fallback Provider (Hunter fails):**

> **v3.0 fix:** Clearbit removed (acquired by HubSpot; API effectively sunset). Replaced with PDL.

| Scenario | Fallback | Notes |
|---|---|---|
| Hunter Discover returns < 10 results | Retry with `query` param (NL mode) | Hunter's AI fills gaps |
| Hunter Enrichment fails for domain | PDL (People Data Labs) Company Enrich | Pay-per-use; ~$0.01-0.02/call |
| Domain Search returns 0 contacts | Firecrawl website scrape for "Team" page | Free; lower coverage |

**PDL Company Enrichment (fallback):**
- Endpoint: `POST https://api.peopledatalabs.com/v5/company/enrich`
- Cost: ~$0.01-0.02 per call (pay-as-you-go)
- Returns: employee count, industry, location, funding, tech stack

### 12.3 Data Caching Strategy

| Data Type | Cache TTL | Storage |
|---|---|---|
| Hunter Discover results | 24 hours | In-memory (dict) / SQLite for MVP |
| Company enrichment | 7 days | SQLite |
| Contact data | 72 hours | SQLite |
| LLM reasoning outputs | 7 days | SQLite (keyed by company_id + icp_hash) |

> **MVP note:** Redis is over-engineering for MVP. Use SQLite for caching. Migrate to Redis when scaling.

---

## 13. Session & State Management (Backend MVP)

For the backend-only MVP, session management is simplified significantly.

### 13.1 Session Schema

```python
class ResearchSession(BaseModel):
    id: str                     # UUID
    created_at: datetime
    updated_at: datetime

    # Status
    status: Literal[
        "draft",
        "interpreting",
        "confirming",
        "discovering",
        "ranking",
        "reviewing",
        "contact_discovery",
        "completed"
    ]

    # Inputs
    company_website: str
    company_documents: List[str]        # File paths
    target_description: Optional[str]
    existing_customers: Optional[List[dict]]
    lead_list: Optional[List[dict]]
    competitors: Optional[List[str]]

    # Derived
    icp_definition: Optional[ICPDefinition]
    icp_confirmed: bool = False

    # Outputs
    candidate_companies: Optional[List[CompanyProfile]]
    ranked_companies: Optional[List[RankedCompany]]
    company_list_confirmed: bool = False
```

### 13.2 Persistence

**MVP approach:** Store sessions as JSON files in `/data/sessions/{session_id}.json`.  
**Post-MVP:** Migrate to PostgreSQL with proper ORM.

**Auto-save:** On every state transition.

### 13.3 Export Formats

| Format | Status | Contents |
|---|---|---|
| CSV | ✅ MVP | Company name, domain, industry, size, tier, score, reasoning, contacts |
| JSON | ✅ MVP | Full `ResearchSession` object |
| Excel (.xlsx) | Post-MVP | — |
| PDF report | Post-MVP | — |

**CSV Column Spec:**

```
company_name, domain, industry, employee_range, location, tier, score,
why_now, contact_1_name, contact_1_title, contact_1_linkedin, contact_1_email,
contact_2_name, contact_2_title, contact_2_linkedin, contact_2_email,
user_action, user_action_reason
```

---

## 14. API Specifications (Backend MVP)

For the backend MVP, the API is a simple Python module interface, not a REST service. REST API is post-MVP.

### 14.1 Core Python Module Interface

```python
# pipeline.py — main entry points

async def run_pipeline(
    company_website: str,
    target_description: Optional[str] = None,
    existing_customers: Optional[List[dict]] = None,
    lead_list: Optional[List[dict]] = None,
    competitors: Optional[List[str]] = None,
    list_size: int = 20,
    deep_enrich: bool = False,
) -> ResearchSession:
    """
    Full pipeline: website analysis → ICP → discovery → scoring → contacts.
    Returns a ResearchSession with ranked companies and contacts.
    """

async def discover_companies(icp: ICPDefinition, limit: int = 100) -> List[CompanyProfile]:
    """Step 3: ICP → Hunter Discover → enriched candidate list."""

async def rank_companies(
    candidates: List[CompanyProfile],
    icp: ICPDefinition,
    existing_customers: List[CompanyProfile] = [],
) -> List[RankedCompany]:
    """Step 4-5: Score, rank, assign tiers, generate reasoning."""

async def discover_contacts(companies: List[RankedCompany]) -> List[RankedCompany]:
    """Step 8: Hunter Domain Search for contacts on confirmed Tier 1/2 companies."""

def export_to_csv(session: ResearchSession, output_path: str) -> str:
    """Export ranked + contacted companies to CSV."""
```

### 14.2 Jupyter Notebook Interface

Primary operator interface for MVP:

```python
# Example notebook usage

from gtm_agent import run_pipeline, export_to_csv

session = await run_pipeline(
    company_website="https://usefluency.com",
    target_description="Financial services and insurance companies in North America with 100-2000 employees that need to automate their compliance and operations documentation",
    list_size=20,
)

# Review ICP
print(session.icp_definition.model_dump_json(indent=2))

# Confirm ICP (in notebook: inspect and confirm manually)
session.icp_confirmed = True

# View ranked companies
for company in session.ranked_companies[:10]:
    print(f"{company.tier} | {company.total_score:.0f} | {company.company.name}")
    print(f"  → {company.reasoning_summary}")
    print()

# Export
export_to_csv(session, "output/fluency_leads_2026_04.csv")
```

### 14.3 Real-time Progress (CLI)

Since there's no frontend, progress is shown via console logs:

```
[1/5] Analyzing usefluency.com...         ✓ (2.1s)
[2/5] Interpreting ICP...                 ✓ (3.4s)
[3/5] Discovering companies (Hunter)...   ✓ 100 candidates (4.8s)
[4/5] Scoring and ranking...              ✓ 20 Tier 1/2/3 results (1.2s)
[5/5] Discovering contacts...             ✓ 47 contacts found (12.3s)

Done. Output: output/session_abc123.csv
```

---

## 15. Performance Requirements

### 15.1 Response Time Targets (Backend Pipeline)

| Operation | Target (P50) | Max (P99) | Timeout |
|---|---|---|---|
| Website analysis (Firecrawl) | 5s | 15s | 30s |
| ICP Interpretation (LLM) | 3s | 8s | 15s |
| Hunter Discover | 2s | 5s | 10s |
| Hunter Enrichment (100 companies, batched) | 15s | 30s | 60s |
| Scoring & Ranking (100 companies) | 2s | 5s | 15s |
| LLM Reasoning (100 companies, parallel) | 20s | 45s | 90s |
| Contact Discovery (50 domains, parallel) | 15s | 30s | 60s |
| **Total pipeline (20 companies)** | **~90s** | **~3min** | **5min** |

### 15.2 Concurrency

For MVP (single operator), no concurrency needed. Use `asyncio` for I/O-bound operations (API calls) to maximize throughput.

```python
# Parallel enrichment example
enriched = await asyncio.gather(*[
    enrich_company(c) for c in candidates
])

# Parallel reasoning generation
reasonings = await asyncio.gather(*[
    generate_reasoning(c, icp) for c in ranked[:20]
])
```

---

## 16. Error Handling

### 16.1 Error Classification

| Category | Handling | User Message |
|---|---|---|
| Validation Error | Raise immediately | Show specific field errors |
| Hunter API 429 (rate limit) | Exponential backoff (1s, 2s, 4s); max 3 retries | "Slowing down to respect API limits..." |
| Hunter API 5xx | Retry 2x; then use fallback or skip | "Data source temporarily unavailable; continuing with partial data" |
| LLM timeout | Retry 1x; use template reasoning as fallback | Silent; use template |
| Company not found in Hunter | Skip; mark as "data unavailable" | Show in output as `data_quality: "limited"` |
| Firecrawl failure | Skip; continue without website signals | Log warning |
| ICP too broad | Warn before proceeding | "~10,000+ companies match. Narrow your criteria." |
| ICP too narrow | Warn; suggest broadening | "Only ~{N} companies found. Consider broader criteria." |

### 16.2 Graceful Degradation

The pipeline should always produce *something*, even if data is incomplete:

```
Priority order for company data:
1. Hunter Enrichment (full data)
2. Hunter Discover (partial: headcount bucket, industry, location)
3. Manual fallback fields from user's lead list
4. Empty values (show company but flag as "limited data")
```

### 16.3 External Service Failure Handling

| Service | Retry | Backoff | Fallback |
|---|---|---|---|
| Hunter (all endpoints) | 3x | Exponential (1s, 2s, 4s) | PDL (enrichment) or skip |
| Firecrawl | 2x | Linear (2s) | Skip website analysis |
| Claude API | 3x | Exponential | Template-based reasoning |
| PDL (fallback) | 1x | None | Skip; mark as limited data |

---

## 17. Security & Compliance

### 17.1 Data Classification

| Data Type | Classification | Handling |
|---|---|---|
| API keys (Hunter, Firecrawl, Claude) | High | Store in `.env`; never commit to git |
| Contact PII (email, phone) | High | Encrypt at rest in SQLite (SQLCipher post-MVP) |
| User's customer list | High | Local only; never sent to external APIs except for domain matching |
| Company profiles | Medium | Cached locally; TTL-limited |
| LLM prompts | Medium | May contain company names; avoid PII in prompts |
| Session data | Medium | Local JSON files; rotate after 90 days |

### 17.2 Compliance

**For MVP (single operator, internal use):**
- Store data locally; no cloud persistence
- Respect Hunter.io ToS (no reselling of data, no scraping beyond API)
- Do not display unverified personal contact info
- Delete session data on request

**For production launch:**
- GDPR compliance required (EU users)
- CCPA compliance required (California users)
- SOC 2 Type II: planned post-seed

### 17.3 API Key Security

```bash
# .env file (never commit)
HUNTER_API_KEY=your_key_here
ANTHROPIC_API_KEY=your_key_here
FIRECRAWL_API_KEY=your_key_here

# Load in code
from dotenv import load_dotenv
load_dotenv()
```

---

## 18. LLM Integration *(Updated in v3.0)*

### 18.1 LLM Task Definitions

> **v3.0 change:** GPT-4o replaced with Claude as primary. Rationale: we're building on Claude infrastructure; using Claude avoids vendor split and gives us access to the same model we're already optimizing for. Claude Haiku is cost-equivalent to GPT-4o-mini for high-volume tasks.

| Task | Model | Max Tokens | Temp | Est. Cost |
|---|---|---|---|---|
| ICP Interpretation | `claude-sonnet-4-6` | 800 | 0.2 | $0.003/call |
| Conflict Detection | `claude-haiku-4-5` | 300 | 0.1 | $0.0003/call |
| Reasoning Summary (per company) | `claude-haiku-4-5` | 150 | 0.3 | $0.0001/call |
| Website Analysis | `claude-sonnet-4-6` | 1500 | 0.2 | $0.005/call |
| Explanation Detail | `claude-haiku-4-5` | 400 | 0.3 | $0.0003/call |

**Fallback model:** If Claude API is unavailable, fall back to `gpt-4o-mini` (same params).

### 18.2 Prompt Templates

**ICP Interpretation Prompt:**

```
System: You are an expert B2B sales strategist. Your job is to interpret
a user's description of their ideal customer and convert it into structured
criteria. Be specific and practical. Focus on observable, filterable signals.

User Input:
- Company website: {website}
- Company description (from website): {description}
- Target customer description: {target}
- Existing customers (if provided): {customers}
- Competitors (if provided): {competitors}

Output ONLY a valid JSON object with this exact schema:
{
  "industries": ["list", "of", "industries"],
  "company_size_min": number,
  "company_size_max": number,
  "locations": ["list", "of", "countries_or_cities"],
  "keywords": ["relevant", "keywords"],
  "pain_points": ["specific", "pain", "points"],
  "growth_stages": ["Series A", "Series B"],
  "interpretation_confidence": 0.0-1.0,
  "warnings": ["any", "warnings"]
}

Do not include any explanation or preamble. Output only the JSON.
```

**Reasoning Summary Prompt:**

```
System: You are a B2B sales assistant. Generate a brief, direct "Why Now"
explanation for why this company is a good prospect. No marketing fluff.

Input:
- Company: {name}, {industry}, {employee_range} employees, {location}
- Description: {description}
- User's product solves: {pain_points}
- Top match signals: {signals}

Output: 1-2 sentences. Start with the company's specific situation.
Focus on WHY NOW, not just why they fit.

Bad: "Great company that would benefit from our product."
Good: "Rapidly scaling ops team post-Series B with manual compliance workflows; audit season approaching."
```

### 18.3 LLM Cost Management

| Operation | Sessions/Month | Cost/Session | Monthly Cost |
|---|---|---|---|
| ICP Interpretation | 12 | $0.003 | $0.04 |
| Website Analysis | 12 | $0.005 | $0.06 |
| Reasoning (20 companies) | 12 | $0.002 | $0.02 |
| **Total LLM (MVP)** | | | **~$0.15/month** |

LLM cost is negligible at MVP scale. Enforce budget guardrails post-launch when usage scales.

**Cost Controls (post-MVP):**
- Per-session LLM limit: $0.50
- Per-user daily limit: $5.00
- Cache reasoning outputs: 7-day TTL keyed by `(company_id, icp_hash)`

---

## 19. Operational Requirements (MVP)

### 19.1 Logging

**Log format:**

```python
import logging
import json

def log_event(level: str, event: str, context: dict):
    print(json.dumps({
        "timestamp": datetime.utcnow().isoformat(),
        "level": level,
        "event": event,
        **context
    }))
```

**What to log:**
- API call start/end + latency + status code
- Pipeline step start/end + duration
- Credit usage per session
- LLM call + token count
- Errors with full context

**Log retention (MVP):** Local file; rotate after 30 days.

### 19.2 Monitoring (MVP)

No external monitoring for MVP. Use:
- Console logs for real-time visibility
- End-of-session summary printed to stdout:

```
=== Session Summary ===
Companies discovered:  100
Companies ranked:       20  (7 Tier 1 / 8 Tier 2 / 5 Tier 3)
Contacts found:         41
Hunter credits used:    42
LLM tokens used:     8,320
Pipeline duration:    1m 47s
Output: output/session_abc123.csv
=======================
```

### 19.3 Deployment (MVP)

**Runtime:** Local Python 3.11+ environment  
**Dependencies:** Managed via `requirements.txt` or `pyproject.toml`  
**Environment:** `.env` file for secrets  
**Data storage:** Local filesystem (`/data/sessions/`, `/data/cache/`)

**Post-MVP deployment stack:**
- Cloud: AWS
- Container: Docker + ECS
- Database: RDS PostgreSQL
- Cache: ElastiCache Redis
- Queue: SQS (for long-running jobs)

---

## 20. Feedback Loop & Learning *(Full rewrite in v3.1)*

### 20.1 Signal Snapshot — The Foundation

Every scoring run writes a signal snapshot to SQLite. This is the single most important data collection mechanism for future learning. Without it, we cannot know which signals predicted good outcomes.

**Schema:**

```python
class SignalSnapshot(BaseModel):
    """
    Immutable record of what signals existed and what scores resulted
    at the time a company was presented to the user.
    Written once per company per session. Never updated.
    """
    id: str                         # UUID
    session_id: str
    company_id: str
    company_domain: str

    # ICP context (what was the ICP when this was scored?)
    icp_hash: str                   # Hash of ICPDefinition for grouping sessions

    # Raw signal values at time of scoring
    signals: dict = {
        # Firmographic
        "industry_match": bool,
        "size_in_range": bool,
        "location_match": bool,
        "employee_count": int,

        # Keyword
        "keywords_matched": List[str],
        "keyword_match_ratio": float,

        # Growth
        "funding_series": Optional[str],
        "funding_months_ago": Optional[int],

        # Timing
        "company_age_years": Optional[int],
        "revenue_range": Optional[str],

        # Lookalike
        "lookalike_score": float,
        "existing_customers_count": int,

        # Data quality
        "enrichment_confidence": float,
        "data_quality": str,
    }

    # Scores assigned
    firmographic_score: float
    keyword_score: float
    growth_score: float
    timing_score: float
    lookalike_score: float
    total_score: float
    tier_assigned: str

    # Populated after user interaction
    user_outcome: Optional[str] = None  # "keep" | "remove" | "revisit" | None (no action)
    outcome_reason: Optional[str] = None
    outcome_timestamp: Optional[datetime] = None

    scored_at: datetime
```

**SQLite table:**
```sql
CREATE TABLE signal_snapshots (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    company_id TEXT NOT NULL,
    company_domain TEXT NOT NULL,
    icp_hash TEXT NOT NULL,
    signals TEXT NOT NULL,          -- JSON
    firmographic_score REAL,
    keyword_score REAL,
    growth_score REAL,
    timing_score REAL,
    lookalike_score REAL,
    total_score REAL NOT NULL,
    tier_assigned TEXT NOT NULL,
    user_outcome TEXT,              -- NULL until user acts
    outcome_reason TEXT,
    outcome_timestamp TEXT,
    scored_at TEXT NOT NULL
);
CREATE INDEX idx_snapshot_session ON signal_snapshots(session_id);
CREATE INDEX idx_snapshot_outcome ON signal_snapshots(user_outcome);
CREATE INDEX idx_snapshot_icp ON signal_snapshots(icp_hash);
```

**Linking snapshots to override events:**

When a user takes an action on a company, the pipeline immediately calls:

```python
async def record_outcome(session_id: str, company_id: str, override: OverrideEvent):
    """Link an override event back to its signal snapshot."""
    db.execute("""
        UPDATE signal_snapshots
        SET user_outcome = ?,
            outcome_reason = ?,
            outcome_timestamp = ?
        WHERE session_id = ? AND company_id = ?
    """, (override.action, override.remove_reason, override.timestamp,
          session_id, company_id))
```

### 20.2 Label Strategy

**Why `remove` is a better label than `keep`:**

- `keep` is ambiguous — user might keep a company because it's good, or because they didn't bother removing it
- `remove` with a reason is a strong negative signal — deliberate and intentional
- `revisit` is a weak positive signal — worth tracking but not as ground truth

**Label assignment for training:**

```python
def assign_label(snapshot: SignalSnapshot) -> Optional[int]:
    """
    Returns 1 (positive), 0 (negative), or None (ambiguous / unlabeled).
    Only called when sample count reaches training threshold.
    """
    if snapshot.user_outcome == "remove":
        return 0  # Strong negative
    elif snapshot.user_outcome == "keep" and snapshot.tier_assigned == "Tier 1":
        return 1  # Reasonably strong positive (Tier 1 + explicit keep)
    elif snapshot.user_outcome is None:
        return None  # No action taken — ambiguous, exclude from training
    elif snapshot.user_outcome == "revisit":
        return None  # Weak signal — exclude from initial training
    return None
```

**Expected label distribution:** ~30% positive (keep), ~20% negative (remove), ~50% unlabeled (no action). The imbalance is expected and handled by class weighting in the model.

### 20.3 Phase 1 — Manual Analysis (Now → 80 labeled samples)

During Phase 1, no model is trained. Learning is done manually via a weekly Jupyter notebook.

**Weekly analysis notebook (`notebooks/weekly_signal_analysis.ipynb`):**

```python
# Step 1: Load labeled data
df = load_labeled_snapshots(min_labels=5)
print(f"Labeled samples: {len(df)}")
print(f"Positive (keep): {(df.label == 1).sum()}")
print(f"Negative (remove): {(df.label == 0).sum()}")

# Step 2: Signal correlation with outcome
correlations = compute_signal_correlations(df)
print("\nSignal → Keep Correlation:")
print(correlations.sort_values(ascending=False).head(10))

# Step 3: Remove reason analysis
reasons = df[df.label == 0].outcome_reason.value_counts()
print("\nWhy companies were removed:")
print(reasons)

# Step 4: Manual weight adjustment recommendation
# (Engineer reviews and manually updates scoring_config.json)
```

### 20.4 Phase 2 — Semi-Automated Weight Tuning (≥ 80 labeled samples)

Phase 2 does not run automatically. It is triggered manually when the evaluation notebook reports ≥ 80 labeled samples. The pipeline outputs *suggested* weights; a human reviews and approves before the config is updated.

**Training pipeline (`scripts/train_scoring_model.py`):**

```python
import json
import sqlite3
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import cross_val_score
from sklearn.preprocessing import StandardScaler

TRAINING_THRESHOLD = 80  # Minimum labeled samples before running

def check_training_readiness() -> bool:
    conn = sqlite3.connect("data/gtm_agent.db")
    count = pd.read_sql(
        "SELECT COUNT(*) as n FROM signal_snapshots WHERE user_outcome IS NOT NULL",
        conn
    ).iloc[0]["n"]
    print(f"Labeled samples: {count} / {TRAINING_THRESHOLD} required")
    return count >= TRAINING_THRESHOLD

def load_training_data() -> pd.DataFrame:
    conn = sqlite3.connect("data/gtm_agent.db")
    df = pd.read_sql("""
        SELECT firmographic_score, keyword_score, growth_score,
               timing_score, lookalike_score, total_score,
               user_outcome, outcome_reason,
               json_extract(signals, '$.funding_months_ago') as funding_months_ago,
               json_extract(signals, '$.keyword_match_ratio') as kw_ratio,
               json_extract(signals, '$.size_in_range') as size_in_range
        FROM signal_snapshots
        WHERE user_outcome IN ('keep', 'remove')
    """, conn)

    df["label"] = df.user_outcome.map({"keep": 1, "remove": 0})
    return df

def train_and_suggest_weights():
    if not check_training_readiness():
        print("Not enough data yet. Continue collecting sessions.")
        return

    df = load_training_data()
    features = ["firmographic_score", "keyword_score", "growth_score",
                "timing_score", "lookalike_score"]
    X = StandardScaler().fit_transform(df[features])
    y = df["label"]

    model = LogisticRegression(class_weight="balanced", max_iter=1000)
    cv_scores = cross_val_score(model, X, y, cv=5, scoring="roc_auc")
    model.fit(X, y)

    print(f"\nModel CV AUC: {cv_scores.mean():.3f} ± {cv_scores.std():.3f}")

    # Normalize coefficients to sum to 100 (suggested weights)
    coefs = model.coef_[0]
    coefs_positive = coefs - coefs.min()
    suggested_weights = (coefs_positive / coefs_positive.sum() * 100).round(1)

    current_config = load_scoring_config()
    current_weights = current_config["weights"]

    print("\n=== SUGGESTED WEIGHT UPDATE ===")
    print(f"{'Signal':<25} {'Current':>10} {'Suggested':>12} {'Change':>10}")
    print("-" * 60)
    for feature, weight in zip(features, suggested_weights):
        signal = feature.replace("_score", "")
        current = current_weights.get(signal.replace("_", ""), "N/A")
        change = weight - (current if isinstance(current, (int, float)) else 0)
        print(f"{signal:<25} {str(current):>10} {weight:>12.1f} {change:>+10.1f}")

    print("\n⚠️  HUMAN REVIEW REQUIRED before updating scoring_config.json")
    print("If weights look reasonable, run: scripts/apply_weights.py --approve")

if __name__ == "__main__":
    train_and_suggest_weights()
```

**`scripts/apply_weights.py`:**

```python
# Human runs this after reviewing suggested weights
# Creates versioned backup of current config before updating

import shutil, json
from datetime import datetime

def apply_suggested_weights(suggested: dict, approval_note: str):
    # Backup current config
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    shutil.copy("scoring_config.json",
                f"scoring_config_history/scoring_config_{timestamp}.json")

    # Load and update
    config = json.load(open("scoring_config.json"))
    old_version = config["version"]
    new_version = increment_version(old_version)

    config["weights"] = suggested
    config["version"] = new_version
    config["updated_at"] = datetime.utcnow().isoformat()
    config["update_reason"] = approval_note

    json.dump(config, open("scoring_config.json", "w"), indent=2)
    print(f"Config updated: v{old_version} → v{new_version}")
    print(f"Backup saved to: scoring_config_history/scoring_config_{timestamp}.json")
```

### 20.5 Learning Roadmap

| Phase | Trigger | Method | Human Role |
|---|---|---|---|
| Phase 1 (now) | Every session | Manual weekly notebook | Reviews signal correlation; manually adjusts weights |
| Phase 2 | ≥ 80 labeled samples | Logistic regression / XGBoost | Reviews suggested weights; approves or rejects |
| Phase 3 (post-MVP) | CRM integration | Conversion-based ground truth | Reviews model performance; sets approval gates |

**Phase 3 requires:** CRM integration (meetings booked, deals opened), which is out of scope for MVP but should be designed for from the start. The `user_outcome` field in `SignalSnapshot` can be extended with `crm_outcome` when that data becomes available.

---

## Appendix A: Glossary

| Term | Definition |
|------|------------|
| ICP | Ideal Customer Profile — characteristics of companies most likely to buy |
| SDR | Sales Development Representative — outbound prospecting |
| BDR | Business Development Representative — inbound lead qualification |
| GTM | Go-To-Market — strategy for launching and selling products |
| Tier | Company priority classification (Tier 1 = highest priority) |
| Lookalike | Similarity score comparing prospect to existing customers |
| Firmographic | Company demographic data (size, industry, location) |
| Pain Point | Business problem that creates urgency to buy |
| Decision Chain | Hierarchy of people involved in purchasing decisions |
| Cold-start | State where no existing customer data is available for lookalike scoring |
| Hunter Discover | Free Hunter.io API endpoint for finding companies by ICP criteria |
| Backend MVP | Version with no user-facing UI; operator runs via Jupyter/CLI |
| Canonical Context | The single shared data structure (`CompanyProfile`) that all agents read and write |
| Signal Snapshot | Immutable record of signals and scores at time of company presentation; primary training data |
| Override Event | Structured record of a user's deliberate action (keep/remove/revisit) on a company |
| Agent Contribution | Record of which agent added which fields to a CompanyProfile |
| Signal Event | A detected change in a company signal over time (used by Timing Agent post-MVP) |

---

## Appendix B: Open Questions — Resolved *(v3.0)*

> All open questions from v2.1 have been resolved or deferred with rationale.

**Product Questions:**

1. ~~Should users be able to save and reuse ICP definitions across sessions?~~  
   **Resolved:** Yes, post-MVP. MVP stores ICP in session JSON; user can copy-paste between sessions manually.

2. ~~How should we handle companies that appear in multiple user sessions (shared intelligence)?~~  
   **Resolved:** Not relevant for backend MVP (single operator). Post-MVP: implement cross-session company scoring aggregation with opt-in cross-user learning (anonymized only).

3. ~~Should we provide industry benchmarks for "good" vs "bad" ICP criteria?~~  
   **Resolved:** Deferred to post-MVP. For now, system warns when ICP is too broad or too narrow. Benchmarks require data we don't have yet.

**Technical Questions:**

1. ~~What's the optimal batch size for Apollo.io API calls?~~  
   **Resolved:** Not applicable — Apollo replaced with Hunter.io. Hunter enrichment: batch 10 domains at a time (no bulk endpoint; use asyncio for parallelism).

2. ~~Should we implement real-time WebSocket updates or is SSE sufficient for MVP?~~  
   **Resolved:** Neither for MVP. Pipeline is synchronous with console progress logs. SSE added when Streamlit wrapper is built; WebSocket post-MVP REST API.

3. ~~How do we handle data provider API deprecations gracefully?~~  
   **Resolved:** Abstraction layer (`DataProvider` base class) with Hunter as primary and PDL as fallback. Swapping providers requires only implementing the interface, not rewriting business logic.

**Business Questions:**

1. ~~What's the pricing model — per session, per contact, or subscription?~~  
   **Resolved (tentative):** Subscription per seat. Pricing validation is out of scope for MVP.

2. ~~How do we measure and report ROI to users?~~  
   **Resolved (deferred):** Post-MVP. Track meetings booked from exported leads (requires CRM integration).

3. ~~What's the competitive differentiation vs. Apollo.io's native search?~~  
   **Resolved:** Apollo is a database; our product is an AI agent that *interprets* your ICP, *explains its reasoning*, and *learns from your feedback*. The value is not the data — it's the workflow.

---

## Appendix C: "Why Now" Reasoning Templates

**Template Patterns:**

| Company Type | Template | Example |
|---|---|---|
| Post-funding scaler | "[Company] recently raised [series], actively expanding [function] team." | "Raised Series B in Jan 2026; hiring 12 ops roles — team scaling faster than current processes." |
| Compliance-sensitive | "[Industry] under [regulatory] pressure. Manual [process] creates [risk]." | "Insurance firm facing APRA CPS 230 compliance deadlines; SOP documentation still manual." |
| Fast hirer | "Headcount doubled in [N] months. Onboarding and [process] consistency at risk." | "Grew from 80 to 200 in 18 months; onboarding consistency a major pain point." |
| Tech migrator | "Migrating from [legacy] to [new system]. Process documentation gap opens." | "Moving from legacy ERP to SAP; process re-documentation underway." |

**Anti-patterns to Avoid:**

| Bad | Why Bad | Better |
|---|---|---|
| "Great company with strong growth" | Generic; no specificity | "Series B raised 3 months ago; actively hiring compliance officers" |
| "Would benefit from our product" | Obvious; not insightful | "Manual SOP process mentioned in 3 job postings this quarter" |
| "Industry leader in AI" | No timing signal | "Launched new product line requiring new compliance documentation" |

---

## Appendix D: Sample Output

**Console Output (Jupyter / CLI):**

```
┌─────────────────────────────────────────────────────┐
│ ACME FINANCIAL GROUP                   Tier 1 (82)  │
├─────────────────────────────────────────────────────┤
│ Financial Services · 320 employees · Sydney, AU     │
│ Founded 2014 · Series B · Revenue ~$10M-$50M        │
├─────────────────────────────────────────────────────┤
│ Why Now: Rapidly scaling post-Series B with 40%     │
│ headcount growth; compliance documentation still    │
│ handled manually per job postings.                  │
├─────────────────────────────────────────────────────┤
│ Score: Firmographic +24 / Keywords +20 / Growth +18 │
│        Timing +12 / Lookalike (cold) +8             │
├─────────────────────────────────────────────────────┤
│ CONTACTS                                            │
│  Sarah Chen — Head of Operations                   │
│  LinkedIn: linkedin.com/in/sarahchen-ops           │
│  Email: s.chen@acmefinancial.com.au (verified)     │
│  Source: Hunter Domain Search                      │
│                                                    │
│  Role: Chief Compliance Officer                    │
│  Why: Directly responsible for compliance SOPs     │
│  Note: Name not public; search on LinkedIn         │
├─────────────────────────────────────────────────────┤
│ Action: [keep] [remove ▼] [revisit] [details →]    │
└─────────────────────────────────────────────────────┘
```

---

## Appendix E: Tech Stack Summary

| Layer | Technology | Rationale |
|---|---|---|
| Language | Python 3.11+ | Standard for data/AI pipelines |
| Async I/O | `asyncio` + `httpx` | Parallel API calls without threading |
| Data models | `pydantic v2` | Type safety; JSON serialization |
| LLM | Anthropic Claude (`anthropic` SDK) | Primary; consistent with our stack |
| Company Discovery | Hunter.io (`requests`) | Free discover; $34/mo for full access |
| Web Scraping | Firecrawl (`firecrawl-py`) | Handles JS rendering; clean output |
| Embeddings (lookalike) | `sentence-transformers` | Local; no API cost for similarity |
| Caching + Signal Store | SQLite (`sqlite3`) | Zero-dependency; sufficient for MVP |
| Data manipulation | `pandas` | CSV export; scoring calculations; weekly analysis |
| ML (Phase 2) | `scikit-learn` | Logistic regression for weight tuning |
| Environment | `python-dotenv` | Secret management |
| Testing | `pytest` + `pytest-asyncio` | Async-compatible test runner |
| Notebook | Jupyter Lab | Operator interface + weekly analysis |

**`requirements.txt` (core):**

```
anthropic>=0.40.0
httpx>=0.27.0
pydantic>=2.0.0
python-dotenv>=1.0.0
sentence-transformers>=2.7.0
pandas>=2.0.0
scikit-learn>=1.4.0
firecrawl-py>=1.0.0
pytest>=8.0.0
pytest-asyncio>=0.23.0
jupyter>=1.0.0
```

---

## Appendix F: Scoring Config Reference *(Added in v3.1)*

**File location:** `scoring_config.json` (project root)

**Full annotated schema:**

```json
{
  "version": "1.0",
  "updated_at": "2026-04-01T00:00:00Z",
  "update_reason": "Initial default weights",

  "weights": {
    // Normal mode (≥1 existing customer)
    // Must sum to 100
    "firmographic": 30,        // Industry + size + location match
    "keyword_relevance": 25,   // Description + tags vs ICP keywords
    "growth_signals": 20,      // Funding recency + stage
    "timing_indicators": 15,   // Company age + revenue stage + pain urgency
    "lookalike_similarity": 10 // Similarity to existing customers
  },

  "cold_start_weights": {
    // Cold-start mode (0 existing customers)
    // lookalike_similarity = 0; remainder redistributed
    // Values (excl. cold_start_floor) must sum to 95
    "firmographic": 38,
    "keyword_relevance": 30,
    "growth_signals": 20,
    "timing_indicators": 17,
    "lookalike_similarity": 0,
    "cold_start_floor": 5  // Fixed floor score when lookalike disabled
  },

  "modifiers": {
    // Applied as additive adjustments AFTER weighted sum
    // Hard cap at 100 applies after all modifiers
    "founder_led_bonus": 5,          // Company ≤ 50 employees
    "small_team_bonus": 3,           // Company 51–200 employees
    "enterprise_penalty": -5,        // Company ≥ 1000 employees
    "explicit_enterprise_penalty": -8, // When icp.prefer_not_enterprise=True AND ≥1000
    "recent_rejection_penalty": -100, // Company was removed in prior session
    "revisit_boost": 10,             // Base boost for revisit-marked companies
    "revisit_decay_half_life_days": 30 // Revisit boost half-life (days)
  },

  "tiers": {
    // Score thresholds for tier assignment
    // Tune if Tier 1 is consistently > 40% or < 10% of results
    "tier_1_min": 70,
    "tier_2_min": 45,
    "tier_3_min": 20
    // Score < tier_3_min → excluded from output
  }
}
```

**Version history convention:**

```
scoring_config_history/
  scoring_config_2026-04-01_000000.json   ← initial
  scoring_config_2026-05-15_143022.json   ← after Phase 1 manual tuning
  scoring_config_2026-07-01_090000.json   ← after Phase 2 model output
```

---

**End of Technical Specification v3.1**
