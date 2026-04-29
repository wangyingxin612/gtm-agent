"""
HunterClient — thin async wrapper around the Hunter.io API.

Endpoints used:
  GET /v2/discover           → candidate company list (free, no credits)
  GET /v2/companies/enrich   → tech stack, funding, revenue (0.2 credits each)
  GET /v2/domain-search      → contacts at a domain (1 credit / 10 emails)

All methods accept an optional `client: httpx.AsyncClient` for testability.
If not supplied, a fresh client is created and closed within the method.
"""

import asyncio
import uuid
from datetime import date, datetime
from typing import Dict, List, Optional

import httpx

from src.models.company import AgentContribution, CompanyProfile
from src.models.contact import Contact
from src.models.icp import ICPDefinition

BASE_URL = "https://api.hunter.io/v2"

# Spec Section 6.4.4 — fixed Hunter headcount buckets and their midpoints
HUNTER_BUCKETS = [
    "1-10", "11-50", "51-200", "201-500",
    "501-1000", "1001-5000", "5001-10000", "10001+",
]
BUCKET_RANGES = [
    (1, 10), (11, 50), (51, 200), (201, 500),
    (501, 1000), (1001, 5000), (5001, 10000), (10001, 9_999_999),
]
BUCKET_MIDPOINTS: Dict[str, int] = {
    "1-10": 5,
    "11-50": 30,
    "51-200": 125,
    "201-500": 350,
    "501-1000": 750,
    "1001-5000": 3000,
    "5001-10000": 7500,
    "10001+": 10001,
}

MIN_CONTACT_CONFIDENCE = 70


def _map_size_to_buckets(size_min: int, size_max: int) -> List[str]:
    """Return Hunter bucket labels that overlap with [size_min, size_max]."""
    return [
        HUNTER_BUCKETS[i]
        for i, (lo, hi) in enumerate(BUCKET_RANGES)
        if lo <= size_max and hi >= size_min
    ]


def _domain_id(domain: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, domain))


class HunterClient:
    """Async client for Hunter.io API. Inject api_key at construction time."""

    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("api_key is required and must be non-empty")
        self.api_key = api_key

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def discover_companies(
        self,
        icp: ICPDefinition,
        limit: int = 100,
        client: Optional[httpx.AsyncClient] = None,
    ) -> List[CompanyProfile]:
        """Fetch candidate companies matching the ICP from Hunter Discover."""
        params = self._build_discover_params(icp, limit)
        response = await self._get_with_retry(
            f"{BASE_URL}/discover", params, client or httpx.AsyncClient()
        )
        companies = response.json().get("data", [])
        return [self._company_from_discover(c) for c in companies]

    async def enrich_company(
        self,
        domain: str,
        client: Optional[httpx.AsyncClient] = None,
    ) -> Optional[CompanyProfile]:
        """Fetch enrichment data (tech stack, funding, revenue) for a domain."""
        params = {"domain": domain, "api_key": self.api_key}
        response = await self._get_with_retry(
            f"{BASE_URL}/companies/enrich", params, client or httpx.AsyncClient()
        )
        if response.status_code == 404:
            return None
        data = response.json().get("data", {})
        return self._company_from_enrich(domain, data)

    async def domain_search(
        self,
        domain: str,
        config: dict,
        client: Optional[httpx.AsyncClient] = None,
    ) -> List[Contact]:
        """Find contacts at a domain, filtered to confidence ≥ 70."""
        seniorities = ",".join(config.get("target_seniorities", []))
        departments = ",".join(config.get("target_departments", []))
        params: dict = {
            "domain": domain,
            "type": "personal",
            "api_key": self.api_key,
        }
        if seniorities:
            params["seniority"] = seniorities
        if departments:
            params["department"] = departments

        response = await self._get_with_retry(
            f"{BASE_URL}/domain-search", params, client or httpx.AsyncClient()
        )
        emails = response.json().get("data", {}).get("emails", [])
        return [
            self._contact_from_email(e)
            for e in emails
            if e.get("confidence", 0) >= MIN_CONTACT_CONFIDENCE
        ]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_with_retry(
        self,
        url: str,
        params: dict,
        client: httpx.AsyncClient,
        max_retries: int = 3,
    ) -> httpx.Response:
        for attempt in range(max_retries + 1):
            response = await client.get(url, params=params)
            if response.status_code != 429:
                return response
            if attempt < max_retries:
                await asyncio.sleep(2 ** attempt)
        raise RuntimeError(
            f"Hunter API rate limit (429) exceeded after {max_retries} retries on {url}"
        )

    def _build_discover_params(self, icp: ICPDefinition, limit: int) -> dict:
        keywords = list(icp.keywords or []) + list(icp.pain_points or [])
        buckets = _map_size_to_buckets(icp.company_size_min, icp.company_size_max)
        return {
            "api_key": self.api_key,
            "limit": limit,
            "industry": icp.industries,
            "headcount": buckets,
            "headquarters_location": icp.locations,
            "keywords": keywords or None,
        }

    def _company_from_discover(self, data: dict) -> CompanyProfile:
        domain = data["domain"]
        bucket = data.get("headcount")
        emp_count = BUCKET_MIDPOINTS.get(bucket) if bucket else None

        now = datetime.utcnow()
        return CompanyProfile(
            id=_domain_id(domain),
            name=data["name"],
            domain=domain,
            industry=data.get("industry"),
            employee_count=emp_count,
            employee_range=bucket,
            hq_country=data.get("country"),
            hq_location=data.get("city"),
            founded_year=data.get("founded_year"),
            description=data.get("description"),
            linkedin_url=data.get("linkedin_handle"),
            data_source="hunter",
            data_quality="partial",
            last_enriched=now,
            enrichment_confidence=0.7,
            agent_contributions={
                "hunter_discover_v1": AgentContribution(
                    agent_id="hunter_discover_v1",
                    agent_version="1.0",
                    signals_added=[
                        "domain", "name", "industry", "employee_range",
                        "hq_country", "hq_location", "description",
                    ],
                    confidence=0.7,
                    timestamp=now,
                )
            },
        )

    def _company_from_enrich(self, domain: str, data: dict) -> CompanyProfile:
        funding = data.get("funding") or {}
        funding_date: Optional[date] = None
        raw_date = funding.get("date")
        if raw_date:
            try:
                funding_date = date.fromisoformat(raw_date)
            except ValueError:
                pass

        now = datetime.utcnow()
        return CompanyProfile(
            id=_domain_id(domain),
            name=data.get("name", domain),
            domain=domain,
            tech_stack=data.get("tech_stack"),
            funding_series=funding.get("series"),
            funding_amount=funding.get("amount"),
            funding_date=funding_date,
            revenue_range=data.get("revenue"),
            employee_count=data.get("employee_count"),
            data_source="hunter",
            data_quality="full",
            last_enriched=now,
            enrichment_confidence=0.9,
            agent_contributions={
                "hunter_enrich_v1": AgentContribution(
                    agent_id="hunter_enrich_v1",
                    agent_version="1.0",
                    signals_added=[
                        "tech_stack", "funding_series", "funding_amount",
                        "funding_date", "revenue_range", "employee_count",
                    ],
                    confidence=0.9,
                    timestamp=now,
                )
            },
        )

    def _contact_from_email(self, data: dict) -> Contact:
        first = data.get("first_name", "")
        last = data.get("last_name", "")
        confidence = data.get("confidence", 0)
        verification_status = (data.get("verification") or {}).get("status", "")

        if verification_status == "valid":
            email_confidence = "verified"
        elif confidence >= MIN_CONTACT_CONFIDENCE:
            email_confidence = "likely"
        else:
            email_confidence = None

        return Contact(
            id=str(uuid.uuid4()),
            first_name=first,
            last_name=last,
            full_name=f"{first} {last}".strip(),
            title=data.get("position", ""),
            seniority=data.get("seniority", ""),
            department=data.get("department", ""),
            email=data.get("value"),
            email_confidence=email_confidence,
            linkedin_url=data.get("linkedin"),
            data_source="hunter_domain_search",
        )
