"""
TDD tests for src/pipeline.py.
All agents and external I/O are mocked — no real API calls ever made.
"""
import csv
import os
import uuid
from datetime import datetime
from typing import List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.company import CompanyProfile, RankedCompany, ScoreBreakdown
from src.models.contact import Contact
from src.models.icp import ICPDefinition
from src.models.session import ResearchSession
from src.pipeline import Pipeline, export_to_csv


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_icp(**kwargs) -> ICPDefinition:
    defaults = dict(
        industries=["Financial Services"],
        company_size_min=50,
        company_size_max=500,
        locations=["US"],
        interpretation_confidence=0.9,
    )
    return ICPDefinition(**{**defaults, **kwargs})


def _make_profile(domain: str) -> CompanyProfile:
    return CompanyProfile(
        id=str(uuid.uuid4()),
        name=f"{domain} Corp",
        domain=domain,
        industry="Financial Services",
        employee_range="201-500",
        hq_country="US",
        data_source="hunter",
        last_enriched=datetime.utcnow(),
        enrichment_confidence=0.9,
    )


def _make_ranked(domain: str, tier: str = "Tier 1", score: float = 75.0) -> RankedCompany:
    return RankedCompany(
        company=_make_profile(domain),
        total_score=score,
        tier=tier,
        score_breakdown=ScoreBreakdown(
            firmographic_score=20.0,
            keyword_score=15.0,
            growth_score=10.0,
            timing_score=10.0,
            lookalike_score=5.0,
        ),
        reasoning_summary="Strong ICP fit.",
    )


def _make_contact(email: str = "jane@example.com") -> Contact:
    return Contact(
        id=str(uuid.uuid4()),
        first_name="Jane",
        last_name="Smith",
        full_name="Jane Smith",
        title="VP of Operations",
        seniority="vp",
        department="management",
        email=email,
        email_confidence="verified",
        linkedin_url="https://linkedin.com/in/janesmith",
        data_source="hunter_domain_search",
    )


def _make_pipeline(
    icp=None,
    companies=None,
    ranked=None,
    ranked_with_contacts=None,
) -> Pipeline:
    """Build a Pipeline with all agents mocked."""
    icp = icp or _make_icp()
    companies = companies or [_make_profile("acme.com")]
    ranked = ranked or [_make_ranked("acme.com")]
    ranked_with_contacts = ranked_with_contacts or ranked

    mock_icp_interp = MagicMock()
    mock_icp_interp.interpret = AsyncMock(return_value=icp)

    mock_discoverer = MagicMock()
    mock_discoverer.discover = AsyncMock(return_value=companies)
    mock_discoverer.enrich_domains = AsyncMock(return_value=companies)

    mock_scorer = MagicMock()
    mock_scorer.score = MagicMock(return_value=ranked)

    mock_contact_agent = MagicMock()
    mock_contact_agent.run = AsyncMock(return_value=ranked_with_contacts)

    mock_db = MagicMock()
    mock_db.save_signal_snapshot = MagicMock()

    return Pipeline(
        icp_interpreter=mock_icp_interp,
        company_discoverer=mock_discoverer,
        scoring_engine=mock_scorer,
        contact_agent=mock_contact_agent,
        db=mock_db,
    )


# ---------------------------------------------------------------------------
# Pipeline.run() — full flow
# ---------------------------------------------------------------------------

class TestPipelineRun:
    async def test_returns_research_session(self):
        pipeline = _make_pipeline()
        result = await pipeline.run(company_website="https://acme.com")

        assert isinstance(result, ResearchSession)

    async def test_session_status_completed(self):
        pipeline = _make_pipeline()
        result = await pipeline.run(company_website="https://acme.com")

        assert result.status == "completed"

    async def test_icp_definition_populated(self):
        icp = _make_icp(industries=["Insurance"])
        pipeline = _make_pipeline(icp=icp)

        result = await pipeline.run(company_website="https://acme.com")

        assert result.icp_definition is not None
        assert result.icp_definition.industries == ["Insurance"]

    async def test_ranked_companies_populated(self):
        ranked = [_make_ranked("a.com"), _make_ranked("b.com")]
        pipeline = _make_pipeline(ranked=ranked)

        result = await pipeline.run(company_website="https://acme.com")

        assert result.ranked_companies is not None
        assert len(result.ranked_companies) == 2

    async def test_candidate_companies_populated(self):
        companies = [_make_profile("a.com"), _make_profile("b.com")]
        pipeline = _make_pipeline(companies=companies)

        result = await pipeline.run(company_website="https://acme.com")

        assert result.candidate_companies is not None
        assert len(result.candidate_companies) == 2

    async def test_company_website_stored_in_session(self):
        pipeline = _make_pipeline()
        result = await pipeline.run(company_website="https://acme.com")

        assert result.company_website == "https://acme.com"

    async def test_icp_interpreter_called_with_target_description(self):
        pipeline = _make_pipeline()
        await pipeline.run(
            company_website="https://acme.com",
            target_description="fintech companies in the US",
        )

        pipeline.icp_interpreter.interpret.assert_called_once()
        call_kwargs = pipeline.icp_interpreter.interpret.call_args[1]
        assert call_kwargs.get("target") == "fintech companies in the US"

    async def test_scorer_called_with_candidates_and_icp(self):
        pipeline = _make_pipeline()
        await pipeline.run(company_website="https://acme.com")

        pipeline.scoring_engine.score.assert_called_once()

    async def test_contact_agent_called_with_ranked_companies(self):
        pipeline = _make_pipeline()
        await pipeline.run(company_website="https://acme.com")

        pipeline.contact_agent.run.assert_called_once()

    async def test_db_snapshot_saved_for_each_ranked_company(self):
        ranked = [_make_ranked("a.com"), _make_ranked("b.com"), _make_ranked("c.com")]
        pipeline = _make_pipeline(ranked=ranked)

        result = await pipeline.run(company_website="https://acme.com")

        assert pipeline.db.save_signal_snapshot.call_count == 3
        # Verify session_id and rc are passed (not just rc alone)
        call_args = pipeline.db.save_signal_snapshot.call_args_list[0]
        assert call_args[0][0] == result.id  # first positional arg is session_id


# ---------------------------------------------------------------------------
# Mode B — rank-only (lead_list provided)
# ---------------------------------------------------------------------------

class TestRankOnlyMode:
    async def test_lead_list_uses_enrich_domains_not_discover(self):
        pipeline = _make_pipeline()
        lead_list = [{"domain": "a.com"}, {"domain": "b.com"}]

        await pipeline.run(
            company_website="https://acme.com",
            lead_list=lead_list,
        )

        pipeline.company_discoverer.enrich_domains.assert_called_once()
        pipeline.company_discoverer.discover.assert_not_called()

    async def test_no_lead_list_uses_discover(self):
        pipeline = _make_pipeline()
        await pipeline.run(company_website="https://acme.com")

        pipeline.company_discoverer.discover.assert_called_once()
        pipeline.company_discoverer.enrich_domains.assert_not_called()

    async def test_lead_list_domains_extracted_and_passed(self):
        pipeline = _make_pipeline()
        lead_list = [{"domain": "a.com"}, {"domain": "b.com"}]

        await pipeline.run(
            company_website="https://acme.com",
            lead_list=lead_list,
        )

        call_args = pipeline.company_discoverer.enrich_domains.call_args[0][0]
        assert set(call_args) == {"a.com", "b.com"}


# ---------------------------------------------------------------------------
# list_size slicing
# ---------------------------------------------------------------------------

def _make_pipeline_passthrough(ranked: list) -> Pipeline:
    """Pipeline where contact agent echoes back whatever it receives (preserves slice)."""
    mock_icp_interp = MagicMock()
    mock_icp_interp.interpret = AsyncMock(return_value=_make_icp())
    mock_discoverer = MagicMock()
    mock_discoverer.discover = AsyncMock(return_value=[_make_profile("acme.com")])
    mock_scorer = MagicMock()
    mock_scorer.score = MagicMock(return_value=ranked)
    mock_contact_agent = MagicMock()
    mock_contact_agent.run = AsyncMock(side_effect=lambda companies: companies)
    mock_db = MagicMock()
    mock_db.save_signal_snapshot = MagicMock()
    return Pipeline(
        icp_interpreter=mock_icp_interp,
        company_discoverer=mock_discoverer,
        scoring_engine=mock_scorer,
        contact_agent=mock_contact_agent,
        db=mock_db,
    )


class TestListSizeSlicing:
    async def test_list_size_limits_ranked_output(self):
        ranked = [_make_ranked(f"{i}.com") for i in range(10)]
        pipeline = _make_pipeline_passthrough(ranked)

        result = await pipeline.run(company_website="https://acme.com", list_size=3)

        assert len(result.ranked_companies) == 3

    async def test_list_size_default_20_applied(self):
        ranked = [_make_ranked(f"{i}.com") for i in range(30)]
        pipeline = _make_pipeline_passthrough(ranked)

        result = await pipeline.run(company_website="https://acme.com")

        assert len(result.ranked_companies) <= 20

    async def test_list_size_larger_than_results_returns_all(self):
        ranked = [_make_ranked("a.com"), _make_ranked("b.com")]
        pipeline = _make_pipeline_passthrough(ranked)

        result = await pipeline.run(company_website="https://acme.com", list_size=50)

        assert len(result.ranked_companies) == 2

    async def test_db_snapshots_only_for_sliced_list(self):
        ranked = [_make_ranked(f"{i}.com") for i in range(10)]
        pipeline = _make_pipeline_passthrough(ranked)

        await pipeline.run(company_website="https://acme.com", list_size=4)

        assert pipeline.db.save_signal_snapshot.call_count == 4


# ---------------------------------------------------------------------------
# export_to_csv
# ---------------------------------------------------------------------------

class TestExportToCsv:
    def test_creates_file_at_path(self, tmp_path):
        session = ResearchSession(
            company_website="https://acme.com",
            status="completed",
            ranked_companies=[_make_ranked("acme.com")],
        )
        output = str(tmp_path / "out.csv")

        export_to_csv(session, output)

        assert os.path.exists(output)

    def test_csv_has_expected_columns(self, tmp_path):
        session = ResearchSession(
            company_website="https://acme.com",
            status="completed",
            ranked_companies=[_make_ranked("acme.com")],
        )
        output = str(tmp_path / "out.csv")
        export_to_csv(session, output)

        with open(output) as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames

        for col in ["company_name", "domain", "tier", "score", "why_now"]:
            assert col in headers

    def test_csv_row_contains_company_data(self, tmp_path):
        ranked = _make_ranked("acme.com", tier="Tier 1", score=82.0)
        session = ResearchSession(
            company_website="https://acme.com",
            status="completed",
            ranked_companies=[ranked],
        )
        output = str(tmp_path / "out.csv")
        export_to_csv(session, output)

        with open(output) as f:
            rows = list(csv.DictReader(f))

        assert len(rows) == 1
        assert rows[0]["domain"] == "acme.com"
        assert rows[0]["tier"] == "Tier 1"
        assert rows[0]["score"] == "82.0"

    def test_contacts_flattened_into_csv_columns(self, tmp_path):
        ranked = _make_ranked("acme.com")
        ranked.contacts = [
            _make_contact("ceo@acme.com"),
            _make_contact("coo@acme.com"),
        ]
        session = ResearchSession(
            company_website="https://acme.com",
            status="completed",
            ranked_companies=[ranked],
        )
        output = str(tmp_path / "out.csv")
        export_to_csv(session, output)

        with open(output) as f:
            rows = list(csv.DictReader(f))

        assert rows[0]["contact_1_email"] == "ceo@acme.com"
        assert rows[0]["contact_2_email"] == "coo@acme.com"

    def test_returns_output_path(self, tmp_path):
        session = ResearchSession(
            company_website="https://acme.com",
            status="completed",
            ranked_companies=[],
        )
        output = str(tmp_path / "out.csv")

        result = export_to_csv(session, output)

        assert result == output

    def test_empty_ranked_companies_writes_header_only(self, tmp_path):
        session = ResearchSession(
            company_website="https://acme.com",
            status="completed",
            ranked_companies=[],
        )
        output = str(tmp_path / "out.csv")
        export_to_csv(session, output)

        with open(output) as f:
            rows = list(csv.DictReader(f))

        assert rows == []

    def test_location_includes_city_and_country(self, tmp_path):
        ranked = _make_ranked("acme.com")
        ranked.company.hq_location = "New York"
        ranked.company.hq_country = "US"
        session = ResearchSession(
            company_website="https://acme.com",
            status="completed",
            ranked_companies=[ranked],
        )
        output = str(tmp_path / "out.csv")
        export_to_csv(session, output)

        with open(output) as f:
            rows = list(csv.DictReader(f))

        assert rows[0]["location"] == "New York, US"

    def test_location_country_only_when_no_city(self, tmp_path):
        ranked = _make_ranked("acme.com")
        ranked.company.hq_location = None
        ranked.company.hq_country = "US"
        session = ResearchSession(
            company_website="https://acme.com",
            status="completed",
            ranked_companies=[ranked],
        )
        output = str(tmp_path / "out.csv")
        export_to_csv(session, output)

        with open(output) as f:
            rows = list(csv.DictReader(f))

        assert rows[0]["location"] == "US"
