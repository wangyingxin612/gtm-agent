"""
TDD tests for src/agents/scoring_engine.py.
All scoring logic is deterministic given fixed inputs — no mocks needed.
"""
from datetime import date, datetime, timedelta
from typing import List

import pytest

from src.models.company import CompanyProfile
from src.models.icp import ICPDefinition
from src.agents.scoring_engine import (
    ScoringEngine,
    assign_tier,
    apply_deal_modifier,
    calculate_total_score,
    score_firmographic,
    score_growth_signals,
    score_keyword_relevance,
    score_lookalike,
    score_timing,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _make_company(**kwargs) -> CompanyProfile:
    defaults = dict(
        id="co-test",
        name="Test Corp",
        domain="testcorp.com",
        last_enriched=datetime(2026, 4, 28),
        enrichment_confidence=0.9,
    )
    return CompanyProfile(**{**defaults, **kwargs})


def _make_icp(**kwargs) -> ICPDefinition:
    defaults = dict(
        industries=["Financial Services", "Insurance"],
        company_size_min=50,
        company_size_max=1000,
        locations=["US", "AU"],
        keywords=["compliance", "operations", "process"],
        pain_points=["documentation", "manual workflows"],
        interpretation_confidence=0.9,
    )
    return ICPDefinition(**{**defaults, **kwargs})


@pytest.fixture
def icp() -> ICPDefinition:
    return _make_icp()


@pytest.fixture
def existing_customers() -> List[CompanyProfile]:
    return [
        _make_company(
            id="cust-001", name="Alpha Co", domain="alpha.com",
            industry="Financial Services", employee_count=250,
        ),
        _make_company(
            id="cust-002", name="Beta Inc", domain="beta.com",
            industry="Financial Services", employee_count=350,
        ),
    ]


@pytest.fixture
def perfect_match() -> CompanyProfile:
    return _make_company(
        id="co-001",
        name="AcmeFin",
        domain="acmefin.com",
        industry="Financial Services",
        employee_count=320,
        hq_country="US",
        hq_location="New York, US",
        funding_series="Series B",
        funding_date=date.today() - timedelta(days=150),  # ~5 months ago → ≤6mo → +8
        founded_year=date.today().year - 8,               # 8 years old → 3-10 range → +4
        revenue_range="$10M-$50M",
        description="compliance operations process documentation manual workflows",
    )


@pytest.fixture
def partial_match() -> CompanyProfile:
    return _make_company(
        id="co-002",
        name="BigCorp",
        domain="bigcorp.com",
        industry="Financial Services",
        employee_count=3000,
        hq_country="US",
        founded_year=date.today().year - 16,
        description="enterprise financial compliance platform",
    )


@pytest.fixture
def cold_start_company() -> CompanyProfile:
    return _make_company(
        id="co-003",
        name="InsureTech",
        domain="insuretech.com",
        industry="Insurance",
        employee_count=150,
        hq_country="AU",
        funding_series="Series A",
        funding_date=date.today() - timedelta(days=305),  # ~10 months → ≤12mo → +5
        founded_year=date.today().year - 6,               # 6 years old → 3-10 range → +4
        revenue_range="$1M-$10M",
        description="insurance process automation compliance",
    )


@pytest.fixture
def no_match() -> CompanyProfile:
    return _make_company(
        id="co-004",
        name="GameCo",
        domain="gameco.com",
        industry="Gaming",
        employee_count=50,
        hq_country="BR",
        founded_year=date.today().year - 2,  # 2 years old → <3 → +2
        description="mobile gaming entertainment platform",
    )


# ---------------------------------------------------------------------------
# TestFirmographicScore
# ---------------------------------------------------------------------------

class TestFirmographicScore:
    def test_exact_industry_match_scores_12(self, icp):
        company = _make_company(industry="Financial Services")
        assert score_firmographic(company, icp) == pytest.approx(12.0)

    def test_employee_count_in_range_scores_12(self, icp):
        company = _make_company(employee_count=320)
        assert score_firmographic(company, icp) == pytest.approx(12.0)

    def test_employee_count_at_lower_boundary_in_range(self, icp):
        company = _make_company(employee_count=50)
        assert score_firmographic(company, icp) == pytest.approx(12.0)

    def test_employee_count_at_upper_boundary_in_range(self, icp):
        company = _make_company(employee_count=1000)
        assert score_firmographic(company, icp) == pytest.approx(12.0)

    def test_employee_count_in_near_range_scores_5(self, icp):
        # 0.5 * 50 = 25 ≤ 30 ≤ 2 * 1000 = 2000 → near range
        company = _make_company(employee_count=30)
        assert score_firmographic(company, icp) == pytest.approx(5.0)

    def test_employee_count_out_of_range_scores_0(self, icp):
        # 3000 > 2 * 1000 = 2000 → out of range
        company = _make_company(employee_count=3000)
        assert score_firmographic(company, icp) == pytest.approx(0.0)

    def test_exact_country_match_scores_6(self, icp):
        company = _make_company(hq_country="US")
        assert score_firmographic(company, icp) == pytest.approx(6.0)

    def test_hq_location_match_scores_6(self, icp):
        # hq_location may contain the ICP location string
        company = _make_company(hq_location="AU")
        assert score_firmographic(company, icp) == pytest.approx(6.0)

    def test_perfect_firmographic_scores_30(self, icp):
        company = _make_company(
            industry="Financial Services",
            employee_count=320,
            hq_country="US",
        )
        assert score_firmographic(company, icp) == pytest.approx(30.0)

    def test_no_match_scores_0(self, icp):
        company = _make_company(
            industry="Gaming",
            employee_count=3000,
            hq_country="BR",
        )
        assert score_firmographic(company, icp) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# TestKeywordRelevanceScore
# ---------------------------------------------------------------------------

class TestKeywordRelevanceScore:
    def test_all_keywords_match_scores_25(self, icp):
        company = _make_company(
            description="compliance operations process documentation manual workflows"
        )
        assert score_keyword_relevance(company, icp) == pytest.approx(25.0)

    def test_no_keywords_match_scores_0(self, icp):
        company = _make_company(description="mobile gaming entertainment")
        assert score_keyword_relevance(company, icp) == pytest.approx(0.0)

    def test_partial_match_scales_proportionally(self, icp):
        # 2 of 5 keywords match → 2/5 * 25 = 10.0
        company = _make_company(description="compliance operations")
        assert score_keyword_relevance(company, icp) == pytest.approx(10.0)

    def test_no_icp_keywords_returns_12_5(self):
        icp_no_kw = _make_icp(keywords=None, pain_points=None)
        company = _make_company(description="some description")
        assert score_keyword_relevance(company, icp_no_kw) == pytest.approx(12.5)

    def test_keywords_matched_in_tech_stack(self, icp):
        company = _make_company(
            description="",
            tech_stack=["compliance", "operations"],
        )
        # 2 of 5 match → 10.0
        assert score_keyword_relevance(company, icp) == pytest.approx(10.0)

    def test_match_is_case_insensitive(self, icp):
        company = _make_company(description="COMPLIANCE OPERATIONS PROCESS")
        # 3 of 5 keywords → 3/5 * 25 = 15.0
        assert score_keyword_relevance(company, icp) == pytest.approx(15.0)


# ---------------------------------------------------------------------------
# TestGrowthSignals
# ---------------------------------------------------------------------------

class TestGrowthSignals:
    def test_funding_within_6_months_scores_8(self):
        company = _make_company(
            funding_date=date.today() - timedelta(days=150)  # ~5 months
        )
        assert score_growth_signals(company) == pytest.approx(8.0)

    def test_funding_within_12_months_scores_5(self):
        company = _make_company(
            funding_date=date.today() - timedelta(days=270)  # ~9 months
        )
        assert score_growth_signals(company) == pytest.approx(5.0)

    def test_funding_within_24_months_scores_2(self):
        company = _make_company(
            funding_date=date.today() - timedelta(days=540)  # ~18 months
        )
        assert score_growth_signals(company) == pytest.approx(2.0)

    def test_no_funding_date_scores_0(self):
        company = _make_company()
        assert score_growth_signals(company) == pytest.approx(0.0)

    def test_series_a_stage_bonus_is_6(self):
        company = _make_company(funding_series="Series A")
        assert score_growth_signals(company) == pytest.approx(6.0)

    def test_series_b_stage_bonus_is_5(self):
        company = _make_company(funding_series="Series B")
        assert score_growth_signals(company) == pytest.approx(5.0)

    def test_seed_stage_bonus_is_3(self):
        company = _make_company(funding_series="Seed")
        assert score_growth_signals(company) == pytest.approx(3.0)

    def test_recent_funding_plus_stage_does_not_exceed_20(self):
        # Max possible: 8 (funding ≤6mo) + 6 (Series A) = 14, capped at 20
        company = _make_company(
            funding_date=date.today() - timedelta(days=30),
            funding_series="Series A",
        )
        assert score_growth_signals(company) <= 20.0


# ---------------------------------------------------------------------------
# TestTimingScore
# ---------------------------------------------------------------------------

class TestTimingScore:
    def test_pain_point_in_description_scores_8(self, icp):
        company = _make_company(description="we handle documentation workflows")
        assert score_timing(company, icp) == pytest.approx(8.0)

    def test_no_pain_point_scores_0(self, icp):
        company = _make_company(description="gaming entertainment platform")
        assert score_timing(company, icp) == pytest.approx(0.0)

    def test_age_3_to_10_years_scores_4(self, icp):
        company = _make_company(founded_year=date.today().year - 7)
        assert score_timing(company, icp) == pytest.approx(4.0)

    def test_age_less_than_3_years_scores_2(self, icp):
        company = _make_company(founded_year=date.today().year - 1)
        assert score_timing(company, icp) == pytest.approx(2.0)

    def test_revenue_range_10m_50m_scores_3(self, icp):
        company = _make_company(revenue_range="$10M-$50M")
        assert score_timing(company, icp) == pytest.approx(3.0)

    def test_revenue_range_1m_10m_scores_3(self, icp):
        company = _make_company(revenue_range="$1M-$10M")
        assert score_timing(company, icp) == pytest.approx(3.0)

    def test_max_timing_score_capped_at_15(self, icp):
        company = _make_company(
            description="documentation manual workflows",
            founded_year=date.today().year - 5,
            revenue_range="$10M-$50M",
        )
        # 8 + 4 + 3 = 15 → at cap
        assert score_timing(company, icp) == pytest.approx(15.0)


# ---------------------------------------------------------------------------
# TestLookalikeSimilarity
# ---------------------------------------------------------------------------

class TestLookalikeSimilarity:
    def test_no_customers_returns_5(self):
        company = _make_company()
        assert score_lookalike(company, []) == pytest.approx(5.0)

    def test_two_customers_full_match_scores_10(self):
        # same industry + in size range for both customers → ratio=1.0 → 10.0
        company = _make_company(industry="Financial Services", employee_count=300)
        customers = [
            _make_company(id="c1", domain="c1.com", industry="Financial Services", employee_count=250),
            _make_company(id="c2", domain="c2.com", industry="Financial Services", employee_count=350),
        ]
        assert score_lookalike(company, customers) == pytest.approx(10.0)

    def test_two_customers_no_match_scores_0(self):
        company = _make_company(industry="Gaming", employee_count=3000)
        customers = [
            _make_company(id="c1", domain="c1.com", industry="Financial Services", employee_count=250),
            _make_company(id="c2", domain="c2.com", industry="Financial Services", employee_count=350),
        ]
        # same_industry=0, in_size_range=0 → ratio=0 → 0.0
        assert score_lookalike(company, customers) == pytest.approx(0.0)

    def test_one_customer_industry_only_match_scores_5(self):
        # 1 customer; same industry → +1, size diff > 200 → 0
        # ratio = (1+0)/(2*1) = 0.5 → 5.0
        company = _make_company(industry="Financial Services", employee_count=10)
        customers = [
            _make_company(id="c1", domain="c1.com", industry="Financial Services", employee_count=500),
        ]
        assert score_lookalike(company, customers) == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# TestCalculateTotalScore
# ---------------------------------------------------------------------------

class TestCalculateTotalScore:
    def test_cold_start_uses_cold_weights_and_floor(self, icp):
        # With 0 customers → cold start formula
        company = _make_company(
            industry="Financial Services",
            employee_count=320,
            hq_country="US",
        )
        score_no_customers = calculate_total_score(company, icp, [])
        score_with_customers = calculate_total_score(
            company, icp,
            [_make_company(id="c1", domain="c1.com")],
        )
        # Cold start floor adds 5 bonus points to base; scores will differ
        assert score_no_customers != score_with_customers

    def test_score_hard_capped_at_100(self, icp):
        # All-max company with 2 matching customers
        company = _make_company(
            industry="Financial Services",
            employee_count=320,
            hq_country="US",
            funding_date=date.today() - timedelta(days=30),
            funding_series="Series A",
            founded_year=date.today().year - 5,
            revenue_range="$10M-$50M",
            description="compliance operations process documentation manual workflows",
        )
        customers = [
            _make_company(id="c1", domain="c1.com", industry="Financial Services", employee_count=300),
            _make_company(id="c2", domain="c2.com", industry="Financial Services", employee_count=320),
        ]
        score = calculate_total_score(company, icp, customers)
        assert score <= 100.0

    def test_perfect_match_normal_mode_score(self, icp, perfect_match, existing_customers):
        # s_firm=30, s_kw=25, s_grow=13, s_time=15, s_like=10 → 93.0
        score = calculate_total_score(perfect_match, icp, existing_customers)
        assert score == pytest.approx(93.0)

    def test_no_match_scores_low(self, icp, no_match, existing_customers):
        # Gaming company, no signals → low score
        score = calculate_total_score(no_match, icp, existing_customers)
        assert score < 20.0

    def test_cold_start_company_score(self, icp, cold_start_company):
        # Insurance, AU, Series A ~10mo ago, 150 emp, some keywords
        # s_firm=30, s_kw=10, s_grow=11, s_time=7
        # cold: (30/30*38)+(10/25*30)+(11/20*20)+(7/15*17)+5 = 38+12+11+7.93+5 = 73.93
        score = calculate_total_score(cold_start_company, icp, [])
        assert score == pytest.approx(73.93, abs=0.1)


# ---------------------------------------------------------------------------
# TestApplyDealModifier
# ---------------------------------------------------------------------------

class TestApplyDealModifier:
    def test_founder_led_bonus_for_emp_50_or_fewer(self, icp):
        company = _make_company(employee_count=50)
        assert apply_deal_modifier(60.0, company, icp) == pytest.approx(65.0)

    def test_small_team_bonus_for_emp_51_to_200(self, icp):
        company = _make_company(employee_count=150)
        assert apply_deal_modifier(60.0, company, icp) == pytest.approx(63.0)

    def test_enterprise_penalty_when_exceeds_size_max_by_50pct(self, icp):
        # icp.company_size_max=1000; 2000 > 1000*1.5=1500 → enterprise_penalty (-5)
        company = _make_company(employee_count=2000)
        assert apply_deal_modifier(60.0, company, icp) == pytest.approx(55.0)

    def test_no_penalty_when_just_at_size_max(self, icp):
        # emp=1000 == size_max; 1000 > 1500? No → no penalty
        company = _make_company(employee_count=1000)
        assert apply_deal_modifier(60.0, company, icp) == pytest.approx(60.0)

    def test_score_never_exceeds_100(self, icp):
        company = _make_company(employee_count=50)
        assert apply_deal_modifier(98.0, company, icp) == pytest.approx(100.0)

    def test_score_never_below_0(self, icp):
        # 2000 > 1500 → enterprise_penalty=-5; 2.0-5=-3 → clamped to 0
        company = _make_company(employee_count=2000)
        assert apply_deal_modifier(2.0, company, icp) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# TestAssignTier
# ---------------------------------------------------------------------------

class TestAssignTier:
    def test_score_70_is_tier_1(self):
        assert assign_tier(70.0) == "Tier 1"

    def test_score_100_is_tier_1(self):
        assert assign_tier(100.0) == "Tier 1"

    def test_score_69_is_tier_2(self):
        assert assign_tier(69.0) == "Tier 2"

    def test_score_45_is_tier_2(self):
        assert assign_tier(45.0) == "Tier 2"

    def test_score_44_is_tier_3(self):
        assert assign_tier(44.0) == "Tier 3"

    def test_score_20_is_tier_3(self):
        assert assign_tier(20.0) == "Tier 3"

    def test_score_19_is_excluded(self):
        assert assign_tier(19.0) == "excluded"

    def test_score_0_is_excluded(self):
        assert assign_tier(0.0) == "excluded"


# ---------------------------------------------------------------------------
# TestScoringEngineIntegration  (STEP D fixtures)
# ---------------------------------------------------------------------------

class TestScoringEngineIntegration:
    def test_perfect_match_is_tier_1(self, icp, perfect_match, existing_customers):
        engine = ScoringEngine()
        results = engine.score([perfect_match], icp, existing_customers)
        assert len(results) == 1
        assert results[0].tier == "Tier 1"
        assert results[0].total_score >= 70.0

    def test_partial_match_penalized_for_exceeding_size_max(
        self, icp, partial_match, existing_customers
    ):
        engine = ScoringEngine()
        results = engine.score([partial_match], icp, existing_customers)
        # 3000 emp > size_max(1000)*1.5=1500 → enterprise_penalty(-5) → 23.0 → Tier 3
        assert len(results) == 1
        assert results[0].total_score == pytest.approx(23.0)
        assert results[0].tier == "Tier 3"

    def test_cold_start_scores_without_customers(self, icp, cold_start_company):
        engine = ScoringEngine()
        results = engine.score([cold_start_company], icp, [])
        assert len(results) == 1
        # Cold start + small_team_bonus → Tier 1
        assert results[0].tier == "Tier 1"

    def test_no_match_is_excluded(self, icp, no_match, existing_customers):
        engine = ScoringEngine()
        results = engine.score([no_match], icp, existing_customers)
        assert len(results) == 1
        assert results[0].tier == "excluded"

    def test_score_breakdown_populated(self, icp, perfect_match, existing_customers):
        engine = ScoringEngine()
        results = engine.score([perfect_match], icp, existing_customers)
        breakdown = results[0].score_breakdown
        assert breakdown.firmographic_score == pytest.approx(30.0)
        assert breakdown.keyword_score == pytest.approx(25.0)
        assert breakdown.growth_score == pytest.approx(13.0)
        assert breakdown.timing_score == pytest.approx(15.0)
        assert breakdown.lookalike_score == pytest.approx(10.0)

    def test_cold_start_score_breakdown_lookalike_is_5(
        self, icp, cold_start_company
    ):
        # With 0 customers, score_lookalike returns 5.0 (neutral)
        engine = ScoringEngine()
        results = engine.score([cold_start_company], icp, [])
        assert results[0].score_breakdown.lookalike_score == pytest.approx(5.0)

    def test_cold_start_scoring_basis_is_cold_start(self, icp, cold_start_company):
        engine = ScoringEngine()
        results = engine.score([cold_start_company], icp, [])
        assert results[0].scoring_basis == "cold_start"

    def test_full_mode_scoring_basis_is_full(self, icp, perfect_match, existing_customers):
        engine = ScoringEngine()
        results = engine.score([perfect_match], icp, existing_customers)
        assert results[0].scoring_basis == "full"

    def test_cold_start_reasoning_contains_warning(self, icp, cold_start_company):
        engine = ScoringEngine()
        results = engine.score([cold_start_company], icp, [])
        assert "no existing customers" in results[0].reasoning_summary
