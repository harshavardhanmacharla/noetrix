"""
Regression test for multi-test-case video recording and association.
Verifies that when multiple test cases are executed in a single test run:
1. Each test case records its own video file in its isolated browser context.
2. Each test result artifact associates with the correct result_id.
3. TestResultResponse exposes the correct video_path for each test case.
4. RunReportResponse provides distinct video artifacts per test result.
"""
from datetime import datetime, timezone
from pathlib import Path
import pytest

from app.database import Base, SessionLocal, engine
from app.models.organization import Organization
from app.models.project import Project
from app.models.test_case import TestCase, TestStep
from app.models.test_run import Artifact, TestResult, TestRun
from app.routers import test_runs
from app.services.result_diagnostics import (
    build_run_report_response,
    build_test_result_response,
)

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
async def test_multi_test_run_associates_correct_video_per_result(
    monkeypatch,
    tmp_path,
    clean_db,
):
    """
    Test that running 3 test cases in a single run (like TC_009, TC_010, TC_011):
    1. Produces 3 distinct video recordings.
    2. Links each video to its own test result in artifacts and TestResultResponse.
    3. Exposes video_path on each result response so the UI displays the correct video per test.
    """
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(test_runs.settings, "ARTIFACTS_DIR", str(artifacts_dir))

    # Track invocations of run_test_case
    executed_cases = []

    async def fake_run_test_case(steps, app_url, artifacts_dir, run_id, test_case_id, project_id=None, variables=None):
        executed_cases.append(test_case_id)
        # Create a mock video file for this specific test case result
        videos_dir = Path(artifacts_dir) / "runs" / run_id / "videos"
        videos_dir.mkdir(parents=True, exist_ok=True)
        video_file = videos_dir / f"recording_{test_case_id}.webm"
        video_file.write_bytes(f"MOCK_VIDEO_DATA_{test_case_id}".encode("utf-8"))

        return {
            "status": "passed",
            "log_lines": [f"Execution log for result {test_case_id}"],
            "screenshot_path": None,
            "video_path": str(video_file),
            "error_message": None,
            "steps": [],
            "steps_path": None,
        }

    monkeypatch.setattr(test_runs, "run_test_case", fake_run_test_case)

    # 1. Setup project and 3 test cases (TC_009, TC_010, TC_011)
    with SessionLocal() as db:
        org = Organization(name="Video Test Org", slug="video-test-org")
        db.add(org)
        db.flush()

        proj = Project(
            name="Video Test Project",
            slug="video-test-proj",
            org_id=org.id,
            app_url="https://oracleapex.com/ords/r/test/login",
        )
        db.add(proj)
        db.flush()

        tc1 = TestCase(project_id=proj.id, name="TC_009 — Verify employee identity", is_active=True)
        tc2 = TestCase(project_id=proj.id, name="TC_010 — Verify project dropdown", is_active=True)
        tc3 = TestCase(project_id=proj.id, name="TC_011 — Verify week navigation", is_active=True)
        db.add_all([tc1, tc2, tc3])
        db.flush()

        run = TestRun(
            project_id=proj.id,
            status="pending",
            total_tests=3,
            passed_tests=0,
            failed_tests=0,
        )
        db.add(run)
        db.commit()

        run_id = run.id
        tc_ids = [tc1.id, tc2.id, tc3.id]

    # 2. Execute run with all 3 test cases
    await test_runs._execute_run(run_id, tc_ids)

    # 3. Verify database records and artifact associations
    with SessionLocal() as db:
        saved_run = db.query(TestRun).filter(TestRun.id == run_id).one()
        assert saved_run.status == "passed"
        assert saved_run.total_tests == 3
        assert saved_run.passed_tests == 3
        assert saved_run.failed_tests == 0
        assert saved_run.video_path is not None  # Fallback run video path

        results = db.query(TestResult).filter(TestResult.run_id == run_id).order_by(TestResult.started_at).all()
        assert len(results) == 3

        artifacts = db.query(Artifact).filter(Artifact.run_id == run_id, Artifact.artifact_type == "video").all()
        assert len(artifacts) == 3

        # Verify that each result has its own distinct video artifact
        result_video_map = {}
        for art in artifacts:
            assert art.result_id is not None
            assert Path(art.file_path).exists()
            result_video_map[art.result_id] = art.file_path

        assert len(result_video_map) == 3
        for res in results:
            assert res.id in result_video_map
            expected_video_suffix = f"recording_{res.id}.webm"
            assert result_video_map[res.id].endswith(expected_video_suffix)

            # Test build_test_result_response populates video_path on result
            res_response = build_test_result_response(res, db)
            assert res_response.video_path is not None
            assert res_response.video_path == result_video_map[res.id]

        # Test build_run_report_response provides distinct video_path per result in the full report
        report = build_run_report_response(saved_run, results, artifacts, db)
        assert len(report.results) == 3
        assert report.results[0].video_path != report.results[1].video_path
        assert report.results[1].video_path != report.results[2].video_path
        assert report.results[0].video_path != report.results[2].video_path

        # Verify TC_011 result (index 2) has its own distinct video
        assert report.results[2].video_path.endswith(f"recording_{results[2].id}.webm")

