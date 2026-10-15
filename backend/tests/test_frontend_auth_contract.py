"""
Frontend Authentication Contract Integration Tests
Verifies the exact interaction flow between the Noetrix React frontend and FastAPI backend:
- Login with credentials yielding token and HttpOnly cookie
- Profile retrieval (/api/auth/me) with cookie and with Bearer token
- Accessing protected dashboard stats with authenticated session
- Logout revoking active session and clearing cookies
- Handling expired / unauthenticated access attempts
"""
import pytest
from httpx import ASGITransport, AsyncClient

import app.models  # noqa: F401
from app.config import get_settings
from app.database import Base, SessionLocal, engine
from app.main import app
from app.models.organization import Organization, OrganizationMembership
from app.models.user import User
from app.services.rate_limiter import login_rate_limiter
from app.services.security import hash_password

settings = get_settings()


@pytest.fixture(autouse=True)
def clean_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with login_rate_limiter._lock:
        login_rate_limiter._failures.clear()
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.mark.asyncio
async def test_frontend_login_and_credentialed_session_flow():
    """Verify frontend login, session retrieval via cookie, and logout invalidation."""
    with SessionLocal() as db:
        user = User(
            email="developer@noetrix.internal",
            hashed_password=hash_password("SafeFrontendPass123!"),
            full_name="Frontend Developer",
            is_active=True,
            is_superuser=False,
        )
        db.add(user)
        db.flush()

        org = Organization(name="Engineering Team", slug="eng-team")
        db.add(org)
        db.flush()

        db.add(OrganizationMembership(org_id=org.id, user_id=user.id, role="member"))
        db.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://localhost:5173",  # Simulating browser client at frontend origin
        headers={"origin": "http://localhost:5173"},
    ) as client:
        # 1. Unauthenticated request to /api/dashboard/stats is rejected
        unauth_resp = await client.get("http://test/api/dashboard/stats")
        assert unauth_resp.status_code == 401

        # 2. Login with valid credentials
        login_resp = await client.post(
            "http://test/api/auth/login",
            json={
                "email": "developer@noetrix.internal",
                "password": "SafeFrontendPass123!",
            },
        )
        assert login_resp.status_code == 200
        login_data = login_resp.json()
        assert "access_token" in login_data
        assert login_data["user"]["email"] == "developer@noetrix.internal"
        assert login_data["user"]["full_name"] == "Frontend Developer"

        # Verify HttpOnly cookie was set in the response
        assert "access_token" in login_resp.cookies
        cookie_token = login_resp.cookies["access_token"]
        assert cookie_token == login_data["access_token"]

        # 3. Retrieve user profile via /api/auth/me using credentials (cookie transmitted automatically)
        me_resp = await client.get("http://test/api/auth/me", cookies=login_resp.cookies)
        assert me_resp.status_code == 200
        profile_data = me_resp.json()
        assert profile_data["user"]["email"] == "developer@noetrix.internal"
        assert len(profile_data["memberships"]) == 1
        assert profile_data["memberships"][0]["org_name"] == "Engineering Team"
        assert profile_data["memberships"][0]["role"] == "member"

        # 4. Access protected dashboard stats with session cookie
        dashboard_resp = await client.get("http://test/api/dashboard/stats", cookies=login_resp.cookies)
        assert dashboard_resp.status_code == 200
        stats = dashboard_resp.json()
        assert "total_organizations" in stats
        assert stats["total_organizations"] == 1

        # 5. Access with in-memory Bearer token
        bearer_resp = await client.get(
            "http://test/api/auth/me",
            headers={"Authorization": f"Bearer {login_data['access_token']}"},
        )
        assert bearer_resp.status_code == 200

        # 6. Logout: clears session cookie and revokes token
        logout_resp = await client.post(
            "http://test/api/auth/logout",
            cookies=login_resp.cookies,
            headers={"Authorization": f"Bearer {login_data['access_token']}"},
        )
        assert logout_resp.status_code == 200
        assert logout_resp.json()["status"] == "ok"

        # 7. Post-logout: subsequent requests with the revoked token/cookie are rejected
        post_logout_resp = await client.get(
            "http://test/api/auth/me",
            headers={"Authorization": f"Bearer {login_data['access_token']}"},
        )
        assert post_logout_resp.status_code == 401


@pytest.mark.asyncio
async def test_frontend_login_failure_sanitization():
    """Verify that failed login attempts do not leak user existence or stack traces."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://localhost:5173",
        headers={"origin": "http://localhost:5173"},
    ) as client:
        # Nonexistent user
        resp1 = await client.post(
            "http://test/api/auth/login",
            json={"email": "nonexistent@noetrix.internal", "password": "RandomPassword123!"},
        )
        assert resp1.status_code == 401
        assert resp1.json()["detail"] == "Invalid email or password."

        # Malformed email validation error
        resp2 = await client.post(
            "http://test/api/auth/login",
            json={"email": "not-an-email", "password": "RandomPassword123!"},
        )
        assert resp2.status_code == 422
