"""
Unit and integration tests for Phase 13 - Project-Scoped Secure Test Variables.
Covers:
- AES-256-GCM encryption at rest and decryption
- Secret masking in API schemas and responses
- Project-scoped CRUD operations and RBAC authorization
- Runtime placeholder interpolation ({{user_name}}, {{password}}, {{base_url}})
- Hardened secret reference resolution with system variable exfiltration prevention
- Playwright runner artifact protection, video/screenshot suppression, and secret redaction
"""
import base64
import os
import sys
from types import ModuleType
import pytest
from httpx import ASGITransport, AsyncClient

import app.models  # noqa: F401
from app.config import get_settings
from app.database import Base, engine, SessionLocal
from app.main import app
from app.models.organization import Organization, OrganizationMembership
from app.models.project import Project
from app.models.project_variable import ProjectVariable
from app.models.test_case import TestCase, TestStep
from app.models.user import User
from app.schemas.project_variable import ProjectVariableResponse
from app.services.encryption import encrypt_secret, decrypt_secret, get_encryption_key
from app.services.playwright_runner import (
    resolve_placeholders,
    _resolve_secret_reference,
    _execute_playwright,
    BLOCKED_SYSTEM_ENV_VARS,
)
from app.services.security import create_access_token, hash_password

TestCase.__test__ = False
TestStep.__test__ = False


@pytest.fixture(autouse=True)
def clean_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def create_user_and_org(email="owner@example.com", role="owner", org_slug="test-org"):
    with SessionLocal() as db:
        user = User(
            email=email,
            hashed_password=hash_password("Password123!"),
            full_name="Test User",
            is_active=True,
        )
        db.add(user)
        db.flush()

        org = Organization(name="Test Org", slug=org_slug)
        db.add(org)
        db.flush()

        membership = OrganizationMembership(
            org_id=org.id,
            user_id=user.id,
            role=role,
        )
        db.add(membership)
        db.flush()

        project = Project(
            name="Main Project",
            slug="main-project",
            org_id=org.id,
            app_url="http://localhost:3000",
        )
        db.add(project)
        db.commit()

        token = create_access_token(data={"sub": user.id})
        return {
            "user_id": user.id,
            "email": user.email,
            "org_id": org.id,
            "project_id": project.id,
            "token": token,
        }


# =============================================================================
# 1. Encryption & Decryption Unit Tests
# =============================================================================

def test_encryption_roundtrip():
    plaintext = "super-secret-password-123!@#"
    ciphertext = encrypt_secret(plaintext)
    assert ciphertext != plaintext
    assert isinstance(ciphertext, str)

    decrypted = decrypt_secret(ciphertext)
    assert decrypted == plaintext


def test_encryption_non_deterministic():
    plaintext = "same-plaintext-value"
    c1 = encrypt_secret(plaintext)
    c2 = encrypt_secret(plaintext)
    assert c1 != c2  # Fresh 12-byte nonce guarantees unique ciphertexts

    assert decrypt_secret(c1) == plaintext
    assert decrypt_secret(c2) == plaintext


def test_encryption_tamper_detection():
    plaintext = "sensitive-api-token"
    ciphertext = encrypt_secret(plaintext)

    # Decode using urlsafe base64, alter ciphertext, re-encode
    raw = base64.urlsafe_b64decode(ciphertext.encode("utf-8"))
    tampered_raw = bytearray(raw)
    tampered_raw[-1] ^= 0x01
    tampered_ciphertext = base64.urlsafe_b64encode(tampered_raw).decode("utf-8")

    with pytest.raises(Exception):
        decrypt_secret(tampered_ciphertext)


def test_encryption_invalid_key_raises(monkeypatch):
    monkeypatch.setenv("SECRET_ENCRYPTION_KEY", "too-short-key")
    get_settings.cache_clear()
    try:
        with pytest.raises(ValueError, match="expected 32 bytes"):
            get_encryption_key()
    finally:
        get_settings.cache_clear()


# =============================================================================
# 2. Schema Masking & DB Model Constraint Tests
# =============================================================================

def test_schema_masks_secret_values():
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)

    # Secret variable must have value=None in response
    resp = ProjectVariableResponse(
        id="var-1",
        project_id="proj-1",
        name="api_key",
        value="raw-unmasked-token",
        is_secret=True,
        description="Production key",
        created_at=now,
        updated_at=now,
    )
    assert resp.value is None
    assert resp.is_secret is True

    # Plaintext variable retains its value
    resp_plain = ProjectVariableResponse(
        id="var-2",
        project_id="proj-1",
        name="base_url",
        value="https://app.example.com",
        is_secret=False,
        description="Target URL",
        created_at=now,
        updated_at=now,
    )
    assert resp_plain.value == "https://app.example.com"
    assert resp_plain.is_secret is False


def test_db_unique_constraint():
    with SessionLocal() as db:
        user = User(email="dbtest@example.com", hashed_password="h", is_active=True)
        db.add(user)
        db.flush()
        org = Organization(name="Org", slug="org")
        db.add(org)
        db.flush()
        proj = Project(name="Proj", slug="proj", org_id=org.id)
        db.add(proj)
        db.flush()

        v1 = ProjectVariable(project_id=proj.id, name="username", value="admin", is_secret=False)
        db.add(v1)
        db.commit()

        v2 = ProjectVariable(project_id=proj.id, name="username", value="other", is_secret=False)
        db.add(v2)
        with pytest.raises(Exception):
            db.commit()


# =============================================================================
# 3. Project Variables API CRUD & RBAC Tests
# =============================================================================

@pytest.mark.asyncio
async def test_crud_variables_api():
    ctx = create_user_and_org()
    headers = {"Authorization": f"Bearer {ctx['token']}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 1. Create plaintext variable
        r_plain = await ac.post(
            f"/api/projects/{ctx['project_id']}/variables",
            headers=headers,
            json={
                "name": "base_url",
                "value": "http://localhost:8080",
                "is_secret": False,
                "description": "Base app URL",
            },
        )
        assert r_plain.status_code == 201
        data_plain = r_plain.json()
        assert data_plain["name"] == "base_url"
        assert data_plain["value"] == "http://localhost:8080"
        assert data_plain["is_secret"] is False

        # 2. Create secret variable
        r_secret = await ac.post(
            f"/api/projects/{ctx['project_id']}/variables",
            headers=headers,
            json={
                "name": "password",
                "value": "SuperSecretPass123!",
                "is_secret": True,
                "description": "Admin login secret",
            },
        )
        assert r_secret.status_code == 201
        data_secret = r_secret.json()
        assert data_secret["name"] == "password"
        assert data_secret["value"] is None  # Never exposed
        assert data_secret["is_secret"] is True
        secret_var_id = data_secret["id"]

        # 3. Verify encrypted storage in DB
        with SessionLocal() as db:
            db_var = db.query(ProjectVariable).filter(ProjectVariable.id == secret_var_id).first()
            assert db_var is not None
            assert db_var.value != "SuperSecretPass123!"
            assert decrypt_secret(db_var.value) == "SuperSecretPass123!"

        # 4. List variables
        r_list = await ac.get(f"/api/projects/{ctx['project_id']}/variables", headers=headers)
        assert r_list.status_code == 200
        vars_list = r_list.json()
        assert len(vars_list) == 2
        sec_item = next(v for v in vars_list if v["name"] == "password")
        assert sec_item["value"] is None

        # 5. Update secret variable with new value
        r_up1 = await ac.put(
            f"/api/projects/{ctx['project_id']}/variables/{secret_var_id}",
            headers=headers,
            json={"value": "NewPassword456!", "description": "Updated description"},
        )
        assert r_up1.status_code == 200
        assert r_up1.json()["value"] is None
        with SessionLocal() as db:
            db_var = db.query(ProjectVariable).filter(ProjectVariable.id == secret_var_id).first()
            assert decrypt_secret(db_var.value) == "NewPassword456!"
            assert db_var.description == "Updated description"

        # 6. Update variable preserving existing secret value (value=None / omitted)
        r_up2 = await ac.put(
            f"/api/projects/{ctx['project_id']}/variables/{secret_var_id}",
            headers=headers,
            json={"description": "Preserved secret value"},
        )
        assert r_up2.status_code == 200
        with SessionLocal() as db:
            db_var = db.query(ProjectVariable).filter(ProjectVariable.id == secret_var_id).first()
            # Secret remains unchanged
            assert decrypt_secret(db_var.value) == "NewPassword456!"
            assert db_var.description == "Preserved secret value"

        # 7. Delete variable
        r_del = await ac.delete(
            f"/api/projects/{ctx['project_id']}/variables/{secret_var_id}",
            headers=headers,
        )
        assert r_del.status_code == 204

        # Confirm deleted
        r_list_after = await ac.get(f"/api/projects/{ctx['project_id']}/variables", headers=headers)
        assert len(r_list_after.json()) == 1


@pytest.mark.asyncio
async def test_api_rbac_member_forbidden():
    ctx = create_user_and_org()

    # Create member in same org
    with SessionLocal() as db:
        member_user = User(
            email="member@example.com",
            hashed_password=hash_password("Password123!"),
            full_name="Regular Member",
            is_active=True,
        )
        db.add(member_user)
        db.flush()

        membership = OrganizationMembership(
            org_id=ctx["org_id"],
            user_id=member_user.id,
            role="member",
        )
        db.add(membership)
        db.commit()

        member_token = create_access_token(data={"sub": member_user.id})

    headers = {"Authorization": f"Bearer {member_token}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Create blocked
        r_post = await ac.post(
            f"/api/projects/{ctx['project_id']}/variables",
            headers=headers,
            json={"name": "user_name", "value": "test_user"},
        )
        assert r_post.status_code == 403


@pytest.mark.asyncio
async def test_api_cross_org_isolation():
    ctx_a = create_user_and_org(email="org_a@example.com", org_slug="org-a")
    ctx_b = create_user_and_org(email="org_b@example.com", org_slug="org-b")

    headers_b = {"Authorization": f"Bearer {ctx_b['token']}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # User from Org B cannot access Org A's project variables
        r = await ac.get(f"/api/projects/{ctx_a['project_id']}/variables", headers=headers_b)
        assert r.status_code in (403, 404)


@pytest.mark.asyncio
async def test_api_duplicate_variable_conflict():
    ctx = create_user_and_org()
    headers = {"Authorization": f"Bearer {ctx['token']}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r1 = await ac.post(
            f"/api/projects/{ctx['project_id']}/variables",
            headers=headers,
            json={"name": "test_var", "value": "v1"},
        )
        assert r1.status_code == 201

        r2 = await ac.post(
            f"/api/projects/{ctx['project_id']}/variables",
            headers=headers,
            json={"name": "test_var", "value": "v2"},
        )
        assert r2.status_code == 409


# =============================================================================
# 4. Runtime Placeholder Resolution & Protection
# =============================================================================

def test_resolve_placeholders_interpolation():
    variables = {
        "base_url": {"value": "https://staging.example.com", "is_secret": False},
        "user_name": {"value": "qa_admin", "is_secret": False},
        "password": {"value": "SuperSecretPass!", "is_secret": True},
    }

    # Interpolate single
    text, secrets = resolve_placeholders("{{base_url}}/login", variables)
    assert text == "https://staging.example.com/login"
    assert secrets == []

    # Interpolate secret
    text2, secrets2 = resolve_placeholders("{{password}}", variables)
    assert text2 == "SuperSecretPass!"
    assert secrets2 == ["SuperSecretPass!"]

    # Multiple placeholders
    text3, secrets3 = resolve_placeholders(
        "{{base_url}}/auth?u={{user_name}}&p={{password}}", variables
    )
    assert text3 == "https://staging.example.com/auth?u=qa_admin&p=SuperSecretPass!"
    assert secrets3 == ["SuperSecretPass!"]


def test_resolve_placeholders_missing_variable():
    variables = {"existing_var": {"value": "foo", "is_secret": False}}
    with pytest.raises(ValueError, match="Required test variable '{{missing_var}}' is not configured"):
        resolve_placeholders("{{missing_var}}", variables, project_id="proj-123")


def test_blocked_system_env_vars():
    # Attempting to read DATABASE_URL or SECRET_KEY via legacy ${secret:...} is blocked
    for blocked_var in ("DATABASE_URL", "SECRET_KEY", "JWT_SECRET", "SECRET_ENCRYPTION_KEY"):
        with pytest.raises(ValueError, match="Access to host environment variable .* is denied"):
            _resolve_secret_reference(f"${{secret:{blocked_var}}}")


def test_project_variable_precedence_over_env(monkeypatch):
    monkeypatch.setenv("TEST_VARIABLE", "env-value")
    variables = {
        "TEST_VARIABLE": {"value": "project-value", "is_secret": True}
    }

    val, secret = _resolve_secret_reference("${secret:TEST_VARIABLE}", variables)
    assert val == "project-value"
    assert secret == "project-value"


# Helper classes for Playwright runner mocking
class MockPage:
    def __init__(self, url="about:blank"):
        self.url = url
        self.context_options = {}
        self.screenshot_calls = []
        self.video = None

    def set_default_timeout(self, _):
        pass

    async def evaluate(self, _):
        return None

    async def goto(self, url, **_):
        self.url = url

    async def fill(self, target, value, **_):
        if "fail" in target:
            raise RuntimeError(f"Element error with {value}")

    async def screenshot(self, **kwargs):
        self.screenshot_calls.append(kwargs)


class MockContext:
    def __init__(self, page):
        self.page = page

    async def new_page(self):
        return self.page

    async def close(self):
        pass


class MockBrowser:
    def __init__(self, page):
        self.context = MockContext(page)

    async def new_context(self, **kwargs):
        self.context.page.context_options = kwargs
        return self.context

    async def close(self):
        pass


class MockChromium:
    def __init__(self, page):
        self.page = page

    async def launch(self, **_):
        return MockBrowser(self.page)


class MockPlaywright:
    def __init__(self, page):
        self.chromium = MockChromium(page)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass


@pytest.mark.asyncio
async def test_runner_redacts_project_variable_secrets(monkeypatch, tmp_path):
    secret_pass = "P@ssword987654321"
    page = MockPage()

    playwright_mod = ModuleType("playwright")
    async_api_mod = ModuleType("playwright.async_api")
    async_api_mod.async_playwright = lambda: MockPlaywright(page)
    playwright_mod.async_api = async_api_mod
    monkeypatch.setitem(sys.modules, "playwright", playwright_mod)
    monkeypatch.setitem(sys.modules, "playwright.async_api", async_api_mod)

    variables = {
        "base_url": {"value": "https://app.local", "is_secret": False},
        "password": {"value": secret_pass, "is_secret": True},
    }

    steps = [
        {"step_number": 1, "action": "navigate", "value": "{{base_url}}/login"},
        {"step_number": 2, "action": "fill", "target": "#fail-field", "value": "{{password}}"},
    ]

    outcome = await _execute_playwright(
        steps=steps,
        app_url="",
        artifacts_dir=str(tmp_path),
        run_id="run-test",
        test_case_id="tc-1",
        variables=variables,
    )

    assert outcome["status"] == "failed"
    logs = "\n".join(outcome.get("log_lines", []))
    err = outcome.get("error_message") or ""

    # Secret is redacted from logs, error messages, and step records
    assert secret_pass not in logs
    assert secret_pass not in err
    for step in outcome.get("steps", []):
        assert step.get("value") != secret_pass

    # Video recording was disabled
    assert "record_video_dir" not in page.context_options

    # Failure screenshot was suppressed
    assert outcome["screenshot_path"] is None
    assert len(page.screenshot_calls) == 0
