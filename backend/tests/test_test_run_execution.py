"""Regression tests for test run status aggregation."""
import pytest
from httpx import ASGITransport, AsyncClient

import app.models  # noqa: F401
from app.database import Base, SessionLocal, engine
from app.models.organization import Organization
from app.models.project import Project
from app.models.test_case import TestCase, TestStep
from app.models.test_run import TestResult, TestRun
from app.models.user import User
from app.routers import test_runs
from app.main import app
from app.services.security import create_access_token

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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("outcome_status", "expected_run_status"),
    [("failed", "failed"), ("error", "error")],
)
async def test_execute_run_preserves_case_error_status(
    outcome_status,
    expected_run_status,
    monkeypatch,
    tmp_path,
    clean_db,
):
    async def fake_run_test_case(**_kwargs):
        return {
            "status": outcome_status,
            "error_message": f"case {outcome_status}",
            "log_lines": [],
            "screenshot_path": None,
            "video_path": None,
        }

    monkeypatch.setattr(test_runs, "run_test_case", fake_run_test_case)
    monkeypatch.setattr(test_runs.settings, "ARTIFACTS_DIR", str(tmp_path))

    with SessionLocal() as db:
        organization = Organization(name="Run Test Org", slug="run-test-org")
        db.add(organization)
        db.flush()
        project = Project(
            name="Run Test Project",
            slug="run-test-project",
            org_id=organization.id,
            app_url="https://example.invalid",
        )
        db.add(project)
        db.flush()
        test_case = TestCase(
            project_id=project.id,
            name="Run Status Case",
            is_active=True,
        )
        db.add(test_case)
        run = TestRun(
            project_id=project.id,
            status="pending",
            total_tests=1,
            passed_tests=0,
            failed_tests=0,
        )
        db.add(run)
        db.commit()
        run_id = run.id
        test_case_id = test_case.id

    await test_runs._execute_run(run_id, [test_case_id])

    with SessionLocal() as db:
        run = db.query(TestRun).filter(TestRun.id == run_id).one()
        result = run.results[0]
        assert run.status == expected_run_status
        assert run.completed_at is not None
        assert run.failed_tests == 1
        assert result.status == outcome_status
        assert result.error_message == f"case {outcome_status}"
        if outcome_status == "error":
            assert run.error_message == (
                "Execution errors occurred in 1 test case(s). "
                "See individual results for details."
            )
        else:
            assert run.error_message is None


@pytest.mark.asyncio
async def test_run_report_includes_error_count_and_run_message(clean_db):
    with SessionLocal() as db:
        user = User(
            email="report-error@example.com",
            hashed_password="not-used-by-this-test",
            is_active=True,
            is_superuser=True,
        )
        organization = Organization(name="Report Error Org", slug="report-error-org")
        db.add_all([user, organization])
        db.flush()
        project = Project(
            name="Report Error Project",
            slug="report-error-project",
            org_id=organization.id,
        )
        db.add(project)
        db.flush()
        run = TestRun(
            project_id=project.id,
            status="error",
            total_tests=1,
            passed_tests=0,
            failed_tests=1,
            error_message="Execution errors occurred in 1 test case(s). See individual results for details.",
        )
        db.add(run)
        db.flush()
        db.add(
            TestResult(
                run_id=run.id,
                status="error",
                error_message="Playwright browser failed to launch.",
            )
        )
        db.commit()
        user_id = user.id
        run_id = run.id

    token = create_access_token(data={"sub": user_id})
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(
            f"/api/runs/{run_id}/report",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    report = response.json()
    assert report["summary"]["errors"] == 1
    assert report["run"]["error_message"] == (
        "Execution errors occurred in 1 test case(s). "
        "See individual results for details."
    )


@pytest.mark.asyncio
async def test_report_response_does_not_expose_missing_secret_reference(
    monkeypatch, clean_db
):
    missing_name = "NOETRIX_REPORT_MISSING_SECRET"

    async def fake_run_test_case(**_kwargs):
        return {
            "status": "failed",
            "error_message": (
                "Step 1 (fill) failed: Required secret is not configured."
            ),
            "log_lines": [
                "[12:00:00.000] Step 1: [fill] target='#password' value='[REDACTED]'"
            ],
            "screenshot_path": None,
            "video_path": None,
        }

    monkeypatch.setattr(test_runs, "run_test_case", fake_run_test_case)
    with SessionLocal() as db:
        user = User(
            email="report-secret@example.com",
            hashed_password="not-used-by-this-test",
            is_active=True,
            is_superuser=True,
        )
        organization = Organization(
            name="Report Secret Org",
            slug="report-secret-org",
        )
        db.add_all([user, organization])
        db.flush()
        project = Project(
            name="Report Secret Project",
            slug="report-secret-project",
            org_id=organization.id,
        )
        db.add(project)
        db.flush()
        test_case = TestCase(
            project_id=project.id,
            name="Missing Secret Case",
            is_active=True,
        )
        db.add(test_case)
        db.flush()
        db.add(
            TestStep(
                test_case_id=test_case.id,
                step_number=1,
                action="fill",
                target="#password",
                value=f"${{secret:{missing_name}}}",
            )
        )
        run = TestRun(
            project_id=project.id,
            status="pending",
            total_tests=1,
            passed_tests=0,
            failed_tests=0,
        )
        db.add(run)
        db.commit()
        user_id = user.id
        run_id = run.id
        test_case_id = test_case.id

    await test_runs._execute_run(run_id, [test_case_id])
    token = create_access_token(data={"sub": user_id})
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(
            f"/api/runs/{run_id}/report",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    report_text = response.text
    assert "Required secret is not configured" in report_text
    assert missing_name not in report_text
    assert f"${{secret:{missing_name}}}" not in report_text
