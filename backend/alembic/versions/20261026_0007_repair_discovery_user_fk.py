"""repair discovery_sessions user_id foreign key to reference tp_users

Revision ID: 20261026_0007
Revises: 20261026_0006
Create Date: 2026-10-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261026_0007"
down_revision: Union[str, None] = "20261026_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name

    if dialect_name == "sqlite":
        # SQLite does not support ALTER TABLE DROP/ADD CONSTRAINT directly.
        # Furthermore, SQLAlchemy reflection fails with NoSuchTableError when reflecting
        # an invalid FK target ('users').
        # We execute a safe 12-step table rebuild:
        # 1. Disable FK checks during swap
        # 2. Create new table with exact schema, defaults, PK, and correct FKs (tp_users.id and projects.id)
        # 3. Copy any existing rows
        # 4. Drop old table
        # 5. Rename new table
        # 6. Recreate indexes
        # 7. Re-enable FK checks
        op.execute("PRAGMA foreign_keys = OFF")

        op.execute("""
            CREATE TABLE _new_discovery_sessions (
                id VARCHAR(36) NOT NULL,
                project_id VARCHAR(36) NOT NULL,
                user_id VARCHAR(36) NOT NULL,
                app_url VARCHAR(2048) NOT NULL,
                current_url VARCHAR(2048),
                current_title VARCHAR(500),
                status VARCHAR(50) DEFAULT 'active' NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                closed_at DATETIME,
                PRIMARY KEY (id),
                FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE CASCADE,
                FOREIGN KEY(user_id) REFERENCES tp_users (id) ON DELETE CASCADE
            )
        """)

        op.execute("""
            INSERT INTO _new_discovery_sessions (
                id, project_id, user_id, app_url, current_url, current_title, status, created_at, updated_at, closed_at
            )
            SELECT id, project_id, user_id, app_url, current_url, current_title, status, created_at, updated_at, closed_at
            FROM discovery_sessions
        """)

        op.execute("DROP TABLE discovery_sessions")
        op.execute("ALTER TABLE _new_discovery_sessions RENAME TO discovery_sessions")
        op.execute("CREATE INDEX ix_discovery_sessions_project_id ON discovery_sessions (project_id)")
        op.execute("CREATE INDEX ix_discovery_sessions_user_id ON discovery_sessions (user_id)")
        op.execute("PRAGMA foreign_keys = ON")

    else:
        # PostgreSQL / generic SQL engines
        inspector = sa.inspect(bind)
        fks = inspector.get_foreign_keys("discovery_sessions")
        for fk in fks:
            if fk.get("constrained_columns") == ["user_id"] and fk.get("referred_table") == "users":
                fk_name = fk.get("name")
                if fk_name:
                    op.drop_constraint(fk_name, "discovery_sessions", type_="foreignkey")
                break
        op.create_foreign_key(
            "fk_discovery_sessions_user_id_tp_users",
            "discovery_sessions",
            "tp_users",
            ["user_id"],
            ["id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name

    if dialect_name == "sqlite":
        op.execute("PRAGMA foreign_keys = OFF")

        op.execute("""
            CREATE TABLE _old_discovery_sessions (
                id VARCHAR(36) NOT NULL,
                project_id VARCHAR(36) NOT NULL,
                user_id VARCHAR(36) NOT NULL,
                app_url VARCHAR(2048) NOT NULL,
                current_url VARCHAR(2048),
                current_title VARCHAR(500),
                status VARCHAR(50) DEFAULT 'active' NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                closed_at DATETIME,
                PRIMARY KEY (id),
                FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE CASCADE,
                FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
            )
        """)

        op.execute("""
            INSERT INTO _old_discovery_sessions (
                id, project_id, user_id, app_url, current_url, current_title, status, created_at, updated_at, closed_at
            )
            SELECT id, project_id, user_id, app_url, current_url, current_title, status, created_at, updated_at, closed_at
            FROM discovery_sessions
        """)

        op.execute("DROP TABLE discovery_sessions")
        op.execute("ALTER TABLE _old_discovery_sessions RENAME TO discovery_sessions")
        op.execute("CREATE INDEX ix_discovery_sessions_project_id ON discovery_sessions (project_id)")
        op.execute("CREATE INDEX ix_discovery_sessions_user_id ON discovery_sessions (user_id)")
        op.execute("PRAGMA foreign_keys = ON")

    else:
        op.drop_constraint("fk_discovery_sessions_user_id_tp_users", "discovery_sessions", type_="foreignkey")
        op.create_foreign_key(
            "fk_discovery_sessions_user_id_users",
            "discovery_sessions",
            "users",
            ["user_id"],
            ["id"],
            ondelete="CASCADE",
        )

