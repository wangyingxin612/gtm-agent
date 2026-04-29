from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel


class SignalSnapshot(BaseModel):
    """
    Immutable record of signals and scores at the time a company was presented.
    Written once per company per session. Never updated.
    """
    id: str
    session_id: str
    company_id: str
    company_domain: str

    icp_hash: str

    # Raw signal values at time of scoring
    signals: Dict = {}

    # Scores assigned
    firmographic_score: float
    keyword_score: float
    growth_score: float
    timing_score: float
    lookalike_score: float
    total_score: float
    tier_assigned: str

    # Populated after user interaction
    user_outcome: Optional[Literal["keep", "remove", "revisit"]] = None
    outcome_reason: Optional[str] = None
    outcome_timestamp: Optional[datetime] = None

    scored_at: datetime


class OverrideEvent(BaseModel):
    """
    Structured record of a user's deliberate action on a ranked company.
    Primary ground truth label for the learning system.
    """
    id: str
    session_id: str
    company_id: str
    company_domain: str

    # The action
    action: Literal["keep", "remove", "revisit", "rerank"]
    remove_reason: Optional[str] = None
    remove_reason_text: Optional[str] = None
    rerank_direction: Optional[Literal["up", "down"]] = None

    # Context at time of override
    score_at_override: float
    tier_at_override: str
    score_breakdown_at_override: dict

    # Metadata
    timestamp: datetime
    user_id: str = "operator"

    # Filled post-hoc by learning pipeline
    was_correct: Optional[bool] = None
