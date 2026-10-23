"""
Reports router — serves full run reports and artifact files with authentication and authorization.
"""
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.dependencies import (
    get_current_user,
    get_user_org_ids,
    verify_artifact_access,
    verify_project_access,
    verify_test_run_access,
)
from app.models.project import Project
from app.models.test_run import Artifact, TestResult, TestRun
from app.models.user import User
from app.schemas.test_run import ArtifactResponse, RunReportResponse, TestResultResponse, TestRunResponse
from app.services.result_diagnostics import (
    build_run_report_response,
    enrich_test_run_response,
)

router = APIRouter(tags=["Reports"])
settings = get_settings()


@router.get("/api/runs/{run_id}/report", response_model=RunReportResponse)
async def get_run_report(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RunReportResponse:
    """Return a full report for a test run including all results, structured steps, and artifacts if user is authorized."""
    run = verify_test_run_access(run_id, current_user, db)

    results = (
        db.query(TestResult)
        .filter(TestResult.run_id == run_id)
        .order_by(TestResult.started_at)
        .all()
    )
    artifacts = db.query(Artifact).filter(Artifact.run_id == run_id).all()

    return build_run_report_response(run, results, artifacts, db)


@router.get("/api/runs/{run_id}/artifacts", response_model=List[ArtifactResponse])
async def list_run_artifacts(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[Artifact]:
    """List all artifacts generated during a test run if user is authorized."""
    verify_test_run_access(run_id, current_user, db)
    return db.query(Artifact).filter(Artifact.run_id == run_id).all()


ALLOWED_ARTIFACT_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".webp",
    ".webm", ".mp4",
    ".log", ".txt",
    ".json",
}


def _resolve_safe_artifact_path(raw_path_str: str) -> Path:
    """
    Safely resolve, canonicalize, and verify that raw_path_str points to an existing file
    strictly confined within settings.ARTIFACTS_DIR.
    Prevents path traversal, drive-letter escapes, and symlink escapes.
    """
    if not raw_path_str or "\x00" in raw_path_str:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid artifact path.",
        )

    base_dir = Path(settings.ARTIFACTS_DIR).resolve()

    # Normalize backslashes for cross-platform handling
    normalized = raw_path_str.replace("\\", "/").strip()

    # Reject empty or relative-root references
    if not normalized or normalized in (".", "/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid artifact path.",
        )

    # Check if this is an absolute path that is already within base_dir
    p = Path(normalized)
    if p.is_absolute():
        try:
            resolved = p.resolve()
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: Invalid artifact path.",
            )
        try:
            if not resolved.is_relative_to(base_dir):
                if "artifacts/" in normalized:
                    sub_rel = normalized.split("artifacts/", 1)[1].lstrip("/")
                    resolved = (base_dir / sub_rel).resolve()
                else:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Access denied: Invalid artifact path.",
                    )
        except (ValueError, AttributeError):
            if "artifacts/" in normalized:
                sub_rel = normalized.split("artifacts/", 1)[1].lstrip("/")
                resolved = (base_dir / sub_rel).resolve()
            else:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied: Invalid artifact path.",
                )
    else:
        # Relative path: if it starts with 'artifacts/' or './artifacts/', strip the prefix
        if normalized.startswith("./artifacts/"):
            normalized = normalized[len("./artifacts/"):]
        elif normalized.startswith("artifacts/"):
            normalized = normalized[len("artifacts/"):]

        resolved = (base_dir / normalized).resolve()

    # Final containment check: must be strictly inside base_dir and not equal to base_dir
    try:
        if not resolved.is_relative_to(base_dir) or resolved == base_dir:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: Invalid artifact path.",
            )
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Invalid artifact path.",
        )

    # Extension check
    if resolved.suffix.lower() not in ALLOWED_ARTIFACT_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported artifact file type.",
        )

    # Existence check
    if not resolved.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Artifact file not found.",
        )

    return resolved


@router.get("/api/artifacts/file")
async def serve_artifact_by_path(
    path: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FileResponse:
    """Serve an artifact file directly by its relative path within the artifacts directory, verifying authorization."""
    file_path = _resolve_safe_artifact_path(path)

    # If the path references a specific run (runs/<run_id>/...), enforce organization access
    normalized_rel = str(file_path.relative_to(Path(settings.ARTIFACTS_DIR).resolve())).replace("\\", "/")
    if normalized_rel.startswith("runs/"):
        parts = normalized_rel.split("/")
        if len(parts) >= 2:
            run_id = parts[1]
            run = db.query(TestRun).filter(TestRun.id == run_id).first()
            if run:
                verify_project_access(run.project_id, current_user, db)
            elif not current_user.is_superuser:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Test run not found.",
                )
    else:
        # Non-run artifacts: strictly require administrative privileges
        if not current_user.is_superuser:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: Non-run artifacts require administrative privileges.",
            )

    suffix = file_path.suffix.lower()
    mime_type = "video/webm" if suffix == ".webm" else (
        "video/mp4" if suffix == ".mp4" else (
            "image/png" if suffix == ".png" else (
                "image/jpeg" if suffix in (".jpg", ".jpeg") else (
                    "image/webp" if suffix == ".webp" else (
                        "text/plain" if suffix in (".log", ".txt") else (
                            "application/json" if suffix == ".json" else "application/octet-stream"
                        )
                    )
                )
            )
        )
    )
    return FileResponse(path=str(file_path), media_type=mime_type, filename=file_path.name)


@router.get("/api/artifacts/{artifact_id}")
async def serve_artifact(
    artifact_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FileResponse:
    """Serve an artifact file (screenshot, video, log) by its ID if user is authorized."""
    artifact = verify_artifact_access(artifact_id, current_user, db)
    file_path = _resolve_safe_artifact_path(artifact.file_path)

    return FileResponse(
        path=str(file_path),
        media_type=artifact.mime_type or "application/octet-stream",
        filename=file_path.name,
    )


@router.get("/artifacts/{path:path}")
async def serve_artifact_mounted(
    path: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FileResponse:
    """Authenticated route replacing the public static mount for /artifacts/<path>."""
    return await serve_artifact_by_path(path=path, current_user=current_user, db=db)


@router.get("/api/runs", response_model=List[TestRunResponse])
async def list_recent_runs(
    project_id: Optional[str] = None,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[TestRun]:
    """List recent test runs filtered by organizations accessible by the user, optionally filtered by project_id."""
    if project_id:
        verify_project_access(project_id, current_user, db)
        query = (
            db.query(TestRun)
            .filter(TestRun.project_id == project_id)
        )
    else:
        user_org_ids = get_user_org_ids(current_user, db)
        if not user_org_ids and not current_user.is_superuser:
            return []

        query = (
            db.query(TestRun)
            .join(Project, Project.id == TestRun.project_id)
        )
        if not current_user.is_superuser:
            query = query.filter(Project.org_id.in_(user_org_ids))

    runs = (
        query.order_by(TestRun.created_at.desc())
        .limit(limit)
        .all()
    )
    return [enrich_test_run_response(r, None, db) for r in runs]
