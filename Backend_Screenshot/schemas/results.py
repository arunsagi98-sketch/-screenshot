from pydantic import BaseModel
from typing import List, Optional


class ExportPPTRequest(BaseModel):
    ids: List[int]


class ResultItem(BaseModel):
    id: int
    url: Optional[str] = None
    screenshot_path: Optional[str] = None
    original_screenshot_path: Optional[str] = None
    status: Optional[str] = None
    ads_found: Optional[int] = None
    matches_found: Optional[int] = None
    matched_creative_name: Optional[str] = None
    matched_creative_size: Optional[str] = None
    injection_type: Optional[str] = None
    device: Optional[str] = None
    created_at: Optional[str] = None
    created_at_ist: Optional[str] = None
