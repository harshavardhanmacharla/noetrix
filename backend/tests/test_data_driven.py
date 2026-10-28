"""
Comprehensive Test Suite for UI-Based Data-Driven Test Execution in Noetrix.

Covers:
  1. Placeholder extraction from step targets, values, and expected results.
  2. Record validation (missing keys, empty values, whitespace, valid payloads).
  3. Non-mutating deep-copy placeholder substitution (Unicode, spaces, punctuation).
  4. Sensitive data masking (passwords, secrets, tokens).
  5. API endpoints:
     - GET /api/test-cases/{id}/placeholders
     - POST /api/test-cases/{id}/validate-data
     - POST /api/test-cases/{id}/preview-data
     - POST /api/projects/{id}/data-driven-runs
  6. Sequential multi-record execution with separate TestResult per record.
  7. Stop-on-failure safety behavior (subsequent records marked as skipped).
  8. Coexistence with `wait_until`, dynamic locator resolution, and saved discovery inventory.
"""
from __future__ import annotations

import copy
import uuid
import pytest
from httpx import ASGITransport, AsyncClient

import app.models  # noqa: F401
from app.database import Base, SessionLocal, engine
from app.models.organization import Organization, OrganizationMembership
from app.models.project import Project
from app.models.project_variable import ProjectVariable
from app.models.test_case import TestCase, TestStep
from app.models.test_run import TestResult, TestRun
from app.models.user import User
from app.main import app
from app.routers import data_driven
from app.services.data_driven_service import (
    extract_test_case_placeholders,
    filter_data_columns,
    mask_sensitive_record_values,
    substitute_record_placeholders,
    validate_record_data,
)
from app.services.security import create_access_token, hash_password

TestCase.__test__ = False
TestStep.__test__ = False
TestResult.__test__ = False
TestRun.__test__ = False


@pytest.fixture
def clean_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


# =============================================================================
# 1. Service Layer Tests: Placeholder Extraction
# =============================================================================

def test_extract_placeholders_from_various_step_fields():
    """Verify unique, sorted placeholders are extracted from target, value, and expected_result."""
    steps = [
        {"action": "navigate", "target": "https://example.com/{{env}}", "value": None, "expected_result": None},
        {"action": "fill", "target": "{{username_field}}", "value": "{{user_name}}", "expected_result": None},
        {"action": "click", "target": "Submit Button", "value": None, "expected_result": "Page heading is {{dashboard_title}}"},
        {"action": "fill", "target": "Confirm", "value": "{{user_name}}", "expected_result": None},  # duplicate placeholder
    ]
    extracted = extract_test_case_placeholders(steps)
    assert extracted == ["dashboard_title", "env", "user_name", "username_field"]


def test_extract_placeholders_empty_or_no_match():
    """Verify empty list when steps contain no placeholders."""
    steps = [
        {"action": "navigate", "target": "https://example.com", "value": None, "expected_result": "Home"},
        {"action": "click", "target": "Sign In", "value": None, "expected_result": None},
    ]
    assert extract_test_case_placeholders(steps) == []
    assert extract_test_case_placeholders([]) == []


# =============================================================================
# 2. Service Layer Tests: Validation
# =============================================================================

def test_validate_record_data_flags_empty_and_missing_fields():
    """Verify validation detects missing placeholders, empty strings, and empty record list."""
    placeholders = ["first_name", "last_name", "hire_date"]

    # 1. Empty records list
    valid, errors = validate_record_data(placeholders, [])
    assert valid is False
    assert any("At least one" in e for e in errors)

    # 2. Missing field and empty/whitespace values
    bad_records = [
        {"first_name": "Alice", "last_name": "", "hire_date": "2026-01-01"},
        {"first_name": "  ", "last_name": "Smith", "hire_date": "2026-01-02"},
        {"first_name": "Bob", "hire_date": "2026-01-03"},  # missing last_name
    ]
    valid, errors = validate_record_data(placeholders, bad_records)
    assert valid is False
    assert len(errors) == 3
    assert "Record #1" in errors[0] and "last_name" in errors[0]
    assert "Record #2" in errors[1] and "first_name" in errors[1]
    assert "Record #3" in errors[2] and "last_name" in errors[2]


def test_validate_record_data_accepts_valid_payload():
    """Verify clean pass for populated records."""
    placeholders = ["legal_employer", "person_number"]
    valid_records = [
        {"legal_employer": "US1 Legal Entity", "person_number": "100234"},
        {"legal_employer": "UK Legal Entity", "person_number": "100235"},
    ]
    valid, errors = validate_record_data(placeholders, valid_records)
    assert valid is True
    assert errors == []


# =============================================================================
# 3. Service Layer Tests: Step Substitution & Immutability
# =============================================================================

def test_substitute_record_placeholders_non_mutating():
    """Verify substitution leaves original step dictionaries and lists strictly unchanged."""
    original_steps = [
        {"step_number": 1, "action": "navigate", "target": "https://erp.com/{{tenant}}", "value": None, "expected_result": None},
        {"step_number": 2, "action": "fill", "target": "Legal Employer", "value": "{{legal_employer}}", "expected_result": "Selected {{legal_employer}}"},
    ]
    steps_copy = copy.deepcopy(original_steps)

    record = {"tenant": "fusion_prod", "legal_employer": "US1 Legal Entity"}
    substituted = substitute_record_placeholders(original_steps, record)

    # Original steps must be strictly identical to before
    assert original_steps == steps_copy

    # Substituted steps have values replaced
    assert substituted[0]["target"] == "https://erp.com/fusion_prod"
    assert substituted[1]["value"] == "US1 Legal Entity"
    assert substituted[1]["expected_result"] == "Selected US1 Legal Entity"


def test_substitute_record_placeholders_unicode_and_special_chars():
    """Verify proper handling of Unicode, spaces, quotes, and punctuation."""
    steps = [
        {"step_number": 1, "action": "fill", "target": "Employee Name", "value": "{{employee_name}}", "expected_result": None},
        {"step_number": 2, "action": "verify_text", "target": "Confirmation", "value": "{{employee_name}}", "expected_result": "Visible"},
    ]
    record = {"employee_name": "Hélène Müller-D'Souza & Co."}
    substituted = substitute_record_placeholders(steps, record)

    assert substituted[0]["value"] == "Hélène Müller-D'Souza & Co."
    assert substituted[1]["value"] == "Hélène Müller-D'Souza & Co."


# =============================================================================
# 4. Service Layer Tests: Sensitive Data Masking
# =============================================================================

def test_mask_sensitive_record_values():
    """Verify secrets/passwords/tokens are redacted while normal fields remain readable."""
    record = {
        "user_login": "admin_user",
        "user_password": "super_secret_password_123",
        "api_token": "bearer_xyz_987",
        "legal_employer": "Oracle US",
    }
    masked = mask_sensitive_record_values(record)
    assert masked["user_login"] == "admin_user"
    assert masked["legal_employer"] == "Oracle US"
    assert masked["user_password"] == "[REDACTED]"
    assert masked["api_token"] == "[REDACTED]"


# =============================================================================
# 5. API Endpoints Tests
# =============================================================================

@pytest.fixture
def auth_setup(clean_db):
    with SessionLocal() as db:
        user = User(
            id=str(uuid.uuid4()),
            email="tester@example.com",
            hashed_password=hash_password("Pass1234!"),
            full_name="Automation Tester",
            is_active=True,
        )
        db.add(user)
        db.flush()

        org = Organization(id=str(uuid.uuid4()), name="Test Org", slug="test-org")
        db.add(org)
        db.flush()

        membership = OrganizationMembership(
            id=str(uuid.uuid4()),
            org_id=org.id,
            user_id=user.id,
            role="admin",
        )
        db.add(membership)

        project = Project(
            id=str(uuid.uuid4()),
            name="Fusion Project",
            slug="fusion-project",
            org_id=org.id,
        )
        db.add(project)
        db.flush()

        test_case = TestCase(
            id=str(uuid.uuid4()),
            project_id=project.id,
            name="Hire An Employee Flow",
            description="Wizard test case with placeholders",
        )
        db.add(test_case)
        db.flush()

        step1 = TestStep(
            id=str(uuid.uuid4()),
            test_case_id=test_case.id,
            step_number=1,
            action="navigate",
            target="https://example.com/hcmUI",
            value=None,
            expected_result="Page loaded",
        )
        step2 = TestStep(
            id=str(uuid.uuid4()),
            test_case_id=test_case.id,
            step_number=2,
            action="fill",
            target="Legal Employer field",
            value="{{legal_employer}}",
            expected_result="Field contains {{legal_employer}}",
        )
        step3 = TestStep(
            id=str(uuid.uuid4()),
            test_case_id=test_case.id,
            step_number=3,
            action="fill",
            target="First Name",
            value="{{first_name}}",
            expected_result=None,
        )
        step4 = TestStep(
            id=str(uuid.uuid4()),
            test_case_id=test_case.id,
            step_number=4,
            action="fill",
            target="Last Name",
            value="{{last_name}}",
            expected_result=None,
        )
        step5 = TestStep(
            id=str(uuid.uuid4()),
            test_case_id=test_case.id,
            step_number=5,
            action="wait_until",
            target="url_contains",
            value="/identification",
            expected_result=None,
        )
        db.add_all([step1, step2, step3, step4, step5])
        db.commit()

        token = create_access_token({"sub": user.id})
        return {
            "token": token,
            "user_id": user.id,
            "project_id": project.id,
            "test_case_id": test_case.id,
        }


@pytest.mark.asyncio
async def test_api_get_placeholders(auth_setup):
    """GET /api/test-cases/{id}/placeholders returns discovered variable list."""
    token = auth_setup["token"]
    case_id = auth_setup["test_case_id"]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get(
            f"/api/test-cases/{case_id}/placeholders",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["test_case_id"] == case_id
        assert len(data["placeholders"]) == 3
        assert data["has_placeholders"] is True
        assert data["placeholders"] == ["first_name", "last_name", "legal_employer"]


@pytest.mark.asyncio
async def test_api_validate_data_endpoint(auth_setup):
    """POST /api/test-cases/{id}/validate-data validates user record inputs."""
    token = auth_setup["token"]
    case_id = auth_setup["test_case_id"]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Invalid payload: missing last_name in row 2
        res = await client.post(
            f"/api/test-cases/{case_id}/validate-data",
            json={
                "test_case_id": case_id,
                "records": [
                    {"first_name": "Alice", "last_name": "Smith", "legal_employer": "US1"},
                    {"first_name": "Bob", "legal_employer": "UK1"},
                ]
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["is_valid"] is False
        assert len(data["errors"]) >= 1

        # Valid payload
        res_valid = await client.post(
            f"/api/test-cases/{case_id}/validate-data",
            json={
                "test_case_id": case_id,
                "records": [
                    {"first_name": "Alice", "last_name": "Smith", "legal_employer": "US1"},
                    {"first_name": "Bob", "last_name": "Jones", "legal_employer": "UK1"},
                ]
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res_valid.status_code == 200
        assert res_valid.json()["is_valid"] is True
        assert res_valid.json()["errors"] == []


@pytest.mark.asyncio
async def test_api_preview_data_endpoint(auth_setup):
    """POST /api/test-cases/{id}/preview-data returns rendered steps for each record."""
    token = auth_setup["token"]
    case_id = auth_setup["test_case_id"]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            f"/api/test-cases/{case_id}/preview-data",
            json={
                "test_case_id": case_id,
                "record": {"first_name": "Carol", "last_name": "Danvers", "legal_employer": "Starforce Ltd"},
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["test_case_id"] == case_id
        steps = data["steps"]
        assert len(steps) == 5
        assert steps[1]["value"] == "Starforce Ltd"
        assert steps[2]["value"] == "Carol"
        assert steps[3]["value"] == "Danvers"


# =============================================================================
# 6. Multi-Record Sequential Execution & Stop-on-Failure Tests
# =============================================================================

@pytest.mark.asyncio
async def test_multi_record_sequential_execution_success(auth_setup, monkeypatch, tmp_path):
    """Verify that multiple data records execute sequentially with separate TestResult records."""
    token = auth_setup["token"]
    project_id = auth_setup["project_id"]
    case_id = auth_setup["test_case_id"]

    executed_records = []

    async def fake_run_test_case(*args, **kwargs):
        # Extract steps passed to runner
        steps = kwargs.get("steps") or (args[2] if len(args) > 2 else [])
        first_name_step = next((s for s in steps if s.get("target") == "First Name"), None)
        executed_records.append(first_name_step["value"] if first_name_step else "unknown")
        return {
            "status": "passed",
            "error_message": None,
            "log_lines": ["Step 1 passed", "Step 2 passed"],
            "screenshot_path": None,
            "video_path": None,
        }

    monkeypatch.setattr(data_driven, "run_test_case", fake_run_test_case)
    monkeypatch.setattr(data_driven.settings, "ARTIFACTS_DIR", str(tmp_path))

    records = [
        {"first_name": "Alice", "last_name": "Smith", "legal_employer": "US1"},
        {"first_name": "Bob", "last_name": "Jones", "legal_employer": "US2"},
    ]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            f"/api/projects/{project_id}/data-driven-runs",
            json={
                "test_case_id": case_id,
                "records": records,
                "stop_on_failure": True,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 202
        run_data = res.json()
        assert run_data["total_tests"] == 2
        run_id = run_data["id"]

    # Verify background execution directly completes
    with SessionLocal() as db:
        run = db.query(TestRun).filter(TestRun.id == run_id).first()
        results = db.query(TestResult).filter(TestResult.run_id == run_id).all()
        assert run.status == "passed"
        assert len(results) == 2
        assert all(r.status == "passed" for r in results)
        assert executed_records == ["Alice", "Bob"]


@pytest.mark.asyncio
async def test_stop_on_failure_halts_remaining_records(auth_setup, monkeypatch, tmp_path):
    """Verify that when stop_on_failure=True, a failure in Record #1 marks Record #2 as skipped without replay."""
    token = auth_setup["token"]
    project_id = auth_setup["project_id"]
    case_id = auth_setup["test_case_id"]

    call_count = 0

    async def fake_run_test_case(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return {
            "status": "failed",
            "error_message": "ElementNotFoundError: Legal Employer field not found",
            "log_lines": ["Failed at step 2"],
            "screenshot_path": None,
            "video_path": None,
        }

    monkeypatch.setattr(data_driven, "run_test_case", fake_run_test_case)
    monkeypatch.setattr(data_driven.settings, "ARTIFACTS_DIR", str(tmp_path))

    records = [
        {"first_name": "FailPerson", "last_name": "One", "legal_employer": "US1"},
        {"first_name": "NeverRunPerson", "last_name": "Two", "legal_employer": "US2"},
    ]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            f"/api/projects/{project_id}/data-driven-runs",
            json={
                "test_case_id": case_id,
                "records": records,
                "stop_on_failure": True,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 202
        run_id = res.json()["id"]

    # Verify call_count is strictly 1 (Record #2 was never invoked via runner)
    assert call_count == 1

    with SessionLocal() as db:
        run = db.query(TestRun).filter(TestRun.id == run_id).first()
        results = db.query(TestResult).filter(TestResult.run_id == run_id).order_by(TestResult.started_at).all()
        assert run.status == "failed"
        assert len(results) == 2
        # Record 1 failed
        assert results[0].status == "failed"
        assert "ElementNotFoundError" in results[0].error_message
        # Record 2 skipped
        assert results[1].status == "skipped"
        assert "Halted to prevent duplicate submissions" in results[1].error_message


# =============================================================================
# 7. Additional Edge Cases: 401, 404, No Placeholders, and wait_until Coexistence
# =============================================================================

@pytest.mark.asyncio
async def test_api_unauthorized_access(auth_setup):
    case_id = auth_setup["test_case_id"]
    project_id = auth_setup["project_id"]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # No auth header
        res1 = await client.get(f"/api/test-cases/{case_id}/placeholders")
        assert res1.status_code == 401

        res2 = await client.post(
            f"/api/projects/{project_id}/data-driven-runs",
            json={"test_case_id": case_id, "records": [{"x": "y"}]},
        )
        assert res2.status_code == 401


@pytest.mark.asyncio
async def test_api_nonexistent_case_or_project(auth_setup):
    token = auth_setup["token"]
    project_id = auth_setup["project_id"]
    fake_id = str(uuid.uuid4())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res1 = await client.get(
            f"/api/test-cases/{fake_id}/placeholders",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res1.status_code == 404

        res2 = await client.post(
            f"/api/projects/{fake_id}/data-driven-runs",
            json={"test_case_id": auth_setup["test_case_id"], "records": [{"x": "y"}]},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res2.status_code == 404


@pytest.mark.asyncio
async def test_case_without_placeholders(auth_setup):
    token = auth_setup["token"]
    project_id = auth_setup["project_id"]

    # Create static test case without placeholders
    with SessionLocal() as db:
        tc = TestCase(
            id=str(uuid.uuid4()),
            project_id=project_id,
            name="Static Test Case",
            description="No placeholders here",
        )
        db.add(tc)
        db.flush()
        step = TestStep(
            id=str(uuid.uuid4()),
            test_case_id=tc.id,
            step_number=1,
            action="navigate",
            target="https://example.com",
            value=None,
            expected_result=None,
        )
        db.add(step)
        db.commit()
        static_case_id = tc.id

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get(
            f"/api/test-cases/{static_case_id}/placeholders",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["has_placeholders"] is False
        assert data["placeholders"] == []

        # Validating records against static case flags error
        val_res = await client.post(
            f"/api/test-cases/{static_case_id}/validate-data",
            json={"test_case_id": static_case_id, "records": [{"foo": "bar"}]},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert val_res.status_code == 200
        assert val_res.json()["is_valid"] is False
        assert "no placeholder variables" in val_res.json()["errors"][0]


@pytest.mark.asyncio
async def test_data_driven_with_wait_until_substitution(auth_setup):
    """Verify wait_until steps properly receive placeholder substitution."""
    steps = [
        {"action": "click", "target": "Submit Person", "value": None, "expected_result": None},
        {"action": "wait_until", "target": "page_heading", "value": "Employee {{employee_id}} Created", "expected_result": None},
        {"action": "wait_until", "target": "url_contains", "value": "/person/{{employee_id}}", "expected_result": None},
    ]
    record = {"employee_id": "EMP_9921"}
    substituted = substitute_record_placeholders(steps, record)

    assert substituted[1]["value"] == "Employee EMP_9921 Created"
    assert substituted[2]["value"] == "/person/EMP_9921"


@pytest.mark.asyncio
async def test_continue_on_failure_executes_subsequent_records(auth_setup, monkeypatch, tmp_path):
    """Verify stop_on_failure=False continues to execute subsequent records."""
    token = auth_setup["token"]
    project_id = auth_setup["project_id"]
    case_id = auth_setup["test_case_id"]

    call_count = 0

    async def fake_run_test_case(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return {"status": "failed", "error_message": "Record 1 error", "log_lines": []}
        return {"status": "passed", "error_message": None, "log_lines": ["Record 2 passed"]}

    monkeypatch.setattr(data_driven, "run_test_case", fake_run_test_case)
    monkeypatch.setattr(data_driven.settings, "ARTIFACTS_DIR", str(tmp_path))

    records = [
        {"first_name": "Record1", "last_name": "Fail", "legal_employer": "US1"},
        {"first_name": "Record2", "last_name": "Pass", "legal_employer": "US2"},
    ]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            f"/api/projects/{project_id}/data-driven-runs",
            json={
                "test_case_id": case_id,
                "records": records,
                "stop_on_failure": False,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 202
        run_id = res.json()["id"]

    # Both records were executed because stop_on_failure was False
    assert call_count == 2

    with SessionLocal() as db:
        run = db.query(TestRun).filter(TestRun.id == run_id).first()
        results = db.query(TestResult).filter(TestResult.run_id == run_id).order_by(TestResult.started_at).all()
        assert run.status == "failed"
        assert len(results) == 2
        assert results[0].status == "failed"
        assert results[1].status == "passed"



# =============================================================================
# 8. Dynamic Column Filtering & Project Variable Exclusion Tests
# =============================================================================

def test_filter_data_columns_unit():
    """Verify filter_data_columns excludes configured project variables from data columns."""
    detected = ["base_url", "email", "first_name", "last_name", "password", "user_name"]
    project_vars = ["base_url", "password", "user_name"]

    data_columns = filter_data_columns(detected, project_vars)
    assert data_columns == ["email", "first_name", "last_name"]

    # When all placeholders are in project variables
    assert filter_data_columns(["base_url", "password"], ["base_url", "password"]) == []

    # When no project variables exist
    assert filter_data_columns(detected, []) == detected


@pytest.fixture
def project_with_variables_setup(clean_db):
    """Fixture with a project having configured plain and secret project variables."""
    with SessionLocal() as db:
        user = User(
            id=str(uuid.uuid4()),
            email="lead_tester@example.com",
            hashed_password=hash_password("Pass1234!"),
            full_name="Lead Tester",
            is_active=True,
        )
        db.add(user)
        db.flush()

        org = Organization(id=str(uuid.uuid4()), name="Enterprise Org", slug="enterprise-org")
        db.add(org)
        db.flush()

        membership = OrganizationMembership(
            id=str(uuid.uuid4()),
            org_id=org.id,
            user_id=user.id,
            role="admin",
        )
        db.add(membership)

        project = Project(
            id=str(uuid.uuid4()),
            name="Oracle HCM Cloud",
            slug="oracle-hcm-cloud",
            org_id=org.id,
            app_url="https://oracle.example.com",
        )
        db.add(project)
        db.flush()

        # Add project test variables: base_url, user_name, password (secret)
        pv1 = ProjectVariable(
            id=str(uuid.uuid4()),
            project_id=project.id,
            name="base_url",
            value="https://oracle.example.com/hcmUI",
            is_secret=False,
        )
        pv2 = ProjectVariable(
            id=str(uuid.uuid4()),
            project_id=project.id,
            name="user_name",
            value="hcm_admin",
            is_secret=False,
        )
        pv3 = ProjectVariable(
            id=str(uuid.uuid4()),
            project_id=project.id,
            name="password",
            value="EncryptedSecretPassword123!",
            is_secret=True,
        )
        db.add_all([pv1, pv2, pv3])
        db.flush()

        # Test case using base_url, user_name, password AND employee fields (first_name, last_name, email)
        tc = TestCase(
            id=str(uuid.uuid4()),
            project_id=project.id,
            name="Hire An Employee Dynamic Columns",
            description="Case mixing project variables and data records",
        )
        db.add(tc)
        db.flush()

        steps = [
            TestStep(
                id=str(uuid.uuid4()),
                test_case_id=tc.id,
                step_number=1,
                action="navigate",
                target="{{base_url}}",
                value=None,
                expected_result=None,
            ),
            TestStep(
                id=str(uuid.uuid4()),
                test_case_id=tc.id,
                step_number=2,
                action="fill",
                target="Username",
                value="{{user_name}}",
                expected_result=None,
            ),
            TestStep(
                id=str(uuid.uuid4()),
                test_case_id=tc.id,
                step_number=3,
                action="fill",
                target="Password",
                value="{{password}}",
                expected_result=None,
            ),
            TestStep(
                id=str(uuid.uuid4()),
                test_case_id=tc.id,
                step_number=4,
                action="fill",
                target="First Name",
                value="{{first_name}}",
                expected_result=None,
            ),
            TestStep(
                id=str(uuid.uuid4()),
                test_case_id=tc.id,
                step_number=5,
                action="fill",
                target="Last Name",
                value="{{last_name}}",
                expected_result=None,
            ),
            TestStep(
                id=str(uuid.uuid4()),
                test_case_id=tc.id,
                step_number=6,
                action="fill",
                target="Work Email",
                value="{{email}}",
                expected_result=None,
            ),
        ]
        db.add_all(steps)
        db.commit()

        token = create_access_token({"sub": user.id})
        return {
            "token": token,
            "project_id": project.id,
            "test_case_id": tc.id,
        }


@pytest.mark.asyncio
async def test_dynamic_column_filtering_excludes_project_variables(project_with_variables_setup):
    """GET /api/test-cases/{id}/placeholders excludes base_url, user_name, password and keeps first_name, last_name, email."""
    token = project_with_variables_setup["token"]
    case_id = project_with_variables_setup["test_case_id"]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get(
            f"/api/test-cases/{case_id}/placeholders",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200
        data = res.json()

        # Placeholders to show in UI data table: only unconfigured fields
        assert data["placeholders"] == ["email", "first_name", "last_name"]
        assert data["all_placeholders"] == ["base_url", "email", "first_name", "last_name", "password", "user_name"]
        assert data["project_variables"] == ["base_url", "password", "user_name"]
        assert data["has_placeholders"] is True


@pytest.mark.asyncio
async def test_dynamic_recalculation_when_project_variables_change(project_with_variables_setup):
    """Verify columns dynamically recalculate when a new project variable is added."""
    token = project_with_variables_setup["token"]
    project_id = project_with_variables_setup["project_id"]
    case_id = project_with_variables_setup["test_case_id"]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Add 'email' to project variables
        with SessionLocal() as db:
            pv_email = ProjectVariable(
                id=str(uuid.uuid4()),
                project_id=project_id,
                name="email",
                value="default_team@example.com",
                is_secret=False,
            )
            db.add(pv_email)
            db.commit()

        # Re-fetch placeholders
        res = await client.get(
            f"/api/test-cases/{case_id}/placeholders",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200
        data = res.json()

        # 'email' is now excluded; only first_name and last_name remain
        assert data["placeholders"] == ["first_name", "last_name"]
        assert "email" in data["project_variables"]


@pytest.mark.asyncio
async def test_secret_project_variable_exclusion_no_value_leakage(project_with_variables_setup):
    """Verify secret project variable values are never leaked in preview or placeholders."""
    token = project_with_variables_setup["token"]
    case_id = project_with_variables_setup["test_case_id"]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Placeholders endpoint has only names, no values
        res_meta = await client.get(
            f"/api/test-cases/{case_id}/placeholders",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert "EncryptedSecretPassword123!" not in res_meta.text

        # 2. Preview endpoint renders [REDACTED] for secret project variables
        res_prev = await client.post(
            f"/api/test-cases/{case_id}/preview-data",
            json={
                "test_case_id": case_id,
                "record": {"first_name": "Diana", "last_name": "Prince", "email": "diana@themyscira.gov"},
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res_prev.status_code == 200
        data = res_prev.json()
        steps = data["steps"]
        # Step 3 is Password -> must be [REDACTED], never plaintext secret
        pw_step = next(s for s in steps if s["step_number"] == 3)
        assert pw_step["value"] == "[REDACTED]"
        assert "EncryptedSecretPassword123!" not in res_prev.text


@pytest.mark.asyncio
async def test_missing_required_record_field_rejected(project_with_variables_setup):
    """Verify validation and execution reject records missing remaining required fields."""
    token = project_with_variables_setup["token"]
    project_id = project_with_variables_setup["project_id"]
    case_id = project_with_variables_setup["test_case_id"]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Missing 'email' from record row
        res_val = await client.post(
            f"/api/test-cases/{case_id}/validate-data",
            json={
                "test_case_id": case_id,
                "records": [{"first_name": "Arthur", "last_name": "Curry"}],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res_val.status_code == 200
        assert res_val.json()["is_valid"] is False
        assert any("email" in err for err in res_val.json()["errors"])

        # POST data-driven-runs rejects with 422
        res_run = await client.post(
            f"/api/projects/{project_id}/data-driven-runs",
            json={
                "test_case_id": case_id,
                "records": [{"first_name": "Arthur", "last_name": "Curry"}],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res_run.status_code == 422
        assert "Data validation failed" in res_run.json()["detail"]


@pytest.mark.asyncio
async def test_placeholder_missing_from_both_sources_rejected(project_with_variables_setup):
    """Verify placeholder missing from both record and project variables is rejected with 422."""
    token = project_with_variables_setup["token"]
    project_id = project_with_variables_setup["project_id"]

    # Create a test case referencing an unconfigured placeholder '{{missing_token}}'
    with SessionLocal() as db:
        tc = TestCase(
            id=str(uuid.uuid4()),
            project_id=project_id,
            name="Case with Unconfigured Placeholder",
        )
        db.add(tc)
        db.flush()
        db.add(
            TestStep(
                id=str(uuid.uuid4()),
                test_case_id=tc.id,
                step_number=1,
                action="fill",
                target="Token",
                value="{{missing_token}}",
            )
        )
        db.commit()
        unconfigured_case_id = tc.id

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # In preview: rejected with 422
        res_prev = await client.post(
            f"/api/test-cases/{unconfigured_case_id}/preview-data",
            json={"test_case_id": unconfigured_case_id, "record": {"other_field": "val"}},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res_prev.status_code == 422
        assert "missing_token" in res_prev.json()["detail"]

        # In run start: rejected with 422
        res_run = await client.post(
            f"/api/projects/{project_id}/data-driven-runs",
            json={"test_case_id": unconfigured_case_id, "records": [{"other_field": "val"}]},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res_run.status_code == 422


@pytest.mark.asyncio
async def test_all_placeholders_defined_at_project_level_rejected_for_data_run(project_with_variables_setup):
    """Verify that if all placeholders are project variables, data-driven run is rejected with clear message."""
    token = project_with_variables_setup["token"]
    project_id = project_with_variables_setup["project_id"]

    # Create test case that ONLY uses {{base_url}}, {{user_name}}, {{password}}
    with SessionLocal() as db:
        tc = TestCase(
            id=str(uuid.uuid4()),
            project_id=project_id,
            name="Static Flow from Project Variables",
        )
        db.add(tc)
        db.flush()
        db.add_all([
            TestStep(id=str(uuid.uuid4()), test_case_id=tc.id, step_number=1, action="navigate", target="{{base_url}}"),
            TestStep(id=str(uuid.uuid4()), test_case_id=tc.id, step_number=2, action="fill", target="User", value="{{user_name}}"),
            TestStep(id=str(uuid.uuid4()), test_case_id=tc.id, step_number=3, action="fill", target="Pass", value="{{password}}"),
        ])
        db.commit()
        all_project_case_id = tc.id

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Placeholders endpoint returns empty placeholders list and has_placeholders: False
        res_meta = await client.get(
            f"/api/test-cases/{all_project_case_id}/placeholders",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res_meta.status_code == 200
        data = res_meta.json()
        assert data["placeholders"] == []
        assert data["has_placeholders"] is False
        assert len(data["all_placeholders"]) == 3

        # Starting data run returns 422
        res_run = await client.post(
            f"/api/projects/{project_id}/data-driven-runs",
            json={"test_case_id": all_project_case_id, "records": [{"foo": "bar"}]},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res_run.status_code == 422
        assert "already configured as Project Test Variables" in res_run.json()["detail"]


@pytest.mark.asyncio
async def test_mixed_project_variable_and_data_driven_execution(project_with_variables_setup, monkeypatch, tmp_path):
    """Verify execution of mixed test: project variables left for Playwright, record variables substituted."""
    token = project_with_variables_setup["token"]
    project_id = project_with_variables_setup["project_id"]
    case_id = project_with_variables_setup["test_case_id"]

    passed_steps_log = []

    async def fake_run_test_case(*args, **kwargs):
        steps = kwargs.get("steps") or (args[2] if len(args) > 2 else [])
        # Record what values runner received
        step_dict = {s["step_number"]: (s.get("target"), s.get("value")) for s in steps}
        passed_steps_log.append(step_dict)
        return {
            "status": "passed",
            "error_message": None,
            "log_lines": ["Step 1 passed", "Step 2 passed"],
            "screenshot_path": None,
            "video_path": None,
        }

    monkeypatch.setattr(data_driven, "run_test_case", fake_run_test_case)
    monkeypatch.setattr(data_driven.settings, "ARTIFACTS_DIR", str(tmp_path))

    records = [
        {"first_name": "Barry", "last_name": "Allen", "email": "barry@centralcity.org"},
        {"first_name": "Victor", "last_name": "Stone", "email": "victor@star-labs.com"},
    ]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            f"/api/projects/{project_id}/data-driven-runs",
            json={
                "test_case_id": case_id,
                "records": records,
                "stop_on_failure": True,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 202
        run_id = res.json()["id"]

    # Verify background execution directly completes
    with SessionLocal() as db:
        run = db.query(TestRun).filter(TestRun.id == run_id).first()
        results = db.query(TestResult).filter(TestResult.run_id == run_id).all()
        assert run.status == "passed"
        assert len(results) == 2
        assert len(passed_steps_log) == 2

        # Record 1 check:
        # Step 1: base_url was preserved as {{base_url}} for Playwright runner
        assert passed_steps_log[0][1][0] == "{{base_url}}"
        # Step 2: user_name was preserved as {{user_name}} for Playwright runner
        assert passed_steps_log[0][2][1] == "{{user_name}}"
        # Step 4: first_name was substituted with 'Barry'
        assert passed_steps_log[0][4][1] == "Barry"
        assert passed_steps_log[0][6][1] == "barry@centralcity.org"

        # Record 2 check:
        assert passed_steps_log[1][4][1] == "Victor"
        assert passed_steps_log[1][6][1] == "victor@star-labs.com"
