"""add select_option to the test step action enum

Revision ID: 20261023_0004
Revises: 20261023_0003
Create Date: 2026-10-23
"""
from typing import Sequence, Union

from alembic import op


revision: str = "20261023_0004"
down_revision: Union[str, None] = "20261023_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    dialect_name = op.get_bind().dialect.name
    if dialect_name == "postgresql":
        op.execute("ALTER TYPE step_action ADD VALUE IF NOT EXISTS 'select_option'")
    elif dialect_name != "sqlite":
        raise RuntimeError(
            f"Adding select_option to step_action is not supported for {dialect_name}."
        )


def downgrade() -> None:
    # PostgreSQL does not support removing an enum value safely in-place.
    pass

