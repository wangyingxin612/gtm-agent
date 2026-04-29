from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel


class Contact(BaseModel):
    id: str
    first_name: str
    last_name: str
    full_name: str

    # Professional Info
    title: str
    seniority: str
    department: str

    # Contact Info
    email: Optional[str] = None
    email_confidence: Optional[Literal["verified", "likely"]] = None
    linkedin_url: Optional[str] = None
    phone: Optional[str] = None

    # Metadata
    data_source: str
    last_verified: Optional[datetime] = None

    # Role-level fallback
    is_role_suggestion: bool = False
    role_suggestion_reason: Optional[str] = None
