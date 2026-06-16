"""Initial schema — screenshot_results table

Revision ID: 0001
Revises:
Create Date: 2026-06-13
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "screenshot_results",
        sa.Column("id",                       sa.Integer(),  nullable=False),
        sa.Column("url",                       sa.String(),   nullable=True),
        sa.Column("screenshot_path",           sa.String(),   nullable=True),
        sa.Column("original_screenshot_path",  sa.String(),   nullable=True),
        sa.Column("status",                    sa.String(),   nullable=True),
        sa.Column("ads_found",                 sa.Integer(),  nullable=True),
        sa.Column("matches_found",             sa.Integer(),  nullable=True),
        sa.Column("matched_creative_name",     sa.String(),   nullable=True),
        sa.Column("matched_creative_size",     sa.String(),   nullable=True),
        sa.Column("injection_type",            sa.String(),   nullable=True),
        sa.Column("device",                    sa.String(),   server_default="Desktop", nullable=True),
        sa.Column("created_at",                sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_screenshot_results_id",  "screenshot_results", ["id"],  unique=False)
    op.create_index("ix_screenshot_results_url", "screenshot_results", ["url"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_screenshot_results_url", table_name="screenshot_results")
    op.drop_index("ix_screenshot_results_id",  table_name="screenshot_results")
    op.drop_table("screenshot_results")
