"""
Comprehensive tests for password reset functionality:
- Forgot password request (generic anti-enumeration, validation, rate limiting)
- Cryptographic token generation, secure SHA-256 storage, single-use, expiry
- Password update with bcrypt hashing and immediate login verification
- Inactive user defense, invalid token defense, token reuse defense
- Token verification endpoint
- Email delivery with SMTP integration and development-only fallback
"""
from datetime import datetime, timedelta, timezone
import hashlib
import secrets
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

import app.models  # noqa: F401
from app.config import get_settings
from app.database import Base, engine
from app.main import app
from app.models.user import PasswordResetToken, User
from app.services.email import (
    clear_dev_reset_links,
    get_latest_dev_reset_url,
    send_password_reset_email,
)
from app.services.rate_limiter import (
    password_reset_confirm_rate_limiter,
    password_reset_request_rate_limiter,
)
from app.services.security import hash_password, verify_password

settings = get_settings()


@pytest.fixture(autouse=True)
def clean_db_and_rate_limiters():
    """Ensure every test runs with a fresh database schema, clean rate limiters, and clean dev store."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with password_reset_request_rate_limiter._lock:
        password_reset_request_rate_limiter._failures.clear()
    with password_reset_confirm_rate_limiter._lock:
        password_reset_confirm_rate_limiter._failures.clear()
    clear_dev_reset_links()
    yield
    Base.metadata.drop_all(bind=engine)
    clear_dev_reset_links()


def create_test_user(
    email: str = "tester@example.com",
    password: str = "OldPassword123!",
    is_active: bool = True,
) -> User:
    """Helper to persist a user into the test database."""
    from app.database import SessionLocal

    db = SessionLocal()
    user = User(
        email=email.lower(),
        hashed_password=hash_password(password),
        full_name="Test User",
        is_active=is_active,
        is_superuser=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    db.close()
    return user


# ---------------------------------------------------------------------------
# Forgot Password Request Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_forgot_password_success_creates_token_and_returns_generic_message():
    """Valid registered user generates token in DB, returns generic message without enumeration."""
    user = create_test_user("alice@example.com")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/auth/forgot-password",
            json={"email": "alice@example.com"},
        )

    assert response.status_code == 200
    data = response.json()
    assert "If that email address is associated with an account" in data["message"]

    # Verify database state
    from app.database import SessionLocal

    db = SessionLocal()
    token_records = db.query(PasswordResetToken).filter(PasswordResetToken.user_id == user.id).all()
    assert len(token_records) == 1
    token_rec = token_records[0]

    assert token_rec.used is False
    assert len(token_rec.token_hash) == 64  # SHA-256 hex length
    exp = token_rec.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    assert exp > datetime.now(timezone.utc)

    # Verify dev link was captured
    dev_url = get_latest_dev_reset_url("alice@example.com")
    assert dev_url is not None
    assert "/reset-password?token=" in dev_url
    raw_token = dev_url.split("token=")[1]
    # Check that token_hash in DB matches sha256(raw_token)
    assert hashlib.sha256(raw_token.encode("utf-8")).hexdigest() == token_rec.token_hash
    db.close()


@pytest.mark.asyncio
async def test_forgot_password_unknown_email_anti_enumeration():
    """Unregistered email returns identical generic 200 message with no token created."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/auth/forgot-password",
            json={"email": "nonexistent@example.com"},
        )

    assert response.status_code == 200
    data = response.json()
    assert "If that email address is associated with an account" in data["message"]

    # Verify no tokens or dev links created
    from app.database import SessionLocal

    db = SessionLocal()
    tokens = db.query(PasswordResetToken).all()
    assert len(tokens) == 0
    assert get_latest_dev_reset_url("nonexistent@example.com") is None
    db.close()


@pytest.mark.asyncio
async def test_forgot_password_invalid_email_format():
    """Invalid email format returns 422 validation error."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/auth/forgot-password",
            json={"email": "invalid-email-address"},
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_forgot_password_rate_limiting():
    """Brute force / spamming reset requests triggers 429 Too Many Requests."""
    create_test_user("target@example.com")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for i in range(5):
            res = await client.post(
                "/api/auth/forgot-password",
                json={"email": "target@example.com"},
            )
            assert res.status_code == 200

        # 6th attempt should be blocked
        blocked = await client.post(
            "/api/auth/forgot-password",
            json={"email": "target@example.com"},
        )
        assert blocked.status_code == 429
        assert "Too many password reset requests" in blocked.json()["detail"]


@pytest.mark.asyncio
async def test_forgot_password_invalidates_prior_tokens_for_same_user():
    """Requesting a reset a second time invalidates the previous active token."""
    user = create_test_user("bob@example.com")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/api/auth/forgot-password", json={"email": "bob@example.com"})
        dev_url_1 = get_latest_dev_reset_url("bob@example.com")
        token_1 = dev_url_1.split("token=")[1]

        await client.post("/api/auth/forgot-password", json={"email": "bob@example.com"})
        dev_url_2 = get_latest_dev_reset_url("bob@example.com")
        token_2 = dev_url_2.split("token=")[1]

    assert token_1 != token_2

    from app.database import SessionLocal

    db = SessionLocal()
    hash_1 = hashlib.sha256(token_1.encode("utf-8")).hexdigest()
    hash_2 = hashlib.sha256(token_2.encode("utf-8")).hexdigest()

    rec_1 = db.query(PasswordResetToken).filter(PasswordResetToken.token_hash == hash_1).first()
    rec_2 = db.query(PasswordResetToken).filter(PasswordResetToken.token_hash == hash_2).first()

    assert rec_1.used is True  # Invalidated
    assert rec_2.used is False  # Active
    db.close()


# ---------------------------------------------------------------------------
# Reset Password Execution Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reset_password_success():
    """Valid token updates user password with bcrypt, enables login, and invalidates token."""
    user = create_test_user("carol@example.com", password="OldPassword123!")

    # Request reset
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/api/auth/forgot-password", json={"email": "carol@example.com"})
        dev_url = get_latest_dev_reset_url("carol@example.com")
        token = dev_url.split("token=")[1]

        # Reset password
        reset_res = await client.post(
            "/api/auth/reset-password",
            json={"token": token, "new_password": "NewSecretPassword456!"},
        )
        assert reset_res.status_code == 200
        assert "Your password has been successfully reset" in reset_res.json()["message"]

        # Verify old password fails
        login_fail = await client.post(
            "/api/auth/login",
            json={"email": "carol@example.com", "password": "OldPassword123!"},
        )
        assert login_fail.status_code == 401

        # Verify new password succeeds
        login_ok = await client.post(
            "/api/auth/login",
            json={"email": "carol@example.com", "password": "NewSecretPassword456!"},
        )
        assert login_ok.status_code == 200
        assert "access_token" in login_ok.json()

    # Verify token is marked used
    from app.database import SessionLocal

    db = SessionLocal()
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    rec = db.query(PasswordResetToken).filter(PasswordResetToken.token_hash == token_hash).first()
    assert rec.used is True
    db.close()


@pytest.mark.asyncio
async def test_reset_password_token_reuse_rejected():
    """Consuming the same token twice is rejected with 400 Bad Request."""
    create_test_user("david@example.com")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/api/auth/forgot-password", json={"email": "david@example.com"})
        token = get_latest_dev_reset_url("david@example.com").split("token=")[1]

        # First consumption
        res1 = await client.post(
            "/api/auth/reset-password",
            json={"token": token, "new_password": "NewPassword123!"},
        )
        assert res1.status_code == 200

        # Second consumption
        res2 = await client.post(
            "/api/auth/reset-password",
            json={"token": token, "new_password": "AnotherPassword456!"},
        )
        assert res2.status_code == 400
        assert "already been used" in res2.json()["detail"]


@pytest.mark.asyncio
async def test_reset_password_expired_token_rejected():
    """Expired token is rejected with 400 and does not change user password."""
    user = create_test_user("eve@example.com", password="InitialPassword123!")

    # Insert an expired token
    from app.database import SessionLocal

    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    db = SessionLocal()
    expired_rec = PasswordResetToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        used=False,
    )
    db.add(expired_rec)
    db.commit()
    db.close()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(
            "/api/auth/reset-password",
            json={"token": raw_token, "new_password": "FailedNewPassword123!"},
        )
        assert res.status_code == 400
        assert "expired" in res.json()["detail"]

        # Ensure original password is preserved
        login_check = await client.post(
            "/api/auth/login",
            json={"email": "eve@example.com", "password": "InitialPassword123!"},
        )
        assert login_check.status_code == 200


@pytest.mark.asyncio
async def test_reset_password_invalid_token_rejected():
    """Tampered or invalid token returns 400 Bad Request."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(
            "/api/auth/reset-password",
            json={"token": "this_is_an_invalid_token_string_12345", "new_password": "ValidPassword123!"},
        )
        assert res.status_code == 400
        assert "Invalid or expired" in res.json()["detail"]


@pytest.mark.asyncio
async def test_reset_password_validation_enforces_password_length():
    """Password shorter than 8 characters is rejected with 422."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(
            "/api/auth/reset-password",
            json={"token": "some_token_that_has_proper_length_12345", "new_password": "short"},
        )
        assert res.status_code == 422


@pytest.mark.asyncio
async def test_reset_password_inactive_user_rejected():
    """Inactive user cannot reset password."""
    user = create_test_user("inactive@example.com", is_active=False)

    from app.database import SessionLocal

    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    db = SessionLocal()
    rec = PasswordResetToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        used=False,
    )
    db.add(rec)
    db.commit()
    db.close()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(
            "/api/auth/reset-password",
            json={"token": raw_token, "new_password": "NewValidPassword123!"},
        )
        assert res.status_code == 400


# ---------------------------------------------------------------------------
# Token Verification Endpoint Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_reset_token_endpoint():
    """GET /api/auth/verify-reset-token reports valid/invalid/expired states accurately."""
    user = create_test_user("frank@example.com")

    from app.database import SessionLocal

    raw_token_valid = secrets.token_urlsafe(32)
    hash_valid = hashlib.sha256(raw_token_valid.encode("utf-8")).hexdigest()

    raw_token_expired = secrets.token_urlsafe(32)
    hash_expired = hashlib.sha256(raw_token_expired.encode("utf-8")).hexdigest()

    raw_token_used = secrets.token_urlsafe(32)
    hash_used = hashlib.sha256(raw_token_used.encode("utf-8")).hexdigest()

    db = SessionLocal()
    db.add_all([
        PasswordResetToken(
            user_id=user.id,
            token_hash=hash_valid,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
            used=False,
        ),
        PasswordResetToken(
            user_id=user.id,
            token_hash=hash_expired,
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=5),
            used=False,
        ),
        PasswordResetToken(
            user_id=user.id,
            token_hash=hash_used,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
            used=True,
        ),
    ])
    db.commit()
    db.close()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Valid token
        res_valid = await client.get(f"/api/auth/verify-reset-token?token={raw_token_valid}")
        assert res_valid.status_code == 200
        assert res_valid.json()["valid"] is True

        # 2. Expired token
        res_expired = await client.get(f"/api/auth/verify-reset-token?token={raw_token_expired}")
        assert res_expired.status_code == 200
        assert res_expired.json()["valid"] is False
        assert "expired" in res_expired.json()["message"]

        # 3. Used token
        res_used = await client.get(f"/api/auth/verify-reset-token?token={raw_token_used}")
        assert res_used.status_code == 200
        assert res_used.json()["valid"] is False
        assert "already been used" in res_used.json()["message"]

        # 4. Unknown token
        res_unknown = await client.get("/api/auth/verify-reset-token?token=unknown_token_123456789")
        assert res_unknown.status_code == 200
        assert res_unknown.json()["valid"] is False


# ---------------------------------------------------------------------------
# Email Delivery Tests (SMTP vs Dev mode vs Production safety)
# ---------------------------------------------------------------------------


def test_smtp_delivery_when_configured():
    """When SMTP is configured, send_password_reset_email sends via smtplib."""
    original_host = settings.SMTP_HOST
    settings.SMTP_HOST = "smtp.example.com"
    settings.SMTP_PORT = 587
    settings.SMTP_USER = "smtp_user"
    settings.SMTP_PASSWORD = "smtp_password"

    try:
        with patch("smtplib.SMTP") as mock_smtp_class:
            mock_server = MagicMock()
            mock_smtp_class.return_value.__enter__.return_value = mock_server

            success = send_password_reset_email("recipient@example.com", "test-token-123")
            assert success is True

            mock_smtp_class.assert_called_once_with("smtp.example.com", 587, timeout=15)
            mock_server.starttls.assert_called_once()
            mock_server.login.assert_called_once_with("smtp_user", "smtp_password")
            mock_server.send_message.assert_called_once()
    finally:
        settings.SMTP_HOST = original_host


def test_smtp_failure_returns_false_and_does_not_crash():
    """If SMTP server fails, send_password_reset_email catches error and returns False."""
    original_host = settings.SMTP_HOST
    settings.SMTP_HOST = "smtp.down.example.com"

    try:
        with patch("smtplib.SMTP") as mock_smtp_class:
            mock_smtp_class.side_effect = Exception("SMTP server connection timeout")

            success = send_password_reset_email("recipient@example.com", "test-token-123")
            assert success is False
    finally:
        settings.SMTP_HOST = original_host


@pytest.mark.asyncio
async def test_production_unconfigured_smtp_raises_503():
    """In production environment without SMTP, reset request returns 503 rather than claiming delivery."""
    original_env = settings.ENVIRONMENT
    original_smtp = settings.SMTP_HOST
    settings.ENVIRONMENT = "production"
    settings.SMTP_HOST = None

    try:
        create_test_user("prod_user@example.com")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            res = await client.post(
                "/api/auth/forgot-password",
                json={"email": "prod_user@example.com"},
            )
            assert res.status_code == 503
            assert "unavailable" in res.json()["detail"].lower()
    finally:
        settings.ENVIRONMENT = original_env
        settings.SMTP_HOST = original_smtp


# ---------------------------------------------------------------------------
# Development-only Endpoint Safety Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dev_latest_reset_link_success_in_development():
    """In development, GET /api/auth/dev/latest-reset-link returns the active reset link."""
    create_test_user("devtester@example.com")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Request reset first
        await client.post(
            "/api/auth/forgot-password",
            json={"email": "devtester@example.com"},
        )

        # Retrieve dev link
        res = await client.get("/api/auth/dev/latest-reset-link?email=devtester@example.com")
        assert res.status_code == 200
        data = res.json()
        assert data["email"] == "devtester@example.com"
        assert "/reset-password?token=" in data["reset_url"]


@pytest.mark.asyncio
async def test_dev_latest_reset_link_nonexistent_user():
    """In development, querying an unknown user gives a descriptive 404 message."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/auth/dev/latest-reset-link?email=missing@example.com")
        assert res.status_code == 404
        assert "does not exist in local database" in res.json()["detail"]


@pytest.mark.asyncio
async def test_dev_latest_reset_link_strictly_disabled_in_production():
    """In production, GET /api/auth/dev/latest-reset-link always returns 404 Not Found."""
    original_env = settings.ENVIRONMENT
    settings.ENVIRONMENT = "production"

    try:
        create_test_user("prodtest@example.com")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            res = await client.get("/api/auth/dev/latest-reset-link?email=prodtest@example.com")
            assert res.status_code == 404
            assert res.json()["detail"] == "Endpoint not found"
    finally:
        settings.ENVIRONMENT = original_env


