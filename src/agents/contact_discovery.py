"""
ContactDiscoveryAgent — finds and ranks contacts for Tier 1/2 companies.

Isolated agent: no knowledge of ICP, scoring, or session state.
Contact discovery failure for any company never drops that company from output.

Ranking priority:
  1. Seniority (c_suite > vp > director > manager > other)
  2. Email confidence (verified > likely > None)
"""

import asyncio
from typing import List

from src.data_providers.hunter_client import HunterClient
from src.models.company import RankedCompany
from src.models.contact import Contact

_SENIORITY_RANK = {
    "c_suite": 0,
    "vp": 1,
    "director": 2,
    "manager": 3,
}

_CONFIDENCE_RANK = {
    "verified": 0,
    "likely": 1,
    None: 2,
}

_SEARCH_TIERS = {"Tier 1", "Tier 2"}


def _contact_sort_key(c: Contact):
    return (
        _SENIORITY_RANK.get(c.seniority, 99),
        _CONFIDENCE_RANK.get(c.email_confidence, 2),
    )


class ContactDiscoveryAgent:
    """Enriches a ranked company list with contacts from Hunter Domain Search."""

    def __init__(self, hunter_client: HunterClient, config: dict):
        if hunter_client is None:
            raise ValueError("hunter_client is required")
        self.hunter_client = hunter_client
        self.config = config
        self._max_contacts = config.get("max_contacts_per_company", 3)
        self._search_tiers = set(config.get("search_tiers", ["Tier 1", "Tier 2"]))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(self, companies: List[RankedCompany]) -> List[RankedCompany]:
        """Entry point: attach contacts to Tier 1/2 companies, return all companies."""
        eligible = [rc for rc in companies if rc.tier in self._search_tiers]
        skip = [rc for rc in companies if rc.tier not in self._search_tiers]

        enriched = await asyncio.gather(
            *[self._find_contacts(rc) for rc in eligible]
        )

        enriched_by_domain = {rc.company.domain: rc for rc in enriched}
        return [
            enriched_by_domain.get(rc.company.domain, rc)
            for rc in companies
        ]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _find_contacts(self, rc: RankedCompany) -> RankedCompany:
        """Fetch, rank, and attach contacts; failures return company with contacts=[]."""
        try:
            contacts: List[Contact] = await self.hunter_client.domain_search(
                rc.company.domain, self.config
            )
        except Exception:
            rc.contacts = []
            return rc

        ranked = sorted(contacts, key=_contact_sort_key)
        rc.contacts = ranked[: self._max_contacts]
        if rc.contacts:
            all_verified = all(c.email_confidence == "verified" for c in rc.contacts)
            rc.contact_confidence = "high" if all_verified else "low"
        return rc
