"""
Comprehensive authentication, authorization, and tenant isolation tests.
Tests registration policies, bootstrap, secret validation, rate limiting,
token revocation, CSRF defenses, and cross-tenant artifact boundaries.
"""
import secrets
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from jose import jwt

import app.models  # noqa: F401
from app.config import Settings, get_settings
from app.database import Base, SessionLocal, engine
from app.main import app
from app.models.organization import Organization, OrganizationMembership
from app.models.project import Project
from app.models.test_case import TestCase
from app.models.test_run import Artifact, TestRun
from app.models.user import User
from app.services.bootstrap import create_initial_admin
from app.services.rate_limiter import login_rate_limiter
from app.services.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    revoke_token,
)

TestCase.__test__ = False
TestRun.__test__ = False

settings = get_settings()


@pytest.fixture(autouse=True)
def clean_db():
    """Ensure every test runs against a clean database schema and clean rate limiter."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    # Reset rate limiter
    with login_rate_limiter._lock:
        login_rate_limiter._failures.clear()
    yield
    Base.metadata.drop_all(bind=engine)


# ---------------------------------------------------------------------------
# Priority 1: Registration and Bootstrap Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_public_registration_disabled_by_default():
    """Public registration is disabled by default and returns 403 Forbidden."""
    original_setting = settings.ALLOW_PUBLIC_REGISTRATION
    settings.ALLOW_PUBLIC_REGISTRATION = False
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/auth/register",
                json={
                    "email": "intruder@example.com",
                    "password": "Password123!",
                    "full_name": "Intruder",
                },
            )
        assert response.status_code == 403
        assert "registration is disabled" in response.json()["detail"].lower()
    finally:
        settings.ALLOW_PUBLIC_REGISTRATION = original_setting


@pytest.mark.asyncio
async def test_public_registration_when_enabled_creates_standard_user():
    """When public registration is explicitly enabled, users are created as standard users (is_superuser=False)."""
    original_setting = settings.ALLOW_PUBLIC_REGISTRATION
    settings.ALLOW_PUBLIC_REGISTRATION = True
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/auth/register",
                json={
                    "email": "newuser@example.com",
                    "password": "Password123!",
                    "full_name": "New User",
                },
            )
        assert response.status_code == 201
        data = response.json()
        assert data["user"]["email"] == "newuser@example.com"
        assert data["user"]["is_superuser"] is False
        assert data["user"]["is_active"] is True
    finally:
        settings.ALLOW_PUBLIC_REGISTRATION = original_setting


@pytest.mark.asyncio
async def test_initial_admin_bootstrap_service():
    """The controlled bootstrap service provisions only the superuser without auto-assigning memberships."""
    with SessionLocal() as db:
        admin = create_initial_admin(
            db=db,
            email="admin@noetrix.local",
            password="AdminPassword123!",
            full_name="Noetrix Administrator",
        )
        assert admin.id is not None
        assert admin.email == "admin@noetrix.local"
        assert admin.is_superuser is True
        assert admin.is_active is True

        # Verify admin has NO automatic organization membership (decoupled from demo org)
        memberships = db.query(OrganizationMembership).filter(OrganizationMembership.user_id == admin.id).all()
        assert len(memberships) == 0


@pytest.mark.asyncio
async def test_admin_bootstrap_creates_no_demo_membership_and_preserves_records():
    """Administrator provisioning creates strictly the User record and preserves all existing demo records."""
    with SessionLocal() as db:
        # Pre-populate demo organization, project, test case, run, and artifact
        org = Organization(name="TestPilot Demo", slug="testpilot-demo", description="Demo workspace")
        db.add(org)
        db.flush()

        proj = Project(name="Demo Project", slug="demo-project", org_id=org.id)
        db.add(proj)
        db.flush()

        tc = TestCase(name="Demo Test Case", project_id=proj.id, is_active=True)
        db.add(tc)
        db.flush()

        run = TestRun(project_id=proj.id, status="passed", total_tests=1, passed_tests=1, failed_tests=0)
        db.add(run)
        db.flush()

        artifact = Artifact(run_id=run.id, artifact_type="screenshot", file_path="artifacts/demo.png")
        db.add(artifact)
        db.commit()

        # Capture pre-bootstrap state
        org_id, org_name, org_slug = org.id, org.name, org.slug
        proj_id, proj_name = proj.id, proj.name
        tc_id = tc.id
        run_id = run.id
        artifact_id = artifact.id

        # Provision initial administrator
        admin = create_initial_admin(
            db=db,
            email="new_superadmin@noetrix.local",
            password="StrongAdminPassword123!",
            full_name="Platform Superadmin",
        )
        assert admin.is_superuser is True

        # Verify NO organization membership was created
        membership_count = db.query(OrganizationMembership).count()
        assert membership_count == 0

        # Verify existing demo organization is completely untouched
        refreshed_org = db.query(Organization).filter(Organization.id == org_id).first()
        assert refreshed_org is not None
        assert refreshed_org.name == org_name
        assert refreshed_org.slug == org_slug

        # Verify existing projects, test cases, runs, and artifacts remain intact
        assert db.query(Project).filter(Project.id == proj_id).first() is not None
        assert db.query(TestCase).filter(TestCase.id == tc_id).first() is not None
        assert db.query(TestRun).filter(TestRun.id == run_id).first() is not None
        assert db.query(Artifact).filter(Artifact.id == artifact_id).first() is not None


@pytest.mark.asyncio
async def test_initial_admin_bootstrap_rejects_second_admin():
    """Attempting to provision a second initial administrator via the bootstrap service is rejected."""
    with SessionLocal() as db:
        create_initial_admin(
            db=db,
            email="first_admin@noetrix.local",
            password="AdminPassword123!",
        )

        with pytest.raises(ValueError, match="already exists"):
            create_initial_admin(
                db=db,
                email="second_admin@noetrix.local",
                password="AnotherPassword123!",
            )



@pytest.mark.asyncio
async def test_register_duplicate_email_rejected():
    """Registration with an already existing email address returns 409 Conflict."""
    original_setting = settings.ALLOW_PUBLIC_REGISTRATION
    settings.ALLOW_PUBLIC_REGISTRATION = True
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r1 = await client.post(
                "/api/auth/register",
                json={"email": "duplicate@example.com", "password": "Password123!"},
            )
            assert r1.status_code == 201

            r2 = await client.post(
                "/api/auth/register",
                json={"email": "duplicate@example.com", "password": "DifferentPassword123!"},
            )
            assert r2.status_code == 409
            assert "already exists" in r2.json()["detail"].lower()
    finally:
        settings.ALLOW_PUBLIC_REGISTRATION = original_setting


@pytest.mark.asyncio
async def test_register_validation_errors():
    """Invalid email format or password shorter than 8 characters must return 422."""
    original_setting = settings.ALLOW_PUBLIC_REGISTRATION
    settings.ALLOW_PUBLIC_REGISTRATION = True
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r_short = await client.post(
                "/api/auth/register",
                json={"email": "valid@example.com", "password": "short"},
            )
            assert r_short.status_code == 422

            r_bad_email = await client.post(
                "/api/auth/register",
                json={"email": "not-an-email", "password": "Password123!"},
            )
            assert r_bad_email.status_code == 422
    finally:
        settings.ALLOW_PUBLIC_REGISTRATION = original_setting


# ---------------------------------------------------------------------------
# Priority 2: Production Secret Validation Tests
# ---------------------------------------------------------------------------

def test_production_secret_key_validation(monkeypatch):
    """Production settings enforce explicit configuration and minimum key checks."""
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(ValueError, match="explicitly configured"):
        Settings(_env_file=None, ENVIRONMENT="production")

    # Known repository and common placeholder values are rejected.
    placeholders = (
        "change-me-in-production",
        "change-this-in-production",
        "change-this-to-a-long-random-string-in-production",
        "local-development-only-not-for-production",
        "test-secret-key-12345678901234567890",
        "secret",
        "password",
        "12345678",
        "change-me",
        "test-secret-key-123",
    )
    for placeholder in placeholders:
        with pytest.raises(ValueError, match="Default or insecure SECRET_KEY"):
            Settings(ENVIRONMENT="production", SECRET_KEY=placeholder)

    # Short secret (< 32 chars) rejected in production.
    with pytest.raises(ValueError, match="minimum length of 32 characters"):
        Settings(ENVIRONMENT="production", SECRET_KEY="too-short-production-key")

    # Repeated characters fail the minimum format check; this is not an entropy proof.
    weak_secret = "a" * 32
    with pytest.raises(ValueError, match="8 distinct characters") as exc_info:
        Settings(ENVIRONMENT="production", SECRET_KEY=weak_secret)
    assert weak_secret not in str(exc_info.value)

    # A runtime-generated value meeting the minimum checks is accepted.
    generated_secret = secrets.token_urlsafe(48)
    prod_settings = Settings(
        ENVIRONMENT="production",
        SECRET_KEY=generated_secret,
    )
    assert prod_settings.SECRET_KEY == generated_secret


def test_development_and_test_secret_behavior_is_preserved(monkeypatch):
    """Development defaults and explicit test secrets remain valid outside production."""
    monkeypatch.delenv("SECRET_KEY", raising=False)
    development = Settings(_env_file=None, ENVIRONMENT="development")
    assert development.SECRET_KEY == "change-me-in-production"

    test_settings = Settings(
        _env_file=None,
        ENVIRONMENT="test",
        SECRET_KEY="test-secret-key-12345678901234567890",
    )
    assert test_settings.SECRET_KEY == "test-secret-key-12345678901234567890"


# ---------------------------------------------------------------------------
# Priority 4: Authentication, CSRF, Token Revocation, Rate Limiting
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_login_successful_sets_cookie_and_returns_token():
    """Valid credentials return a JWT access token and set an HttpOnly cookie."""
    with SessionLocal() as db:
        user = User(
            email="user@example.com",
            hashed_password=hash_password("Password123!"),
            is_active=True,
        )
        db.add(user)
        db.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/auth/login",
            json={"email": "user@example.com", "password": "Password123!"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["user"]["email"] == "user@example.com"
        assert "access_token" in response.cookies


@pytest.mark.asyncio
async def test_login_invalid_credentials():
    """Incorrect password or nonexistent email returns 401 with generic error."""
    with SessionLocal() as db:
        user = User(
            email="user@example.com",
            hashed_password=hash_password("Password123!"),
            is_active=True,
        )
        db.add(user)
        db.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r1 = await client.post(
            "/api/auth/login",
            json={"email": "user@example.com", "password": "WrongPassword!"},
        )
        assert r1.status_code == 401
        assert "invalid email or password" in r1.json()["detail"].lower()

        r2 = await client.post(
            "/api/auth/login",
            json={"email": "nobody@example.com", "password": "Password123!"},
        )
        assert r2.status_code == 401
        assert "invalid email or password" in r2.json()["detail"].lower()


@pytest.mark.asyncio
async def test_login_rate_limiting():
    """Exceeding 5 failed login attempts triggers HTTP 429 Too Many Requests."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for _ in range(5):
            res = await client.post(
                "/api/auth/login",
                json={"email": "victim@example.com", "password": "WrongPassword!"},
            )
            assert res.status_code == 401

        # 6th attempt must be rate-limited
        res_blocked = await client.post(
            "/api/auth/login",
            json={"email": "victim@example.com", "password": "WrongPassword!"},
        )
        assert res_blocked.status_code == 429
        assert "too many failed login attempts" in res_blocked.json()["detail"].lower()


@pytest.mark.asyncio
async def test_login_inactive_user_rejected():
    """Inactive accounts cannot authenticate."""
    with SessionLocal() as db:
        user = User(
            email="inactive@example.com",
            hashed_password=hash_password("Password123!"),
            is_active=False,
        )
        db.add(user)
        db.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/auth/login",
            json={"email": "inactive@example.com", "password": "Password123!"},
        )
    assert response.status_code == 403
    assert "inactive" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_logout_invalidates_token_and_cookie():
    """Logging out revokes the active token and deletes the cookie."""
    with SessionLocal() as db:
        user = User(
            email="logout_test@example.com",
            hashed_password=hash_password("Password123!"),
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        user_id = user.id

    token = create_access_token(data={"sub": user_id, "email": "logout_test@example.com"})

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Verify token is initially valid
        r_before = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r_before.status_code == 200

        # Logout
        r_logout = await client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token}"})
        assert r_logout.status_code == 200

        # Verify token is now revoked and rejected with 401
        r_after = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r_after.status_code == 401
        assert "revoked" in r_after.json()["detail"].lower()


@pytest.mark.asyncio
async def test_jwt_alg_none_and_unsupported_rejected():
    """JWT tokens with 'alg': 'none' or unsupported algorithms must be rejected with 401."""
    import base64
    import json

    with SessionLocal() as db:
        user = User(email="test@example.com", hashed_password=hash_password("Password123!"), is_active=True)
        db.add(user)
        db.commit()
        db.refresh(user)
        user_id = user.id

    # Construct forged token with alg=none
    hdr = base64.urlsafe_b64encode(json.dumps({"alg": "none", "typ": "JWT"}).encode()).decode().rstrip("=")
    pld = base64.urlsafe_b64encode(json.dumps({"sub": user_id}).encode()).decode().rstrip("=")
    none_token = f"{hdr}.{pld}."

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {none_token}"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_cookie_csrf_defense():
    """Cookie-authenticated state mutations require trusted Origin/Referer headers."""
    with SessionLocal() as db:
        user = User(email="csrf@example.com", hashed_password=hash_password("Password123!"), is_active=True)
        org = Organization(name="CSRF Org", slug="csrf-org")
        db.add_all([user, org])
        db.commit()
        db.refresh(user)
        db.refresh(org)
        db.add(OrganizationMembership(org_id=org.id, user_id=user.id, role="owner"))
        db.commit()
        user_id = user.id
        org_id = org.id

    token = create_access_token(data={"sub": user_id, "email": "csrf@example.com"})

    # 1. Cookie auth with UNTRUSTED Origin header -> rejected with 403
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={"access_token": token},
    ) as client:
        res_evil = await client.post(
            "/api/projects",
            headers={"Origin": "https://evil-attacker.com"},
            json={"name": "Attacker Proj", "slug": "atk-proj", "org_id": org_id},
        )
        assert res_evil.status_code == 403
        assert "csrf protection" in res_evil.json()["detail"].lower()

    # 2. Cookie auth with TRUSTED Origin header -> accepted
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={"access_token": token},
    ) as client:
        res_ok = await client.post(
            "/api/projects",
            headers={"Origin": "http://localhost:5173"},
            json={"name": "Trusted Proj", "slug": "trusted-proj", "org_id": org_id},
        )
        assert res_ok.status_code == 201

    # 3. Bearer token auth without Origin header -> accepted (immune to CSRF)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res_bearer = await client.post(
            "/api/projects",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": "Bearer Proj", "slug": "bearer-proj", "org_id": org_id},
        )
        assert res_bearer.status_code == 201


# ---------------------------------------------------------------------------
# Priority 3: Tenant Isolation & Artifact Boundaries
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cross_tenant_artifact_retrieval_by_id_blocked(tmp_path):
    """User in Org B cannot retrieve an artifact belonging to Org A by ID."""
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    run_dir = artifacts_dir / "runs" / "run_org_a"
    run_dir.mkdir(parents=True, exist_ok=True)
    png_file = run_dir / "screenshot.png"
    png_file.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRtest")

    original_artifacts_dir = settings.ARTIFACTS_DIR
    settings.ARTIFACTS_DIR = str(artifacts_dir)

    try:
        with SessionLocal() as db:
            user_a = User(email="user_a@example.com", hashed_password=hash_password("Pass123!"), is_active=True)
            org_a = Organization(name="Org A", slug="org-a")
            db.add_all([user_a, org_a])
            db.commit()
            db.refresh(user_a)
            db.refresh(org_a)
            db.add(OrganizationMembership(org_id=org_a.id, user_id=user_a.id, role="owner"))

            user_b = User(email="user_b@example.com", hashed_password=hash_password("Pass123!"), is_active=True)
            org_b = Organization(name="Org B", slug="org-b")
            db.add_all([user_b, org_b])
            db.commit()
            db.refresh(user_b)
            db.refresh(org_b)
            db.add(OrganizationMembership(org_id=org_b.id, user_id=user_b.id, role="owner"))

            proj_a = Project(name="Proj A", slug="proj-a", org_id=org_a.id)
            db.add(proj_a)
            db.commit()
            db.refresh(proj_a)

            run_a = TestRun(id="run_org_a", project_id=proj_a.id, status="passed", total_tests=1, passed_tests=1, failed_tests=0)
            db.add(run_a)
            db.commit()
            db.refresh(run_a)

            art_a = Artifact(
                run_id=run_a.id,
                artifact_type="screenshot",
                file_path=str(png_file),
                mime_type="image/png",
            )
            db.add(art_a)
            db.commit()
            db.refresh(art_a)

            art_a_id = art_a.id
            user_a_id = user_a.id
            user_b_id = user_b.id

        token_a = create_access_token(data={"sub": user_a_id, "email": "user_a@example.com"})
        token_b = create_access_token(data={"sub": user_b_id, "email": "user_b@example.com"})

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # User A can access artifact
            res_a = await client.get(f"/api/artifacts/{art_a_id}", headers={"Authorization": f"Bearer {token_a}"})
            assert res_a.status_code == 200

            # User B is blocked with 403 Forbidden
            res_b = await client.get(f"/api/artifacts/{art_a_id}", headers={"Authorization": f"Bearer {token_b}"})
            assert res_b.status_code == 403
            assert "access denied" in res_b.json()["detail"].lower()
    finally:
        settings.ARTIFACTS_DIR = original_artifacts_dir


@pytest.mark.asyncio
async def test_cross_tenant_artifact_retrieval_by_path_blocked(tmp_path):
    """User in Org B cannot retrieve an artifact belonging to Org A by relative path."""
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    run_dir = artifacts_dir / "runs" / "run_tenant_a"
    run_dir.mkdir(parents=True, exist_ok=True)
    png_file = run_dir / "screenshot.png"
    png_file.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRtest")

    original_artifacts_dir = settings.ARTIFACTS_DIR
    settings.ARTIFACTS_DIR = str(artifacts_dir)

    try:
        with SessionLocal() as db:
            user_a = User(email="tenant_a@example.com", hashed_password=hash_password("Pass123!"), is_active=True)
            org_a = Organization(name="Tenant Org A", slug="tenant-org-a")
            db.add_all([user_a, org_a])
            db.commit()
            db.refresh(user_a)
            db.refresh(org_a)
            db.add(OrganizationMembership(org_id=org_a.id, user_id=user_a.id, role="owner"))

            user_b = User(email="tenant_b@example.com", hashed_password=hash_password("Pass123!"), is_active=True)
            org_b = Organization(name="Tenant Org B", slug="tenant-org-b")
            db.add_all([user_b, org_b])
            db.commit()
            db.refresh(user_b)
            db.refresh(org_b)
            db.add(OrganizationMembership(org_id=org_b.id, user_id=user_b.id, role="owner"))

            proj_a = Project(name="Tenant Proj A", slug="t-proj-a", org_id=org_a.id)
            db.add(proj_a)
            db.commit()
            db.refresh(proj_a)

            run_a = TestRun(id="run_tenant_a", project_id=proj_a.id, status="passed", total_tests=1, passed_tests=1, failed_tests=0)
            db.add(run_a)
            db.commit()

            user_a_id = user_a.id
            user_b_id = user_b.id

        token_a = create_access_token(data={"sub": user_a_id, "email": "tenant_a@example.com"})
        token_b = create_access_token(data={"sub": user_b_id, "email": "tenant_b@example.com"})

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # User A can access artifact via /artifacts/runs/...
            res_a = await client.get("/artifacts/runs/run_tenant_a/screenshot.png", headers={"Authorization": f"Bearer {token_a}"})
            assert res_a.status_code == 200

            # User B is blocked with 403 Forbidden
            res_b = await client.get("/artifacts/runs/run_tenant_a/screenshot.png", headers={"Authorization": f"Bearer {token_b}"})
            assert res_b.status_code == 403

            # User B is also blocked via /api/artifacts/file
            res_b_api = await client.get("/api/artifacts/file", params={"path": "runs/run_tenant_a/screenshot.png"}, headers={"Authorization": f"Bearer {token_b}"})
            assert res_b_api.status_code == 403
    finally:
        settings.ARTIFACTS_DIR = original_artifacts_dir


@pytest.mark.asyncio
async def test_non_run_artifact_requires_superuser(tmp_path):
    """Non-run artifacts (e.g. root logs) strictly require administrative privileges (superuser)."""
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    root_log = artifacts_dir / "system.log"
    root_log.write_text("System execution diagnostics", encoding="utf-8")

    original_artifacts_dir = settings.ARTIFACTS_DIR
    settings.ARTIFACTS_DIR = str(artifacts_dir)

    try:
        with SessionLocal() as db:
            std_user = User(email="standard@example.com", hashed_password=hash_password("Pass123!"), is_active=True, is_superuser=False)
            admin_user = User(email="admin@example.com", hashed_password=hash_password("Pass123!"), is_active=True, is_superuser=True)
            db.add_all([std_user, admin_user])
            db.commit()
            db.refresh(std_user)
            db.refresh(admin_user)
            std_id = std_user.id
            admin_id = admin_user.id

        std_token = create_access_token(data={"sub": std_id, "email": "standard@example.com", "is_superuser": False})
        admin_token = create_access_token(data={"sub": admin_id, "email": "admin@example.com", "is_superuser": True})

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # Standard user is rejected with 403 Forbidden
            res_std = await client.get("/artifacts/system.log", headers={"Authorization": f"Bearer {std_token}"})
            assert res_std.status_code == 403
            assert "administrative privileges" in res_std.json()["detail"].lower()

            # Superuser is permitted
            res_admin = await client.get("/artifacts/system.log", headers={"Authorization": f"Bearer {admin_token}"})
            assert res_admin.status_code == 200
            assert "System execution diagnostics" in res_admin.text
    finally:
        settings.ARTIFACTS_DIR = original_artifacts_dir
