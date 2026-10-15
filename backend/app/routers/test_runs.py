"""
Test runs router — starts runs, tracks status, and exposes results.
"""
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal, get_db
from app.dependencies import (
    get_current_user,
    verify_project_access,
    verify_test_run_access,
)
from app.models.project import Project
from app.models.test_case import TestCase
from app.models.test_run import Artifact, TestResult, TestRun
from app.models.user import User
from app.schemas.test_run import RunCreateBody, RunStartRequest, TestResultResponse, TestRunResponse
from app.services.artifact_service import ArtifactService
from app.services.playwright_runner import run_test_case

router = APIRouter(tags=["Test Runs"])
settings = get_settings()


async def _execute_run(run_id: str, test_case_ids: List[str]) -> None:
    """
    Background task: executes all test cases for a run sequentially.
    Uses short-lived sessions so database connections are not held open
    across lengthy browser automation steps.
    """
    artifact_svc = ArtifactService(settings.ARTIFACTS_DIR)

    # 1. Initialize run to running
    with SessionLocal() as db:
        run = db.query(TestRun).filter(TestRun.id == run_id).first()
        if not run:
            return

        project = db.query(Project).filter(Project.id == run.project_id).first()
        app_url = (project.app_url or "") if project else ""

        run.status = "running"
        run.started_at = datetime.now(timezone.utc)
        db.commit()

    passed = 0
    failed = 0

    for tc_id in test_case_ids:
        # 2. Create TestResult and extract steps in a short transaction
        result_id = None
        steps = []
        with SessionLocal() as db:
            tc = db.query(TestCase).filter(TestCase.id == tc_id).first()
            if not tc:
                continue

            result = TestResult(
                run_id=run_id,
                test_case_id=tc_id,
                status="running",
                started_at=datetime.now(timezone.utc),
            )
            db.add(result)
            db.commit()
            result_id = result.id

            steps = [
                {
                    "step_number": s.step_number,
                    "action": s.action,
                    "target": s.target,
                    "value": s.value,
                    "expected_result": s.expected_result,
                }
                for s in tc.steps
            ]

        if not result_id:
            continue

        # 3. Execute browser automation without holding ANY database connection
        outcome = await run_test_case(
            steps=steps,
            app_url=app_url,
            artifacts_dir=settings.ARTIFACTS_DIR,
            run_id=run_id,
            test_case_id=result_id,
        )

        # 4. Save results and artifacts in a short transaction
        with SessionLocal() as db:
            result = db.query(TestResult).filter(TestResult.id == result_id).first()
            if result:
                result.status = outcome["status"]
                result.completed_at = datetime.now(timezone.utc)
                result.error_message = outcome.get("error_message")
                result.screenshot_path = outcome.get("screenshot_path")
                result.log_output = "\n".join(outcome.get("log_lines", []))

            if outcome["status"] == "passed":
                passed += 1
            else:
                failed += 1

            if outcome.get("screenshot_path"):
                ss_path = outcome["screenshot_path"]
                art = Artifact(
                    run_id=run_id,
                    result_id=result_id,
                    artifact_type="screenshot",
                    file_path=ss_path,
                    file_size=artifact_svc.file_size(
                        artifact_svc.absolute_path(ss_path)
                    ),
                    mime_type="image/png",
                )
                db.add(art)

            if outcome.get("video_path"):
                vp = outcome["video_path"]
                run = db.query(TestRun).filter(TestRun.id == run_id).first()
                if run and not run.video_path:
                    run.video_path = vp

                existing_video = (
                    db.query(Artifact)
                    .filter(
                        Artifact.run_id == run_id,
                        Artifact.artifact_type == "video",
                        Artifact.file_path == vp,
                    )
                    .first()
                )
                if not existing_video:
                    video_art = Artifact(
                        run_id=run_id,
                        result_id=result_id,
                        artifact_type="video",
                        file_path=vp,
                        file_size=artifact_svc.file_size(
                            artifact_svc.absolute_path(vp)
                        ),
                        mime_type="video/webm",
                    )
                    db.add(video_art)

            db.commit()

    # 5. Finalize run record
    with SessionLocal() as db:
        run = db.query(TestRun).filter(TestRun.id == run_id).first()
        if run:
            run.status = "passed" if failed == 0 else "failed"
            run.completed_at = datetime.now(timezone.utc)
            run.passed_tests = passed
            run.failed_tests = failed
            db.commit()


@router.post(
    "/api/projects/{project_id}/runs",
    response_model=TestRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_test_run(
    project_id: str,
    payload: RunStartRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TestRun:
    """
    Start a new test run for a project.
    Creates a TestRun record immediately and launches execution in the background.
    """
    project = verify_project_access(project_id, current_user, db)

    # Validate that the test cases belong to the project
    valid_ids = []
    for tc_id in payload.test_case_ids:
        tc = db.query(TestCase).filter(
            TestCase.id == tc_id,
            TestCase.project_id == project_id,
            TestCase.is_active.is_(True),
        ).first()
        if tc:
            valid_ids.append(tc_id)

    if not valid_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No valid active test cases found for this project.",
        )

    run = TestRun(
        project_id=project_id,
        status="pending",
        triggered_by=payload.triggered_by or current_user.email,
        total_tests=len(valid_ids),
        passed_tests=0,
        failed_tests=0,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    background_tasks.add_task(_execute_run, run.id, valid_ids)

    return run


@router.post(
    "/api/runs",
    response_model=TestRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_and_start_run(
    payload: RunCreateBody,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TestRun:
    """Start a test run with project_id and optional test_case_ids in JSON body."""
    project = verify_project_access(payload.project_id, current_user, db)

    if payload.test_case_ids and len(payload.test_case_ids) > 0:
        target_ids = payload.test_case_ids
    else:
        # Select all active test cases in project
        tcs = (
            db.query(TestCase)
            .filter(TestCase.project_id == payload.project_id, TestCase.is_active.is_(True))
            .all()
        )
        target_ids = [tc.id for tc in tcs]

    valid_ids = []
    for tc_id in target_ids:
        tc = db.query(TestCase).filter(
            TestCase.id == tc_id,
            TestCase.project_id == payload.project_id,
            TestCase.is_active.is_(True),
        ).first()
        if tc:
            valid_ids.append(tc_id)

    if not valid_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No valid active test cases found for this project.",
        )

    run = TestRun(
        project_id=payload.project_id,
        status="pending",
        triggered_by=payload.triggered_by or current_user.email or "QA Engineer",
        total_tests=len(valid_ids),
        passed_tests=0,
        failed_tests=0,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    background_tasks.add_task(_execute_run, run.id, valid_ids)

    return run


@router.get(
    "/api/projects/{project_id}/runs",
    response_model=List[TestRunResponse],
)
async def list_project_runs(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[TestRun]:
    """List all test runs for a project, most recent first."""
    verify_project_access(project_id, current_user, db)
    return (
        db.query(TestRun)
        .filter(TestRun.project_id == project_id)
        .order_by(TestRun.created_at.desc())
        .all()
    )


@router.get("/api/runs/{run_id}", response_model=TestRunResponse)
async def get_run(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TestRun:
    """Get the status and summary of a specific test run."""
    run = verify_test_run_access(run_id, current_user, db)
    return run


@router.get("/api/runs/{run_id}/results", response_model=List[TestResultResponse])
async def get_run_results(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[TestResult]:
    """Get all individual test case results for a run."""
    verify_test_run_access(run_id, current_user, db)
    return (
        db.query(TestResult)
        .filter(TestResult.run_id == run_id)
        .order_by(TestResult.started_at)
        .all()
    )
