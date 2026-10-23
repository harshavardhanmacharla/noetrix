import re
from typing import Optional, Set
from urllib.parse import urlparse

from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models.organization import Organization, OrganizationMembership
from app.models.project import Project
from app.models.test_case import TestCase
from app.models.test_run import Artifact, TestRun
from app.models.user import User
from app.services.security import decode_access_token

settings = get_settings()


async def get_current_user(
    request: Request,
    authorization: Optional[str] = Header(None),
    access_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_db),
) -> User:
    """
    Extract and validate JWT from Authorization: Bearer <token> header or HttpOnly cookie.
    Enforces CSRF protection (Origin/Referer validation) for cookie-authenticated state-changing requests.
    Retrieves and validates the active User record from database.
    """
    token: Optional[str] = None
    is_cookie_auth = False

    if authorization and authorization.startswith("Bearer "):
        token = authorization.split("Bearer ", 1)[1].strip()
    elif access_token:
        token = access_token.strip()
        is_cookie_auth = True

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials were not provided.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # CSRF defense: When authenticated via cookie on state-changing methods, require trusted Origin/Referer
    if is_cookie_auth and request.method in ("POST", "PUT", "PATCH", "DELETE"):
        origin = request.headers.get("origin")
        referer = request.headers.get("referer")
        source = origin
        if not source and referer:
            parsed = urlparse(referer)
            source = f"{parsed.scheme}://{parsed.netloc}"

        trusted = False
        if source:
            allowed_origins = set(settings.cors_origins_list)
            if source in allowed_origins or re.match(r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$", source):
                trusted = True

        if not trusted:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="CSRF protection: State-changing request with cookie authentication requires a trusted Origin or Referer header.",
            )

    payload = decode_access_token(token)
    user_id = payload.get("sub")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or credentials revoked.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user account.",
        )

    return user


def get_user_org_ids(user: User, db: Session) -> Set[str]:
    """Return all organization IDs accessible by this user."""
    if user.is_superuser:
        return {org_id for (org_id,) in db.query(Organization.id).all()}
    memberships = (
        db.query(OrganizationMembership.org_id)
        .filter(OrganizationMembership.user_id == user.id)
        .all()
    )
    return {org_id for (org_id,) in memberships}


def verify_org_access(org_id: str, user: User, db: Session) -> Organization:
    """Verify that user belongs to the requested organization."""
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found.",
        )

    if not user.is_superuser:
        membership = (
            db.query(OrganizationMembership)
            .filter(
                OrganizationMembership.org_id == org_id,
                OrganizationMembership.user_id == user.id,
            )
            .first()
        )
        if not membership:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: You are not a member of this organization.",
            )

    return org


def verify_org_admin_access(org_id: str, user: User, db: Session) -> Organization:
    """Verify that user has owner or admin role in the organization, or is a superuser."""
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found.",
        )

    if not user.is_superuser:
        membership = (
            db.query(OrganizationMembership)
            .filter(
                OrganizationMembership.org_id == org_id,
                OrganizationMembership.user_id == user.id,
            )
            .first()
        )
        if not membership:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: You are not a member of this organization.",
            )
        if membership.role not in ("owner", "admin"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: Organization update requires owner or admin role.",
            )

    return org


def verify_project_access(project_id: str, user: User, db: Session) -> Project:
    """Verify that project exists and user has access to its parent organization."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found.",
        )

    verify_org_access(project.org_id, user, db)
    return project


def verify_project_admin_access(project_id: str, user: User, db: Session) -> Project:
    """Verify that project exists and user has owner or admin role in its parent organization."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found.",
        )

    verify_org_admin_access(project.org_id, user, db)
    return project


def verify_test_case_access(test_case_id: str, user: User, db: Session) -> TestCase:
    """Verify that test case exists and user has access to its parent project."""
    test_case = db.query(TestCase).filter(TestCase.id == test_case_id).first()
    if not test_case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Test case not found.",
        )

    verify_project_access(test_case.project_id, user, db)
    return test_case


def verify_test_run_access(run_id: str, user: User, db: Session) -> TestRun:
    """Verify that test run exists and user has access to its parent project."""
    run = db.query(TestRun).filter(TestRun.id == run_id).first()
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Test run not found.",
        )

    verify_project_access(run.project_id, user, db)
    return run


def verify_artifact_access(artifact_id: str, user: User, db: Session) -> Artifact:
    """Verify that artifact exists and user has access to its parent run."""
    artifact = db.query(Artifact).filter(Artifact.id == artifact_id).first()
    if not artifact:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Artifact not found.",
        )

    verify_test_run_access(artifact.run_id, user, db)
    return artifact
