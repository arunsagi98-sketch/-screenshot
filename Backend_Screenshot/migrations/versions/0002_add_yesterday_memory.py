"""No-op migration (0002 was for crm_yesterday_memory in scanner_db — wrong DB, reverted)

CRM tables live in ctr_db which is managed separately.
This migration intentionally does nothing.

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-14
"""
from typing import Sequence, Union

revision:      str              = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on:    Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass  # CRM tables are in ctr_db — not managed by this Alembic config


def downgrade() -> None:
    pass
