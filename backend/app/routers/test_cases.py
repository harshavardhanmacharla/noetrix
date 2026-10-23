"""
Test cases router with authentication, tenant isolation, and natural-language test creation.
"""
import io
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.dependencies import (
    get_current_user,
    get_user_org_ids,
    verify_project_access,
    verify_test_case_access,
)
from app.models.project import Project
from app.models.test_case import TestCase, TestStep
from app.models.user import User
from app.schemas.test_case import (
    CreateTestCaseFromInstructionsRequest,
    ParseInstructionsRequest,
    ParseInstructionsResponse,
    ParsedStepItem,
    TestCaseResponse,
)
from app.services.csv_validator import (
    REQUIRED_COLUMNS,
    SUPPORTED_ACTIONS,
    ValidationResult,
    validate_csv,
)
from app.services.instruction_parser import parse_instruction

router = APIRouter(tags=["Test Cases"])
settings = get_settings()

CSV_TEMPLATE_ROWS = [
    "TC001,Login Test,1,navigate,,https://example.com,",
    "TC001,Login Test,2,fill,#username,admin@example.com,",
    "TC001,Login Test,3,fill,#password,secret123,",
    "TC001,Login Test,4,click,button[type=submit],,",
    "TC001,Login Test,5,verify_url,,,https://example.com/dashboard",
    "TC002,Search Test,1,navigate,,https://example.com,",
    "TC002,Search Test,2,fill,input[name=search],test query,",
    "TC002,Search Test,3,click,.search-btn,,",
    "TC002,Search Test,4,verify_text,.search-results,,Results found",
]


def extract_instruction_lines(
    instructions: Optional[List[str]] = None,
    raw_text: Optional[str] = None,
) -> List[tuple[int, str]]:
    """
    Extract non-empty natural language instruction lines with 1-based line numbers.
    Skips purely blank or whitespace-only lines gracefully.
    """
    lines: List[tuple[int, str]] = []
    if raw_text is not None:
        for idx, line in enumerate(raw_text.splitlines(), start=1):
            stripped = line.strip()
            if stripped:
                lines.append((idx, stripped))
    elif instructions is not None:
        line_counter = 1
        for item in instructions:
            sub_lines = (item or "").splitlines()
            if not sub_lines:
                stripped = (item or "").strip()
                if stripped:
                    lines.append((line_counter, stripped))
                    line_counter += 1
            else:
                for sub in sub_lines:
                    stripped = sub.strip()
                    if stripped:
                        lines.append((line_counter, stripped))
                        line_counter += 1
    return lines


@router.post("/api/test-cases/parse-instructions", response_model=ParseInstructionsResponse)
async def parse_instructions_endpoint(
    req: ParseInstructionsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ParseInstructionsResponse:
    """
    Parse a sequence of plain-English test instructions into canonical Playwright actions.
    Performs tenant/project authorization checks and returns structured validation diagnostics
    without executing or persisting test steps.
    """
    verify_project_access(req.project_id, current_user, db)

    raw_lines = extract_instruction_lines(req.instructions, req.raw_text)
    if not raw_lines:
        return ParseInstructionsResponse(
            is_valid=False,
            total_lines=0,
            valid_steps_count=0,
            steps=[],
            errors=[{
                "line": 0,
                "instruction": "",
                "message": "No instructions provided. Please enter at least one natural-language instruction.",
            }],
        )

    parsed_steps: List[ParsedStepItem] = []
    errors: List[dict] = []

    for line_num, line_text in raw_lines:
        res = parse_instruction(line_text)
        if res.is_valid and res.action_data:
            parsed_steps.append(
                ParsedStepItem(
                    line_number=line_num,
                    raw_instruction=line_text,
                    is_valid=True,
                    action=res.action_data.action,
                    target=res.action_data.target,
                    value=res.action_data.value,
                    expected_result=res.action_data.expected_result,
                    confidence=res.action_data.confidence,
                )
            )
        else:
            err_msg = res.error or f"Could not interpret instruction '{line_text}'."
            parsed_steps.append(
                ParsedStepItem(
                    line_number=line_num,
                    raw_instruction=line_text,
                    is_valid=False,
                    error=err_msg,
                )
            )
            errors.append({
                "line": line_num,
                "instruction": line_text,
                "message": err_msg,
            })

    all_valid = (len(errors) == 0)
    valid_count = sum(1 for s in parsed_steps if s.is_valid)

    return ParseInstructionsResponse(
        is_valid=all_valid,
        total_lines=len(raw_lines),
        valid_steps_count=valid_count,
        steps=parsed_steps,
        errors=errors,
    )


@router.post(
    "/api/test-cases/create-from-instructions",
    response_model=TestCaseResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_from_instructions(
    req: CreateTestCaseFromInstructionsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TestCase:
    """
    Validate natural-language instructions and persist as an active TestCase with ordered TestSteps.
    Preserves organization/project isolation. Does not launch execution.
    """
    verify_project_access(req.project_id, current_user, db)

    name_clean = req.name.strip()
    if not name_clean:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Test case name is required.",
        )

    raw_lines = extract_instruction_lines(req.instructions, req.raw_text)
    if not raw_lines:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No instructions provided. Please enter at least one natural-language instruction.",
        )

    valid_steps = []
    errors = []

    for line_num, line_text in raw_lines:
        res = parse_instruction(line_text)
        if res.is_valid and res.action_data:
            valid_steps.append(res.action_data)
        else:
            errors.append(f"Line {line_num} ('{line_text}'): {res.error}")

    if errors:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot save test case with invalid instructions: {'; '.join(errors)}",
        )

    try:
        tc = TestCase(
            project_id=req.project_id,
            name=name_clean,
            description=req.description.strip() if req.description else None,
            created_by=current_user.email,
            csv_filename="natural_language",
            is_active=True,
        )
        db.add(tc)
        db.flush()

        for idx, step_data in enumerate(valid_steps, start=1):
            step = TestStep(
                test_case_id=tc.id,
                step_number=idx,
                action=step_data.action,
                target=step_data.target,
                value=step_data.value,
                expected_result=step_data.expected_result,
            )
            db.add(step)

        db.commit()
        db.refresh(tc)
        return tc
    except Exception:
        db.rollback()
        raise


@router.post(
    "/api/projects/{project_id}/test-cases/from-instructions",
    response_model=TestCaseResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_from_instructions_project_route(
    project_id: str,
    req: CreateTestCaseFromInstructionsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TestCase:
    """Project-scoped alias for creating a test case from natural language instructions."""
    req.project_id = project_id
    return await create_from_instructions(req, current_user, db)


@router.get("/api/test-cases", response_model=List[TestCaseResponse])
async def list_all_test_cases(
    project_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[TestCase]:
    """List test cases accessible by current user, optionally filtered by project_id."""
    if project_id:
        verify_project_access(project_id, current_user, db)
        return (
            db.query(TestCase)
            .filter(TestCase.project_id == project_id, TestCase.is_active.is_(True))
            .order_by(TestCase.created_at.desc())
            .all()
        )

    user_org_ids = get_user_org_ids(current_user, db)
    if not user_org_ids and not current_user.is_superuser:
        return []

    query = (
        db.query(TestCase)
        .join(Project, Project.id == TestCase.project_id)
        .filter(TestCase.is_active.is_(True))
    )
    if not current_user.is_superuser:
        query = query.filter(Project.org_id.in_(user_org_ids))

    return query.order_by(TestCase.created_at.desc()).all()


@router.get("/api/projects/{project_id}/test-cases", response_model=List[TestCaseResponse])
async def list_test_cases(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[TestCase]:
    """List all test cases for a project if user has organization access."""
    verify_project_access(project_id, current_user, db)
    return (
        db.query(TestCase)
        .filter(TestCase.project_id == project_id, TestCase.is_active.is_(True))
        .order_by(TestCase.created_at.desc())
        .all()
    )


@router.post(
    "/api/projects/{project_id}/test-cases/upload",
    status_code=status.HTTP_201_CREATED,
)
async def upload_test_cases_csv(
    project_id: str,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """
    Upload a CSV file, validate it, and persist test cases + steps to DB.
    Verifies organization authorization before saving.
    """
    verify_project_access(project_id, current_user, db)

    content = await file.read()
    if len(content) > settings.max_upload_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds max upload size of {settings.MAX_UPLOAD_SIZE_MB} MB.",
        )

    result = validate_csv(content, filename=file.filename or "upload.csv")

    val_dump = result.model_dump()
    if not result.is_valid:
        return {
            **val_dump,
            "validation": val_dump,
            "saved": False,
            "created_test_cases": [],
        }

    created_ids = []
    try:
        for parsed_case in result.parsed_cases:
            tc = TestCase(
                project_id=project_id,
                name=parsed_case["test_name"],
                created_by=current_user.email,
                csv_filename=file.filename,
                is_active=True,
            )
            db.add(tc)
            db.flush()

            for step_data in parsed_case["steps"]:
                step = TestStep(
                    test_case_id=tc.id,
                    step_number=step_data["step_number"],
                    action=step_data["action"],
                    target=step_data.get("target"),
                    value=step_data.get("value"),
                    expected_result=step_data.get("expected_result"),
                )
                db.add(step)

            created_ids.append({"id": tc.id, "name": tc.name})

        db.commit()
    except Exception:
        db.rollback()
        raise

    return {
        **val_dump,
        "validation": val_dump,
        "saved": True,
        "created_test_cases": created_ids,
    }


@router.post("/api/test-cases/upload-csv", status_code=status.HTTP_201_CREATED)
async def upload_csv_form(
    project_id: str = Form(...),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Form upload endpoint for test cases CSV."""
    return await upload_test_cases_csv(
        project_id=project_id,
        file=file,
        current_user=current_user,
        db=db,
    )


@router.post("/api/test-cases/validate-csv")
async def validate_csv_endpoint(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Validate uploaded CSV without saving to database."""
    content = await file.read()
    result = validate_csv(content, filename=file.filename or "upload.csv")
    return result.model_dump()


@router.get("/api/test-cases/{test_case_id}", response_model=TestCaseResponse)
async def get_test_case(
    test_case_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TestCase:
    """Get a single test case with its steps if user has access."""
    return verify_test_case_access(test_case_id, current_user, db)


@router.delete("/api/test-cases/{test_case_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_test_case(
    test_case_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Soft-delete a test case by setting is_active=False if user has access."""
    tc = verify_test_case_access(test_case_id, current_user, db)
    tc.is_active = False
    db.commit()


@router.get("/api/csv-template")
async def download_csv_template(
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Return a downloadable CSV template file with example data."""
    header = ",".join(REQUIRED_COLUMNS)
    body = "\n".join(CSV_TEMPLATE_ROWS)
    content = f"{header}\n{body}\n"

    return StreamingResponse(
        io.BytesIO(content.encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="testpilot_template.csv"'},
    )
