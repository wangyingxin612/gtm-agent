"""
TDD tests for src/agents/company_discoverer.py.
All HunterClient calls are mocked — no real API calls ever made.
"""
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.models.company import AgentContribution, CompanyProfile
from src.models.icp import ICPDefinition
from src.agents.company_discoverer import CompanyDiscoverer


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


def _partial_profile(domain: str, name: str = None) -> CompanyProfile:
    """Simulate what HunterClient.discover_companies() returns (sparse)."""
    now = datetime.utcnow()
    return CompanyProfile(
        id=f"id-{domain}",
        name=name or domain,
        domain=domain,
        data_source="hunter",
        data_quality="partial",
        last_enriched=now,
        enrichment_confidence=0.7,
        agent_contributions={
            "hunter_discover_v1": AgentContribution(
                agent_id="hunter_discover_v1",
                agent_version="1.0",
                signals_added=["domain", "name"],
                confidence=0.7,
                timestamp=now,
            )
        },
    )


def _full_profile(domain: str) -> CompanyProfile:
    """Simulate what HunterClient.enrich_company() returns (full)."""
    now = datetime.utcnow()
    return CompanyProfile(
        id=f"id-{domain}",
        name=f"{domain} Corp",
        domain=domain,
        industry="Financial Services",
        hq_country="US",
        tech_stack=["Salesforce"],
        data_source="hunter",
        data_quality="full",
        last_enriched=now,
        enrichment_confidence=0.9,
        agent_contributions={
            "hunter_enrich_v1": AgentContribution(
                agent_id="hunter_enrich_v1",
                agent_version="1.0",
                signals_added=["industry", "tech_stack"],
                confidence=0.9,
                timestamp=now,
            )
        },
    )


@pytest.fixture
def mock_hunter():
    """A MagicMock that quacks like HunterClient."""
    m = MagicMock()
    m.discover_companies = AsyncMock(return_value=[])
    m.enrich_company = AsyncMock(return_value=None)
    return m


@pytest.fixture
def discoverer(mock_hunter):
    return CompanyDiscoverer(hunter_client=mock_hunter)


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------

class TestConstructor:
    def test_stores_hunter_client(self, mock_hunter):
        d = CompanyDiscoverer(hunter_client=mock_hunter)
        assert d.hunter_client is mock_hunter

    def test_raises_without_hunter_client(self):
        with pytest.raises((TypeError, ValueError)):
            CompanyDiscoverer(hunter_client=None)


# ---------------------------------------------------------------------------
# Mode A — Full Discovery
# ---------------------------------------------------------------------------

class TestDiscoverModeA:
    async def test_returns_list_of_company_profiles(self, discoverer, mock_hunter):
        mock_hunter.discover_companies.return_value = [_partial_profile("acme.com")]
        mock_hunter.enrich_company.return_value = _full_profile("acme.com")

        result = await discoverer.discover(icp=_make_icp())

        assert len(result) == 1
        assert all(isinstance(c, CompanyProfile) for c in result)

    async def test_discover_called_with_icp(self, discoverer, mock_hunter):
        icp = _make_icp()
        await discoverer.discover(icp=icp)

        mock_hunter.discover_companies.assert_called_once()
        call_icp = mock_hunter.discover_companies.call_args[1].get("icp") or \
                   mock_hunter.discover_companies.call_args[0][0]
        assert call_icp is icp

    async def test_enrich_called_for_each_domain(self, discoverer, mock_hunter):
        mock_hunter.discover_companies.return_value = [
            _partial_profile("a.com"),
            _partial_profile("b.com"),
            _partial_profile("c.com"),
        ]
        mock_hunter.enrich_company.return_value = None

        await discoverer.discover(icp=_make_icp())

        assert mock_hunter.enrich_company.call_count == 3

    async def test_enriched_profile_replaces_partial(self, discoverer, mock_hunter):
        mock_hunter.discover_companies.return_value = [_partial_profile("acme.com")]
        full = _full_profile("acme.com")
        mock_hunter.enrich_company.return_value = full

        result = await discoverer.discover(icp=_make_icp())

        assert result[0].data_quality == "full"
        assert result[0].industry == "Financial Services"
        assert result[0].tech_stack == ["Salesforce"]

    async def test_both_agent_contributions_present_after_merge(self, discoverer, mock_hunter):
        mock_hunter.discover_companies.return_value = [_partial_profile("acme.com")]
        mock_hunter.enrich_company.return_value = _full_profile("acme.com")

        result = await discoverer.discover(icp=_make_icp())

        contributions = result[0].agent_contributions
        assert "hunter_discover_v1" in contributions
        assert "hunter_enrich_v1" in contributions

    async def test_enrich_failure_keeps_partial_profile(self, discoverer, mock_hunter):
        partial = _partial_profile("acme.com")
        mock_hunter.discover_companies.return_value = [partial]
        mock_hunter.enrich_company.return_value = None  # 404

        result = await discoverer.discover(icp=_make_icp())

        assert len(result) == 1
        assert result[0].data_quality == "partial"
        assert result[0].domain == "acme.com"

    async def test_empty_discover_returns_empty_list(self, discoverer, mock_hunter):
        mock_hunter.discover_companies.return_value = []

        result = await discoverer.discover(icp=_make_icp())

        assert result == []
        mock_hunter.enrich_company.assert_not_called()


# ---------------------------------------------------------------------------
# Exclude companies filter
# ---------------------------------------------------------------------------

class TestExcludeFilter:
    async def test_exclude_companies_filtered_out(self, discoverer, mock_hunter):
        mock_hunter.discover_companies.return_value = [
            _partial_profile("keep.com"),
            _partial_profile("exclude.com"),
        ]
        mock_hunter.enrich_company.return_value = None

        icp = _make_icp(exclude_companies=["exclude.com"])
        result = await discoverer.discover(icp=icp)

        domains = [c.domain for c in result]
        assert "exclude.com" not in domains
        assert "keep.com" in domains

    async def test_no_exclusions_returns_all(self, discoverer, mock_hunter):
        mock_hunter.discover_companies.return_value = [
            _partial_profile("a.com"),
            _partial_profile("b.com"),
        ]
        mock_hunter.enrich_company.return_value = None

        result = await discoverer.discover(icp=_make_icp())

        assert len(result) == 2

    async def test_exclude_list_is_case_insensitive(self, discoverer, mock_hunter):
        mock_hunter.discover_companies.return_value = [_partial_profile("Acme.COM")]
        mock_hunter.enrich_company.return_value = None

        icp = _make_icp(exclude_companies=["acme.com"])
        result = await discoverer.discover(icp=icp)

        assert result == []


# ---------------------------------------------------------------------------
# Mode B — Rank-Only (user-supplied domain list)
# ---------------------------------------------------------------------------

class TestRankOnlyModeB:
    async def test_enrich_called_for_each_supplied_domain(self, discoverer, mock_hunter):
        domains = ["a.com", "b.com"]
        mock_hunter.enrich_company.side_effect = [
            _full_profile("a.com"),
            _full_profile("b.com"),
        ]

        result = await discoverer.enrich_domains(domains)

        assert mock_hunter.enrich_company.call_count == 2
        assert len(result) == 2

    async def test_discover_not_called_in_rank_only_mode(self, discoverer, mock_hunter):
        mock_hunter.enrich_company.return_value = _full_profile("a.com")

        await discoverer.enrich_domains(["a.com"])

        mock_hunter.discover_companies.assert_not_called()

    async def test_failed_enrich_domain_excluded_from_result(self, discoverer, mock_hunter):
        mock_hunter.enrich_company.side_effect = [
            _full_profile("good.com"),
            None,  # 404 for bad.com
        ]

        result = await discoverer.enrich_domains(["good.com", "bad.com"])

        assert len(result) == 1
        assert result[0].domain == "good.com"

    async def test_empty_domain_list_returns_empty(self, discoverer, mock_hunter):
        result = await discoverer.enrich_domains([])

        assert result == []
        mock_hunter.enrich_company.assert_not_called()
