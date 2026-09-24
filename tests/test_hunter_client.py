"""
TDD tests for src/data_providers/hunter_client.py.
All HTTP calls are mocked — no real API calls ever made.
"""
import asyncio
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.company import CompanyProfile
from src.models.contact import Contact
from src.models.icp import ICPDefinition
from src.data_providers.hunter_client import HunterClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_icp(**kwargs) -> ICPDefinition:
    defaults = dict(
        industries=["Financial Services"],
        company_size_min=50,
        company_size_max=1000,
        locations=["US"],
        interpretation_confidence=0.9,
    )
    return ICPDefinition(**{**defaults, **kwargs})


def _mock_response(status_code: int, body: dict) -> MagicMock:
    m = MagicMock()
    m.status_code = status_code
    m.json.return_value = body
    return m


def _discover_resp(companies: list) -> MagicMock:
    return _mock_response(200, {"data": companies})


def _enrich_resp(data: dict) -> MagicMock:
    return _mock_response(200, {"data": data})


def _domain_search_resp(emails: list) -> MagicMock:
    return _mock_response(200, {"data": {"emails": emails}})


SAMPLE_COMPANY = {
    "domain": "acme.com",
    "name": "Acme Corp",
    "headcount": "201-500",
    "industry": "Financial Services",
    "country": "US",
    "city": "New York",
    "description": "compliance and operations platform",
    "linkedin_handle": "company/acme-corp",
    "founded_year": 2015,
    "tags": ["fintech", "compliance"],
}

SAMPLE_ENRICH = {
    "tech_stack": ["Salesforce", "Workday"],
    "funding": {"series": "Series B", "amount": 25_000_000, "date": "2023-06-15"},
    "revenue": "$10M-$50M",
    "employee_count": 320,
}

SAMPLE_EMAIL = {
    "value": "jane@acme.com",
    "type": "personal",
    "confidence": 88,
    "first_name": "Jane",
    "last_name": "Smith",
    "position": "VP of Operations",
    "seniority": "director",
    "department": "management",
    "linkedin": "https://linkedin.com/in/janesmith",
    "verification": {"status": "valid"},
}


@pytest.fixture
def hunter() -> HunterClient:
    return HunterClient(api_key="test-api-key")


# ---------------------------------------------------------------------------
# discover_companies
# ---------------------------------------------------------------------------

class TestDiscoverCompanies:
    async def test_basic_returns_list_of_company_profiles(self, hunter):
        companies = [SAMPLE_COMPANY, {**SAMPLE_COMPANY, "domain": "beta.com", "name": "Beta"},
                     {**SAMPLE_COMPANY, "domain": "gamma.com", "name": "Gamma"}]
        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=_discover_resp(companies))

        result = await hunter.discover_companies(_make_icp(), client=mock_client)

        assert len(result) == 3
        assert all(isinstance(r, CompanyProfile) for r in result)

    async def test_empty_response_returns_empty_list(self, hunter):
        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=_discover_resp([]))

        result = await hunter.discover_companies(_make_icp(), client=mock_client)
        assert result == []

    async def test_headcount_bucket_maps_to_midpoint_and_range(self, hunter):
        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=_discover_resp([SAMPLE_COMPANY]))

        result = await hunter.discover_companies(_make_icp(), client=mock_client)

        assert result[0].employee_count == 350   # midpoint of "201-500"
        assert result[0].employee_range == "201-500"

    async def test_correct_field_mapping(self, hunter):
        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=_discover_resp([SAMPLE_COMPANY]))

        r = (await hunter.discover_companies(_make_icp(), client=mock_client))[0]

        assert r.domain == "acme.com"
        assert r.name == "Acme Corp"
        assert r.industry == "Financial Services"
        assert r.hq_country == "US"
        assert r.hq_location == "New York"
        assert r.description == "compliance and operations platform"
        assert r.founded_year == 2015

    async def test_missing_optional_fields_produce_none_not_crash(self, hunter):
        minimal = {"domain": "min.com", "name": "Min Corp", "headcount": "11-50",
                   "industry": "Finance", "country": "US"}
        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=_discover_resp([minimal]))

        result = await hunter.discover_companies(_make_icp(), client=mock_client)

        assert len(result) == 1
        r = result[0]
        assert r.hq_location is None
        assert r.description is None
        assert r.linkedin_url is None
        assert r.founded_year is None

    async def test_agent_contributions_hunter_key_set(self, hunter):
        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=_discover_resp([SAMPLE_COMPANY]))

        result = await hunter.discover_companies(_make_icp(), client=mock_client)

        assert "hunter_discover_v1" in result[0].agent_contributions


# ---------------------------------------------------------------------------
# enrich_company
# ---------------------------------------------------------------------------

class TestEnrichCompany:
    async def test_success_returns_profile_with_enrichment_fields(self, hunter):
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=_enrich_resp(SAMPLE_ENRICH))

        result = await hunter.enrich_company("acme.com", client=mock_client)

        assert result is not None
        assert result.tech_stack == ["Salesforce", "Workday"]
        assert result.funding_series == "Series B"
        assert result.funding_amount == 25_000_000
        assert result.funding_date == date(2023, 6, 15)
        assert result.revenue_range == "$10M-$50M"
        assert result.employee_count == 320

    async def test_not_found_returns_none(self, hunter):
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=_mock_response(404, {}))

        result = await hunter.enrich_company("notfound.com", client=mock_client)
        assert result is None

    async def test_non_404_error_raises_not_returns_garbage(self, hunter):
        import httpx
        resp = _mock_response(401, {"errors": [{"details": "Invalid API key"}]})
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "401 Unauthorized", request=MagicMock(), response=MagicMock()
        )
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=resp)

        with pytest.raises(httpx.HTTPStatusError):
            await hunter.enrich_company("acme.com", client=mock_client)

    async def test_missing_funding_does_not_crash(self, hunter):
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=_enrich_resp({
            "tech_stack": ["Salesforce"],
            "revenue": "$1M-$10M",
        }))

        result = await hunter.enrich_company("partial.com", client=mock_client)

        assert result is not None
        assert result.funding_series is None
        assert result.funding_date is None


# ---------------------------------------------------------------------------
# domain_search
# ---------------------------------------------------------------------------

class TestDomainSearch:
    async def test_returns_contacts_with_correct_field_mapping(self, hunter):
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=_domain_search_resp([SAMPLE_EMAIL]))

        config = {"target_seniorities": ["director"], "target_departments": ["management"]}
        result = await hunter.domain_search("acme.com", config, client=mock_client)

        assert len(result) == 1
        c = result[0]
        assert isinstance(c, Contact)
        assert c.first_name == "Jane"
        assert c.last_name == "Smith"
        assert c.full_name == "Jane Smith"
        assert c.title == "VP of Operations"
        assert c.email == "jane@acme.com"
        assert c.email_confidence == "verified"
        assert c.linkedin_url == "https://linkedin.com/in/janesmith"
        assert c.data_source == "hunter_domain_search"
        assert c.seniority == "director"
        assert c.department == "management"

    async def test_filters_out_low_confidence_contacts(self, hunter):
        low_conf = {**SAMPLE_EMAIL, "value": "low@acme.com", "confidence": 65,
                    "verification": {"status": "risky"}}
        high_conf = {**SAMPLE_EMAIL, "value": "high@acme.com", "confidence": 90}
        mock_client = MagicMock()
        mock_client.get = AsyncMock(
            return_value=_domain_search_resp([low_conf, high_conf])
        )

        config = {}
        result = await hunter.domain_search("acme.com", config, client=mock_client)

        assert len(result) == 1
        assert result[0].email == "high@acme.com"

    async def test_empty_emails_returns_empty_list(self, hunter):
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=_domain_search_resp([]))

        result = await hunter.domain_search("acme.com", {}, client=mock_client)
        assert result == []

    async def test_unverified_high_confidence_gets_likely(self, hunter):
        unverified = {**SAMPLE_EMAIL, "verification": {"status": "risky"}, "confidence": 75}
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=_domain_search_resp([unverified]))

        result = await hunter.domain_search("acme.com", {}, client=mock_client)

        assert len(result) == 1
        assert result[0].email_confidence == "likely"


# ---------------------------------------------------------------------------
# Retry logic
# ---------------------------------------------------------------------------

class TestRetryBehavior:
    async def test_retries_on_429_and_succeeds(self, hunter):
        mock_client = MagicMock()
        resp_429 = _mock_response(429, {})
        resp_200 = _discover_resp([SAMPLE_COMPANY])
        mock_client.post = AsyncMock(side_effect=[resp_429, resp_200])

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await hunter.discover_companies(_make_icp(), client=mock_client)

        assert mock_sleep.called
        assert len(result) == 1

    async def test_raises_after_all_retries_exhausted(self, hunter):
        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=_mock_response(429, {}))

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(Exception, match="[Rr]ate limit|429"):
                await hunter.discover_companies(_make_icp(), client=mock_client)


# ---------------------------------------------------------------------------
# Concurrency limiting
# ---------------------------------------------------------------------------

class TestConcurrencyLimit:
    async def test_in_flight_requests_capped_at_max_concurrency(self):
        hunter = HunterClient(api_key="test-api-key", max_concurrency=3)
        in_flight = 0
        peak = 0

        async def slow_get(url, params=None):
            nonlocal in_flight, peak
            in_flight += 1
            peak = max(peak, in_flight)
            await asyncio.sleep(0.01)
            in_flight -= 1
            return _mock_response(404, {})

        mock_client = MagicMock()
        mock_client.get = slow_get

        await asyncio.gather(
            *[hunter.enrich_company(f"{i}.com", client=mock_client) for i in range(10)]
        )

        assert peak == 3

    def test_rejects_non_positive_max_concurrency(self):
        with pytest.raises(ValueError, match="max_concurrency"):
            HunterClient(api_key="test-api-key", max_concurrency=0)


# ---------------------------------------------------------------------------
# Constructor validation
# ---------------------------------------------------------------------------

class TestConstructor:
    def test_raises_value_error_for_empty_api_key(self):
        with pytest.raises(ValueError, match="api_key"):
            HunterClient(api_key="")

    def test_raises_value_error_for_none_api_key(self):
        with pytest.raises((ValueError, TypeError)):
            HunterClient(api_key=None)

    def test_valid_api_key_does_not_raise(self):
        client = HunterClient(api_key="valid-key")
        assert client.api_key == "valid-key"
