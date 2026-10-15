"""
Projects router with tenant authorization.
"""
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import (
    get_current_user,
    get_user_org_ids,
    verify_org_access,
    verify_org_admin_access,
    verify_project_access,
)
from app.models.organization import Organization
from app.models.project import Project
from app.models.test_case import TestCase
from app.models.test_run import TestRun
from app.models.user import User
from app.schemas.project import ProjectCreate, ProjectResponse, ProjectUpdate

router = APIRouter(tags=["Projects"])


@router.get("/api/projects", response_model=List[ProjectResponse])
async def list_all_projects(
    org_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[Project]:
    """List projects across accessible organizations, optionally filtered by org_id."""
    user_org_ids = get_user_org_ids(current_user, db)
    if not user_org_ids and not current_user.is_superuser:
        return []

    query = db.query(Project)
    if org_id:
        verify_org_access(org_id, current_user, db)
        query = query.filter(Project.org_id == org_id)
    elif not current_user.is_superuser:
        query = query.filter(Project.org_id.in_(user_org_ids))

    return query.order_by(Project.created_at.desc()).all()


@router.post("/api/projects", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_generic_project(
    payload: ProjectCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Project:
    """Create a project within an accessible organization."""
    org_id = payload.org_id
    if org_id:
        verify_org_access(org_id, current_user, db)
    else:
        user_org_ids = list(get_user_org_ids(current_user, db))
        if not user_org_ids:
            # Create a default organization for this user
            org = Organization(
                name="Default Workspace",
                slug=f"org-{current_user.id[:8]}",
                description="Default workspace organization",
            )
            db.add(org)
            db.flush()
            from app.models.organization import OrganizationMembership
            membership = OrganizationMembership(
                org_id=org.id,
                user_id=current_user.id,
                role="owner",
                created_at=datetime.now(timezone.utc),
            )
            db.add(membership)
            db.commit()
            org_id = org.id
        else:
            org_id = user_org_ids[0]

    project = Project(
        name=payload.name,
        slug=payload.slug,
        description=payload.description,
        org_id=org_id,
        app_url=payload.app_url,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get("/api/organizations/{org_id}/projects", response_model=List[ProjectResponse])
async def list_projects(
    org_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[Project]:
    """List all projects for an organization if user has access."""
    verify_org_access(org_id, current_user, db)
    return (
        db.query(Project)
        .filter(Project.org_id == org_id)
        .order_by(Project.created_at.desc())
        .all()
    )


@router.post(
    "/api/organizations/{org_id}/projects",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_project(
    org_id: str,
    payload: ProjectCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Project:
    """Create a new project within a specific organization."""
    verify_org_access(org_id, current_user, db)

    project = Project(
        name=payload.name,
        slug=payload.slug,
        description=payload.description,
        org_id=org_id,
        app_url=payload.app_url,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get("/api/projects/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Project:
    """Get a single project by ID if user has organization access."""
    return verify_project_access(project_id, current_user, db)


@router.put("/api/projects/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str,
    payload: ProjectUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Project:
    """Update a project (name, description, app_url) if user has organization access."""
    project = verify_project_access(project_id, current_user, db)

    if payload.name is not None:
        project.name = payload.name
    if payload.description is not None:
        project.description = payload.description
    if payload.app_url is not None:
        project.app_url = payload.app_url

    db.commit()
    db.refresh(project)
    return project


@router.delete("/api/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """
    Safely delete an empty project if user has owner or admin role in its organization.
    Deletion is blocked with 409 Conflict if historical test runs or test cases exist.
    """
    project = verify_project_access(project_id, current_user, db)
    verify_org_admin_access(project.org_id, current_user, db)

    # Check for historical test runs (retention requirement)
    has_runs = db.query(TestRun.id).filter(TestRun.project_id == project_id).first()
    if has_runs:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete project: Project has historical test runs and results. Retention policy requires historical test evidence to be preserved.",
        )

    # Check for existing test cases
    has_test_cases = db.query(TestCase.id).filter(TestCase.project_id == project_id).first()
    if has_test_cases:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete project: Project contains test cases. Remove or migrate test cases before deleting the project.",
        )

    db.delete(project)
    db.commit()

