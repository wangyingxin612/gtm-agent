"""
TDD tests for src/agents/contact_discovery.py.
All HunterClient calls are mocked — no real API calls ever made.
"""
import logging
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.models.company import CompanyProfile, RankedCompany, ScoreBreakdown
from src.models.contact import Contact
from src.agents.contact_discovery import ContactDiscoveryAgent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "target_seniorities": ["c_suite", "vp", "director"],
    "target_departments": ["management", "operations", "legal"],
    "max_contacts_per_company": 3,
    "max_contacts_searched_per_company": 10,
    "search_tiers": ["Tier 1", "Tier 2"],
}


def _make_profile(domain: str) -> CompanyProfile:
    return CompanyProfile(
        id=str(uuid.uuid4()),
        name=domain,
        domain=domain,
        data_source="hunter",
        last_enriched=datetime.now(timezone.utc),
        enrichment_confidence=0.9,
    )


def _make_ranked(domain: str, tier: str = "Tier 1") -> RankedCompany:
    return RankedCompany(
        company=_make_profile(domain),
        total_score=75.0,
        tier=tier,
        score_breakdown=ScoreBreakdown(
            firmographic_score=20.0,
            keyword_score=15.0,
            growth_score=10.0,
            timing_score=10.0,
            lookalike_score=5.0,
        ),
        reasoning_summary="Good fit",
    )


def _make_contact(
    email: str = "jane@example.com",
    seniority: str = "director",
    email_confidence: str = "verified",
) -> Contact:
    return Contact(
        id=str(uuid.uuid4()),
        first_name="Jane",
        last_name="Smith",
        full_name="Jane Smith",
        title="VP of Operations",
        seniority=seniority,
        department="management",
        email=email,
        email_confidence=email_confidence,
        data_source="hunter_domain_search",
    )


@pytest.fixture
def mock_hunter():
    m = MagicMock()
    m.domain_search = AsyncMock(return_value=[])
    return m


@pytest.fixture
def agent(mock_hunter):
    return ContactDiscoveryAgent(hunter_client=mock_hunter, config=DEFAULT_CONFIG)


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------

class TestConstructor:
    def test_raises_without_hunter_client(self):
        with pytest.raises((TypeError, ValueError)):
            ContactDiscoveryAgent(hunter_client=None, config=DEFAULT_CONFIG)

    def test_stores_client_and_config(self, mock_hunter):
        a = ContactDiscoveryAgent(hunter_client=mock_hunter, config=DEFAULT_CONFIG)
        assert a.hunter_client is mock_hunter
        assert a.config == DEFAULT_CONFIG


# ---------------------------------------------------------------------------
# run() — tier filtering
# ---------------------------------------------------------------------------

class TestTierFiltering:
    async def test_tier1_company_gets_contact_search(self, agent, mock_hunter):
        companies = [_make_ranked("acme.com", tier="Tier 1")]
        await agent.run(companies)

        mock_hunter.domain_search.assert_called_once()

    async def test_tier2_company_gets_contact_search(self, agent, mock_hunter):
        companies = [_make_ranked("acme.com", tier="Tier 2")]
        await agent.run(companies)

        mock_hunter.domain_search.assert_called_once()

    async def test_tier3_company_skipped(self, agent, mock_hunter):
        companies = [_make_ranked("acme.com", tier="Tier 3")]
        await agent.run(companies)

        mock_hunter.domain_search.assert_not_called()

    async def test_excluded_company_skipped(self, agent, mock_hunter):
        companies = [_make_ranked("acme.com", tier="excluded")]
        await agent.run(companies)

        mock_hunter.domain_search.assert_not_called()

    async def test_mixed_tiers_only_eligible_searched(self, agent, mock_hunter):
        companies = [
            _make_ranked("t1.com", tier="Tier 1"),
            _make_ranked("t2.com", tier="Tier 2"),
            _make_ranked("t3.com", tier="Tier 3"),
            _make_ranked("ex.com", tier="excluded"),
        ]
        await agent.run(companies)

        assert mock_hunter.domain_search.call_count == 2


# ---------------------------------------------------------------------------
# run() — output shape
# ---------------------------------------------------------------------------

class TestOutputShape:
    async def test_returns_same_number_of_companies(self, agent, mock_hunter):
        companies = [_make_ranked(f"c{i}.com") for i in range(5)]
        result = await agent.run(companies)

        assert len(result) == 5

    async def test_contacts_attached_to_company(self, agent, mock_hunter):
        contact = _make_contact()
        mock_hunter.domain_search.return_value = [contact]
        companies = [_make_ranked("acme.com")]

        result = await agent.run(companies)

        assert result[0].contacts == [contact]

    async def test_tier3_company_contacts_unchanged(self, agent, mock_hunter):
        companies = [_make_ranked("t3.com", tier="Tier 3")]
        result = await agent.run(companies)

        assert result[0].contacts is None

    async def test_no_contacts_found_sets_empty_list(self, agent, mock_hunter):
        mock_hunter.domain_search.return_value = []
        companies = [_make_ranked("acme.com")]

        result = await agent.run(companies)

        assert result[0].contacts == []


# ---------------------------------------------------------------------------
# Failure isolation
# ---------------------------------------------------------------------------

class TestFailureIsolation:
    async def test_known_failure_logs_warning_with_domain(self, agent, mock_hunter, caplog):
        mock_hunter.domain_search.side_effect = RuntimeError("rate limit exceeded")

        with caplog.at_level(logging.WARNING, logger="src.agents.contact_discovery"):
            await agent.run([_make_ranked("acme.com")])

        assert any(
            r.levelno == logging.WARNING and "acme.com" in r.getMessage()
            and "rate limit exceeded" in r.getMessage()
            for r in caplog.records
        )

    async def test_unexpected_failure_logs_traceback_but_keeps_company(
        self, agent, mock_hunter, caplog
    ):
        mock_hunter.domain_search.side_effect = KeyError("emails")

        with caplog.at_level(logging.WARNING, logger="src.agents.contact_discovery"):
            result = await agent.run([_make_ranked("acme.com")])

        assert len(result) == 1 and result[0].contacts == []
        errors = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert errors and errors[0].exc_info is not None

    async def test_domain_search_exception_does_not_drop_company(self, agent, mock_hunter):
        mock_hunter.domain_search.side_effect = Exception("Hunter API down")
        companies = [_make_ranked("acme.com")]

        result = await agent.run(companies)

        assert len(result) == 1
        assert result[0].contacts == []

    async def test_one_failure_does_not_affect_other_companies(self, agent, mock_hunter):
        good_contact = _make_contact()
        mock_hunter.domain_search.side_effect = [
            Exception("timeout"),
            [good_contact],
        ]
        companies = [
            _make_ranked("fail.com", tier="Tier 1"),
            _make_ranked("good.com", tier="Tier 1"),
        ]

        result = await agent.run(companies)

        fail_result = next(r for r in result if r.company.domain == "fail.com")
        good_result = next(r for r in result if r.company.domain == "good.com")
        assert fail_result.contacts == []
        assert good_result.contacts == [good_contact]


# ---------------------------------------------------------------------------
# Contact ranking
# ---------------------------------------------------------------------------

class TestContactRanking:
    async def test_c_suite_ranked_above_director(self, agent, mock_hunter):
        director = _make_contact(email="dir@a.com", seniority="director")
        ceo = _make_contact(email="ceo@a.com", seniority="c_suite")
        mock_hunter.domain_search.return_value = [director, ceo]
        companies = [_make_ranked("a.com")]

        result = await agent.run(companies)

        assert result[0].contacts[0].seniority == "c_suite"

    async def test_vp_ranked_above_director(self, agent, mock_hunter):
        director = _make_contact(email="dir@a.com", seniority="director")
        vp = _make_contact(email="vp@a.com", seniority="vp")
        mock_hunter.domain_search.return_value = [director, vp]
        companies = [_make_ranked("a.com")]

        result = await agent.run(companies)

        assert result[0].contacts[0].seniority == "vp"

    async def test_verified_ranked_above_likely_at_same_seniority(self, agent, mock_hunter):
        likely = _make_contact(email="l@a.com", seniority="director", email_confidence="likely")
        verified = _make_contact(email="v@a.com", seniority="director", email_confidence="verified")
        mock_hunter.domain_search.return_value = [likely, verified]
        companies = [_make_ranked("a.com")]

        result = await agent.run(companies)

        assert result[0].contacts[0].email_confidence == "verified"

    async def test_max_contacts_per_company_respected(self, agent, mock_hunter):
        contacts = [_make_contact(email=f"c{i}@a.com") for i in range(8)]
        mock_hunter.domain_search.return_value = contacts
        companies = [_make_ranked("a.com")]

        result = await agent.run(companies)

        assert len(result[0].contacts) == 3  # DEFAULT_CONFIG max is 3


# ---------------------------------------------------------------------------
# contact_confidence population
# ---------------------------------------------------------------------------

class TestContactConfidence:
    async def test_all_verified_sets_high_confidence(self, agent, mock_hunter):
        contacts = [
            _make_contact(email="a@x.com", email_confidence="verified"),
            _make_contact(email="b@x.com", email_confidence="verified"),
        ]
        mock_hunter.domain_search.return_value = contacts
        companies = [_make_ranked("x.com")]

        result = await agent.run(companies)

        assert result[0].contact_confidence == "high"

    async def test_any_likely_sets_low_confidence(self, agent, mock_hunter):
        contacts = [
            _make_contact(email="a@x.com", email_confidence="verified"),
            _make_contact(email="b@x.com", email_confidence="likely"),
        ]
        mock_hunter.domain_search.return_value = contacts
        companies = [_make_ranked("x.com")]

        result = await agent.run(companies)

        assert result[0].contact_confidence == "low"

    async def test_no_contacts_leaves_confidence_none(self, agent, mock_hunter):
        mock_hunter.domain_search.return_value = []
        companies = [_make_ranked("x.com")]

        result = await agent.run(companies)

        assert result[0].contact_confidence is None

    async def test_failed_search_leaves_confidence_none(self, agent, mock_hunter):
        mock_hunter.domain_search.side_effect = RuntimeError("API error")
        companies = [_make_ranked("x.com")]

        result = await agent.run(companies)

        assert result[0].contact_confidence is None
