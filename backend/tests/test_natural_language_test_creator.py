"""
Unit and integration tests for Natural Language Test Case Creator (Phase 11.5).
Tests:
- Parsing natural-language instructions into structured canonical steps
- Blank line handling and whitespace normalization
- Rejection of compound, ambiguous, unsupported, and incomplete instructions
- Tenant / organization isolation and authorization checks
- Persistence of validated test cases with ordered steps
- Rejection of test case creation when instructions are invalid
- Separation of parsing from execution (never triggers Playwright runs)
"""
from datetime import datetime, timezone
import pytest
from httpx import ASGITransport, AsyncClient

import app.models  # noqa: F401
from app.database import Base, engine, SessionLocal
from app.main import app
from app.models.organization import Organization, OrganizationMembership
from app.models.project import Project
from app.models.test_case import TestCase, TestStep
from app.models.test_run import TestRun
from app.models.user import User
from app.services.security import create_access_token, hash_password

TestCase.__test__ = False
TestStep.__test__ = False
TestRun.__test__ = False


@pytest.fixture(autouse=True)
def clean_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def create_test_context():
    """Helper to seed test user, org, membership, and project."""
    with SessionLocal() as db:
        user = User(
            email="author@example.com",
            hashed_password=hash_password("Password123!"),
            full_name="Test Author",
            is_active=True,
        )
        db.add(user)
        db.flush()

        org = Organization(name="Author Org", slug="author-org")
        db.add(org)
        db.flush()

        membership = OrganizationMembership(
            org_id=org.id,
            user_id=user.id,
            role="owner",
        )
        db.add(membership)

        project = Project(
            org_id=org.id,
            name="Author Project",
            slug="author-project",
            app_url="https://example.com",
        )
        db.add(project)

        # Other user and project for isolation testing
        other_user = User(
            email="other@example.com",
            hashed_password=hash_password("Password123!"),
            full_name="Other User",
            is_active=True,
        )
        db.add(other_user)
        db.flush()

        other_org = Organization(name="Other Org", slug="other-org")
        db.add(other_org)
        db.flush()

        other_membership = OrganizationMembership(
            org_id=other_org.id,
            user_id=other_user.id,
            role="owner",
        )
        db.add(other_membership)

        other_project = Project(
            org_id=other_org.id,
            name="Other Project",
            slug="other-project",
            app_url="https://other.com",
        )
        db.add(other_project)
        db.commit()

        token = create_access_token(data={"sub": user.id})
        other_token = create_access_token(data={"sub": other_user.id})

        return {
            "user_id": user.id,
            "project_id": project.id,
            "token": token,
            "other_project_id": other_project.id,
            "other_token": other_token,
        }


@pytest.mark.asyncio
async def test_parse_instructions_success():
    """Valid natural-language instructions parse into canonical actions without saving or executing."""
    ctx = create_test_context()
    raw_instructions = (
        'navigate to https://example.com/login\n'
        'type "admin" into "#username"\n'
        'enter "secret123" into "#password"\n'
        'click the "Sign In" button\n'
        'verify that text "Welcome to Dashboard" is visible\n'
        'verify current url contains "/dashboard"\n'
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(
            "/api/test-cases/parse-instructions",
            headers={"Authorization": f"Bearer {ctx['token']}"},
            json={
                "project_id": ctx["project_id"],
                "raw_text": raw_instructions,
            },
        )

    assert res.status_code == 200
    data = res.json()
    assert data["is_valid"] is True
    assert data["total_lines"] == 6
    assert data["valid_steps_count"] == 6
    assert len(data["errors"]) == 0
    assert len(data["steps"]) == 6

    # Verify canonical representations
    steps = data["steps"]
    assert steps[0]["action"] == "navigate"
    assert steps[0]["value"] == "https://example.com/login"

    assert steps[1]["action"] == "fill"
    assert steps[1]["target"] == "#username"
    assert steps[1]["value"] == "admin"

    assert steps[2]["action"] == "fill"
    assert steps[2]["target"] == "#password"
    assert steps[2]["value"] == "secret123"

    assert steps[3]["action"] == "click"
    assert steps[3]["target"] == "Sign In"

    assert steps[4]["action"] == "verify_text"
    assert steps[4]["expected_result"] == "Welcome to Dashboard"

    assert steps[5]["action"] == "verify_url"
    assert steps[5]["expected_result"] == "/dashboard"

    # Confirm parsing alone did not create any database records or runs
    with SessionLocal() as db:
        assert db.query(TestCase).count() == 0
        assert db.query(TestStep).count() == 0
        assert db.query(TestRun).count() == 0


@pytest.mark.asyncio
async def test_parse_instructions_with_blank_lines_and_list_format():
    """Blank lines and whitespace are skipped gracefully without counting as errors."""
    ctx = create_test_context()
    lines_list = [
        "  open https://example.com  ",
        "",
        "   ",
        'click "#explore-btn"',
        "",
        'verify text "Explore Noetrix"',
    ]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(
            "/api/test-cases/parse-instructions",
            headers={"Authorization": f"Bearer {ctx['token']}"},
            json={
                "project_id": ctx["project_id"],
                "instructions": lines_list,
            },
        )

    assert res.status_code == 200
    data = res.json()
    assert data["is_valid"] is True
    assert data["total_lines"] == 3
    assert data["valid_steps_count"] == 3
    assert len(data["steps"]) == 3


@pytest.mark.asyncio
async def test_parse_instructions_rejects_ambiguous_compound():
    """Compound instructions combining multiple actions with 'and' are rejected."""
    ctx = create_test_context()
    raw = 'type "admin" into "#username" and click "#submit"'

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(
            "/api/test-cases/parse-instructions",
            headers={"Authorization": f"Bearer {ctx['token']}"},
            json={
                "project_id": ctx["project_id"],
                "raw_text": raw,
            },
        )

    assert res.status_code == 200
    data = res.json()
    assert data["is_valid"] is False
    assert len(data["errors"]) == 1
    assert "Ambiguous compound instruction" in data["errors"][0]["message"]
    assert data["steps"][0]["is_valid"] is False


@pytest.mark.asyncio
async def test_parse_instructions_rejects_unsupported_actions():
    """Unsupported actions like conditionals or explicit sleeps are rejected with clean diagnostics."""
    ctx = create_test_context()
    raw = (
        'if error is visible, click retry\n'
        'wait 5 seconds\n'
        'hover over the avatar\n'
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(
            "/api/test-cases/parse-instructions",
            headers={"Authorization": f"Bearer {ctx['token']}"},
            json={
                "project_id": ctx["project_id"],
                "raw_text": raw,
            },
        )

    assert res.status_code == 200
    data = res.json()
    assert data["is_valid"] is False
    assert len(data["errors"]) == 3
    assert any("conditional" in e["message"].lower() for e in data["errors"])
    assert any("wait/sleep" in e["message"].lower() for e in data["errors"])
    assert any("unsupported" in e["message"].lower() for e in data["errors"])


@pytest.mark.asyncio
async def test_parse_instructions_empty_input_returns_clean_error():
    """Empty or whitespace-only instruction input returns is_valid=False with actionable error."""
    ctx = create_test_context()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(
            "/api/test-cases/parse-instructions",
            headers={"Authorization": f"Bearer {ctx['token']}"},
            json={
                "project_id": ctx["project_id"],
                "raw_text": "   \n\n   ",
            },
        )

    assert res.status_code == 200
    data = res.json()
    assert data["is_valid"] is False
    assert data["total_lines"] == 0
    assert len(data["errors"]) == 1
    assert "No instructions provided" in data["errors"][0]["message"]


@pytest.mark.asyncio
async def test_parse_instructions_enforces_tenant_authorization():
    """Users cannot parse instructions against a project they do not belong to."""
    ctx = create_test_context()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Cross-tenant access attempt
        res = await client.post(
            "/api/test-cases/parse-instructions",
            headers={"Authorization": f"Bearer {ctx['token']}"},
            json={
                "project_id": ctx["other_project_id"],
                "raw_text": "open https://example.com",
            },
        )

    assert res.status_code in (403, 404)


@pytest.mark.asyncio
async def test_create_test_case_from_instructions_persists_canonical_steps():
    """Explicit save commits test case and structured steps into database."""
    ctx = create_test_context()
    raw = (
        'navigate to https://example.com/checkout\n'
        'clear the "Discount Code" field\n'
        'check the "I Agree to Terms" checkbox\n'
        'click the "Complete Order" button\n'
        'verify that text "Order Confirmed!" is visible\n'
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(
            "/api/test-cases/create-from-instructions",
            headers={"Authorization": f"Bearer {ctx['token']}"},
            json={
                "project_id": ctx["project_id"],
                "name": "Checkout Flow Test",
                "description": "Created via natural language creator",
                "raw_text": raw,
            },
        )

    assert res.status_code == 201
    created = res.json()
    assert created["name"] == "Checkout Flow Test"
    assert created["description"] == "Created via natural language creator"
    assert created["project_id"] == ctx["project_id"]
    assert created["csv_filename"] == "natural_language"
    assert len(created["steps"]) == 5

    # Check step actions
    step_actions = [s["action"] for s in created["steps"]]
    assert step_actions == ["navigate", "clear", "check", "click", "verify_text"]

    # Verify persisted in database
    with SessionLocal() as db:
        tc = db.query(TestCase).filter(TestCase.id == created["id"]).first()
        assert tc is not None
        assert tc.name == "Checkout Flow Test"
        assert len(tc.steps) == 5
        assert tc.steps[1].action == "clear"
        assert tc.steps[1].target == "Discount Code"
        assert tc.steps[2].action == "check"
        assert tc.steps[2].target == "I Agree to Terms"

    # Verify accessible via standard test-cases listing endpoint
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        list_res = await client.get(
            f"/api/projects/{ctx['project_id']}/test-cases",
            headers={"Authorization": f"Bearer {ctx['token']}"},
        )
    assert list_res.status_code == 200
    cases = list_res.json()
    assert any(c["id"] == created["id"] for c in cases)


@pytest.mark.asyncio
async def test_create_test_case_rejects_invalid_instructions_with_rollback():
    """Creation fails with 400 and does not persist any records if instructions contain errors."""
    ctx = create_test_context()
    raw = (
        'navigate to https://example.com\n'
        'click and type admin\n'  # Compound ambiguity
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(
            "/api/test-cases/create-from-instructions",
            headers={"Authorization": f"Bearer {ctx['token']}"},
            json={
                "project_id": ctx["project_id"],
                "name": "Invalid Flow",
                "raw_text": raw,
            },
        )

    assert res.status_code == 400
    assert "Cannot save test case with invalid instructions" in res.json()["detail"]

    # Assert no records saved
    with SessionLocal() as db:
        assert db.query(TestCase).count() == 0
        assert db.query(TestStep).count() == 0


@pytest.mark.asyncio
async def test_create_test_case_project_scoped_route_alias():
    """Project-scoped route /api/projects/{id}/test-cases/from-instructions functions as alias."""
    ctx = create_test_context()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(
            f"/api/projects/{ctx['project_id']}/test-cases/from-instructions",
            headers={"Authorization": f"Bearer {ctx['token']}"},
            json={
                "project_id": ctx["project_id"],
                "name": "Project Alias Test",
                "raw_text": "open https://example.com\nverify current url is 'https://example.com'",
            },
        )

    assert res.status_code == 201
    assert res.json()["name"] == "Project Alias Test"
    assert len(res.json()["steps"]) == 2
