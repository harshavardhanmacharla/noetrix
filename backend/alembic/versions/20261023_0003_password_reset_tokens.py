"""create tp_password_reset_tokens table for secure password reset flow

Revision ID: 20261023_0003
Revises: 20261016_0002
Create Date: 2026-10-23 11:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20261023_0003"
down_revision: Union[str, None] = "20261016_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    if "tp_password_reset_tokens" not in tables:
        op.create_table(
            "tp_password_reset_tokens",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("used", sa.Boolean(), nullable=False, server_default=sa.text("0" if bind.dialect.name == "sqlite" else "false")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["tp_users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_tp_password_reset_tokens_user_id",
            "tp_password_reset_tokens",
            ["user_id"],
            unique=False,
        )
        op.create_index(
            "ix_tp_password_reset_tokens_token_hash",
            "tp_password_reset_tokens",
            ["token_hash"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    if "tp_password_reset_tokens" in tables:
        op.drop_index("ix_tp_password_reset_tokens_token_hash", table_name="tp_password_reset_tokens")
        op.drop_index("ix_tp_password_reset_tokens_user_id", table_name="tp_password_reset_tokens")
        op.drop_table("tp_password_reset_tokens")

