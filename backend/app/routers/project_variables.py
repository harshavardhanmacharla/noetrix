"""
Project-scoped test variables router with tenant authorization and AES-256-GCM encryption.
"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import (
    get_current_user,
    verify_project_access,
    verify_project_admin_access,
)
from app.models.project_variable import ProjectVariable
from app.models.user import User
from app.schemas.project_variable import (
    ProjectVariableCreate,
    ProjectVariableResponse,
    ProjectVariableUpdate,
)
from app.services.encryption import encrypt_secret, decrypt_secret

router = APIRouter(tags=["Project Variables"])


@router.get(
    "/api/projects/{project_id}/variables",
    response_model=List[ProjectVariableResponse],
)
async def list_project_variables(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[ProjectVariableResponse]:
    """
    List all test variables configured for a project.
    Accessible to all users authorized on the project's organization.
    CRITICAL: Secret values are NEVER returned in the API response.
    """
    verify_project_access(project_id, current_user, db)

    variables = (
        db.query(ProjectVariable)
        .filter(ProjectVariable.project_id == project_id)
        .order_by(ProjectVariable.name.asc())
        .all()
    )

    return [ProjectVariableResponse.from_orm_model(v) for v in variables]


@router.post(
    "/api/projects/{project_id}/variables",
    response_model=ProjectVariableResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_project_variable(
    project_id: str,
    payload: ProjectVariableCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProjectVariableResponse:
    """
    Create a project-scoped test variable.
    Restricted to organization owners, admins, or superusers.
    If is_secret is True, the value is encrypted using AES-256-GCM before database insertion.
    """
    verify_project_admin_access(project_id, current_user, db)

    # Enforce uniqueness within project
    existing = (
        db.query(ProjectVariable)
        .filter(
            ProjectVariable.project_id == project_id,
            ProjectVariable.name == payload.name,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Variable '{payload.name}' already exists in this project.",
        )

    stored_value: str
    if payload.is_secret:
        stored_value = encrypt_secret(payload.value)
    else:
        stored_value = payload.value

    variable = ProjectVariable(
        project_id=project_id,
        name=payload.name,
        value=stored_value,
        is_secret=payload.is_secret,
        description=payload.description,
    )

    db.add(variable)
    db.commit()
    db.refresh(variable)

    return ProjectVariableResponse.from_orm_model(variable)


@router.put(
    "/api/projects/{project_id}/variables/{variable_id}",
    response_model=ProjectVariableResponse,
)
async def update_project_variable(
    project_id: str,
    variable_id: str,
    payload: ProjectVariableUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProjectVariableResponse:
    """
    Update a project variable. Restricted to organization owners, admins, or superusers.
    For an existing secret, value may be omitted to preserve the current encrypted secret.
    """
    verify_project_admin_access(project_id, current_user, db)

    variable = (
        db.query(ProjectVariable)
        .filter(
            ProjectVariable.id == variable_id,
            ProjectVariable.project_id == project_id,
        )
        .first()
    )
    if not variable:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Variable not found in this project.",
        )

    # If renaming, verify new name is unique within this project
    if payload.name and payload.name != variable.name:
        conflict = (
            db.query(ProjectVariable)
            .filter(
                ProjectVariable.project_id == project_id,
                ProjectVariable.name == payload.name,
                ProjectVariable.id != variable_id,
            )
            .first()
        )
        if conflict:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Variable '{payload.name}' already exists in this project.",
            )
        variable.name = payload.name

    if payload.description is not None:
        variable.description = payload.description

    # Handle secret toggle and value update
    new_is_secret = payload.is_secret if payload.is_secret is not None else variable.is_secret

    if payload.value is not None:
        if new_is_secret:
            variable.value = encrypt_secret(payload.value)
        else:
            variable.value = payload.value
    elif payload.is_secret is not None and payload.is_secret != variable.is_secret:
        # Secret status toggled without supplying a new value
        if new_is_secret:
            # Plaintext to encrypted
            if variable.value:
                variable.value = encrypt_secret(variable.value)
        else:
            # Encrypted to plaintext
            if variable.value:
                variable.value = decrypt_secret(variable.value)

    variable.is_secret = new_is_secret

    db.commit()
    db.refresh(variable)

    return ProjectVariableResponse.from_orm_model(variable)


@router.delete(
    "/api/projects/{project_id}/variables/{variable_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_project_variable(
    project_id: str,
    variable_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """
    Delete a project-scoped variable.
    Restricted to organization owners, admins, or superusers.
    """
    verify_project_admin_access(project_id, current_user, db)

    variable = (
        db.query(ProjectVariable)
        .filter(
            ProjectVariable.id == variable_id,
            ProjectVariable.project_id == project_id,
        )
        .first()
    )
    if not variable:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Variable not found in this project.",
        )

    db.delete(variable)
    db.commit()

