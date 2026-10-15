"""
Tests for Phase 4C Batch 3B:
- Backend Organization Membership APIs and RBAC Safeguards
- GET /api/organizations/{org_id}/members
- POST /api/organizations/{org_id}/members
- PATCH /api/organizations/{org_id}/members/{user_id}
- DELETE /api/organizations/{org_id}/members/{user_id}
- POST /api/organizations/{org_id}/leave
- RBAC hierarchy (owner, admin, member, superuser)
- Last-owner safeguards (demotion, removal, departure)
- Immediate access revocation
- Preservation of test cases, runs, results, and artifacts
- Database-level composite uniqueness enforcement
"""
import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import IntegrityError

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


def add_membership(org: Organization, user: User, role: str = "member") -> OrganizationMembership:
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
        db.refresh(membership)
        return membership


def auth_headers(user: User) -> dict:
    """Generate auth headers for test user."""
    token = create_access_token(
        data={"sub": user.id, "email": user.email, "is_superuser": user.is_superuser}
    )
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Part A.1: List Members
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_members_success_and_cross_tenant_exclusion():
    """Verify list members returns accurate details and excludes members from other orgs."""
    owner = create_test_user("owner@example.com")
    member = create_test_user("member@example.com")
    other_user = create_test_user("other@example.com")

    org1 = create_test_org("Org One", "org-one", creator=owner, role="owner")
    add_membership(org1, member, role="member")

    org2 = create_test_org("Org Two", "org-two", creator=other_user, role="owner")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Member lists members of Org1
        resp = await client.get(
            f"/api/organizations/{org1.id}/members",
            headers=auth_headers(member),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2

        user_ids = [m["user_id"] for m in data]
        emails = [m["email"] for m in data]
        roles = {m["email"]: m["role"] for m in data}

        assert owner.id in user_ids
        assert member.id in user_ids
        assert other_user.id not in user_ids

        assert "owner@example.com" in emails
        assert "member@example.com" in emails
        assert "other@example.com" not in emails

        assert roles["owner@example.com"] == "owner"
        assert roles["member@example.com"] == "member"

        # Check no sensitive fields exposed
        for m in data:
            assert "password" not in m
            assert "hashed_password" not in m
            assert "token" not in m
            assert "created_at" in m


@pytest.mark.asyncio
async def test_list_members_permissions():
    """Verify list members access control: non-member rejected, superuser allowed."""
    owner = create_test_user("owner@example.com")
    stranger = create_test_user("stranger@example.com")
    superuser = create_test_user("superuser@example.com", is_superuser=True)

    org = create_test_org("Acme Corp", "acme-corp", creator=owner, role="owner")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Unauthenticated -> 401
        resp = await client.get(f"/api/organizations/{org.id}/members")
        assert resp.status_code == 401

        # Non-member -> 403
        resp = await client.get(
            f"/api/organizations/{org.id}/members",
            headers=auth_headers(stranger),
        )
        assert resp.status_code == 403

        # Superuser -> 200 (even without direct membership)
        resp = await client.get(
            f"/api/organizations/{org.id}/members",
            headers=auth_headers(superuser),
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 1


# ---------------------------------------------------------------------------
# Part A.2: Add Member
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_add_member_owner_success():
    """Verify organization owner can add an existing registered user."""
    owner = create_test_user("owner@example.com")
    colleague = create_test_user("colleague@example.com")
    org = create_test_org("TechOrg", "tech-org", creator=owner, role="owner")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/api/organizations/{org.id}/members",
            json={"email": "colleague@example.com", "role": "member"},
            headers=auth_headers(owner),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["user_id"] == colleague.id
        assert data["email"] == colleague.email
        assert data["role"] == "member"
        assert data["created_at"] is not None

        # Verify membership exists in DB
        with SessionLocal() as db:
            m = db.query(OrganizationMembership).filter(
                OrganizationMembership.org_id == org.id,
                OrganizationMembership.user_id == colleague.id,
            ).first()
            assert m is not None
            assert m.role == "member"


@pytest.mark.asyncio
async def test_add_member_admin_permissions():
    """Verify admin can add 'member' role only; granting admin or owner returns 403."""
    owner = create_test_user("owner@example.com")
    admin = create_test_user("admin@example.com")
    user1 = create_test_user("user1@example.com")
    user2 = create_test_user("user2@example.com")

    org = create_test_org("DevCorp", "dev-corp", creator=owner, role="owner")
    add_membership(org, admin, role="admin")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Admin adds user1 with 'member' -> succeeds (201)
        resp = await client.post(
            f"/api/organizations/{org.id}/members",
            json={"email": "user1@example.com", "role": "member"},
            headers=auth_headers(admin),
        )
        assert resp.status_code == 201

        # Admin attempts to add user2 with 'admin' -> 403 Forbidden
        resp = await client.post(
            f"/api/organizations/{org.id}/members",
            json={"email": "user2@example.com", "role": "admin"},
            headers=auth_headers(admin),
        )
        assert resp.status_code == 403

        # Admin attempts to add user2 with 'owner' -> 403 Forbidden
        resp = await client.post(
            f"/api/organizations/{org.id}/members",
            json={"email": "user2@example.com", "role": "owner"},
            headers=auth_headers(admin),
        )
        assert resp.status_code == 403


@pytest.mark.asyncio
async def test_add_member_regular_member_forbidden():
    """Verify standard 'member' role cannot add members (403 Forbidden)."""
    owner = create_test_user("owner@example.com")
    member = create_test_user("member@example.com")
    target = create_test_user("target@example.com")

    org = create_test_org("DevCorp", "dev-corp", creator=owner, role="owner")
    add_membership(org, member, role="member")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/api/organizations/{org.id}/members",
            json={"email": "target@example.com", "role": "member"},
            headers=auth_headers(member),
        )
        assert resp.status_code == 403


@pytest.mark.asyncio
async def test_add_member_unknown_email_and_duplicate():
    """Verify 404 for unknown email and 409 for duplicate membership."""
    owner = create_test_user("owner@example.com")
    existing_member = create_test_user("existing@example.com")

    org = create_test_org("DevCorp", "dev-corp", creator=owner, role="owner")
    add_membership(org, existing_member, role="member")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Unknown email -> 404
        resp = await client.post(
            f"/api/organizations/{org.id}/members",
            json={"email": "ghost@example.com", "role": "member"},
            headers=auth_headers(owner),
        )
        assert resp.status_code == 404

        # Duplicate membership -> 409 Conflict
        resp = await client.post(
            f"/api/organizations/{org.id}/members",
            json={"email": "existing@example.com", "role": "member"},
            headers=auth_headers(owner),
        )
        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Part A.3: Change Member Role
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_change_member_role_owner_promotions():
    """Verify owner can promote members to admin or owner."""
    owner = create_test_user("owner@example.com")
    member = create_test_user("member@example.com")

    org = create_test_org("RoleOrg", "role-org", creator=owner, role="owner")
    add_membership(org, member, role="member")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Promote to admin -> 200
        resp = await client.patch(
            f"/api/organizations/{org.id}/members/{member.id}",
            json={"role": "admin"},
            headers=auth_headers(owner),
        )
        assert resp.status_code == 200
        assert resp.json()["role"] == "admin"

        # Promote to owner -> 200
        resp = await client.patch(
            f"/api/organizations/{org.id}/members/{member.id}",
            json={"role": "owner"},
            headers=auth_headers(owner),
        )
        assert resp.status_code == 200
        assert resp.json()["role"] == "owner"


@pytest.mark.asyncio
async def test_change_member_role_admin_restrictions():
    """Verify admin cannot modify owners, other admins, or grant admin/owner roles."""
    owner = create_test_user("owner@example.com")
    admin1 = create_test_user("admin1@example.com")
    admin2 = create_test_user("admin2@example.com")
    member = create_test_user("member@example.com")

    org = create_test_org("RoleOrg", "role-org", creator=owner, role="owner")
    add_membership(org, admin1, role="admin")
    add_membership(org, admin2, role="admin")
    add_membership(org, member, role="member")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Admin1 attempts to modify owner -> 403 Forbidden
        resp = await client.patch(
            f"/api/organizations/{org.id}/members/{owner.id}",
            json={"role": "member"},
            headers=auth_headers(admin1),
        )
        assert resp.status_code == 403

        # Admin1 attempts to modify Admin2 -> 403 Forbidden
        resp = await client.patch(
            f"/api/organizations/{org.id}/members/{admin2.id}",
            json={"role": "member"},
            headers=auth_headers(admin1),
        )
        assert resp.status_code == 403

        # Admin1 attempts to promote Member to admin -> 403 Forbidden
        resp = await client.patch(
            f"/api/organizations/{org.id}/members/{member.id}",
            json={"role": "admin"},
            headers=auth_headers(admin1),
        )
        assert resp.status_code == 403

        # Admin1 attempts to promote Member to owner -> 403 Forbidden
        resp = await client.patch(
            f"/api/organizations/{org.id}/members/{member.id}",
            json={"role": "owner"},
            headers=auth_headers(admin1),
        )
        assert resp.status_code == 403


@pytest.mark.asyncio
async def test_last_owner_demotion_guard():
    """Verify that demoting the sole owner is blocked (409 Conflict)."""
    sole_owner = create_test_user("soleowner@example.com")
    org = create_test_org("SoloOrg", "solo-org", creator=sole_owner, role="owner")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Demote to admin -> 409 Conflict
        resp = await client.patch(
            f"/api/organizations/{org.id}/members/{sole_owner.id}",
            json={"role": "admin"},
            headers=auth_headers(sole_owner),
        )
        assert resp.status_code == 409
        assert "last remaining owner" in resp.json()["detail"].lower()

        # Demote to member -> 409 Conflict
        resp = await client.patch(
            f"/api/organizations/{org.id}/members/{sole_owner.id}",
            json={"role": "member"},
            headers=auth_headers(sole_owner),
        )
        assert resp.status_code == 409


@pytest.mark.asyncio
async def test_demotion_allowed_when_multiple_owners():
    """Verify owner demotion succeeds when another owner is present."""
    owner1 = create_test_user("owner1@example.com")
    owner2 = create_test_user("owner2@example.com")

    org = create_test_org("MultiOwnerOrg", "multi-owner-org", creator=owner1, role="owner")
    add_membership(org, owner2, role="owner")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Owner1 demotes Owner2 to admin -> 200 OK
        resp = await client.patch(
            f"/api/organizations/{org.id}/members/{owner2.id}",
            json={"role": "admin"},
            headers=auth_headers(owner1),
        )
        assert resp.status_code == 200
        assert resp.json()["role"] == "admin"


# ---------------------------------------------------------------------------
# Part A.4: Remove Member
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_remove_member_owner_and_admin():
    """Verify member removal rules for owners and admins."""
    owner = create_test_user("owner@example.com")
    admin = create_test_user("admin@example.com")
    member1 = create_test_user("member1@example.com")
    member2 = create_test_user("member2@example.com")

    org = create_test_org("RemovalOrg", "removal-org", creator=owner, role="owner")
    add_membership(org, admin, role="admin")
    add_membership(org, member1, role="member")
    add_membership(org, member2, role="member")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Admin removes Member1 -> 204 No Content
        resp = await client.delete(
            f"/api/organizations/{org.id}/members/{member1.id}",
            headers=auth_headers(admin),
        )
        assert resp.status_code == 204

        # Admin attempts to remove Owner -> 403 Forbidden
        resp = await client.delete(
            f"/api/organizations/{org.id}/members/{owner.id}",
            headers=auth_headers(admin),
        )
        assert resp.status_code == 403

        # Member2 attempts to remove Admin -> 403 Forbidden
        resp = await client.delete(
            f"/api/organizations/{org.id}/members/{admin.id}",
            headers=auth_headers(member2),
        )
        assert resp.status_code == 403

        # Owner removes Admin -> 204 No Content
        resp = await client.delete(
            f"/api/organizations/{org.id}/members/{admin.id}",
            headers=auth_headers(owner),
        )
        assert resp.status_code == 204


@pytest.mark.asyncio
async def test_last_owner_removal_guard():
    """Verify removing the last owner is blocked with 409 Conflict."""
    sole_owner = create_test_user("soleowner@example.com")
    org = create_test_org("SoloRemovalOrg", "solo-removal-org", creator=sole_owner, role="owner")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.delete(
            f"/api/organizations/{org.id}/members/{sole_owner.id}",
            headers=auth_headers(sole_owner),
        )
        assert resp.status_code == 409
        assert "last remaining owner" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Part A.5: Voluntary Departure (Leave)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_voluntary_leave_member_and_admin():
    """Verify members and admins can leave an organization voluntarily."""
    owner = create_test_user("owner@example.com")
    member = create_test_user("member@example.com")
    admin = create_test_user("admin@example.com")

    org = create_test_org("LeaveOrg", "leave-org", creator=owner, role="owner")
    add_membership(org, member, role="member")
    add_membership(org, admin, role="admin")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Member leaves -> 204
        resp = await client.post(
            f"/api/organizations/{org.id}/leave",
            headers=auth_headers(member),
        )
        assert resp.status_code == 204

        # Admin leaves -> 204
        resp = await client.post(
            f"/api/organizations/{org.id}/leave",
            headers=auth_headers(admin),
        )
        assert resp.status_code == 204

        # Verify DB: only owner remains
        with SessionLocal() as db:
            remaining = db.query(OrganizationMembership).filter(
                OrganizationMembership.org_id == org.id
            ).all()
            assert len(remaining) == 1
            assert remaining[0].user_id == owner.id


@pytest.mark.asyncio
async def test_voluntary_leave_sole_owner_blocked():
    """Verify sole owner is blocked from leaving (409 Conflict)."""
    sole_owner = create_test_user("soleowner@example.com")
    org = create_test_org("SoloLeaveOrg", "solo-leave-org", creator=sole_owner, role="owner")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/api/organizations/{org.id}/leave",
            headers=auth_headers(sole_owner),
        )
        assert resp.status_code == 409
        assert "transfer ownership" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_voluntary_leave_owner_allowed_when_co_owner_exists():
    """Verify owner can leave when another owner exists."""
    owner1 = create_test_user("owner1@example.com")
    owner2 = create_test_user("owner2@example.com")

    org = create_test_org("CoOwnerOrg", "co-owner-org", creator=owner1, role="owner")
    add_membership(org, owner2, role="owner")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/api/organizations/{org.id}/leave",
            headers=auth_headers(owner1),
        )
        assert resp.status_code == 204

        # Owner2 is now sole owner
        with SessionLocal() as db:
            remaining = db.query(OrganizationMembership).filter(
                OrganizationMembership.org_id == org.id
            ).all()
            assert len(remaining) == 1
            assert remaining[0].user_id == owner2.id


@pytest.mark.asyncio
async def test_leave_preserves_other_memberships_and_account():
    """Verify leaving one org does not affect the user's account or other memberships."""
    user = create_test_user("multiuser@example.com")
    org1 = create_test_org("Org A", "org-a", creator=user, role="member")
    org2 = create_test_org("Org B", "org-b", creator=user, role="owner")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/api/organizations/{org1.id}/leave",
            headers=auth_headers(user),
        )
        assert resp.status_code == 204

        # Check DB: user still exists and retains membership in org2
        with SessionLocal() as db:
            u = db.query(User).filter(User.id == user.id).first()
            assert u is not None

            memberships = db.query(OrganizationMembership).filter(
                OrganizationMembership.user_id == user.id
            ).all()
            assert len(memberships) == 1
            assert memberships[0].org_id == org2.id


# ---------------------------------------------------------------------------
# Part D: Immediate Access Revocation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_immediate_access_revocation_on_removal():
    """Verify that removing a member immediately revokes their access on the next request."""
    owner = create_test_user("owner@example.com")
    member = create_test_user("member@example.com")

    org = create_test_org("RevokeOrg", "revoke-org", creator=owner, role="owner")
    add_membership(org, member, role="member")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Member accesses org -> 200 OK
        resp = await client.get(
            f"/api/organizations/{org.id}",
            headers=auth_headers(member),
        )
        assert resp.status_code == 200

        # Owner removes member -> 204 No Content
        del_resp = await client.delete(
            f"/api/organizations/{org.id}/members/{member.id}",
            headers=auth_headers(owner),
        )
        assert del_resp.status_code == 204

        # Member attempts to access org again -> immediately 403 Forbidden
        resp_after = await client.get(
            f"/api/organizations/{org.id}",
            headers=auth_headers(member),
        )
        assert resp_after.status_code == 403


# ---------------------------------------------------------------------------
# Preservation of Evidence (Runs, Results, Artifacts)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_member_removal_preserves_test_evidence():
    """Verify that removing a member preserves test cases, runs, results, and artifacts."""
    owner = create_test_user("owner@example.com")
    member = create_test_user("member@example.com")

    org = create_test_org("EvidenceOrg", "evidence-org", creator=owner, role="owner")
    add_membership(org, member, role="member")

    # Create project, test case, test run, result, artifact
    with SessionLocal() as db:
        project = Project(
            id=str(uuid.uuid4()),
            org_id=org.id,
            name="Evidence Project",
            slug="evidence-project",
            app_url="https://example.com",
        )
        db.add(project)
        db.flush()

        tc = TestCase(
            id=str(uuid.uuid4()),
            project_id=project.id,
            name="Login Test",
            created_by=member.email,
        )
        db.add(tc)
        db.flush()

        run = TestRun(
            id=str(uuid.uuid4()),
            project_id=project.id,
            triggered_by=member.email,
            status="passed",
            total_tests=1,
            passed_tests=1,
        )
        db.add(run)
        db.flush()

        res = TestResult(
            id=str(uuid.uuid4()),
            run_id=run.id,
            test_case_id=tc.id,
            status="passed",
        )
        db.add(res)
        db.flush()

        artifact = Artifact(
            id=str(uuid.uuid4()),
            run_id=run.id,
            artifact_type="screenshot",
            file_path="screenshots/test.png",
        )
        db.add(artifact)
        db.commit()

        p_id, tc_id, r_id, res_id, art_id = project.id, tc.id, run.id, res.id, artifact.id

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Remove member
        resp = await client.delete(
            f"/api/organizations/{org.id}/members/{member.id}",
            headers=auth_headers(owner),
        )
        assert resp.status_code == 204

    # Verify all testing records still exist
    with SessionLocal() as db:
        assert db.query(Project).filter(Project.id == p_id).first() is not None
        assert db.query(TestCase).filter(TestCase.id == tc_id).first() is not None
        assert db.query(TestRun).filter(TestRun.id == r_id).first() is not None
        assert db.query(TestResult).filter(TestResult.id == res_id).first() is not None
        assert db.query(Artifact).filter(Artifact.id == art_id).first() is not None


# ---------------------------------------------------------------------------
# Part B: Database-Level Composite Uniqueness Enforcement
# ---------------------------------------------------------------------------

def test_db_composite_uniqueness_enforcement():
    """Verify that the database schema enforces uniqueness on (org_id, user_id)."""
    owner = create_test_user("dbowner@example.com")
    org = create_test_org("UniqueDBOrg", "unique-db-org", creator=owner, role="owner")

    with SessionLocal() as db:
        # First membership already created by helper
        # Attempting to insert a duplicate (org_id, user_id) directly at ORM/DB level
        duplicate = OrganizationMembership(
            id=str(uuid.uuid4()),
            org_id=org.id,
            user_id=owner.id,
            role="admin",
        )
        db.add(duplicate)
        with pytest.raises(IntegrityError):
            db.commit()
