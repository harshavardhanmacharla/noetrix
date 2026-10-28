"""create discovery_sessions and discovery_snapshots tables

Revision ID: 20261026_0006
Revises: 20261023_0005
Create Date: 2026-10-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261026_0006"
down_revision: Union[str, None] = "20261023_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "discovery_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("app_url", sa.String(length=2048), nullable=False),
        sa.Column("current_url", sa.String(length=2048), nullable=True),
        sa.Column("current_title", sa.String(length=500), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["tp_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_discovery_sessions_project_id", "discovery_sessions", ["project_id"], unique=False)
    op.create_index("ix_discovery_sessions_user_id", "discovery_sessions", ["user_id"], unique=False)

    op.create_table(
        "discovery_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("page_url", sa.String(length=2048), nullable=False),
        sa.Column("page_title", sa.String(length=500), nullable=True),
        sa.Column("elements_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("inventory_data", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["discovery_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_discovery_snapshots_session_id", "discovery_snapshots", ["session_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_discovery_snapshots_session_id", table_name="discovery_snapshots")
    op.drop_table("discovery_snapshots")
    op.drop_index("ix_discovery_sessions_user_id", table_name="discovery_sessions")
    op.drop_index("ix_discovery_sessions_project_id", table_name="discovery_sessions")
    op.drop_table("discovery_sessions")
