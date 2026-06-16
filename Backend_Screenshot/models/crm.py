"""
SQLAlchemy models for ctr_db — mirrors existing tables, does NOT create them.

Tables (all in ctr_db / public schema):
  campaign_rules    — per-campaign CTR/VCR/Viewability overrides
  global_settings   — global CTR min/max fallback
  processed_files   — audit log of every processed file
  yesterday_memory  — CTR snapshot from the last run (de-dup across days)
"""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String

from database.crm_db import CrmBase


class CampaignRule(CrmBase):
    __tablename__ = "campaign_rules"

    id              = Column(Integer, primary_key=True, index=True)
    line_item_id    = Column(String, nullable=False, index=True)
    campaign_name   = Column(String, nullable=True)
    min_ctr         = Column(Float,   nullable=True)
    max_ctr         = Column(Float,   nullable=True)
    min_vcr         = Column(Float,   nullable=True)
    max_vcr         = Column(Float,   nullable=True)
    min_viewability = Column(Float,   nullable=True)
    max_viewability = Column(Float,   nullable=True)
    enabled         = Column(Boolean, nullable=True, default=True)
    created_at      = Column(DateTime, nullable=True, default=datetime.utcnow)
    updated_at      = Column(DateTime, nullable=True, onupdate=datetime.utcnow)


class GlobalSetting(CrmBase):
    __tablename__ = "global_settings"

    id      = Column(Integer, primary_key=True, index=True)
    min_ctr = Column(Float, nullable=True)
    max_ctr = Column(Float, nullable=True)


class ProcessedFile(CrmBase):
    __tablename__ = "processed_files"

    id                = Column(Integer, primary_key=True, index=True)
    original_filename = Column(String,   nullable=True)
    saved_filename    = Column(String,   nullable=True)
    processed_at      = Column(DateTime, nullable=True, default=datetime.utcnow)
    ad_type           = Column(String,   nullable=True)   # "Video" | "Banner"


class YesterdayMemory(CrmBase):
    __tablename__ = "yesterday_memory"

    id           = Column(Integer, primary_key=True, index=True)
    line_item_id = Column(String,  nullable=False, index=True)
    clicks       = Column(Integer, nullable=False)
    ctr          = Column(String,  nullable=False)
    run_date     = Column(String,  nullable=False)
