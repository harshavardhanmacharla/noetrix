"""
Test suite verifying the SQLite foreign-key schema and Alembic migration
for Live Discovery tables (discovery_sessions and discovery_snapshots).
"""
import os
import sqlite3
import uuid
from pathlib import Path
import pytest
from alembic import command
from alembic.config import Config

BACKEND_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BACKEND_DIR / "testpilot.db"
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"


def test_sqlite_foreign_key_references_tp_users():
    """Verify that discovery_sessions user_id references tp_users(id), NOT users(id)."""
    assert DB_PATH.exists(), f"Database file {DB_PATH} must exist"

    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()

    cur.execute("PRAGMA foreign_key_list(discovery_sessions)")
    fks = cur.fetchall()
    conn.close()

    # Form: (id, seq, table, from, to, on_update, on_delete, match)
    fk_targets = {fk[3]: (fk[2], fk[4], fk[6]) for fk in fks}

    # Verify user_id references tp_users(id) with CASCADE
    assert "user_id" in fk_targets, "user_id must be a foreign key in discovery_sessions"
    assert fk_targets["user_id"][0] == "tp_users", f"user_id must reference 'tp_users', got '{fk_targets['user_id'][0]}'"
    assert fk_targets["user_id"][1] == "id"
    assert fk_targets["user_id"][2] == "CASCADE"

    # Verify project_id references projects(id) with CASCADE
    assert "project_id" in fk_targets, "project_id must be a foreign key in discovery_sessions"
    assert fk_targets["project_id"][0] == "projects"
    assert fk_targets["project_id"][1] == "id"
    assert fk_targets["project_id"][2] == "CASCADE"


def test_sqlite_discovery_snapshots_foreign_key():
    """Verify that discovery_snapshots session_id references discovery_sessions(id)."""
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()

    cur.execute("PRAGMA foreign_key_list(discovery_snapshots)")
    fks = cur.fetchall()
    conn.close()

    fk_targets = {fk[3]: (fk[2], fk[4], fk[6]) for fk in fks}
    assert "session_id" in fk_targets, "session_id must be a foreign key in discovery_snapshots"
    assert fk_targets["session_id"][0] == "discovery_sessions"
    assert fk_targets["session_id"][1] == "id"
    assert fk_targets["session_id"][2] == "CASCADE"


def test_indexes_are_preserved():
    """Verify that indexes on foreign keys remain created after migration."""
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()

    cur.execute("SELECT name FROM sqlite_master WHERE type='index'")
    indexes = {row[0] for row in cur.fetchall()}
    conn.close()

    assert "ix_discovery_sessions_project_id" in indexes
    assert "ix_discovery_sessions_user_id" in indexes
    assert "ix_discovery_snapshots_session_id" in indexes


def test_insert_with_foreign_keys_enabled():
    """
    Simulate the exact POST /api/discovery/sessions operation with PRAGMA foreign_keys = ON.
    Must NOT raise sqlite3.OperationalError: no such table: main.users.
    """
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    cur.execute("PRAGMA foreign_keys = ON")

    # Fetch a valid project and user
    cur.execute("SELECT id FROM tp_users LIMIT 1")
    user_row = cur.fetchone()
    cur.execute("SELECT id FROM projects LIMIT 1")
    project_row = cur.fetchone()

    assert user_row is not None, "Need at least one user in tp_users"
    assert project_row is not None, "Need at least one project in projects"

    user_id = user_row[0]
    project_id = project_row[0]
    session_id = f"test-sess-{uuid.uuid4()}"
    snap_id = f"test-snap-{uuid.uuid4()}"

    try:
        # Inserting discovery session must succeed
        cur.execute(
            """
            INSERT INTO discovery_sessions (id, project_id, user_id, app_url, status)
            VALUES (?, ?, ?, 'https://example.com/test', 'active')
            """,
            (session_id, project_id, user_id),
        )

        # Inserting snapshot referencing discovery session must succeed
        cur.execute(
            """
            INSERT INTO discovery_snapshots (id, session_id, page_url, elements_count, inventory_data)
            VALUES (?, ?, 'https://example.com/test', 0, '{}')
            """,
            (snap_id, session_id),
        )

        # Non-existent user must fail with IntegrityError (FK constraint failed), NOT OperationalError (no such table)
        with pytest.raises(sqlite3.IntegrityError):
            cur.execute(
                """
                INSERT INTO discovery_sessions (id, project_id, user_id, app_url, status)
                VALUES (?, ?, 'non-existent-user-id', 'https://example.com/test', 'active')
                """,
                (f"invalid-sess-{uuid.uuid4()}", project_id),
            )

    finally:
        # Clean up test rows
        cur.execute("DELETE FROM discovery_snapshots WHERE id = ?", (snap_id,))
        cur.execute("DELETE FROM discovery_sessions WHERE id = ?", (session_id,))
        conn.commit()
        conn.close()


def test_migration_upgrade_and_downgrade_cycle(tmp_path):
    """Test running upgrade and downgrade on an isolated database copy."""
    temp_db = tmp_path / "migration_cycle_test.db"

    # Copy schema up to 20261026_0006
    conn = sqlite3.connect(str(temp_db))
    cur = conn.cursor()
    cur.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL, PRIMARY KEY (version_num))")
    cur.execute("INSERT INTO alembic_version VALUES ('20261026_0006')")
    cur.execute("CREATE TABLE tp_users (id VARCHAR(36) PRIMARY KEY)")
    cur.execute("CREATE TABLE projects (id VARCHAR(36) PRIMARY KEY)")
    cur.execute("""
        CREATE TABLE discovery_sessions (
            id VARCHAR(36) NOT NULL PRIMARY KEY,
            project_id VARCHAR(36) NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            app_url VARCHAR(2048) NOT NULL,
            current_url VARCHAR(2048),
            current_title VARCHAR(500),
            status VARCHAR(50) DEFAULT 'active' NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
            closed_at DATETIME
        )
    """)
    cur.execute("CREATE INDEX ix_discovery_sessions_project_id ON discovery_sessions (project_id)")
    cur.execute("CREATE INDEX ix_discovery_sessions_user_id ON discovery_sessions (user_id)")
    cur.execute("""
        CREATE TABLE discovery_snapshots (
            id VARCHAR(36) NOT NULL PRIMARY KEY,
            session_id VARCHAR(36) NOT NULL REFERENCES discovery_sessions(id) ON DELETE CASCADE,
            page_url VARCHAR(2048) NOT NULL,
            page_title VARCHAR(500),
            elements_count INTEGER DEFAULT '0' NOT NULL,
            inventory_data TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
        )
    """)
    cur.execute("CREATE INDEX ix_discovery_snapshots_session_id ON discovery_snapshots (session_id)")
    conn.commit()
    conn.close()

    # Configure Alembic for temp_db
    alembic_cfg = Config(str(ALEMBIC_INI))
    alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{temp_db.as_posix()}")
    alembic_cfg.set_main_option("script_location", str((BACKEND_DIR / "alembic").as_posix()))

    # Run upgrade to 20261026_0007
    command.upgrade(alembic_cfg, "20261026_0007")

    # Verify isolated schema has tp_users FK
    conn = sqlite3.connect(str(temp_db))
    cur = conn.cursor()
    cur.execute("PRAGMA foreign_key_list(discovery_sessions)")
    fks_upgraded = {row[3]: row[2] for row in cur.fetchall()}
    assert fks_upgraded.get("user_id") == "tp_users"
    conn.close()

    # Run downgrade back to 20261026_0006
    command.downgrade(alembic_cfg, "20261026_0006")

    # Verify downgraded schema has users FK
    conn = sqlite3.connect(str(temp_db))
    cur = conn.cursor()
    cur.execute("PRAGMA foreign_key_list(discovery_sessions)")
    fks_downgraded = {row[3]: row[2] for row in cur.fetchall()}
    assert fks_downgraded.get("user_id") == "users"
    conn.close()

    # Re-upgrade to head (20261026_0007)
    command.upgrade(alembic_cfg, "head")

    conn = sqlite3.connect(str(temp_db))
    cur = conn.cursor()
    cur.execute("PRAGMA foreign_key_list(discovery_sessions)")
    fks_final = {row[3]: row[2] for row in cur.fetchall()}
    assert fks_final.get("user_id") == "tp_users"
    conn.close()


@pytest.mark.asyncio
async def test_api_post_discovery_sessions_endpoint():
    """
    Verify that POST /api/discovery/sessions succeeds against the real database
    with foreign keys enabled, confirming the bug is completely resolved end-to-end.
    """
    from unittest.mock import MagicMock, patch
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import sessionmaker
    from app.main import app
    from app.database import get_db
    from app.models.user import User
    from app.models.project import Project
    from app.models.discovery import DiscoverySession
    from app.services.security import create_access_token
    from app.services.discovery_service import DiscoverySessionManager

    # Build an engine explicitly bound to backend/testpilot.db with PRAGMA foreign_keys=ON
    real_db_engine = create_engine(
        f"sqlite:///{DB_PATH.as_posix()}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(real_db_engine, "connect")
    def set_fk_on_connect(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    RealSessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=real_db_engine,
    )

    def override_get_db():
        db = RealSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    created_session_id = None
    try:
        with RealSessionLocal() as db:
            user = db.query(User).first()
            assert user is not None, "Need at least one user in testpilot.db"
            project = db.query(Project).first()
            assert project is not None, "Need at least one project in testpilot.db"
            user_id = user.id
            project_id = project.id

        token = create_access_token(data={"sub": user_id})

        mock_worker = MagicMock()
        mock_worker.is_active = True
        mock_worker.current_url = "https://example.com"
        mock_worker.current_title = "Example Domain"

        manager = DiscoverySessionManager.get_instance()
        with patch.object(manager, "start_session", return_value=mock_worker):
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://testserver",
            ) as client:
                resp = await client.post(
                    "/api/discovery/sessions",
                    json={
                        "project_id": project_id,
                        "url": "https://example.com",
                        "headless": True,
                    },
                    headers={"Authorization": f"Bearer {token}"},
                )
                assert resp.status_code == 201, f"Expected 201 Created, got {resp.status_code}: {resp.text}"
                data = resp.json()
                created_session_id = data["id"]
                assert data["status"] == "active"
                assert data["user_id"] == user_id
                assert data["project_id"] == project_id

        # Verify the session was persisted in the real database under the repaired FK
        with RealSessionLocal() as db:
            saved_sess = db.query(DiscoverySession).filter(DiscoverySession.id == created_session_id).first()
            assert saved_sess is not None
            assert saved_sess.user_id == user_id
            assert saved_sess.project_id == project_id
    finally:
        # Clean up database row and remove dependency override
        if created_session_id:
            with RealSessionLocal() as db:
                db.query(DiscoverySession).filter(DiscoverySession.id == created_session_id).delete()
                db.commit()
        app.dependency_overrides.pop(get_db, None)
        real_db_engine.dispose()


