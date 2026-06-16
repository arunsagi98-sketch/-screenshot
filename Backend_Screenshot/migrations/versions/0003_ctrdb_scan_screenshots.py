"""Create scan_screenshots table in ctr_db

NOTE: This migration targets ctr_db (PostgreSQL), NOT scanner.db.
      The table is created automatically on app startup via
      CrmBase.metadata.create_all(crm_engine) in main.py.

      This file is kept here as a human-readable record of the schema.
      If you need to run it manually via Alembic against ctr_db, configure
      a second alembic env pointing at settings.crm_database_url.

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision:      str              = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on:    Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Creates scan_screenshots in ctr_db.

    Column notes
    ------------
    screenshot_data  BYTEA  — full PNG of the injected (after) screenshot
    original_data    BYTEA  — full PNG of the original (before) screenshot
    Both are served via GET /db-screenshots/{id}/image|original so the
    frontend can display before/after without reading from disk.
    """
    op.create_table(
        "scan_screenshots",
        # Identity
        sa.Column("id",             sa.Integer(),                    nullable=False),
        sa.Column("scan_job_id",    sa.String(64),                   nullable=True),
        sa.Column("url",            sa.Text(),                       nullable=False),
        sa.Column("domain",         sa.String(255),                  nullable=True),
        sa.Column("device",         sa.String(20),  server_default="Desktop", nullable=True),
        # Result metadata
        sa.Column("status",         sa.String(30),                   nullable=True),
        sa.Column("ads_found",      sa.Integer(),   server_default="0", nullable=True),
        sa.Column("slots_injected", sa.Integer(),   server_default="0", nullable=True),
        sa.Column("creative_name",  sa.String(255),                  nullable=True),
        sa.Column("creative_size",  sa.String(20),                   nullable=True),
        sa.Column("injection_type", sa.String(50),                   nullable=True),
        sa.Column("match_score",    sa.Float(),                      nullable=True),
        sa.Column("notes",          sa.Text(),                       nullable=True),
        # Binary image storage
        sa.Column("screenshot_data", sa.LargeBinary(),               nullable=True),
        sa.Column("original_data",   sa.LargeBinary(),               nullable=True),
        sa.Column("mime_type",      sa.String(30),  server_default="image/png", nullable=True),
        sa.Column("file_size_kb",   sa.Integer(),                    nullable=True),
        # Timestamp
        sa.Column("captured_at",    sa.DateTime(timezone=True),      nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scan_screenshots_id",          "scan_screenshots", ["id"],          unique=False)
    op.create_index("ix_scan_screenshots_url",         "scan_screenshots", ["url"],         unique=False)
    op.create_index("ix_scan_screenshots_scan_job_id", "scan_screenshots", ["scan_job_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_scan_screenshots_scan_job_id", table_name="scan_screenshots")
    op.drop_index("ix_scan_screenshots_url",         table_name="scan_screenshots")
    op.drop_index("ix_scan_screenshots_id",          table_name="scan_screenshots")
    op.drop_table("scan_screenshots")
