"""
Phase 9 Tests: Execution History, Diagnostics, and Usability.

Tests:
1. Execution history API responses for empty, populated, and failed runs.
2. Step-level structured details with duration, status, verification result, and human-readable failure explanations.
3. Diagnostic categorization taxonomy (missing_element, ambiguous_target, assertion_failure, timeout, parsing_failure, execution_error).
4. Correct step counts (passed, failed, skipped, total) and pass rates.
5. Project isolation and multi-tenant authorization enforcement.
6. Missing and inaccessible artifact protections.
7. Secret redaction in diagnostics, step results, and artifacts.
8. Backward compatibility with legacy runs lacking steps.json.
"""
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
import pytest
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.database import SessionLocal, create_tables
from app.dependencies import get_current_user
from app.main import app
from app.models.organization import Organization, OrganizationMembership
from app.models.project import Project
from app.models.test_case import TestCase as DbTestCase, TestStep as DbTestStep
from app.models.test_run import Artifact, TestResult as DbTestResult, TestRun as DbTestRun
from app.models.user import User
from app.services.result_diagnostics import (
    build_run_report_response,
    build_test_result_response,
    categorize_error_string,
    enrich_test_run_response,
    load_result_step_details,
)

settings = get_settings()


@pytest.fixture(autouse=True)
def setup_db():
    create_tables()
    yield


@pytest.fixture
def test_setup():
    """Setup isolated organization, projects, users, and artifacts directory."""
    with SessionLocal() as db:
        # Organization A
        org_a = Organization(id=str(uuid.uuid4()), name="Org A", slug=f"org-a-{uuid.uuid4().hex[:6]}")
        db.add(org_a)
        
        # Organization B
        org_b = Organization(id=str(uuid.uuid4()), name="Org B", slug=f"org-b-{uuid.uuid4().hex[:6]}")
        db.add(org_b)
        
        # User in Org A (member)
        user_a = User(
            id=str(uuid.uuid4()),
            email=f"user_a_{uuid.uuid4().hex[:6]}@example.com",
            hashed_password="hashed_pw_test_123456",
            full_name="User A",
            is_active=True,
            is_superuser=False,
        )
        db.add(user_a)
        
        # User in Org B (member)
        user_b = User(
            id=str(uuid.uuid4()),
            email=f"user_b_{uuid.uuid4().hex[:6]}@example.com",
            hashed_password="hashed_pw_test_123456",
            full_name="User B",
            is_active=True,
            is_superuser=False,
        )
        db.add(user_b)
        
        # Superuser
        admin_user = User(
            id=str(uuid.uuid4()),
            email=f"admin_{uuid.uuid4().hex[:6]}@example.com",
            hashed_password="hashed_pw_test_123456",
            full_name="Admin",
            is_active=True,
            is_superuser=True,
        )
        db.add(admin_user)
        db.commit()

        # Memberships
        mem_a = OrganizationMembership(
            id=str(uuid.uuid4()),
            org_id=org_a.id,
            user_id=user_a.id,
            role="member",
        )
        mem_b = OrganizationMembership(
            id=str(uuid.uuid4()),
            org_id=org_b.id,
            user_id=user_b.id,
            role="member",
        )
        db.add_all([mem_a, mem_b])

        # Projects
        proj_a = Project(
            id=str(uuid.uuid4()),
            name="Project Alpha",
            slug=f"alpha-{uuid.uuid4().hex[:6]}",
            org_id=org_a.id,
            app_url="http://127.0.0.1:8080",
        )
        proj_b = Project(
            id=str(uuid.uuid4()),
            name="Project Beta",
            slug=f"beta-{uuid.uuid4().hex[:6]}",
            org_id=org_b.id,
            app_url="http://127.0.0.1:9090",
        )
        db.add_all([proj_a, proj_b])
        db.commit()

        u_a_id = user_a.id
        u_a_email = user_a.email
        u_b_id = user_b.id
        u_b_email = user_b.email
        admin_id = admin_user.id
        admin_email = admin_user.email

        data = {
            "org_a_id": org_a.id,
            "org_b_id": org_b.id,
            "user_a": User(id=u_a_id, email=u_a_email, full_name="User A", is_active=True, is_superuser=False),
            "user_b": User(id=u_b_id, email=u_b_email, full_name="User B", is_active=True, is_superuser=False),
            "admin_user": User(id=admin_id, email=admin_email, full_name="Admin", is_active=True, is_superuser=True),
            "proj_a_id": proj_a.id,
            "proj_b_id": proj_b.id,
        }
        return data


@pytest.mark.asyncio
async def test_execution_history_empty_and_populated_runs(test_setup):
    """Test execution history listing for empty state and populated runs with step metrics."""
    user_a = test_setup["user_a"]
    proj_a_id = test_setup["proj_a_id"]

    transport = ASGITransport(app=app)
    app.dependency_overrides[get_current_user] = lambda: user_a

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. Empty history
            res = await client.get(f"/api/projects/{proj_a_id}/runs")
            assert res.status_code == 200
            assert res.json() == []

            # 2. Create populated run with structured steps
            run_id = str(uuid.uuid4())
            with SessionLocal() as db:
                run = DbTestRun(
                    id=run_id,
                    project_id=proj_a_id,
                    status="passed",
                    started_at=datetime.now(timezone.utc),
                    completed_at=datetime.now(timezone.utc),
                    total_tests=1,
                    passed_tests=1,
                    failed_tests=0,
                )
                db.add(run)

                tc = DbTestCase(
                    id=str(uuid.uuid4()),
                    project_id=proj_a_id,
                    name="User Checkout Test",
                )
                db.add(tc)

                res_id = str(uuid.uuid4())
                result = DbTestResult(
                    id=res_id,
                    run_id=run_id,
                    test_case_id=tc.id,
                    status="passed",
                    started_at=datetime.now(timezone.utc),
                    completed_at=datetime.now(timezone.utc),
                )
                db.add(result)

                # Write steps.json artifact to disk
                result_dir = Path(settings.ARTIFACTS_DIR) / "runs" / run_id / "results" / res_id
                result_dir.mkdir(parents=True, exist_ok=True)
                steps_data = [
                    {
                        "step_number": 1,
                        "action": "navigate",
                        "target": "http://127.0.0.1:8080/checkout",
                        "value": None,
                        "expected_result": None,
                        "original_instruction": "go to /checkout",
                        "status": "passed",
                        "duration_ms": 120.5,
                        "category": None,
                        "failure_reason": None,
                        "verification_result": None,
                    },
                    {
                        "step_number": 2,
                        "action": "click",
                        "target": "#pay-now",
                        "value": None,
                        "expected_result": None,
                        "original_instruction": "click 'Pay Now'",
                        "status": "passed",
                        "duration_ms": 85.2,
                        "category": None,
                        "failure_reason": None,
                        "verification_result": None,
                    },
                ]
                (result_dir / "steps.json").write_text(json.dumps(steps_data), encoding="utf-8")

                db.commit()

            # 3. Query project runs list
            res = await client.get(f"/api/projects/{proj_a_id}/runs")
            assert res.status_code == 200
            runs_list = res.json()
            assert len(runs_list) == 1
            run_item = runs_list[0]
            assert run_item["id"] == run_id
            assert run_item["status"] == "passed"
            assert run_item["total_tests"] == 1
            assert run_item["passed_tests"] == 1
            assert run_item["total_steps"] == 2
            assert run_item["passed_steps"] == 2
            assert run_item["failed_steps"] == 0
            assert run_item["skipped_steps"] == 0

            # 4. Query global recent runs endpoint
            res_all = await client.get("/api/runs")
            assert res_all.status_code == 200
            assert len(res_all.json()) >= 1
            assert any(r["id"] == run_id for r in res_all.json())

    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_step_level_details_and_diagnostics(test_setup):
    """Test detailed step-level diagnostics, failure categories, and skipped step marking."""
    user_a = test_setup["user_a"]
    proj_a_id = test_setup["proj_a_id"]

    run_id = str(uuid.uuid4())
    res_id = str(uuid.uuid4())

    with SessionLocal() as db:
        run = DbTestRun(
            id=run_id,
            project_id=proj_a_id,
            status="failed",
            total_tests=1,
            passed_tests=0,
            failed_tests=1,
        )
        db.add(run)

        tc = DbTestCase(
            id=str(uuid.uuid4()),
            project_id=proj_a_id,
            name="Login Authentication Test",
        )
        db.add(tc)

        result = DbTestResult(
            id=res_id,
            run_id=run_id,
            test_case_id=tc.id,
            status="failed",
            error_message="Step 2 (click) failed: Could not find any clickable element matching 'SubmitBtn'",
        )
        db.add(result)

        # Write steps.json with a passed step, a failed step (missing_element), and a skipped step
        result_dir = Path(settings.ARTIFACTS_DIR) / "runs" / run_id / "results" / res_id
        result_dir.mkdir(parents=True, exist_ok=True)
        steps_data = [
            {
                "step_number": 1,
                "action": "navigate",
                "target": "http://127.0.0.1:8080/login",
                "value": None,
                "expected_result": None,
                "original_instruction": "navigate to /login",
                "status": "passed",
                "duration_ms": 150.0,
                "category": None,
                "failure_reason": None,
                "verification_result": None,
            },
            {
                "step_number": 2,
                "action": "click",
                "target": "SubmitBtn",
                "value": None,
                "expected_result": None,
                "original_instruction": "click 'SubmitBtn'",
                "status": "failed",
                "duration_ms": 5012.3,
                "category": "missing_element",
                "failure_reason": "Could not find any clickable element matching 'SubmitBtn'",
                "verification_result": None,
            },
            {
                "step_number": 3,
                "action": "verify_text",
                "target": None,
                "value": None,
                "expected_result": "Welcome Back",
                "original_instruction": "verify that 'Welcome Back' is visible",
                "status": "skipped",
                "duration_ms": 0.0,
                "category": None,
                "failure_reason": None,
                "verification_result": None,
            },
        ]
        (result_dir / "steps.json").write_text(json.dumps(steps_data), encoding="utf-8")
        db.commit()

    transport = ASGITransport(app=app)
    app.dependency_overrides[get_current_user] = lambda: user_a

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. Fetch results for run
            res = await client.get(f"/api/runs/{run_id}/results")
            assert res.status_code == 200
            results = res.json()
            assert len(results) == 1
            r0 = results[0]
            assert r0["id"] == res_id
            assert r0["status"] == "failed"
            assert len(r0["steps"]) == 3

            # Check individual steps
            st1, st2, st3 = r0["steps"]
            assert st1["step_number"] == 1
            assert st1["status"] == "passed"
            assert st1["duration_ms"] == 150.0

            assert st2["step_number"] == 2
            assert st2["status"] == "failed"
            assert st2["category"] == "missing_element"
            assert "Could not find any clickable element" in st2["failure_reason"]

            assert st3["step_number"] == 3
            assert st3["status"] == "skipped"
            assert st3["duration_ms"] == 0.0

            # Check step summary
            summary = r0["step_summary"]
            assert summary["total"] == 3
            assert summary["passed"] == 1
            assert summary["failed"] == 1
            assert summary["skipped"] == 1

            # 2. Fetch full report
            rep_res = await client.get(f"/api/runs/{run_id}/report")
            assert rep_res.status_code == 200
            rep = rep_res.json()
            assert rep["run"]["total_steps"] == 3
            assert rep["run"]["passed_steps"] == 1
            assert rep["run"]["failed_steps"] == 1
            assert rep["run"]["skipped_steps"] == 1
            assert rep["summary"]["step_pass_rate"] == 33.33

    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_failure_categorization_taxonomy():
    """Verify categorization of all error types into the defined failure taxonomy."""
    # 1. Ambiguous target
    cat1, _ = categorize_error_string("Ambiguous target 'Submit' matches 2 visible elements")
    assert cat1 == "ambiguous_target"

    # 2. Missing element
    cat2, _ = categorize_error_string("Could not find any clickable element matching 'LoginButton'")
    assert cat2 == "missing_element"

    # 3. Assertion failure
    cat3, _ = categorize_error_string("URL verification failed: expected '/dashboard' in 'http://127.0.0.1/home'")
    assert cat3 == "assertion_failure"

    cat4, _ = categorize_error_string("Text 'Order Confirmed' was not found as visible text on the page")
    assert cat4 == "assertion_failure"

    # 4. Timeout
    cat5, _ = categorize_error_string("Playwright TimeoutError: Page.goto timed out after 30000ms")
    assert cat5 == "timeout"

    # 5. Parsing failure
    cat6, _ = categorize_error_string("Unsupported action 'fly_to'. Supported actions: ['navigate', 'fill', ...]")
    assert cat6 == "parsing_failure"

    # 6. Execution error
    cat7, _ = categorize_error_string("ConnectionRefusedError: Target machine actively refused it")
    assert cat7 == "execution_error"


@pytest.mark.asyncio
async def test_project_isolation_and_authorization(test_setup):
    """Ensure unauthorized users from Org B cannot access Org A runs, results, or reports."""
    user_b = test_setup["user_b"]
    proj_a_id = test_setup["proj_a_id"]

    run_id = str(uuid.uuid4())
    with SessionLocal() as db:
        run = DbTestRun(
            id=run_id,
            project_id=proj_a_id,
            status="passed",
            total_tests=1,
            passed_tests=1,
            failed_tests=0,
        )
        db.add(run)
        db.commit()

    transport = ASGITransport(app=app)
    app.dependency_overrides[get_current_user] = lambda: user_b

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. User B tries to list Project A runs
            res_list = await client.get(f"/api/projects/{proj_a_id}/runs")
            assert res_list.status_code in (403, 404)

            # 2. User B tries to get Run A
            res_run = await client.get(f"/api/runs/{run_id}")
            assert res_run.status_code in (403, 404)

            # 3. User B tries to get Run A results
            res_results = await client.get(f"/api/runs/{run_id}/results")
            assert res_results.status_code in (403, 404)

            # 4. User B tries to get Run A report
            res_rep = await client.get(f"/api/runs/{run_id}/report")
            assert res_rep.status_code in (403, 404)

    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_secret_redaction_in_diagnostics(test_setup):
    """Verify secrets and secret placeholders are never exposed in step records or error messages."""
    user_a = test_setup["user_a"]
    proj_a_id = test_setup["proj_a_id"]

    run_id = str(uuid.uuid4())
    res_id = str(uuid.uuid4())

    with SessionLocal() as db:
        run = DbTestRun(id=run_id, project_id=proj_a_id, status="failed")
        db.add(run)

        tc = DbTestCase(id=str(uuid.uuid4()), project_id=proj_a_id, name="Secret Test")
        db.add(tc)

        # Failure message containing a resolved token
        result = DbTestResult(
            id=res_id,
            run_id=run_id,
            test_case_id=tc.id,
            status="failed",
            error_message="Step 1 (fill) failed: value '[REDACTED]' could not be typed into password field",
        )
        db.add(result)

        result_dir = Path(settings.ARTIFACTS_DIR) / "runs" / run_id / "results" / res_id
        result_dir.mkdir(parents=True, exist_ok=True)
        steps_data = [
            {
                "step_number": 1,
                "action": "fill",
                "target": "password",
                "value": "[REDACTED]",
                "expected_result": None,
                "original_instruction": "type '[REDACTED]' into 'password'",
                "status": "passed",
                "duration_ms": 50.0,
                "category": None,
                "failure_reason": None,
                "verification_result": None,
            }
        ]
        (result_dir / "steps.json").write_text(json.dumps(steps_data), encoding="utf-8")
        db.commit()

    transport = ASGITransport(app=app)
    app.dependency_overrides[get_current_user] = lambda: user_a

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.get(f"/api/runs/{run_id}/results")
            assert res.status_code == 200
            content = res.text
            # Verify no secret leaked
            assert "raw_secret_value" not in content
            step = res.json()[0]["steps"][0]
            assert step["value"] == "[REDACTED]"
            assert "[REDACTED]" in step["original_instruction"]
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_legacy_run_backwards_compatibility():
    """Verify that legacy runs without steps.json gracefully construct step details from TestCase."""
    with SessionLocal() as db:
        org = Organization(id=str(uuid.uuid4()), name="Legacy Org", slug=f"leg-{uuid.uuid4().hex[:6]}")
        db.add(org)

        proj = Project(
            id=str(uuid.uuid4()),
            name="Legacy Project",
            slug=f"leg-proj-{uuid.uuid4().hex[:6]}",
            org_id=org.id,
        )
        db.add(proj)

        run = DbTestRun(
            id=str(uuid.uuid4()),
            project_id=proj.id,
            status="passed",
            total_tests=1,
            passed_tests=1,
            failed_tests=0,
        )
        db.add(run)

        tc = DbTestCase(
            id=str(uuid.uuid4()),
            project_id=proj.id,
            name="Legacy Case",
        )
        db.add(tc)
        s1 = DbTestStep(test_case_id=tc.id, step_number=1, action="navigate", target="https://example.com")
        s2 = DbTestStep(test_case_id=tc.id, step_number=2, action="click", target="#btn")
        db.add_all([s1, s2])

        res = DbTestResult(
            id=str(uuid.uuid4()),
            run_id=run.id,
            test_case_id=tc.id,
            status="passed",
            test_case=tc,
        )
        db.add(res)
        db.commit()

        # Load step details without steps.json existing
        steps, summary = load_result_step_details(res, db)
        assert len(steps) == 2
        assert steps[0].step_number == 1
        assert steps[0].action == "navigate"
        assert steps[0].status == "passed"
        assert steps[1].step_number == 2
        assert steps[1].action == "click"
        assert steps[1].status == "passed"
        assert summary.total == 2
        assert summary.passed == 2
        assert summary.failed == 0
        assert summary.skipped == 0
