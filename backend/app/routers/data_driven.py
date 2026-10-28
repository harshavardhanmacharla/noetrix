"""
Data-driven test execution router for Noetrix.

Allows users to inspect placeholders in test cases, validate data records,
preview substituted workflows, and launch multi-record executions sequentially
reusing the existing Playwright runner, while automatically excluding variables
configured at the project level.
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal, get_db
from app.dependencies import (
    get_current_user,
    verify_project_access,
)
from app.models.project import Project
from app.models.project_variable import ProjectVariable
from app.models.test_case import TestCase
from app.models.test_run import Artifact, TestResult, TestRun
from app.models.user import User
from app.schemas.data_driven import (
    DataDrivenPreviewRequest,
    DataDrivenPreviewResponse,
    DataDrivenRunRequest,
    DataDrivenValidationRequest,
    DataDrivenValidationResponse,
    TestCasePlaceholdersResponse,
)
from app.schemas.test_run import TestRunResponse
from app.services.artifact_service import ArtifactService
from app.services.data_driven_service import (
    extract_test_case_placeholders,
    filter_data_columns,
    mask_sensitive_record_values,
    substitute_record_placeholders,
    validate_record_data,
)
from app.services.playwright_runner import run_test_case

router = APIRouter(tags=["Data-Driven Testing"])
settings = get_settings()


async def _execute_data_driven_run(
    run_id: str,
    test_case_id: str,
    records: List[Dict[str, Any]],
    stop_on_failure: bool,
) -> None:
    """
    Background worker: sequentially executes each test data record
    using substituted step copies through the existing Playwright runner.
    Project-configured variables are left intact for runtime resolution by Playwright.
    """
    artifact_svc = ArtifactService(settings.ARTIFACTS_DIR)

    # 1. Initialize run to running and fetch project context
    with SessionLocal() as db:
        run = db.query(TestRun).filter(TestRun.id == run_id).first()
        if not run:
            return

        project = db.query(Project).filter(Project.id == run.project_id).first()
        app_url = (project.app_url or "") if project else ""

        tc = db.query(TestCase).filter(TestCase.id == test_case_id).first()
        if not tc:
            run.status = "error"
            run.error_message = f"TestCase '{test_case_id}' not found."
            run.completed_at = datetime.now(timezone.utc)
            db.commit()
            return

        project_id = tc.project_id
        original_steps = [
            {
                "step_number": s.step_number,
                "action": s.action,
                "target": s.target,
                "value": s.value,
                "expected_result": s.expected_result,
            }
            for s in tc.steps
        ]

        # Retrieve configured project variable names for this project
        project_vars = db.query(ProjectVariable.name).filter(ProjectVariable.project_id == project_id).all()
        configured_var_names: Set[str] = {v.name for v in project_vars}

        run.status = "running"
        run.started_at = datetime.now(timezone.utc)
        db.commit()

    passed_count = 0
    failed_count = 0
    errors_count = 0
    halt_further_records = False
    halt_reason = ""

    for rec_idx, record in enumerate(records, start=1):
        safe_record_dict = mask_sensitive_record_values(record)
        record_desc = ", ".join(f"{k}='{v}'" for k, v in safe_record_dict.items())

        # If a prior record failed and stop_on_failure is enabled, mark remaining as skipped
        if halt_further_records:
            with SessionLocal() as db:
                skipped_res = TestResult(
                    run_id=run_id,
                    test_case_id=test_case_id,
                    status="skipped",
                    started_at=datetime.now(timezone.utc),
                    completed_at=datetime.now(timezone.utc),
                    error_message=f"Skipped: {halt_reason}",
                    log_output=(
                        f"[Record #{rec_idx} of {len(records)}: {record_desc}]\n"
                        f"SKIPPED: Execution halted after failure in previous record."
                    ),
                )
                db.add(skipped_res)
                db.commit()
            continue

        # 2. Create running TestResult record for this iteration
        result_id = None
        with SessionLocal() as db:
            result = TestResult(
                run_id=run_id,
                test_case_id=test_case_id,
                status="running",
                started_at=datetime.now(timezone.utc),
            )
            db.add(result)
            db.commit()
            result_id = result.id

        if not result_id:
            continue

        # 3. Substitute record-specific placeholders.
        # Variables configured at project level are preserved for Playwright runner resolution.
        try:
            substituted_steps = substitute_record_placeholders(
                original_steps,
                record,
                allowed_missing=configured_var_names,
            )
        except Exception as subst_err:
            with SessionLocal() as db:
                result = db.query(TestResult).filter(TestResult.id == result_id).first()
                if result:
                    result.status = "error"
                    result.completed_at = datetime.now(timezone.utc)
                    result.error_message = f"Data substitution error: {subst_err}"
                    result.log_output = f"[Record #{rec_idx}: {record_desc}]\nFailed to substitute placeholders: {subst_err}"
                errors_count += 1
                failed_count += 1
                db.commit()

            if stop_on_failure:
                halt_further_records = True
                halt_reason = f"Data mapping failure on Record #{rec_idx} ({subst_err})"
            continue

        # 4. Execute the workflow using the existing Playwright runner.
        # The runner automatically resolves any remaining {{project_var}} placeholders with decryption.
        outcome = await run_test_case(
            steps=substituted_steps,
            app_url=app_url,
            artifacts_dir=settings.ARTIFACTS_DIR,
            run_id=run_id,
            test_case_id=result_id,
            project_id=project_id,
        )

        # 5. Save outcome and artifacts in a short transaction
        with SessionLocal() as db:
            result = db.query(TestResult).filter(TestResult.id == result_id).first()
            if result:
                result.status = outcome["status"]
                result.completed_at = datetime.now(timezone.utc)
                result.error_message = outcome.get("error_message")
                result.screenshot_path = outcome.get("screenshot_path")
                banner = f"[Record #{rec_idx} of {len(records)}: {record_desc}]"
                result.log_output = f"{banner}\n" + "\n".join(outcome.get("log_lines", []))

            if outcome["status"] == "passed":
                passed_count += 1
            else:
                failed_count += 1
                if outcome["status"] == "error":
                    errors_count += 1

                if stop_on_failure:
                    halt_further_records = True
                    halt_reason = (
                        f"Record #{rec_idx} failed with {outcome.get('error_message') or 'execution error'}. "
                        "Halted to prevent duplicate submissions or inconsistent state."
                    )

            if outcome.get("screenshot_path"):
                ss_path = outcome["screenshot_path"]
                art = Artifact(
                    run_id=run_id,
                    result_id=result_id,
                    artifact_type="screenshot",
                    file_path=ss_path,
                    file_size=artifact_svc.file_size(artifact_svc.absolute_path(ss_path)),
                    mime_type="image/png",
                )
                db.add(art)

            if outcome.get("video_path"):
                vp = outcome["video_path"]
                run = db.query(TestRun).filter(TestRun.id == run_id).first()
                if run and not run.video_path:
                    run.video_path = vp

                video_art = Artifact(
                    run_id=run_id,
                    result_id=result_id,
                    artifact_type="video",
                    file_path=vp,
                    file_size=artifact_svc.file_size(artifact_svc.absolute_path(vp)),
                    mime_type="video/webm",
                )
                db.add(video_art)

            if outcome.get("steps_path"):
                stp_path = outcome["steps_path"]
                steps_art = Artifact(
                    run_id=run_id,
                    result_id=result_id,
                    artifact_type="log",
                    file_path=stp_path,
                    file_size=artifact_svc.file_size(artifact_svc.absolute_path(stp_path)),
                    mime_type="application/json",
                )
                db.add(steps_art)

            db.commit()

    # 6. Finalize TestRun record
    with SessionLocal() as db:
        run = db.query(TestRun).filter(TestRun.id == run_id).first()
        if run:
            run.status = "error" if errors_count else ("failed" if failed_count else "passed")
            if failed_count > 0:
                run.error_message = (
                    f"Data-driven run completed: {passed_count} passed, {failed_count} failed"
                    + (f" ({halt_reason})" if halt_further_records else ".")
                )
            else:
                run.error_message = None
            run.completed_at = datetime.now(timezone.utc)
            run.passed_tests = passed_count
            run.failed_tests = failed_count
            db.commit()


@router.get(
    "/api/test-cases/{test_case_id}/placeholders",
    response_model=TestCasePlaceholdersResponse,
)
async def get_test_case_placeholders(
    test_case_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TestCasePlaceholdersResponse:
    """
    Inspect a saved TestCase and extract its placeholder variables,
    excluding variables that are already configured in Project Test Variables.
    """
    tc = db.query(TestCase).filter(TestCase.id == test_case_id).first()
    if not tc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="TestCase not found.")

    verify_project_access(tc.project_id, current_user, db)

    all_placeholders = extract_test_case_placeholders(tc.steps)

    # Retrieve project-configured variables
    project_vars = db.query(ProjectVariable.name).filter(ProjectVariable.project_id == tc.project_id).all()
    project_var_names = sorted([v.name for v in project_vars])

    # Filter: data_columns = all_placeholders - project_variables
    data_columns = filter_data_columns(all_placeholders, project_var_names)

    return TestCasePlaceholdersResponse(
        test_case_id=tc.id,
        test_case_name=tc.name,
        placeholders=data_columns,
        all_placeholders=all_placeholders,
        project_variables=project_var_names,
        step_count=len(tc.steps),
        has_placeholders=len(data_columns) > 0,
    )


@router.post(
    "/api/test-cases/{test_case_id}/validate-data",
    response_model=DataDrivenValidationResponse,
)
async def validate_test_data(
    test_case_id: str,
    payload: DataDrivenValidationRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DataDrivenValidationResponse:
    """
    Validate a set of data records against required placeholders,
    excluding variables that are configured at the project level.
    """
    tc = db.query(TestCase).filter(TestCase.id == test_case_id).first()
    if not tc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="TestCase not found.")

    verify_project_access(tc.project_id, current_user, db)

    all_placeholders = extract_test_case_placeholders(tc.steps)

    project_vars = db.query(ProjectVariable.name).filter(ProjectVariable.project_id == tc.project_id).all()
    project_var_names = sorted([v.name for v in project_vars])

    data_columns = filter_data_columns(all_placeholders, project_var_names)
    is_valid, errors = validate_record_data(all_placeholders, payload.records, project_variables=project_var_names)

    return DataDrivenValidationResponse(
        is_valid=is_valid,
        errors=errors,
        record_count=len(payload.records),
        placeholders=data_columns,
        all_placeholders=all_placeholders,
        project_variables=project_var_names,
    )


@router.post(
    "/api/test-cases/{test_case_id}/preview-data",
    response_model=DataDrivenPreviewResponse,
)
async def preview_substituted_steps(
    test_case_id: str,
    payload: DataDrivenPreviewRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DataDrivenPreviewResponse:
    """
    Preview how the test case's steps will look when substituted with a given record's values
    and project variables. Secret project variables are never exposed in plaintext.
    """
    tc = db.query(TestCase).filter(TestCase.id == test_case_id).first()
    if not tc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="TestCase not found.")

    verify_project_access(tc.project_id, current_user, db)

    all_placeholders = extract_test_case_placeholders(tc.steps)
    project_vars = db.query(ProjectVariable).filter(ProjectVariable.project_id == tc.project_id).all()
    project_var_map = {v.name: v for v in project_vars}

    # Verify that every placeholder in steps is supplied by the record OR configured in project variables
    missing = [p for p in all_placeholders if p not in payload.record and p not in project_var_map]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Placeholder '{{{{{missing[0]}}}}}' is missing from test data record and is not configured in Project Test Variables.",
        )

    # Build safe preview mapping: record values override project variables; secrets are masked
    preview_record: Dict[str, Any] = {}
    # First, project variables
    for v_name, v_model in project_var_map.items():
        if v_model.is_secret:
            preview_record[v_name] = "[REDACTED]"
        else:
            preview_record[v_name] = v_model.value or ""
    # Second, record-specific values override project variables
    for r_k, r_v in payload.record.items():
        preview_record[r_k] = r_v

    original_steps = [
        {
            "step_number": s.step_number,
            "action": s.action,
            "target": s.target,
            "value": s.value,
            "expected_result": s.expected_result,
        }
        for s in tc.steps
    ]

    try:
        substituted = substitute_record_placeholders(original_steps, preview_record)
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(ve))

    return DataDrivenPreviewResponse(
        test_case_id=tc.id,
        record=mask_sensitive_record_values(payload.record),
        steps=substituted,
    )


@router.post(
    "/api/projects/{project_id}/data-driven-runs",
    response_model=TestRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_data_driven_run(
    project_id: str,
    payload: DataDrivenRunRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TestRun:
    """
    Start a data-driven test run for a specific test case using multiple data records.
    Excludes configured project variables from required data columns and rejects runs
    if any placeholder is missing from both the record and project variables.
    """
    project = verify_project_access(project_id, current_user, db)

    tc = db.query(TestCase).filter(
        TestCase.id == payload.test_case_id,
        TestCase.project_id == project_id,
        TestCase.is_active.is_(True),
    ).first()

    if not tc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Test case '{payload.test_case_id}' not found in project '{project_id}'.",
        )

    all_placeholders = extract_test_case_placeholders(tc.steps)
    if not all_placeholders:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Test case '{tc.name}' does not contain any placeholder variables (e.g. {{{{variable}}}}). "
                "Data-driven testing requires placeholders in test steps."
            ),
        )

    project_vars = db.query(ProjectVariable.name).filter(ProjectVariable.project_id == project_id).all()
    project_var_names = set(v.name for v in project_vars)

    data_columns = filter_data_columns(all_placeholders, project_var_names)
    if not data_columns:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"All placeholders in test case '{tc.name}' are already configured as Project Test Variables. "
                "Data-driven execution requires at least one custom record-specific data column."
            ),
        )

    # Validate that records supply every remaining data column
    is_valid, validation_errors = validate_record_data(
        all_placeholders,
        payload.records,
        project_variables=project_var_names,
    )
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Data validation failed: {'; '.join(validation_errors)}",
        )

    trigger_label = payload.triggered_by or f"Data-Driven ({len(payload.records)} records): {current_user.email}"

    run = TestRun(
        project_id=project_id,
        status="pending",
        triggered_by=trigger_label,
        total_tests=len(payload.records),
        passed_tests=0,
        failed_tests=0,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    background_tasks.add_task(
        _execute_data_driven_run,
        run.id,
        tc.id,
        payload.records,
        payload.stop_on_failure,
    )

    return run
