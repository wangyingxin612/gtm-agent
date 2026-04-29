from pydantic import BaseModel, field_validator
from typing import Optional, List


class ICPDefinition(BaseModel):
    # Core Fields (Required)
    industries: List[str]
    company_size_min: int = 10
    company_size_max: int = 5000
    locations: List[str]

    # Optional Fields
    keywords: Optional[List[str]] = None
    growth_stages: Optional[List[str]] = None
    revenue_min: Optional[int] = None
    revenue_max: Optional[int] = None

    # Pain Point Indicators
    pain_points: Optional[List[str]] = None

    # Exclusions
    exclude_industries: Optional[List[str]] = None
    exclude_companies: Optional[List[str]] = None

    # Timing Preferences
    recent_funding: Optional[bool] = False
    recent_funding_months: Optional[int] = 6
    hiring_growth: Optional[bool] = False

    # Deal Probability Factors
    prefer_short_decision_chain: bool = True
    prefer_not_enterprise: bool = True

    # Metadata
    interpretation_confidence: float
    warnings: List[str] = []

    @field_validator("industries")
    @classmethod
    def validate_industries(cls, v: List[str]) -> List[str]:
        if not (1 <= len(v) <= 10):
            raise ValueError("industries must have between 1 and 10 entries")
        return v

    @field_validator("keywords")
    @classmethod
    def validate_keywords(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is not None and len(v) > 20:
            raise ValueError("keywords must have at most 20 entries")
        return v

    @field_validator("company_size_max")
    @classmethod
    def validate_size_range(cls, v: int, info) -> int:
        size_min = info.data.get("company_size_min", 1)
        if size_min >= v:
            raise ValueError("company_size_min must be less than company_size_max")
        return v

    @field_validator("interpretation_confidence")
    @classmethod
    def validate_confidence(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError("interpretation_confidence must be between 0.0 and 1.0")
        return v
