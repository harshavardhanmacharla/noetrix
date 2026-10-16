"""add discover_page to the test step action enum

Revision ID: 20261016_0002
Revises: 20261016_0001
Create Date: 2026-10-16
"""
from typing import Sequence, Union

from alembic import op


revision: str = "20261016_0002"
down_revision: Union[str, None] = "20261016_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    dialect_name = op.get_bind().dialect.name
    if dialect_name == "postgresql":
        op.execute("ALTER TYPE step_action ADD VALUE IF NOT EXISTS 'discover_page'")
    elif dialect_name != "sqlite":
        raise RuntimeError(
            f"Adding discover_page to step_action is not supported for {dialect_name}."
        )


def downgrade() -> None:
    # PostgreSQL does not support removing an enum value safely in-place.
    pass
