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
import logging
from typing import List, Optional

from src.data_providers.hunter_client import HunterClient
from src.models.company import CompanyProfile
from src.models.icp import ICPDefinition

logger = logging.getLogger(__name__)


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
        """Mode B: user-supplied domains → enrich → list (failures excluded)."""
        if not domains:
            return []

        results = await asyncio.gather(
            *[self.hunter_client.enrich_company(d) for d in domains],
            return_exceptions=True,
        )
        profiles = []
        for domain, result in zip(domains, results):
            if isinstance(result, Exception):
                logger.warning("enrich failed for %s: %s", domain, result)
            elif result is not None:
                profiles.append(result)
        return profiles

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _enrich_or_keep(self, partial: CompanyProfile) -> CompanyProfile:
        """Enrich a domain; on 404 or any error, return the partial profile."""
        try:
            full = await self.hunter_client.enrich_company(partial.domain)
        except Exception as exc:
            logger.warning("enrich failed for %s: %s — keeping partial profile", partial.domain, exc)
            return partial
        if full is None:
            return partial
        # Merge: carry discover contribution forward onto the enriched profile
        full.agent_contributions.update(partial.agent_contributions)
        return full
