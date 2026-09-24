from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from src.models.company import CompanyProfile, RankedCompany
from src.models.icp import ICPDefinition


class ResearchSession(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    status: Literal[
        "draft",
        "interpreting",
        "discovering",
        "ranking",
        "contact_discovery",
        "completed",
    ] = "draft"

    # Inputs
    company_website: str
    company_documents: List[str] = []
    target_description: Optional[str] = None
    existing_customers: Optional[List[Dict[str, Any]]] = None
    lead_list: Optional[List[Dict[str, Any]]] = None
    competitors: Optional[List[str]] = None

    # Derived
    icp_definition: Optional[ICPDefinition] = None
    icp_confirmed: bool = False

    # Outputs
    candidate_companies: Optional[List[CompanyProfile]] = None
    ranked_companies: Optional[List[RankedCompany]] = None
    company_list_confirmed: bool = False
