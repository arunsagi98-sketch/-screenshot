"""Pydantic schemas for the CRM Excel Processor."""
from typing import Optional
from pydantic import BaseModel


class CampaignRule(BaseModel):
    """Per-campaign metric overrides."""
    campaign: str
    line_id: Optional[str] = None
    ctr_min: Optional[float] = None
    ctr_max: Optional[float] = None
    vcr_min: Optional[float] = None
    vcr_max: Optional[float] = None
    view_min: Optional[float] = None
    view_max: Optional[float] = None


class GlobalSettings(BaseModel):
    """Global fallback metric ranges."""
    ctr_min: float = 0.10
    ctr_max: float = 0.55
    vcr_min: float = 75.0
    vcr_max: float = 89.0
    view_min: float = 75.0
    view_max: float = 89.0
