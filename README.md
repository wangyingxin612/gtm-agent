# GTM Agent

[![tests](https://github.com/wangyingxin612/gtm-agent/actions/workflows/test.yml/badge.svg)](https://github.com/wangyingxin612/gtm-agent/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Backend Python pipeline for B2B lead research.

**Input:** Company website + natural-language ICP description  
**Output:** Ranked company list with contacts (CSV / JSON)

---

## Quick Start

```bash
# 1. Install (Python 3.11+)
pip install -r requirements.txt
pip install -e .

# 2. Set API keys
cp .env.example .env
# Edit .env with your Hunter.io and Anthropic keys

# 3. Run tests
pytest tests/

# 4. Open the pipeline notebook
jupyter notebook notebooks/gtm_pipeline.ipynb
```

## API Keys Required

| Key | Where to get |
|-----|-------------|
| `HUNTER_API_KEY` | [hunter.io](https://hunter.io) — Free plan sufficient to start |
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) |
| `FIRECRAWL_API_KEY` | [firecrawl.dev](https://firecrawl.dev) — Optional for MVP |

## What You Get

Tell it who you sell to; it returns a ranked, explained list of companies to reach out to now, with the right people at each.
One row of the CSV output (illustrative, fictional company):

| company_name | tier | score | why_now | contact_1_title |
|---|---|---|---|---|
| Northwind Mutual | Tier 1 | 78.5 | Strong firmographic fit; high keyword match; funded 4mo ago (Series B) | VP of Operations |

Scores are prioritization heuristics, not conversion predictions — differences under 5 points aren't meaningful.

## Architecture

```
ICPInterpreter       → Claude Sonnet: NL → structured ICPDefinition
CompanyDiscoverer    → Hunter Discover API (free) + concurrent enrichment
ScoringEngine        → scoring_config.json weights (firmographic + keyword + growth + timing + lookalike)
ContactDiscoveryAgent → Hunter Domain Search, Tier 1/2 only, failure-isolated
```

All weights, tier thresholds, and modifiers live in `scoring_config.json` — never in code.

## Usage

### Notebook (recommended)

Open `notebooks/gtm_pipeline.ipynb` and run top-to-bottom. Configure your ICP in Section 2, then run the pipeline cell.

### CLI

```python
import asyncio
from src.pipeline import run_pipeline

session = asyncio.run(run_pipeline(
    company_website="https://mycompany.com",
    target_description="Mid-market fintech companies in the US with 50-500 employees",
))

from src.pipeline import export_to_csv
export_to_csv(session, "output/results.csv")
```

## Learning Loop

| Phase | Trigger | Action |
|-------|---------|--------|
| Phase 1 | Weekly | Run `notebooks/weekly_signal_analysis.ipynb` to review signal quality |
| Phase 2 | ≥ 80 labeled samples | `python scripts/train_scoring_model.py` → review → `python scripts/apply_weights.py` |

Label outcomes by updating `user_outcome` in `signal_snapshots` after outreach.
Each snapshot records its `scoring_basis` (`full` vs `cold_start`) so training can segment by it.

`load_scoring_config()` is cached per process. After `apply_weights.py` rewrites
`scoring_config.json`, restart any running notebook kernel (or call
`load_scoring_config.cache_clear()`) to pick up the new weights.

## Project Layout

```
src/
  agents/          icp_interpreter, company_discoverer, scoring_engine, contact_discovery
  data_providers/  hunter_client (+ firecrawl_client post-MVP)
  models/          company, contact, icp, session, events
  storage/         database.py — SQLite signal_snapshots + override_events
  pipeline.py      run_pipeline() entry point

notebooks/
  gtm_pipeline.ipynb            Main operator interface
  weekly_signal_analysis.ipynb  Phase 1 learning analysis

scripts/
  train_scoring_model.py   Phase 2: train weights from labeled data (triggers at 80 samples)
  apply_weights.py         Human-approved weight update

scoring_config.json   All weights and thresholds (never hardcode in Python)
```

## Tests

```bash
pytest tests/          # all external APIs (Hunter, Claude) mocked — no real calls
```
