"""
Comprehensive tests for Open Sign-Up / User Registration:
- Successful registration with default or custom workspace
- Automatic organization onboarding and ownership
- Multi-tenant organization isolation between registered users
- Secure bcrypt password hashing and immediate login
- Duplicate email conflict rejection
- Input validation (email format, password constraints)
- Sliding-window rate limiting on registration
"""
from datetime import datetime, timezone
import pytest
from httpx import ASGITransport, AsyncClient

import app.models  # noqa: F401
from app.config import get_settings
from app.database import Base, engine, SessionLocal
from app.main import app
from app.models.organization import Organization, OrganizationMembership
from app.models.user import User
from app.services.rate_limiter import register_rate_limiter
from app.services.security import verify_password

settings = get_settings()


@pytest.fixture(autouse=True)
def clean_db_and_rate_limiter():
    """Ensure clean database schema and reset registration rate limiter."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with register_rate_limiter._lock:
        register_rate_limiter._failures.clear()
    original_allow = settings.ALLOW_PUBLIC_REGISTRATION
    settings.ALLOW_PUBLIC_REGISTRATION = True
    yield
    settings.ALLOW_PUBLIC_REGISTRATION = original_allow
    Base.metadata.drop_all(bind=engine)
    with register_rate_limiter._lock:
        register_rate_limiter._failures.clear()


@pytest.mark.asyncio
async def test_successful_registration_creates_user_and_personal_workspace():
    """New user registers successfully, receives JWT + cookie, and owns their initial workspace."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/auth/register",
            json={
                "email": "sarah.connor@example.com",
                "password": "SecurePassword123!",
                "full_name": "Sarah Connor",
            },
        )

    assert response.status_code == 201
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["email"] == "sarah.connor@example.com"
    assert data["user"]["full_name"] == "Sarah Connor"
    assert data["user"]["is_active"] is True
    assert data["user"]["is_superuser"] is False

    # Check cookies
    cookies = response.cookies
    assert "access_token" in cookies

    # Verify database state
    with SessionLocal() as db:
        user = db.query(User).filter(User.email == "sarah.connor@example.com").first()
        assert user is not None
        assert user.is_active is True
        assert user.is_superuser is False

        # Verify initial workspace organization was created
        memberships = (
            db.query(OrganizationMembership)
            .filter(OrganizationMembership.user_id == user.id)
            .all()
        )
        assert len(memberships) == 1
        membership = memberships[0]
        assert membership.role == "owner"

        org = db.query(Organization).filter(Organization.id == membership.org_id).first()
        assert org is not None
        assert org.name == "Sarah Connor's Workspace"
        assert org.slug.startswith("sarah-connor")


@pytest.mark.asyncio
async def test_successful_registration_with_custom_organization_name():
    """User can optionally specify their organization name during registration."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/auth/register",
            json={
                "email": "ceo@cyberdyne.io",
                "password": "SkynetLaunch2026!",
                "full_name": "Miles Dyson",
                "organization_name": "Cyberdyne Systems",
            },
        )

    assert response.status_code == 201

    with SessionLocal() as db:
        user = db.query(User).filter(User.email == "ceo@cyberdyne.io").first()
        membership = (
            db.query(OrganizationMembership)
            .filter(OrganizationMembership.user_id == user.id)
            .first()
        )
        assert membership is not None
        assert membership.role == "owner"

        org = db.query(Organization).filter(Organization.id == membership.org_id).first()
        assert org.name == "Cyberdyne Systems"
        assert org.slug == "cyberdyne-systems"


@pytest.mark.asyncio
async def test_registration_duplicate_email_rejected_case_insensitively():
    """Registering with an already registered email (even with different case) returns 409 Conflict."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r1 = await client.post(
            "/api/auth/register",
            json={
                "email": "john.doe@example.com",
                "password": "ValidPassword123!",
                "full_name": "John Doe",
            },
        )
        assert r1.status_code == 201

        # Second attempt with uppercase
        r2 = await client.post(
            "/api/auth/register",
            json={
                "email": "JOHN.DOE@example.com",
                "password": "AnotherPassword123!",
                "full_name": "John Duplicate",
            },
        )
        assert r2.status_code == 409
        assert "already exists" in r2.json()["detail"].lower()


@pytest.mark.asyncio
async def test_registration_validation_errors():
    """Invalid email format, empty password, or password shorter than 8 characters returns 422."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Invalid email
        r_email = await client.post(
            "/api/auth/register",
            json={"email": "not-valid", "password": "ValidPassword123!"},
        )
        assert r_email.status_code == 422

        # Short password
        r_short = await client.post(
            "/api/auth/register",
            json={"email": "valid@example.com", "password": "short"},
        )
        assert r_short.status_code == 422

        # Missing password
        r_missing = await client.post(
            "/api/auth/register",
            json={"email": "valid@example.com"},
        )
        assert r_missing.status_code == 422


@pytest.mark.asyncio
async def test_registration_password_securely_hashed():
    """Plaintext password must never be stored in database; only bcrypt hash is persisted."""
    raw_password = "MySuperSecretPassword99!"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post(
            "/api/auth/register",
            json={"email": "vault@example.com", "password": raw_password},
        )

    with SessionLocal() as db:
        user = db.query(User).filter(User.email == "vault@example.com").first()
        assert user.hashed_password != raw_password
        assert user.hashed_password.startswith("$2b$") or user.hashed_password.startswith("$2a$")
        assert verify_password(raw_password, user.hashed_password) is True
        assert verify_password("WrongPassword!", user.hashed_password) is False


@pytest.mark.asyncio
async def test_login_immediately_after_registration():
    """A registered user can immediately log in through /api/auth/login with the new password."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        reg_res = await client.post(
            "/api/auth/register",
            json={
                "email": "login_test@example.com",
                "password": "PasswordTest123!",
                "full_name": "Login Tester",
            },
        )
        assert reg_res.status_code == 201

        # Log in
        login_res = await client.post(
            "/api/auth/login",
            json={
                "email": "login_test@example.com",
                "password": "PasswordTest123!",
            },
        )
        assert login_res.status_code == 200
        assert "access_token" in login_res.json()
        assert login_res.json()["user"]["email"] == "login_test@example.com"


@pytest.mark.asyncio
async def test_multi_tenant_organization_isolation_between_registered_users():
    """Two newly registered users have strict organization boundaries and cannot view each other's data."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Register User A
        res_a = await client.post(
            "/api/auth/register",
            json={
                "email": "usera@example.com",
                "password": "UserAPassword123!",
                "full_name": "User Alpha",
            },
        )
        token_a = res_a.json()["access_token"]

        # Register User B
        res_b = await client.post(
            "/api/auth/register",
            json={
                "email": "userb@example.com",
                "password": "UserBPassword123!",
                "full_name": "User Beta",
            },
        )
        token_b = res_b.json()["access_token"]

        # List organizations for User A
        list_a = await client.get(
            "/api/organizations",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        orgs_a = list_a.json()
        assert len(orgs_a) == 1
        org_a_id = orgs_a[0]["id"]
        assert orgs_a[0]["name"] == "User Alpha's Workspace"

        # List organizations for User B
        list_b = await client.get(
            "/api/organizations",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        orgs_b = list_b.json()
        assert len(orgs_b) == 1
        org_b_id = orgs_b[0]["id"]
        assert orgs_b[0]["name"] == "User Beta's Workspace"

        # User A cannot view User B's organization
        access_b_as_a = await client.get(
            f"/api/organizations/{org_b_id}",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert access_b_as_a.status_code in (403, 404)

        # User B cannot view User A's organization
        access_a_as_b = await client.get(
            f"/api/organizations/{org_a_id}",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert access_a_as_b.status_code in (403, 404)


@pytest.mark.asyncio
async def test_slug_collision_resolution():
    """Registering users with the same organization name automatically increments the slug."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r1 = await client.post(
            "/api/auth/register",
            json={
                "email": "user1@company.com",
                "password": "Password123!",
                "organization_name": "Common Workspace",
            },
        )
        assert r1.status_code == 201

        r2 = await client.post(
            "/api/auth/register",
            json={
                "email": "user2@company.com",
                "password": "Password123!",
                "organization_name": "Common Workspace",
            },
        )
        assert r2.status_code == 201

    with SessionLocal() as db:
        orgs = db.query(Organization).filter(Organization.name == "Common Workspace").order_by(Organization.created_at).all()
        assert len(orgs) == 2
        assert orgs[0].slug == "common-workspace"
        assert orgs[1].slug == "common-workspace-1"


@pytest.mark.asyncio
async def test_registration_rate_limiting():
    """Exceeding 10 registration attempts from the same IP/email within 5 minutes returns 429."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for i in range(10):
            res = await client.post(
                "/api/auth/register",
                json={
                    "email": f"rate_user_{i}@example.com",
                    "password": "Password123!",
                },
            )
            assert res.status_code == 201

        # 11th request triggers rate limit
        blocked = await client.post(
            "/api/auth/register",
            json={
                "email": "rate_user_blocked@example.com",
                "password": "Password123!",
            },
        )
        assert blocked.status_code == 429
        assert "Too many registration attempts" in blocked.json()["detail"]
