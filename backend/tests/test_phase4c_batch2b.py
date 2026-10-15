"""
Tests for Phase 4C Batch 2B:
- Safe Project deletion (DELETE /api/projects/{project_id}) with retention and dependency safeguards
- Safe Organization deletion (DELETE /api/organizations/{org_id}) with member and project dependency safeguards
- Prevention of accidental deletion of last organization
- Preservation of historical runs, test cases, and artifact records
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
from app.models.test_run import Artifact, TestResult, TestRun
from app.models.user import User
from app.services.security import create_access_token, hash_password

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


def create_test_org(name: str, slug: str, creator: User = None, role: str = "owner") -> Organization:
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
    """Helper to create a test run with result and artifact."""
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
        db.flush()

        result = TestResult(
            id=str(uuid.uuid4()),
            run_id=run.id,
            status=status,
        )
        db.add(result)
        db.flush()

        artifact = Artifact(
            id=str(uuid.uuid4()),
            run_id=run.id,
            result_id=result.id,
            artifact_type="screenshot",
            file_path="runs/test_run/screenshot.png",
        )
        db.add(artifact)
        db.commit()
        db.refresh(run)
        return run


def auth_headers(user: User) -> dict:
    """Generate authorization headers for a user."""
    token = create_access_token(data={"sub": user.id})
    return {"Authorization": f"Bearer {token}"}


# ===========================================================================
# Project Deletion Tests (DELETE /api/projects/{project_id})
# ===========================================================================

@pytest.mark.asyncio
async def test_delete_empty_project_by_owner_succeeds():
    """An organization owner can safely delete an empty project."""
    owner = create_test_user("owner@example.com")
    org = create_test_org("Org One", "org-one", owner, role="owner")
    project = create_test_project(org, "Empty Project", "empty-proj")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete(
            f"/api/projects/{project.id}",
            headers=auth_headers(owner),
        )

    assert resp.status_code == 204

    # Verify project is removed from database
    with SessionLocal() as db:
        p = db.query(Project).filter(Project.id == project.id).first()
        assert p is None


@pytest.mark.asyncio
async def test_delete_empty_project_by_admin_succeeds():
    """An organization admin can safely delete an empty project."""
    owner = create_test_user("owner@example.com")
    admin = create_test_user("admin@example.com")
    org = create_test_org("Org Two", "org-two", owner, role="owner")
    add_membership(org, admin, role="admin")
    project = create_test_project(org, "Admin Project", "admin-proj")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete(
            f"/api/projects/{project.id}",
            headers=auth_headers(admin),
        )

    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_delete_project_blocked_by_historical_test_runs():
    """Deleting a project with historical test runs is strictly BLOCKED with 409 Conflict to protect evidence."""
    owner = create_test_user("owner@example.com")
    org = create_test_org("Org Evidence", "org-evidence", owner, role="owner")
    project = create_test_project(org, "Run Project", "run-proj")
    run = create_test_run_record(project)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete(
            f"/api/projects/{project.id}",
            headers=auth_headers(owner),
        )

    assert resp.status_code == 409
    assert "historical test runs" in resp.json()["detail"].lower()

    # Verify that project, run, result, and artifact rows remain intact in the database
    with SessionLocal() as db:
        assert db.query(Project).filter(Project.id == project.id).first() is not None
        assert db.query(TestRun).filter(TestRun.id == run.id).first() is not None
        assert db.query(TestResult).filter(TestResult.run_id == run.id).first() is not None
        assert db.query(Artifact).filter(Artifact.run_id == run.id).first() is not None


@pytest.mark.asyncio
async def test_delete_project_blocked_by_test_cases():
    """Deleting a project with test cases is BLOCKED with 409 Conflict."""
    owner = create_test_user("owner@example.com")
    org = create_test_org("Org Cases", "org-cases", owner, role="owner")
    project = create_test_project(org, "Case Project", "case-proj")
    create_test_case_record(project, "Test 1")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete(
            f"/api/projects/{project.id}",
            headers=auth_headers(owner),
        )

    assert resp.status_code == 409
    assert "contains test cases" in resp.json()["detail"].lower()

    with SessionLocal() as db:
        assert db.query(Project).filter(Project.id == project.id).first() is not None


@pytest.mark.asyncio
async def test_delete_project_by_member_forbidden():
    """A standard member without owner or admin role cannot delete projects (403 Forbidden)."""
    owner = create_test_user("owner@example.com")
    member = create_test_user("member@example.com")
    org = create_test_org("Org Member", "org-member", owner, role="owner")
    add_membership(org, member, role="member")
    project = create_test_project(org, "Member Project", "mem-proj")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete(
            f"/api/projects/{project.id}",
            headers=auth_headers(member),
        )

    assert resp.status_code == 403
    assert "owner or admin role" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_delete_project_cross_tenant_forbidden():
    """A user from another organization cannot delete a project (403 Forbidden)."""
    owner1 = create_test_user("owner1@example.com")
    owner2 = create_test_user("owner2@example.com")
    org1 = create_test_org("Org 1", "org-1", owner1, role="owner")
    org2 = create_test_org("Org 2", "org-2", owner2, role="owner")
    project = create_test_project(org1, "Project 1", "proj-1")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete(
            f"/api/projects/{project.id}",
            headers=auth_headers(owner2),
        )

    assert resp.status_code == 403
    assert "access denied" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_delete_project_by_superuser_succeeds():
    """A superuser can delete an eligible empty project across organizations."""
    owner = create_test_user("owner@example.com")
    superuser = create_test_user("super@example.com", is_superuser=True)
    org = create_test_org("Org Super", "org-super", owner, role="owner")
    project = create_test_project(org, "Super Project", "super-proj")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete(
            f"/api/projects/{project.id}",
            headers=auth_headers(superuser),
        )

    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_delete_project_nonexistent_returns_404():
    """Deleting a non-existent project ID returns 404 Not Found."""
    superuser = create_test_user("super@example.com", is_superuser=True)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete(
            "/api/projects/nonexistent-project-id",
            headers=auth_headers(superuser),
        )

    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_delete_project_unauthenticated_returns_401():
    """Unauthenticated project deletion returns 401 Unauthorized."""
    owner = create_test_user("owner@example.com")
    org = create_test_org("Org A", "org-a", owner, role="owner")
    project = create_test_project(org, "Proj A", "proj-a")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete(f"/api/projects/{project.id}")

    assert resp.status_code == 401


# ===========================================================================
# Organization Deletion Tests (DELETE /api/organizations/{org_id})
# ===========================================================================

@pytest.mark.asyncio
async def test_delete_empty_organization_by_owner_succeeds():
    """An owner can delete an empty organization when another organization exists."""
    owner = create_test_user("owner@example.com")
    org1 = create_test_org("Primary Org", "primary-org", owner, role="owner")
    org2 = create_test_org("Secondary Org", "secondary-org", owner, role="owner")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete(
            f"/api/organizations/{org2.id}",
            headers=auth_headers(owner),
        )

    assert resp.status_code == 204

    # Verify org2 is removed
    with SessionLocal() as db:
        assert db.query(Organization).filter(Organization.id == org2.id).first() is None
        # Org1 remains intact
        assert db.query(Organization).filter(Organization.id == org1.id).first() is not None


@pytest.mark.asyncio
async def test_delete_organization_blocked_if_last_remaining():
    """Deleting the last remaining platform organization is BLOCKED with 409 Conflict."""
    owner = create_test_user("owner@example.com")
    only_org = create_test_org("Only Org", "only-org", owner, role="owner")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete(
            f"/api/organizations/{only_org.id}",
            headers=auth_headers(owner),
        )

    assert resp.status_code == 409
    assert "last remaining organization" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_delete_organization_blocked_by_child_projects():
    """Deleting an organization that still contains projects is BLOCKED with 409 Conflict."""
    owner = create_test_user("owner@example.com")
    org1 = create_test_org("Org One", "org-one", owner, role="owner")
    create_test_org("Org Two", "org-two", owner, role="owner")
    create_test_project(org1, "Child Project", "child-proj")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete(
            f"/api/organizations/{org1.id}",
            headers=auth_headers(owner),
        )

    assert resp.status_code == 409
    assert "contains projects" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_delete_organization_blocked_by_active_members():
    """Deleting an organization that still has other active members is BLOCKED with 409 Conflict."""
    owner = create_test_user("owner@example.com")
    other_member = create_test_user("other@example.com")
    org1 = create_test_org("Org With Members", "org-members", owner, role="owner")
    create_test_org("Spare Org", "spare-org", owner, role="owner")
    add_membership(org1, other_member, role="member")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete(
            f"/api/organizations/{org1.id}",
            headers=auth_headers(owner),
        )

    assert resp.status_code == 409
    assert "active members" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_delete_organization_by_admin_or_member_forbidden():
    """An organization admin or member who is not owner cannot delete the organization (403 Forbidden)."""
    owner = create_test_user("owner@example.com")
    admin = create_test_user("admin@example.com")
    org1 = create_test_org("Org Admin", "org-admin", owner, role="owner")
    create_test_org("Spare Org", "spare-org", owner, role="owner")
    add_membership(org1, admin, role="admin")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete(
            f"/api/organizations/{org1.id}",
            headers=auth_headers(admin),
        )

    assert resp.status_code == 403
    assert "owner role" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_delete_organization_cross_tenant_forbidden():
    """A user outside the organization cannot delete it (403 Forbidden)."""
    owner1 = create_test_user("owner1@example.com")
    owner2 = create_test_user("owner2@example.com")
    org1 = create_test_org("Org 1", "org-1", owner1, role="owner")
    create_test_org("Org 2", "org-2", owner2, role="owner")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete(
            f"/api/organizations/{org1.id}",
            headers=auth_headers(owner2),
        )

    assert resp.status_code == 403
    assert "access denied" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_delete_organization_by_superuser_succeeds():
    """A superuser can delete an eligible empty organization (no members, no projects) when other orgs exist."""
    owner = create_test_user("owner@example.com")
    superuser = create_test_user("super@example.com", is_superuser=True)
    create_test_org("Org Main", "org-main", owner, role="owner")
    org_to_delete = create_test_org("Org Scrap", "org-scrap", creator=None, role=None)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete(
            f"/api/organizations/{org_to_delete.id}",
            headers=auth_headers(superuser),
        )

    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_delete_organization_by_superuser_blocked_by_active_members():
    """A superuser attempting to delete an organization with active members is BLOCKED with 409 Conflict."""
    owner = create_test_user("owner@example.com")
    superuser = create_test_user("super@example.com", is_superuser=True)
    create_test_org("Org Main", "org-main", owner, role="owner")
    org_with_member = create_test_org("Org With Member", "org-with-member", owner, role="owner")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete(
            f"/api/organizations/{org_with_member.id}",
            headers=auth_headers(superuser),
        )

    assert resp.status_code == 409
    assert "active members" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_delete_organization_nonexistent_returns_404():
    """Deleting a non-existent organization returns 404 Not Found."""
    superuser = create_test_user("super@example.com", is_superuser=True)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete(
            "/api/organizations/nonexistent-org-id",
            headers=auth_headers(superuser),
        )

    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_delete_organization_unauthenticated_returns_401():
    """Unauthenticated organization deletion returns 401 Unauthorized."""
    owner = create_test_user("owner@example.com")
    org = create_test_org("Org Test", "org-test", owner, role="owner")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete(f"/api/organizations/{org.id}")

    assert resp.status_code == 401
