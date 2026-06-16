"""
User ORM model — stored in scanner_db (local).

Roles
-----
super_admin  Full access + user management (all pages always)
admin        Specific pages only (controlled by allowed_pages)

allowed_pages
-------------
None (NULL)  → super_admin; all pages accessible
[]           → no page access
["crm_excel", "final_report", "ppt_store", "scanner"]  → example

Page keys:
  "scanner"      → index.html
  "crm_excel"    → crm-excel.html
  "ppt_store"    → ppt-store.html
  "final_report" → final-report.html
"""
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, Column, DateTime, Integer, String

from database.db import Base


class User(Base):
    __tablename__ = "users"

    id            = Column(Integer, primary_key=True, index=True)
    username      = Column(String(64),  unique=True, nullable=False, index=True)
    email         = Column(String(255), unique=True, nullable=True,  index=True)
    hashed_password = Column(String(255), nullable=False)
    role          = Column(String(20),  nullable=False, default="admin")
    # role values: "admin" | "super_admin"
    allowed_pages = Column(JSON, nullable=True, default=None)
    # None = all pages (super_admin), list = restricted page access
    is_active     = Column(Boolean, default=True, nullable=False)
    created_at    = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    last_login    = Column(DateTime(timezone=True), nullable=True)
