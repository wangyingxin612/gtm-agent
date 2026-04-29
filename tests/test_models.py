import pytest
from datetime import datetime, date
from pydantic import ValidationError

from src.models.icp import ICPDefinition
from src.models.company import (
    AgentContribution, SignalEvent, CompanyProfile, ScoreBreakdown, RankedCompany,
)
from src.models.contact import Contact
from src.models.events import SignalSnapshot, OverrideEvent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def valid_icp():
    return ICPDefinition(
        industries=["Financial Services", "Insurance"],
        company_size_min=100,
        company_size_max=2000,
        locations=["US", "GB"],
        keywords=["compliance", "operations"],
        pain_points=["manual documentation"],
        interpretation_confidence=0.91,
    )


@pytest.fixture
def valid_company():
    return CompanyProfile(
        id="550e8400-e29b-41d4-a716-446655440000",
        name="Acme Financial Corp",
        domain="acme.com",
        industry="Financial Services",
        employee_count=320,
        employee_range="201-500",
        hq_country="US",
        founded_year=2016,
        funding_series="Series B",
        funding_date=date(2023, 6, 15),
        description="Automates compliance workflows for financial services firms.",
        data_source="hunter",
        last_enriched=datetime(2026, 4, 28, 10, 0, 0),
        enrichment_confidence=0.87,
        data_quality="full",
    )


@pytest.fixture
def valid_score_breakdown():
    return ScoreBreakdown(
        firmographic_score=26.0,
        keyword_score=22.5,
        growth_score=18.0,
        timing_score=13.0,
        lookalike_score=7.0,
    )


# ---------------------------------------------------------------------------
# 1. Valid instantiation — all models
# ---------------------------------------------------------------------------

class TestValidInstantiation:
    def test_icp_definition(self, valid_icp):
        assert valid_icp.industries == ["Financial Services", "Insurance"]
        assert valid_icp.company_size_min == 100
        assert valid_icp.company_size_max == 2000

    def test_agent_contribution(self):
        ac = AgentContribution(
            agent_id="lead_research_v1",
            agent_version="1.0",
            signals_added=["industry", "employee_count"],
            confidence=0.88,
            timestamp=datetime(2026, 4, 28, 10, 0, 0),
        )
        assert ac.agent_id == "lead_research_v1"
        assert ac.source_urls is None

    def test_signal_event(self):
        se = SignalEvent(
            signal_type="funding",
            old_value=None,
            new_value="Series B",
            detected_at=datetime(2026, 4, 28, 10, 0, 0),
            source_agent="lead_research_v1",
            confidence=0.95,
        )
        assert se.signal_type == "funding"
        assert se.old_value is None

    def test_company_profile(self, valid_company):
        assert valid_company.domain == "acme.com"
        assert valid_company.data_quality == "full"

    def test_ranked_company(self, valid_company, valid_score_breakdown):
        rc = RankedCompany(
            company=valid_company,
            total_score=89.5,
            tier="Tier 1",
            score_breakdown=valid_score_breakdown,
            reasoning_summary="Scaling ops post-Series B with manual compliance workflows.",
        )
        assert rc.tier == "Tier 1"
        assert rc.total_score == 89.5
        assert rc.user_action is None

    def test_contact(self):
        c = Contact(
            id="c-001",
            first_name="Jane",
            last_name="Smith",
            full_name="Jane Smith",
            title="VP of Operations",
            seniority="VP",
            department="operations",
            email="jane@acme.com",
            email_confidence="verified",
            linkedin_url="https://linkedin.com/in/janesmith",
            data_source="hunter_domain_search",
        )
        assert c.full_name == "Jane Smith"
        assert c.is_role_suggestion is False

    def test_signal_snapshot(self):
        snap = SignalSnapshot(
            id="snap-001",
            session_id="sess-abc",
            company_id="550e8400-e29b-41d4-a716-446655440000",
            company_domain="acme.com",
            icp_hash="sha256:abc123",
            signals={"industry_match": True, "size_in_range": True},
            firmographic_score=26.0,
            keyword_score=22.5,
            growth_score=18.0,
            timing_score=13.0,
            lookalike_score=7.0,
            total_score=89.5,
            tier_assigned="Tier 1",
            scored_at=datetime(2026, 4, 28, 10, 5, 0),
        )
        assert snap.tier_assigned == "Tier 1"
        assert snap.total_score == 89.5

    def test_override_event(self):
        ov = OverrideEvent(
            id="ov-001",
            session_id="sess-abc",
            company_id="550e8400-e29b-41d4-a716-446655440000",
            company_domain="acme.com",
            action="keep",
            score_at_override=89.5,
            tier_at_override="Tier 1",
            score_breakdown_at_override={"firmographic_score": 26.0},
            timestamp=datetime(2026, 4, 28, 10, 10, 0),
        )
        assert ov.action == "keep"
        assert ov.user_id == "operator"


# ---------------------------------------------------------------------------
# 2. ICPDefinition validators
# ---------------------------------------------------------------------------

class TestICPDefinitionValidators:
    def _base_kwargs(self):
        return dict(
            company_size_min=10,
            company_size_max=500,
            locations=["US"],
            interpretation_confidence=0.9,
        )

    def test_industries_minimum_one(self):
        with pytest.raises(ValidationError, match="industries"):
            ICPDefinition(industries=[], **self._base_kwargs())

    def test_industries_maximum_ten(self):
        with pytest.raises(ValidationError, match="industries"):
            ICPDefinition(industries=[f"Industry{i}" for i in range(11)], **self._base_kwargs())

    def test_industries_exactly_one_is_valid(self):
        icp = ICPDefinition(industries=["Finance"], **self._base_kwargs())
        assert len(icp.industries) == 1

    def test_industries_exactly_ten_is_valid(self):
        icp = ICPDefinition(industries=[f"Industry{i}" for i in range(10)], **self._base_kwargs())
        assert len(icp.industries) == 10

    def test_size_min_less_than_max(self):
        with pytest.raises(ValidationError, match="company_size_min must be less than"):
            ICPDefinition(
                industries=["Finance"],
                company_size_min=500,
                company_size_max=100,
                locations=["US"],
                interpretation_confidence=0.9,
            )

    def test_size_min_equal_to_max_is_invalid(self):
        with pytest.raises(ValidationError):
            ICPDefinition(
                industries=["Finance"],
                company_size_min=200,
                company_size_max=200,
                locations=["US"],
                interpretation_confidence=0.9,
            )

    def test_size_min_less_than_max_is_valid(self):
        icp = ICPDefinition(
            industries=["Finance"],
            company_size_min=10,
            company_size_max=11,
            locations=["US"],
            interpretation_confidence=0.9,
        )
        assert icp.company_size_min < icp.company_size_max

    def test_keywords_max_twenty(self):
        with pytest.raises(ValidationError, match="keywords"):
            ICPDefinition(
                industries=["Finance"],
                keywords=[f"kw{i}" for i in range(21)],
                **self._base_kwargs(),
            )

    def test_keywords_exactly_twenty_is_valid(self):
        icp = ICPDefinition(
            industries=["Finance"],
            keywords=[f"kw{i}" for i in range(20)],
            **self._base_kwargs(),
        )
        assert len(icp.keywords) == 20

    def test_interpretation_confidence_above_one_is_invalid(self):
        with pytest.raises(ValidationError, match="interpretation_confidence"):
            ICPDefinition(industries=["Finance"], locations=["US"],
                          company_size_min=10, company_size_max=500,
                          interpretation_confidence=1.1)

    def test_interpretation_confidence_below_zero_is_invalid(self):
        with pytest.raises(ValidationError, match="interpretation_confidence"):
            ICPDefinition(industries=["Finance"], locations=["US"],
                          company_size_min=10, company_size_max=500,
                          interpretation_confidence=-0.1)


# ---------------------------------------------------------------------------
# 3. SignalSnapshot defaults
# ---------------------------------------------------------------------------

class TestSignalSnapshotDefaults:
    @pytest.fixture
    def snapshot(self):
        return SignalSnapshot(
            id="snap-001",
            session_id="sess-abc",
            company_id="comp-001",
            company_domain="acme.com",
            icp_hash="sha256:abc123",
            firmographic_score=20.0,
            keyword_score=15.0,
            growth_score=10.0,
            timing_score=8.0,
            lookalike_score=5.0,
            total_score=58.0,
            tier_assigned="Tier 2",
            scored_at=datetime(2026, 4, 28, 10, 0, 0),
        )

    def test_user_outcome_defaults_to_none(self, snapshot):
        assert snapshot.user_outcome is None

    def test_outcome_reason_defaults_to_none(self, snapshot):
        assert snapshot.outcome_reason is None

    def test_outcome_timestamp_defaults_to_none(self, snapshot):
        assert snapshot.outcome_timestamp is None

    def test_signals_defaults_to_empty_dict(self, snapshot):
        assert snapshot.signals == {}

    def test_user_outcome_accepts_valid_values(self, snapshot):
        for outcome in ("keep", "remove", "revisit"):
            snapshot.user_outcome = outcome
            assert snapshot.user_outcome == outcome


# ---------------------------------------------------------------------------
# 4. CompanyProfile defaults
# ---------------------------------------------------------------------------

class TestCompanyProfileDefaults:
    @pytest.fixture
    def minimal_company(self):
        return CompanyProfile(
            id="comp-001",
            name="Minimal Co",
            domain="minimal.com",
            last_enriched=datetime(2026, 4, 28, 10, 0, 0),
            enrichment_confidence=0.5,
        )

    def test_agent_contributions_defaults_to_empty_dict(self, minimal_company):
        assert minimal_company.agent_contributions == {}

    def test_signal_history_defaults_to_empty_list(self, minimal_company):
        assert minimal_company.signal_history == []

    def test_data_source_defaults_to_hunter(self, minimal_company):
        assert minimal_company.data_source == "hunter"

    def test_data_quality_defaults_to_full(self, minimal_company):
        assert minimal_company.data_quality == "full"

    def test_data_quality_rejects_invalid_value(self):
        with pytest.raises(ValidationError, match="data_quality"):
            CompanyProfile(
                id="x", name="X", domain="x.com",
                last_enriched=datetime(2026, 4, 28),
                enrichment_confidence=0.5,
                data_quality="unknown",
            )

    def test_enrichment_confidence_above_one_is_invalid(self):
        with pytest.raises(ValidationError, match="enrichment_confidence"):
            CompanyProfile(
                id="x", name="X", domain="x.com",
                last_enriched=datetime(2026, 4, 28),
                enrichment_confidence=1.5,
            )
