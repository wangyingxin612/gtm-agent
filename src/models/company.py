from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, field_validator


class AgentContribution(BaseModel):
    """Records what a specific agent contributed to this company's context."""
    agent_id: str
    agent_version: str
    signals_added: List[str]
    confidence: float
    timestamp: datetime
    source_urls: Optional[List[str]] = None

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError("confidence must be between 0.0 and 1.0")
        return v


class SignalEvent(BaseModel):
    """An observed change in a company signal over time."""
    signal_type: str
    old_value: Optional[Any] = None
    new_value: Any
    detected_at: datetime
    source_agent: str
    confidence: float
    source_url: Optional[str] = None

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError("confidence must be between 0.0 and 1.0")
        return v


class CompanyProfile(BaseModel):
    # Identifiers
    id: str
    name: str
    domain: str
    linkedin_url: Optional[str] = None

    # Firmographics
    industry: Optional[str] = None
    sub_industry: Optional[str] = None
    employee_count: Optional[int] = None
    employee_range: Optional[str] = None
    hq_location: Optional[str] = None
    hq_country: Optional[str] = None
    founded_year: Optional[int] = None
    company_type: Optional[str] = None

    # Signals
    tech_stack: Optional[List[str]] = None
    funding_series: Optional[str] = None
    funding_amount: Optional[int] = None
    funding_date: Optional[date] = None
    revenue_range: Optional[str] = None
    description: Optional[str] = None

    # Canonical Context Fields (v3.1)
    agent_contributions: Dict[str, AgentContribution] = {}
    signal_history: List[SignalEvent] = []

    # Metadata
    data_source: str = "hunter"
    last_enriched: datetime
    enrichment_confidence: float
    data_quality: str = "full"

    @field_validator("enrichment_confidence")
    @classmethod
    def validate_confidence(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError("enrichment_confidence must be between 0.0 and 1.0")
        return v

    @field_validator("data_quality")
    @classmethod
    def validate_data_quality(cls, v: str) -> str:
        if v not in {"full", "partial", "limited"}:
            raise ValueError("data_quality must be 'full', 'partial', or 'limited'")
        return v


class ScoreBreakdown(BaseModel):
    firmographic_score: float
    keyword_score: float
    growth_score: float
    timing_score: float
    lookalike_score: float
    modifiers_applied: Dict[str, float] = {}


class RankedCompany(BaseModel):
    company: CompanyProfile

    # Scoring
    total_score: float
    tier: Literal["Tier 1", "Tier 2", "Tier 3"]
    score_breakdown: ScoreBreakdown

    # Explanation
    reasoning_summary: str

    # Contacts (populated after contact discovery)
    # Uses Any to avoid circular import; runtime type is List[Contact]
    contacts: Optional[List[Any]] = None
    contact_confidence: Optional[Literal["high", "low"]] = None

    # User Actions
    user_action: Optional[Literal["keep", "remove", "revisit"]] = None
    user_action_reason: Optional[str] = None
    user_action_timestamp: Optional[datetime] = None

    @field_validator("total_score")
    @classmethod
    def validate_score(cls, v: float) -> float:
        if not (0.0 <= v <= 100.0):
            raise ValueError("total_score must be between 0.0 and 100.0")
        return v
