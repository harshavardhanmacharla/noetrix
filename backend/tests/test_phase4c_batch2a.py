"""
Tests for Phase 4C Batch 2A:
- Organization update endpoint (PUT /api/organizations/{org_id}) with owner/admin authorization and slug conflict checks
- Dashboard test case count excluding soft-deleted records for superusers and members
- Project-filtered run listing (GET /api/runs?project_id=...) with tenant isolation
"""
import uuid
import pytest
from httpx import ASGITransport, AsyncClient

import app.models  # noqa: F401
from app.config import get_settings
from app.database import Base, SessionLocal, engine
from app.main import app
from app.models.organization import Organization, OrganizationMembership
from app.models.project import Project
from app.models.test_case import TestCase
from app.models.test_run import TestRun
from app.models.user import User
from app.services.security import create_access_token, hash_password

TestCase.__test__ = False
TestRun.__test__ = False

settings = get_settings()


@pytest.fixture(autouse=True)
def clean_db():
    """Ensure every test runs against a clean database schema."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def create_test_user(email: str, is_superuser: bool = False) -> User:
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


def create_test_org(name: str, slug: str, creator: User, role: str = "owner") -> Organization:
    """Helper to create an organization and membership."""
    with SessionLocal() as db:
        org = Organization(
            id=str(uuid.uuid4()),
            name=name,
            slug=slug,
            description=f"Description for {name}",
        )
        db.add(org)
        db.flush()

        if creator and role:
            membership = OrganizationMembership(
                id=str(uuid.uuid4()),
                org_id=org.id,
                user_id=creator.id,
                role=role,
            )
            db.add(membership)
        db.commit()
        db.refresh(org)
        return org


def add_membership(org: Organization, user: User, role: str = "member"):
    """Helper to add an organization membership."""
    with SessionLocal() as db:
        membership = OrganizationMembership(
            id=str(uuid.uuid4()),
            org_id=org.id,
            user_id=user.id,
            role=role,
        )
        db.add(membership)
        db.commit()


def create_test_project(org: Organization, name: str, slug: str) -> Project:
    """Helper to create a project within an organization."""
    with SessionLocal() as db:
        project = Project(
            id=str(uuid.uuid4()),
            org_id=org.id,
            name=name,
            slug=slug,
            app_url="https://example.com",
        )
        db.add(project)
        db.commit()
        db.refresh(project)
        return project


def create_test_case_record(project: Project, name: str, is_active: bool = True) -> TestCase:
    """Helper to create a test case."""
    with SessionLocal() as db:
        tc = TestCase(
            id=str(uuid.uuid4()),
            project_id=project.id,
            name=name,
            is_active=is_active,
        )
        db.add(tc)
        db.commit()
        db.refresh(tc)
        return tc


def create_test_run_record(project: Project, status: str = "passed") -> TestRun:
    """Helper to create a test run."""
    with SessionLocal() as db:
        run = TestRun(
            id=str(uuid.uuid4()),
            project_id=project.id,
            status=status,
            total_tests=1,
            passed_tests=1 if status == "passed" else 0,
            failed_tests=1 if status == "failed" else 0,
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        return run


def auth_headers(user: User) -> dict:
    """Generate authorization headers for a user."""
    token = create_access_token(data={"sub": user.id})
    return {"Authorization": f"Bearer {token}"}


# ===========================================================================
# Part A: Organization Update Tests
# ===========================================================================

@pytest.mark.asyncio
async def test_org_update_by_owner_succeeds():
    """An organization owner can update name, slug, and description."""
    owner = create_test_user("owner@example.com")
    org = create_test_org("Initial Name", "initial-slug", owner, role="owner")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.put(
            f"/api/organizations/{org.id}",
            json={"name": "Updated Org", "slug": "updated-slug", "description": "New description"},
            headers=auth_headers(owner),
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Updated Org"
    assert data["slug"] == "updated-slug"
    assert data["description"] == "New description"


@pytest.mark.asyncio
async def test_org_update_by_admin_succeeds():
    """An organization admin can update organization details."""
    owner = create_test_user("owner@example.com")
    admin = create_test_user("admin-user@example.com")
    org = create_test_org("Corp Org", "corp-slug", owner, role="owner")
    add_membership(org, admin, role="admin")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.put(
            f"/api/organizations/{org.id}",
            json={"name": "Corp Org Renamed"},
            headers=auth_headers(admin),
        )

    assert resp.status_code == 200
    assert resp.json()["name"] == "Corp Org Renamed"
    assert resp.json()["slug"] == "corp-slug"


@pytest.mark.asyncio
async def test_org_update_by_member_forbidden():
    """A standard member without admin/owner role is forbidden from updating organization."""
    owner = create_test_user("owner@example.com")
    member = create_test_user("member@example.com")
    org = create_test_org("Member Org", "member-slug", owner, role="owner")
    add_membership(org, member, role="member")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.put(
            f"/api/organizations/{org.id}",
            json={"name": "Hacked Name"},
            headers=auth_headers(member),
        )

    assert resp.status_code == 403
    assert "owner or admin role" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_org_update_by_non_member_forbidden():
    """A user who is not a member of the organization is forbidden with 403."""
    owner = create_test_user("owner@example.com")
    stranger = create_test_user("stranger@example.com")
    org = create_test_org("Secret Org", "secret-slug", owner, role="owner")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.put(
            f"/api/organizations/{org.id}",
            json={"name": "Takeover"},
            headers=auth_headers(stranger),
        )

    assert resp.status_code == 403
    assert "not a member" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_org_update_by_superuser_succeeds():
    """A platform superuser can update any organization even without membership."""
    owner = create_test_user("owner@example.com")
    superuser = create_test_user("superuser@example.com", is_superuser=True)
    org = create_test_org("Super Org", "super-slug", owner, role="owner")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.put(
            f"/api/organizations/{org.id}",
            json={"name": "Superuser Overwrite"},
            headers=auth_headers(superuser),
        )

    assert resp.status_code == 200
    assert resp.json()["name"] == "Superuser Overwrite"


@pytest.mark.asyncio
async def test_org_update_unauthenticated_returns_401():
    """An unauthenticated request returns 401 Unauthorized."""
    owner = create_test_user("owner@example.com")
    org = create_test_org("Noauth Org", "noauth-slug", owner, role="owner")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.put(
            f"/api/organizations/{org.id}",
            json={"name": "No Auth"},
        )

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_org_update_nonexistent_org_returns_404():
    """Updating a non-existent organization returns 404 Not Found."""
    superuser = create_test_user("superuser@example.com", is_superuser=True)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.put(
            "/api/organizations/nonexistent-org-id",
            json={"name": "Ghost Org"},
            headers=auth_headers(superuser),
        )

    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_org_update_duplicate_slug_returns_409():
    """Attempting to update an organization slug to one already used by another org returns 409 Conflict."""
    owner = create_test_user("owner@example.com")
    create_test_org("Org One", "slug-one", owner, role="owner")
    org2 = create_test_org("Org Two", "slug-two", owner, role="owner")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.put(
            f"/api/organizations/{org2.id}",
            json={"slug": "slug-one"},
            headers=auth_headers(owner),
        )

    assert resp.status_code == 409
    assert "already exists" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_org_update_same_slug_succeeds():
    """Submitting the organization's existing slug does not trigger a 409 Conflict."""
    owner = create_test_user("owner@example.com")
    org = create_test_org("Org Identity", "identity-slug", owner, role="owner")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.put(
            f"/api/organizations/{org.id}",
            json={"name": "Identity Renamed", "slug": "identity-slug"},
            headers=auth_headers(owner),
        )

    assert resp.status_code == 200
    assert resp.json()["name"] == "Identity Renamed"
    assert resp.json()["slug"] == "identity-slug"


@pytest.mark.asyncio
async def test_org_update_invalid_slug_returns_422():
    """Providing an invalid slug format (e.g. uppercase or spaces) returns 422 Unprocessable Entity."""
    owner = create_test_user("owner@example.com")
    org = create_test_org("Org Valid", "org-valid", owner, role="owner")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.put(
            f"/api/organizations/{org.id}",
            json={"slug": "INVALID SLUG!"},
            headers=auth_headers(owner),
        )

    assert resp.status_code == 422


# ===========================================================================
# Part B: Dashboard Test-Case Counts Tests
# ===========================================================================

@pytest.mark.asyncio
async def test_dashboard_stats_excludes_soft_deleted_test_cases_superuser():
    """Dashboard statistics for superusers exclude soft-deleted (is_active=False) test cases."""
    superuser = create_test_user("superuser@example.com", is_superuser=True)
    org = create_test_org("Test Org", "test-org", None, role=None)
    project = create_test_project(org, "Test Project", "test-proj")

    # Create 3 active and 2 soft-deleted test cases
    create_test_case_record(project, "Active 1", is_active=True)
    create_test_case_record(project, "Active 2", is_active=True)
    create_test_case_record(project, "Active 3", is_active=True)
    create_test_case_record(project, "Deleted 1", is_active=False)
    create_test_case_record(project, "Deleted 2", is_active=False)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/dashboard/stats", headers=auth_headers(superuser))

    assert resp.status_code == 200
    data = resp.json()
    assert data["total_test_cases"] == 3


@pytest.mark.asyncio
async def test_dashboard_stats_excludes_soft_deleted_test_cases_member():
    """Dashboard statistics for organization members exclude soft-deleted test cases."""
    member = create_test_user("member@example.com")
    org = create_test_org("Member Org", "member-org", member, role="member")
    project = create_test_project(org, "Member Project", "member-proj")

    # Create 2 active and 3 inactive test cases
    create_test_case_record(project, "Active 1", is_active=True)
    create_test_case_record(project, "Active 2", is_active=True)
    create_test_case_record(project, "Deleted 1", is_active=False)
    create_test_case_record(project, "Deleted 2", is_active=False)
    create_test_case_record(project, "Deleted 3", is_active=False)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/dashboard/stats", headers=auth_headers(member))

    assert resp.status_code == 200
    data = resp.json()
    assert data["total_test_cases"] == 2


@pytest.mark.asyncio
async def test_dashboard_stats_zero_membership_user():
    """An ordinary user with 0 memberships safely receives static zeros for all metrics."""
    user = create_test_user("lonely@example.com", is_superuser=False)

    # Database has other orgs and test cases
    other_user = create_test_user("other@example.com")
    other_org = create_test_org("Other Org", "other-org", other_user, role="owner")
    other_proj = create_test_project(other_org, "Other Proj", "other-proj")
    create_test_case_record(other_proj, "Other Active", is_active=True)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/dashboard/stats", headers=auth_headers(user))

    assert resp.status_code == 200
    data = resp.json()
    assert data["total_organizations"] == 0
    assert data["total_projects"] == 0
    assert data["total_test_cases"] == 0
    assert data["total_runs"] == 0
    assert data["recent_runs"] == []


# ===========================================================================
# Part C: Project-Filtered Run Listing Tests
# ===========================================================================

@pytest.mark.asyncio
async def test_runs_list_unfiltered_returns_accessible_runs():
    """GET /api/runs without project_id returns recent runs for user's organizations."""
    user = create_test_user("user@example.com")
    org = create_test_org("Org A", "org-a", user, role="member")
    proj = create_test_project(org, "Proj A", "proj-a")
    run1 = create_test_run_record(proj, status="passed")
    run2 = create_test_run_record(proj, status="failed")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/runs", headers=auth_headers(user))

    assert resp.status_code == 200
    data = resp.json()
    returned_ids = {r["id"] for r in data}
    assert run1.id in returned_ids
    assert run2.id in returned_ids


@pytest.mark.asyncio
async def test_runs_list_filtered_by_project_succeeds():
    """GET /api/runs?project_id=... returns only runs belonging to the specified project."""
    user = create_test_user("user@example.com")
    org = create_test_org("Org Multi", "org-multi", user, role="member")
    proj1 = create_test_project(org, "Proj 1", "proj-1")
    proj2 = create_test_project(org, "Proj 2", "proj-2")

    run_p1 = create_test_run_record(proj1, status="passed")
    run_p2 = create_test_run_record(proj2, status="passed")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/runs?project_id={proj1.id}", headers=auth_headers(user))

    assert resp.status_code == 200
    data = resp.json()
    returned_ids = [r["id"] for r in data]
    assert run_p1.id in returned_ids
    assert run_p2.id not in returned_ids


@pytest.mark.asyncio
async def test_runs_list_filtered_by_nonexistent_project_returns_404():
    """GET /api/runs?project_id=nonexistent returns 404 Not Found."""
    user = create_test_user("user@example.com")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/runs?project_id=nonexistent-uuid", headers=auth_headers(user))

    assert resp.status_code == 404
    assert "project not found" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_runs_list_filtered_by_cross_tenant_project_returns_403():
    """GET /api/runs?project_id=... for a project in another organization returns 403 Forbidden."""
    user1 = create_test_user("user1@example.com")
    user2 = create_test_user("user2@example.com")

    org1 = create_test_org("Org 1", "org-1", user1, role="member")
    org2 = create_test_org("Org 2", "org-2", user2, role="member")

    proj2 = create_test_project(org2, "Proj 2", "proj-2")
    create_test_run_record(proj2, status="passed")

    # user1 attempts to query runs for user2's project
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/runs?project_id={proj2.id}", headers=auth_headers(user1))

    assert resp.status_code == 403
    assert "access denied" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_runs_list_filtered_by_project_superuser_succeeds():
    """A superuser can filter runs by any project across organizations."""
    superuser = create_test_user("super@example.com", is_superuser=True)
    org = create_test_org("Any Org", "any-org", None, role=None)
    proj = create_test_project(org, "Any Proj", "any-proj")
    run = create_test_run_record(proj, status="passed")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/runs?project_id={proj.id}", headers=auth_headers(superuser))

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == run.id
