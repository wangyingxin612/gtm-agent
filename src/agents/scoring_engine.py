"""
ScoringEngine: heuristic lead prioritization.

Scoring is purely deterministic given company data and ICP — no I/O,
no external calls. All weights and thresholds come from scoring_config.json.

Score semantics: higher = higher expected outreach value *right now*.
Differences < 5 points are not meaningful.
"""

import json
import os
from datetime import date
from functools import lru_cache
from typing import List, Optional

from src.models.company import CompanyProfile, RankedCompany, ScoreBreakdown
from src.models.icp import ICPDefinition


@lru_cache(maxsize=1)
def load_scoring_config(path: str = "scoring_config.json") -> dict:
    abs_path = os.path.join(os.path.dirname(__file__), "..", "..", path)
    with open(abs_path) as f:
        return json.load(f)


def _midpoint(employee_range: Optional[str]) -> float:
    """Parse 'N-M' employee range string and return midpoint."""
    if not employee_range:
        return 0.0
    try:
        parts = employee_range.split("-")
        return (float(parts[0]) + float(parts[1])) / 2
    except (IndexError, ValueError):
        return 0.0


def _is_related_industry(industry: Optional[str], icp_industries: List[str]) -> bool:
    """Return True if industry is a close variant of any ICP industry."""
    if not industry:
        return False
    related_map = {
        "finance": ["financial services", "banking", "fintech"],
        "financial services": ["finance", "banking", "fintech"],
        "banking": ["financial services", "finance", "fintech"],
        "insurance": ["insurtech", "reinsurance"],
        "insurtech": ["insurance"],
        "tech": ["software", "saas", "technology"],
        "software": ["tech", "saas", "technology"],
        "saas": ["software", "tech", "technology"],
    }
    industry_lower = industry.lower()
    related = related_map.get(industry_lower, [])
    return any(icp.lower() in related or icp.lower() == industry_lower for icp in icp_industries)


def _is_same_region(country: Optional[str], icp_locations: List[str]) -> bool:
    """Return True if country is in the same broad region as any ICP location."""
    if not country:
        return False
    region_map = {
        "US": "north_america",
        "CA": "north_america",
        "MX": "north_america",
        "GB": "europe",
        "DE": "europe",
        "FR": "europe",
        "NL": "europe",
        "SE": "europe",
        "AU": "apac",
        "NZ": "apac",
        "SG": "apac",
        "JP": "apac",
    }
    company_region = region_map.get(country.upper())
    if not company_region:
        return False
    return any(region_map.get(loc.upper()) == company_region for loc in icp_locations)


def score_firmographic(company: CompanyProfile, icp: ICPDefinition) -> float:
    score = 0.0

    # Industry match (0-12)
    if company.industry in icp.industries:
        score += 12
    elif _is_related_industry(company.industry, icp.industries):
        score += 6

    # Company size (0-12)
    emp = company.employee_count or _midpoint(company.employee_range)
    if emp and icp.company_size_min <= emp <= icp.company_size_max:
        score += 12
    elif emp and icp.company_size_min * 0.5 <= emp <= icp.company_size_max * 2:
        score += 5

    # Location (0-6)
    if company.hq_country in icp.locations or company.hq_location in icp.locations:
        score += 6
    elif _is_same_region(company.hq_country, icp.locations):
        score += 3

    return score  # max 30


def score_keyword_relevance(company: CompanyProfile, icp: ICPDefinition) -> float:
    target_keywords = (icp.keywords or []) + (icp.pain_points or [])
    if not target_keywords:
        return 12.5  # neutral when no keywords defined

    company_text = (
        f"{company.description or ''} "
        f"{' '.join(company.tech_stack or [])} "
        f"{company.industry or ''}"
    ).lower()

    matched = sum(1 for kw in target_keywords if kw.lower() in company_text)
    ratio = matched / len(target_keywords)
    return min(25.0, 25.0 * ratio)


def score_growth_signals(company: CompanyProfile) -> float:
    score = 0.0

    if company.funding_date:
        months_ago = (date.today() - company.funding_date).days / 30
        if months_ago <= 6:
            score += 8
        elif months_ago <= 12:
            score += 5
        elif months_ago <= 24:
            score += 2

    stage_scores = {
        "Seed": 3, "Pre-Seed": 2,
        "Series A": 6, "Series B": 5, "Series C": 4,
        "Series C+": 3, "IPO": 2,
    }
    score += stage_scores.get(company.funding_series or "", 0)

    return min(20.0, score)


def score_timing(company: CompanyProfile, icp: ICPDefinition) -> float:
    score = 0.0

    urgency_keywords = icp.pain_points or []
    if any(kw.lower() in (company.description or "").lower() for kw in urgency_keywords):
        score += 8

    if company.founded_year:
        age = date.today().year - company.founded_year
        if 3 <= age <= 10:
            score += 4
        elif age < 3:
            score += 2

    revenue_stage_map = {
        "$1M-$10M": 3, "$10M-$50M": 3, "$50M-$100M": 2,
        "<$1M": 1, ">$100M": 1,
    }
    score += revenue_stage_map.get(company.revenue_range or "", 0)

    return min(15.0, score)


def score_lookalike(
    company: CompanyProfile,
    existing_customers: List[CompanyProfile],
) -> float:
    if len(existing_customers) == 0:
        return 5.0

    if len(existing_customers) < 3:
        same_industry = sum(
            1 for c in existing_customers if c.industry == company.industry
        )
        in_size_range = sum(
            1 for c in existing_customers
            if c.employee_count and
            abs(c.employee_count - (company.employee_count or 0)) < 200
        )
        ratio = (same_industry + in_size_range) / (2 * len(existing_customers))
        return round(10.0 * ratio, 2)

    # 3+ customers: cosine similarity placeholder — use simple overlap until
    # embedding integration is added in Phase 2.
    same_industry = sum(
        1 for c in existing_customers if c.industry == company.industry
    )
    in_size_range = sum(
        1 for c in existing_customers
        if c.employee_count and
        abs(c.employee_count - (company.employee_count or 0)) < 200
    )
    ratio = (same_industry + in_size_range) / (2 * len(existing_customers))
    return round(10.0 * ratio, 2)


def calculate_total_score(
    company: CompanyProfile,
    icp: ICPDefinition,
    existing_customers: List[CompanyProfile],
) -> float:
    config = load_scoring_config()
    w = config["weights"]
    cw = config["cold_start_weights"]

    s_firm = score_firmographic(company, icp)
    s_kw = score_keyword_relevance(company, icp)
    s_grow = score_growth_signals(company)
    s_time = score_timing(company, icp)
    s_like = score_lookalike(company, existing_customers)

    if len(existing_customers) == 0:
        total = (
            (s_firm / 30 * cw["firmographic"]) +
            (s_kw / 25 * cw["keyword_relevance"]) +
            (s_grow / 20 * cw["growth_signals"]) +
            (s_time / 15 * cw["timing_indicators"]) +
            cw["cold_start_floor"]
        )
    else:
        total = (
            (s_firm / 30 * w["firmographic"]) +
            (s_kw / 25 * w["keyword_relevance"]) +
            (s_grow / 20 * w["growth_signals"]) +
            (s_time / 15 * w["timing_indicators"]) +
            (s_like / 10 * w["lookalike_similarity"])
        )

    return min(100.0, round(total, 2))


def apply_deal_modifier(
    score: float,
    company: CompanyProfile,
    icp: ICPDefinition,
) -> float:
    config = load_scoring_config()
    m = config["modifiers"]
    emp = company.employee_count or _midpoint(company.employee_range)
    adjustment = 0.0

    if emp > icp.company_size_max * 1.5:
        adjustment += m["enterprise_penalty"]
    elif emp <= 50:
        adjustment += m["founder_led_bonus"]
    elif emp <= 200:
        adjustment += m["small_team_bonus"]

    return min(100.0, max(0.0, score + adjustment))


def assign_tier(score: float) -> str:
    config = load_scoring_config()
    t = config["tiers"]
    if score >= t["tier_1_min"]:
        return "Tier 1"
    if score >= t["tier_2_min"]:
        return "Tier 2"
    if score >= t["tier_3_min"]:
        return "Tier 3"
    return "excluded"


class ScoringEngine:
    """Scores a list of CompanyProfiles against an ICP and existing customers."""

    def __init__(self, config_path: str = "scoring_config.json"):
        self._config_path = config_path

    def score(
        self,
        companies: List[CompanyProfile],
        icp: ICPDefinition,
        existing_customers: List[CompanyProfile],
    ) -> List[RankedCompany]:
        is_cold_start = len(existing_customers) == 0
        scoring_basis = "cold_start" if is_cold_start else "full"
        cold_start_note = (
            "⚠ Score based on firmographic fit only — no existing customers to validate against."
            if is_cold_start else ""
        )

        results = []
        for company in companies:
            s_firm = score_firmographic(company, icp)
            s_kw = score_keyword_relevance(company, icp)
            s_grow = score_growth_signals(company)
            s_time = score_timing(company, icp)
            s_like = score_lookalike(company, existing_customers)

            raw = calculate_total_score(company, icp, existing_customers)
            modified = apply_deal_modifier(raw, company, icp)
            tier = assign_tier(modified)

            results.append(
                RankedCompany(
                    company=company,
                    total_score=modified,
                    tier=tier,
                    score_breakdown=ScoreBreakdown(
                        firmographic_score=s_firm,
                        keyword_score=s_kw,
                        growth_score=s_grow,
                        timing_score=s_time,
                        lookalike_score=s_like,
                    ),
                    scoring_basis=scoring_basis,
                    reasoning_summary=cold_start_note,
                )
            )
        return results
