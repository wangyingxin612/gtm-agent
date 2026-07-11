"""
CompanyDiscoverer — fetches and enriches company candidates via Hunter.io.

Mode A (Full Discovery):
  ICPDefinition → HunterClient.discover_companies() → concurrent enrich → List[CompanyProfile]

Mode B (Rank-Only):
  List[domain] → concurrent enrich → List[CompanyProfile]

Enrichment failures (404) never drop a company; the partial discover profile is kept instead.
Agent contributions from both discover and enrich are merged on the returned profile.
icp.exclude_companies is applied as a post-process filter (Hunter doesn't support it natively).
"""

import asyncio
from typing import List, Optional

from src.data_providers.hunter_client import HunterClient
from src.models.company import CompanyProfile
from src.models.icp import ICPDefinition


class CompanyDiscoverer:
    """Orchestrates Hunter discover + enrich into a clean CompanyProfile list."""

    def __init__(self, hunter_client: HunterClient):
        if hunter_client is None:
            raise ValueError("hunter_client is required")
        self.hunter_client = hunter_client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def discover(self, icp: ICPDefinition) -> List[CompanyProfile]:
        """Mode A: ICP → discover → enrich → filtered list."""
        partials = await self.hunter_client.discover_companies(icp=icp)
        if not partials:
            return []

        exclude = {d.lower() for d in (icp.exclude_companies or [])}
        partials = [p for p in partials if p.domain.lower() not in exclude]

        enriched = await asyncio.gather(
            *[self._enrich_or_keep(p) for p in partials]
        )
        return list(enriched)

    async def enrich_domains(self, domains: List[str]) -> List[CompanyProfile]:
        """Mode B: user-supplied domains → enrich → list (404s excluded)."""
        if not domains:
            return []

        results = await asyncio.gather(
            *[self.hunter_client.enrich_company(d) for d in domains]
        )
        return [r for r in results if r is not None]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _enrich_or_keep(self, partial: CompanyProfile) -> CompanyProfile:
        """Enrich a domain; if 404, return the partial profile unchanged."""
        full = await self.hunter_client.enrich_company(partial.domain)
        if full is None:
            return partial
        # Merge: carry discover contribution forward onto the enriched profile
        full.agent_contributions.update(partial.agent_contributions)
        return full
