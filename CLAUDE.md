# GTM AI Agent — Project Instructions for Claude Code

## What This Project Is

Backend-only Python pipeline for B2B lead research.
Takes a company website + ICP description → returns a ranked company list with contacts.
No frontend in MVP. Output is CSV/JSON via Jupyter Notebook or CLI.

Full spec:  docs/Tech_Spec_v3.1.md  ← read this before any architectural decisions
PRD:        docs/PRD_v2.md

---

## System Objective

The system optimizes for:
> Expected value of reaching out to a company at a given point in time

= f(ICP Fit, Timing, Signal Confidence)

Scores are heuristic prioritization signals, not conversion predictions.
Small differences (< 5 points) are not meaningful.

---

## Architecture

Four agents, all synchronous in MVP, all Python classes with a single async entry point.
See docs/Tech_Spec_v3.1.md Section 3.4 for the full agent map.

```
ICPInterpreter          → LLM (Claude Sonnet), NL → structured ICPDefinition
CompanyDiscoverer       → Hunter Discover API (free endpoint, no credits)
ScoringEngine           → reads scoring_config.json, never hardcoded weights
ContactDiscoveryAgent   → Hunter Domain Search, isolated failure handling
```

Agent encapsulation rule: each agent is a class with its own __init__, single
primary async method, own error handling. No agent knows another's internals.

---

## Project Structure

```
gtm-agent/
├── src/
│   ├── agents/
│   │   ├── icp_interpreter.py        # ICPInterpreter class
│   │   ├── company_discoverer.py     # CompanyDiscoverer class
│   │   ├── scoring_engine.py         # ScoringEngine class
│   │   └── contact_discovery.py      # ContactDiscoveryAgent class
│   ├── models/
│   │   ├── icp.py                    # ICPDefinition, all ICP-related models
│   │   ├── company.py                # CompanyProfile (canonical context), RankedCompany
│   │   ├── contact.py                # Contact model
│   │   ├── events.py                 # SignalSnapshot, OverrideEvent, SignalEvent
│   │   └── session.py                # ResearchSession
│   ├── data_providers/
│   │   └── hunter_client.py          # All Hunter.io API calls (retry + concurrency cap)
│   │                                 # firecrawl_client.py — post-MVP, not yet implemented
│   ├── storage/
│   │   └── database.py               # SQLite: signal_snapshots, override_events tables
│   ├── config.py                     # load_scoring_config() (lru_cached)
│   └── pipeline.py                   # run_pipeline() — main entry point
├── data/
│   ├── sessions/                     # Session JSON files (gitignored)
│   ├── cache/                        # API response cache (gitignored)
│   └── signal_store/                 # SQLite DB lives here (gitignored)
├── notebooks/
│   ├── gtm_pipeline.ipynb            # Operator interface: run pipeline, review, export
│   └── weekly_signal_analysis.ipynb  # Phase 1 manual learning analysis
├── scripts/
│   ├── train_scoring_model.py        # Phase 2: triggers at 80 labeled samples
│   └── apply_weights.py              # Human-approved weight update
├── tests/                            # One test_*.py per module; all external APIs mocked
├── docs/
│   ├── Tech_Spec_v3.1.md
│   └── PRD_v2.md
├── .github/workflows/test.yml        # CI: pytest on Python 3.11 + 3.12
├── scoring_config.json               # All weights, tiers, modifiers — never hardcode
├── scoring_config_history/           # Versioned backups (created on first weight update)
├── CLAUDE.md                         # This file
├── .env                              # Real API keys — NEVER commit
├── .env.example                      # Template — safe to commit
├── pyproject.toml                    # pip install -e .
└── requirements.txt
```

---

## Canonical Data Model

`CompanyProfile` is the single source of truth shared across all agents.
All agents read from and write to this structure. No parallel representations.
See docs/Tech_Spec_v3.1.md Section 7.2 for full schema including:
- `agent_contributions: Dict[str, AgentContribution]` — who wrote what
- `signal_history: List[SignalEvent]` — for future Timing Agent (post-MVP)

---

## Database — Two Critical Tables

### signal_snapshots
Written once per company per scoring run.
Contains: all signal values at time of scoring + score breakdown + tier assigned.
`user_outcome` field filled post-hoc when user takes action.
This is the foundation of the learning loop. Must never be skipped.

### override_events
Written immediately when user keeps/removes/revisits a company.
Contains: `score_breakdown_at_override` (full snapshot of scores at time of action).
This is ground truth for Phase 2 weight training.

Schema: docs/Tech_Spec_v3.1.md Sections 10.1 and 20.1

---

## Scoring Config

All scoring weights, tier thresholds, and modifiers live in `scoring_config.json`.
Never hardcode a weight or threshold in Python code.
Load with `load_scoring_config()` (cached with `@lru_cache`).
When weights change: bump version, backup to `scoring_config_history/`.
See docs/Tech_Spec_v3.1.md Section 8.0 and Appendix F.

---

## Non-Negotiables

- Weights in scoring_config.json only — never in code
- Never display guessed or generated emails (only verified public ones)
- Contact discovery failure must NOT drop companies from output
- All external API calls must be injectable/mockable for tests
- .env for secrets, never committed to git
- signal_snapshots written on EVERY scoring run, no exceptions
- override_events written IMMEDIATELY on EVERY user action

---

## Testing Rules

- Unit test every scoring function with known inputs and expected outputs
- Mock ALL external API calls: Hunter, Firecrawl, Claude API
- SQLite tests use in-memory DB: `sqlite3.connect(":memory:")`
- Test cold-start separately from normal scoring (0 customers vs 3+ customers)
- Run `pytest tests/` before every commit
- Every value passed between agents in `pipeline.py` needs a pipeline-level test,
  not just a unit test on the receiving agent (unit tests alone missed that
  `existing_customers` never reached the scorer)
- CI runs on every push/PR (Python 3.11 + 3.12); DeprecationWarnings fail the build

---

## API Keys (via python-dotenv)

```python
from dotenv import load_dotenv
import os
load_dotenv()

HUNTER_API_KEY = os.getenv("HUNTER_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY")
```

Keys required:
- HUNTER_API_KEY    → hunter.io (free plan sufficient to start)
- ANTHROPIC_API_KEY → console.anthropic.com → API Keys
- FIRECRAWL_API_KEY → firecrawl.dev (optional for MVP early stage)

---

## Error Handling Defaults

| Service   | Retry | Backoff         | Fallback               |
|-----------|-------|-----------------|------------------------|
| Hunter    | 3x    | Exponential 1-4s| PDL or skip            |
| Firecrawl | 2x    | Linear 2s       | Skip website analysis  |
| Claude    | 3x    | Exponential     | Template-based output  |

Pipeline should always produce output, even with partial data.
Flag low-confidence companies with `data_quality: "limited"` rather than dropping.

---

## Learning Pipeline (read docs/Tech_Spec_v3.1.md Section 20)

Phase 1 (now):        Manual weekly analysis of signal_snapshots via Jupyter notebook
Phase 2 (≥80 labels): Run scripts/train_scoring_model.py → review → apply_weights.py
Phase 3 (post-MVP):   CRM integration for conversion-based ground truth

Trigger for Phase 2:
```python
SELECT COUNT(*) FROM signal_snapshots WHERE user_outcome IS NOT NULL
# When this reaches 80, run Phase 2
```

---

## Implementation Order (recommended)

1. models/          — Pydantic schemas first (no dependencies)
2. storage/         — SQLite tables (depends on models)
3. scoring_engine   — Core logic, fully testable without API calls
4. data_providers/  — Hunter client + Firecrawl client (mockable)
5. agents/          — Wire up each agent class
6. pipeline.py      — Orchestrate end-to-end
7. notebooks/       — Jupyter interface for operator use
