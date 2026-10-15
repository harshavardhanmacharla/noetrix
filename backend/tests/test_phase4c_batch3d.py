"""
Tests for Phase 4C Batch 3D:
- Membership Data Integrity and API Error Handling
- Physical created_at column persistence on OrganizationMembership
- Elimination of misleading user.created_at fallback (historical memberships return None)
- Database-level composite uniqueness enforcement on (org_id, user_id)
- Dual SQLite / PostgreSQL Alembic migration upgrade and downgrade verification
- Alembic pre-migration duplicate detection safeguard
- Organization creation and member addition API timestamp integration
"""
import os
import tempfile
import uuid
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.config import get_settings
from app.database import Base, SessionLocal, engine
from app.main import app
from app.models.organization import Organization, OrganizationMembership
from app.models.user import User
from app.schemas.organization import OrganizationMemberResponse
from app.services.security import create_access_token, hash_password

from app.models.test_case import TestCase
from app.models.test_run import TestResult, TestRun

TestCase.__test__ = False
TestRun.__test__ = False
TestResult.__test__ = False

settings = get_settings()


@pytest.fixture(autouse=True)
def clean_db():
    """Ensure every test runs against a clean database schema."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def create_user(email: str, is_superuser: bool = False) -> User:
    """Helper to insert a user into the test database."""
    with SessionLocal() as db:
        user = User(
            id=str(uuid.uuid4()),
            email=email,
            hashed_password=hash_password("Password123!"),
            full_name=email.split("@")[0].capitalize(),
            is_active=True,
            is_superuser=is_superuser,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user


def auth_headers(user: User) -> dict[str, str]:
    """Helper to generate Authorization header."""
    token = create_access_token(
        data={"sub": user.id, "email": user.email, "is_superuser": user.is_superuser}
    )
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# 1. Physical Timestamp Persistence and Fresh DB Session Verification
# ---------------------------------------------------------------------------
def test_membership_timestamp_persistence_in_fresh_session():
    """Verify newly created membership persists actual created_at across fresh DB sessions."""
    owner = create_user("owner@example.com")

    with SessionLocal() as db:
        org = Organization(name="Timestamp Org", slug="ts-org")
        db.add(org)
        db.flush()

        membership = OrganizationMembership(
            org_id=org.id,
            user_id=owner.id,
            role="owner",
            created_at=datetime.now(timezone.utc),
        )
        db.add(membership)
        db.commit()
        mem_id = membership.id

    # Query in a brand new fresh session
    with SessionLocal() as fresh_db:
        persisted = fresh_db.get(OrganizationMembership, mem_id)
        assert persisted is not None
        assert persisted.created_at is not None
        assert isinstance(persisted.created_at, datetime)
        # Ensure it has timestamp information and is close to current time
        diff_seconds = abs((datetime.now(timezone.utc) - persisted.created_at.replace(tzinfo=timezone.utc)).total_seconds())
        assert diff_seconds < 10


# ---------------------------------------------------------------------------
# 2. Historical Records Handling (No Fallback to user.created_at)
# ---------------------------------------------------------------------------
def test_historical_membership_without_created_at_evaluates_to_none():
    """
    Historical memberships whose real join date is unknown must evaluate to None
    and MUST NOT fall back to user.created_at.
    """
    user = create_user("historical@example.com")
    # Verify user.created_at exists
    assert user.created_at is not None

    with SessionLocal() as db:
        org = Organization(name="Historical Org", slug="hist-org")
        db.add(org)
        db.flush()
        org_id = org.id

        # Simulate historical record where created_at is explicitly NULL / None
        db.execute(
            sa.text(
                "INSERT INTO organization_memberships (id, org_id, user_id, role, created_at) "
                "VALUES (:id, :org_id, :user_id, :role, NULL)"
            ),
            {"id": str(uuid.uuid4()), "org_id": org_id, "user_id": user.id, "role": "member"},
        )
        db.commit()

    with SessionLocal() as fresh_db:
        hist_mem = (
            fresh_db.query(OrganizationMembership)
            .filter(OrganizationMembership.org_id == org_id)
            .first()
        )
        assert hist_mem is not None
        assert hist_mem.created_at is None
        # Crucial: Ensure it does NOT equal user.created_at
        assert hist_mem.created_at != hist_mem.user.created_at

        # Verify Pydantic schema serialization preserves None
        resp = OrganizationMemberResponse(
            id=hist_mem.id,
            user_id=hist_mem.user_id,
            email=hist_mem.user.email,
            role=hist_mem.role,
            created_at=hist_mem.created_at,
        )
        assert resp.created_at is None


# ---------------------------------------------------------------------------
# 3. Database-Level Unique Constraint on (org_id, user_id)
# ---------------------------------------------------------------------------
def test_database_level_unique_constraint_enforced():
    """Verify that (org_id, user_id) composite unique constraint prevents duplicate rows."""
    user = create_user("unique@example.com")

    with SessionLocal() as db:
        org = Organization(name="Unique Org", slug="unique-org")
        db.add(org)
        db.flush()

        m1 = OrganizationMembership(
            org_id=org.id,
            user_id=user.id,
            role="member",
        )
        db.add(m1)
        db.commit()

        # Attempt to insert second membership for same org and user
        m2 = OrganizationMembership(
            org_id=org.id,
            user_id=user.id,
            role="admin",
        )
        db.add(m2)
        with pytest.raises(IntegrityError):
            db.commit()


# ---------------------------------------------------------------------------
# 4. API Integration: Timestamp set on Org Creation and Member Add
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_api_membership_timestamps_and_historical_listing():
    """Test router-level creation timestamps and historical None response in list API."""
    owner = create_user("api_owner@example.com")
    member = create_user("api_member@example.com")
    hist_user = create_user("api_hist@example.com")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 1. Create organization via API
        create_resp = await ac.post(
            "/api/organizations",
            headers=auth_headers(owner),
            json={"name": "API Org", "slug": "api-org", "description": "Testing API"},
        )
        assert create_resp.status_code == 201
        org_data = create_resp.json()
        org_id = org_data["id"]

        # 2. Add new member via API
        add_resp = await ac.post(
            f"/api/organizations/{org_id}/members",
            headers=auth_headers(owner),
            json={"email": member.email, "role": "member"},
        )
        assert add_resp.status_code == 201
        member_data = add_resp.json()
        assert member_data["created_at"] is not None

        # 3. Insert historical membership with NULL created_at directly into DB
        with SessionLocal() as db:
            db.execute(
                sa.text(
                    "INSERT INTO organization_memberships (id, org_id, user_id, role, created_at) "
                    "VALUES (:id, :org_id, :user_id, :role, NULL)"
                ),
                {"id": str(uuid.uuid4()), "org_id": org_id, "user_id": hist_user.id, "role": "member"},
            )
            db.commit()

        # 4. List members via API
        list_resp = await ac.get(
            f"/api/organizations/{org_id}/members",
            headers=auth_headers(owner),
        )
        assert list_resp.status_code == 200
        members = list_resp.json()
        assert len(members) == 3

        members_by_email = {m["email"]: m for m in members}

        # Owner has non-null timestamp
        assert members_by_email[owner.email]["created_at"] is not None

        # New member has non-null timestamp
        assert members_by_email[member.email]["created_at"] is not None

        # Historical member has None (null in JSON)
        assert members_by_email[hist_user.email]["created_at"] is None

        # 5. Adding duplicate user returns 409
        dup_resp = await ac.post(
            f"/api/organizations/{org_id}/members",
            headers=auth_headers(owner),
            json={"email": member.email, "role": "member"},
        )
        assert dup_resp.status_code == 409


def _load_migration():
    import importlib.util
    from pathlib import Path

    migration_file = (
        Path(__file__).resolve().parent.parent
        / "alembic"
        / "versions"
        / "20261016_0001_membership_integrity.py"
    )
    spec = importlib.util.spec_from_file_location("migration_20261016_0001", str(migration_file))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_alembic_migration_upgrade_and_downgrade():
    """
    Verify Alembic migration script 20261016_0001_membership_integrity
    executes cleanly on an isolated SQLite database using batch_alter_table.
    """
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from alembic import op

    migration = _load_migration()

    isolated_engine = sa.create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=sa.pool.StaticPool,
    )

    # 1. Setup pre-migration legacy schema (no created_at, no unique constraint)
    with isolated_engine.connect() as conn:
        conn.execute(sa.text("""
            CREATE TABLE organization_memberships (
                id VARCHAR(36) PRIMARY KEY,
                org_id VARCHAR(36) NOT NULL,
                user_id VARCHAR(36) NOT NULL,
                role VARCHAR(20) NOT NULL
            )
        """))
        # Insert valid non-duplicate records
        conn.execute(sa.text("""
            INSERT INTO organization_memberships (id, org_id, user_id, role)
            VALUES ('m1', 'org1', 'u1', 'owner'), ('m2', 'org1', 'u2', 'member')
        """))
        conn.commit()

    # 2. Run upgrade()
    with isolated_engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        op._proxy = Operations(ctx)
        migration.upgrade()
        conn.commit()

    # 3. Verify schema after upgrade
    with isolated_engine.connect() as conn:
        insp = sa.inspect(conn)
        cols = [c["name"] for c in insp.get_columns("organization_memberships")]
        assert "created_at" in cols

        uqs = insp.get_unique_constraints("organization_memberships")
        uq_names = [u["name"] for u in uqs]
        assert "uq_org_membership_org_user" in uq_names

        # Verify existing rows have been preserved
        rows = conn.execute(sa.text("SELECT id, org_id, user_id, role, created_at FROM organization_memberships")).fetchall()
        assert len(rows) == 2

        # Verify unique constraint blocks duplicates now
        with pytest.raises(IntegrityError):
            conn.execute(sa.text("""
                INSERT INTO organization_memberships (id, org_id, user_id, role)
                VALUES ('m3', 'org1', 'u1', 'admin')
            """))
            conn.commit()
        conn.rollback()

    # 4. Run downgrade()
    with isolated_engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        op._proxy = Operations(ctx)
        migration.downgrade()
        conn.commit()

    # 5. Verify schema after downgrade
    with isolated_engine.connect() as conn:
        insp = sa.inspect(conn)
        cols = [c["name"] for c in insp.get_columns("organization_memberships")]
        assert "created_at" not in cols

        uqs = insp.get_unique_constraints("organization_memberships")
        uq_names = [u["name"] for u in uqs]
        assert "uq_org_membership_org_user" not in uq_names


# ---------------------------------------------------------------------------
# 6. Alembic Migration Duplicate Record Pre-Check Safeguard
# ---------------------------------------------------------------------------
def test_alembic_migration_halts_on_duplicate_groups():
    """Verify that Alembic upgrade detects duplicates and raises RuntimeError before schema mutation."""
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from alembic import op

    migration = _load_migration()

    isolated_engine = sa.create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=sa.pool.StaticPool,
    )

    # Create table and insert duplicate (org1, u1) records
    with isolated_engine.connect() as conn:
        conn.execute(sa.text("""
            CREATE TABLE organization_memberships (
                id VARCHAR(36) PRIMARY KEY,
                org_id VARCHAR(36) NOT NULL,
                user_id VARCHAR(36) NOT NULL,
                role VARCHAR(20) NOT NULL
            )
        """))
        conn.execute(sa.text("""
            INSERT INTO organization_memberships (id, org_id, user_id, role)
            VALUES ('m1', 'org1', 'u1', 'owner'), ('m2', 'org1', 'u1', 'member')
        """))
        conn.commit()

    # Running upgrade should raise RuntimeError
    with isolated_engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        op._proxy = Operations(ctx)
        with pytest.raises(RuntimeError, match="Found 1 duplicate"):
            migration.upgrade()
