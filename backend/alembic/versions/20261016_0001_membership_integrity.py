"""add created_at and unique constraint to organization_memberships

Revision ID: 20261016_0001
Revises: 
Create Date: 2026-10-16 01:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20261016_0001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Inspect current schema
    existing_columns = [col['name'] for col in inspector.get_columns('organization_memberships')]
    existing_uqs = [uq['name'] for uq in inspector.get_unique_constraints('organization_memberships')]

    # Check for existing duplicate (org_id, user_id) records before applying constraint
    duplicate_groups = bind.execute(sa.text(
        "SELECT org_id, user_id, COUNT(*) FROM organization_memberships GROUP BY org_id, user_id HAVING COUNT(*) > 1"
    )).fetchall()
    if duplicate_groups:
        raise RuntimeError(
            f"Cannot apply unique constraint: Found {len(duplicate_groups)} duplicate (org_id, user_id) group(s). "
            "Resolve duplicates before running this migration."
        )

    # Use batch_alter_table for universal SQLite (table-rebuilding) and PostgreSQL compatibility
    with op.batch_alter_table('organization_memberships', schema=None) as batch_op:
        if 'created_at' not in existing_columns:
            batch_op.add_column(
                sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True)
            )
        if 'uq_org_membership_org_user' not in existing_uqs:
            batch_op.create_unique_constraint('uq_org_membership_org_user', ['org_id', 'user_id'])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = [col['name'] for col in inspector.get_columns('organization_memberships')]
    existing_uqs = [uq['name'] for uq in inspector.get_unique_constraints('organization_memberships')]

    with op.batch_alter_table('organization_memberships', schema=None) as batch_op:
        if 'uq_org_membership_org_user' in existing_uqs:
            batch_op.drop_constraint('uq_org_membership_org_user', type_='unique')
        if 'created_at' in existing_columns:
            batch_op.drop_column('created_at')
