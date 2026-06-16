"""
ORM model for scan_screenshots table — lives in ctr_db (PostgreSQL).

Stores the full binary image data alongside scan metadata so the
frontend can display before/after screenshots without touching the
local filesystem.
"""
from datetime import datetime, timezone

from sqlalchemy import (
    Column, DateTime, Float, Integer, LargeBinary, String, Text
)

from database.crm_db import CrmBase


class ScanScreenshot(CrmBase):
    __tablename__ = "scan_screenshots"

    id              = Column(Integer, primary_key=True, index=True)

    # ── Scan identity ─────────────────────────────────────────────────────────
    scan_job_id     = Column(String(64),  nullable=True,  index=True)   # UUID of the batch run
    url             = Column(Text,        nullable=False, index=True)
    domain          = Column(String(255), nullable=True)
    device          = Column(String(20),  nullable=True,  default="Desktop")

    # ── Result metadata ───────────────────────────────────────────────────────
    status          = Column(String(30),  nullable=True)   # success / skipped / failed / blocked
    ads_found       = Column(Integer,     nullable=True,  default=0)
    slots_injected  = Column(Integer,     nullable=True,  default=0)
    creative_name   = Column(String(255), nullable=True)
    creative_size   = Column(String(20),  nullable=True)
    injection_type  = Column(String(50),  nullable=True)
    match_score     = Column(Float,       nullable=True)
    notes           = Column(Text,        nullable=True)

    # ── Binary image storage ──────────────────────────────────────────────────
    # PostgreSQL BYTEA — store full PNG/JPEG bytes so the frontend can
    # retrieve images via /db-screenshots/{id}/image without hitting disk.
    screenshot_data = Column(LargeBinary, nullable=True)   # injected / after screenshot
    original_data   = Column(LargeBinary, nullable=True)   # before-injection screenshot
    mime_type       = Column(String(30),  nullable=True,  default="image/png")
    file_size_kb    = Column(Integer,     nullable=True)   # size of screenshot_data in KB

    # ── Timestamp ─────────────────────────────────────────────────────────────
    captured_at     = Column(
        DateTime(timezone=True),
        nullable=True,
        default=lambda: datetime.now(timezone.utc),
    )
