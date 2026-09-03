"""
GTM Agent pipeline — main entry point.

run_pipeline() is the convenience function for notebook/CLI use.
Pipeline class accepts injectable agents for testability.

Flow:
  1. ICPInterpreter  : NL description → ICPDefinition
  2. CompanyDiscoverer: ICP → discover+enrich  (Mode A)
                  OR  lead_list → enrich only  (Mode B)
  3. ScoringEngine   : candidates → ranked+tiered list
  4. DB              : write signal_snapshot per company
  5. ContactDiscoveryAgent: Tier 1/2 → contacts
"""

import csv
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.agents.company_discoverer import CompanyDiscoverer
from src.agents.contact_discovery import ContactDiscoveryAgent
from src.agents.icp_interpreter import ICPInterpreter
from src.agents.scoring_engine import ScoringEngine
from src.config import load_scoring_config
from src.data_providers.hunter_client import HunterClient
from src.models.session import ResearchSession

_CSV_COLUMNS = [
    "company_name", "domain", "industry", "employee_range", "location",
    "tier", "score", "why_now",
    "contact_1_name", "contact_1_title", "contact_1_linkedin", "contact_1_email",
    "contact_2_name", "contact_2_title", "contact_2_linkedin", "contact_2_email",
    "contact_3_name", "contact_3_title", "contact_3_linkedin", "contact_3_email",
    "user_action", "user_action_reason",
]


class Pipeline:
    """Orchestrates all agents. Agents are injectable for testing."""

    def __init__(
        self,
        icp_interpreter=None,
        company_discoverer=None,
        scoring_engine=None,
        contact_agent=None,
        db=None,
    ):
        self.icp_interpreter = icp_interpreter
        self.company_discoverer = company_discoverer
        self.scoring_engine = scoring_engine
        self.contact_agent = contact_agent
        self.db = db

    async def run(
        self,
        company_website: str,
        target_description: Optional[str] = None,
        existing_customers: Optional[List[Dict[str, Any]]] = None,
        lead_list: Optional[List[Dict[str, Any]]] = None,
        competitors: Optional[List[str]] = None,
        list_size: int = 20,
    ) -> ResearchSession:
        session = ResearchSession(
            company_website=company_website,
            target_description=target_description,
            existing_customers=existing_customers,
            lead_list=lead_list,
            competitors=competitors,
            status="interpreting",
        )

        # Step 1 — Interpret ICP
        icp = await self.icp_interpreter.interpret(
            target=target_description or "",
            website=company_website,
            existing_customers=[c.get("domain", "") for c in (existing_customers or [])],
            competitors=competitors or [],
        )
        session.icp_definition = icp

        # Step 2 — Discover / enrich candidates
        session.status = "discovering"
        if lead_list:
            domains = [item["domain"] for item in lead_list if "domain" in item]
            candidates = await self.company_discoverer.enrich_domains(domains)
        else:
            candidates = await self.company_discoverer.discover(icp=icp)
        session.candidate_companies = candidates

        # Step 3 — Score and rank
        session.status = "ranking"
        customer_profiles = []  # Phase 2: populate from existing_customers
        ranked = self.scoring_engine.score(candidates, icp, customer_profiles)
        ranked = ranked[:list_size]
        session.ranked_companies = ranked

        # Step 4 — Persist signal snapshots (non-negotiable invariant)
        if self.db:
            for rc in ranked:
                self.db.save_signal_snapshot(session.id, rc, icp)

        # Step 5 — Contact discovery
        session.status = "contact_discovery"
        ranked_with_contacts = await self.contact_agent.run(ranked)
        session.ranked_companies = ranked_with_contacts

        session.status = "completed"
        session.updated_at = datetime.utcnow()
        return session


def export_to_csv(session: ResearchSession, output_path: str) -> str:
    """Export ranked companies to CSV. Returns output_path."""
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_COLUMNS)
        writer.writeheader()

        for rc in (session.ranked_companies or []):
            c = rc.company
            contacts = rc.contacts or []
            row: Dict[str, Any] = {
                "company_name": c.name,
                "domain": c.domain,
                "industry": c.industry or "",
                "employee_range": c.employee_range or "",
                "location": ", ".join(filter(None, [c.hq_location, c.hq_country])) or "",
                "tier": rc.tier,
                "score": rc.total_score,
                "why_now": rc.reasoning_summary,
                "user_action": rc.user_action or "",
                "user_action_reason": rc.user_action_reason or "",
            }
            for i in range(1, 4):
                contact = contacts[i - 1] if len(contacts) >= i else None
                prefix = f"contact_{i}_"
                row[f"{prefix}name"] = contact.full_name if contact else ""
                row[f"{prefix}title"] = contact.title if contact else ""
                row[f"{prefix}linkedin"] = contact.linkedin_url or "" if contact else ""
                row[f"{prefix}email"] = contact.email or "" if contact else ""
            writer.writerow(row)

    return output_path


async def run_pipeline(
    company_website: str,
    target_description: Optional[str] = None,
    existing_customers: Optional[List[Dict[str, Any]]] = None,
    lead_list: Optional[List[Dict[str, Any]]] = None,
    competitors: Optional[List[str]] = None,
    list_size: int = 20,
    deep_enrich: bool = False,
    anthropic_api_key: Optional[str] = None,
    hunter_api_key: Optional[str] = None,
) -> ResearchSession:
    """Convenience entry point: builds agents from env vars and runs the pipeline."""
    import os
    from pathlib import Path
    from dotenv import load_dotenv
    from src.storage.database import SignalStore, get_connection, init_db

    # Load .env relative to this file — works regardless of caller's CWD
    load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")

    anthropic_key = anthropic_api_key or os.getenv("ANTHROPIC_API_KEY", "")
    hunter_key = hunter_api_key or os.getenv("HUNTER_API_KEY", "")

    config = load_scoring_config()
    hunter = HunterClient(api_key=hunter_key)

    conn = get_connection()
    init_db(conn)

    pipeline = Pipeline(
        icp_interpreter=ICPInterpreter(api_key=anthropic_key),
        company_discoverer=CompanyDiscoverer(hunter_client=hunter),
        scoring_engine=ScoringEngine(),
        contact_agent=ContactDiscoveryAgent(
            hunter_client=hunter,
            config=config.get("contact", {}),
        ),
        db=SignalStore(conn),
    )
    return await pipeline.run(
        company_website=company_website,
        target_description=target_description,
        existing_customers=existing_customers,
        lead_list=lead_list,
        competitors=competitors,
        list_size=list_size,
    )
