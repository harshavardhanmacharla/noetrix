"""
Organizations router with tenant isolation.
"""
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, verify_org_access, verify_org_admin_access
from app.models.organization import Organization, OrganizationMembership
from app.models.project import Project
from app.models.user import User
from app.schemas.organization import (
    OrganizationCreate,
    OrganizationMemberAdd,
    OrganizationMemberResponse,
    OrganizationMemberRoleUpdate,
    OrganizationResponse,
    OrganizationUpdate,
)
from app.services.membership_service import (
    ensure_not_last_owner,
    get_caller_role,
    validate_member_removal,
    validate_role_assignment,
    validate_role_mutation,
)

router = APIRouter(prefix="/api/organizations", tags=["Organizations"])


@router.get("", response_model=List[OrganizationResponse])
async def list_organizations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[Organization]:
    """List organizations accessible by the authenticated user."""
    if current_user.is_superuser:
        return db.query(Organization).order_by(Organization.created_at.desc()).all()

    return (
        db.query(Organization)
        .join(OrganizationMembership, OrganizationMembership.org_id == Organization.id)
        .filter(OrganizationMembership.user_id == current_user.id)
        .order_by(Organization.created_at.desc())
        .all()
    )


@router.post("", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED)
async def create_organization(
    payload: OrganizationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Organization:
    """Create a new organization and assign owner membership to current user."""
    existing = db.query(Organization).filter(Organization.slug == payload.slug).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Organization with slug '{payload.slug}' already exists.",
        )

    org = Organization(
        name=payload.name,
        slug=payload.slug,
        description=payload.description,
    )
    db.add(org)
    db.flush()

    membership = OrganizationMembership(
        org_id=org.id,
        user_id=current_user.id,
        role="owner",
        created_at=datetime.now(timezone.utc),
    )
    db.add(membership)
    db.commit()
    db.refresh(org)
    return org


@router.get("/{org_id}", response_model=OrganizationResponse)
async def get_organization(
    org_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Organization:
    """Get a single organization by ID if user has membership."""
    return verify_org_access(org_id, current_user, db)
 
 
@router.put("/{org_id}", response_model=OrganizationResponse)
async def update_organization(
    org_id: str,
    payload: OrganizationUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Organization:
    """Update organization details (name, slug, description) if user has owner or admin role."""
    org = verify_org_admin_access(org_id, current_user, db)

    if payload.slug is not None and payload.slug != org.slug:
        existing = (
            db.query(Organization)
            .filter(Organization.slug == payload.slug, Organization.id != org_id)
            .first()
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Organization with slug '{payload.slug}' already exists.",
            )
        org.slug = payload.slug

    if payload.name is not None:
        org.name = payload.name
    if payload.description is not None:
        org.description = payload.description

    db.commit()
    db.refresh(org)
    return org


@router.delete("/{org_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_organization(
    org_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """
    Safely delete an organization if user is owner and organization has no child projects or additional members.
    Deletion of the last remaining platform organization is blocked.
    """
    org = verify_org_admin_access(org_id, current_user, db)

    if not current_user.is_superuser:
        membership = (
            db.query(OrganizationMembership)
            .filter(
                OrganizationMembership.org_id == org_id,
                OrganizationMembership.user_id == current_user.id,
            )
            .first()
        )
        if not membership or membership.role != "owner":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: Organization deletion requires owner role.",
            )

    # Protect last remaining organization
    total_orgs = db.query(func.count(Organization.id)).scalar() or 0
    if total_orgs <= 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete organization: Cannot delete the last remaining organization in the platform.",
        )

    # Dependency check: check for any projects in the organization
    has_projects = db.query(Project.id).filter(Project.org_id == org_id).first()
    if has_projects:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete organization: Organization contains projects. Remove all projects before deleting the organization.",
        )

    # Dependency check: check for additional members
    other_members = (
        db.query(OrganizationMembership.id)
        .filter(
            OrganizationMembership.org_id == org_id,
            OrganizationMembership.user_id != current_user.id,
        )
        .first()
    )
    if other_members:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete organization: Organization has active members. Remove all members before deleting the organization.",
        )

    db.delete(org)
    db.commit()


@router.get("/{org_id}/members", response_model=List[OrganizationMemberResponse])
async def list_organization_members(
    org_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[OrganizationMemberResponse]:
    """
    List all members belonging to the specified organization.
    Requires authentication and membership in the organization (or superuser).
    """
    verify_org_access(org_id, current_user, db)

    memberships = (
        db.query(OrganizationMembership)
        .join(User, OrganizationMembership.user_id == User.id)
        .filter(OrganizationMembership.org_id == org_id)
        .all()
    )

    return [
        OrganizationMemberResponse(
            id=m.id,
            user_id=m.user_id,
            email=m.user.email if m.user else "",
            role=m.role,
            created_at=m.created_at,
        )
        for m in memberships
    ]


@router.post(
    "/{org_id}/members",
    response_model=OrganizationMemberResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_organization_member(
    org_id: str,
    payload: OrganizationMemberAdd,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OrganizationMemberResponse:
    """
    Add an existing registered user to the organization by email.
    Requires owner or admin authorization (admins may only assign 'member' role).
    """
    verify_org_admin_access(org_id, current_user, db)

    caller_role = get_caller_role(db, org_id, current_user)
    validate_role_assignment(caller_role, payload.role)

    target_user = db.query(User).filter(User.email == payload.email).first()
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with email '{payload.email}' not found. Users must register before being added to an organization.",
        )

    # Check for existing membership (application-level duplicate guard)
    existing = (
        db.query(OrganizationMembership)
        .filter(
            OrganizationMembership.org_id == org_id,
            OrganizationMembership.user_id == target_user.id,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"User '{payload.email}' is already a member of this organization with role '{existing.role}'.",
        )

    now = datetime.now(timezone.utc)
    membership = OrganizationMembership(
        org_id=org_id,
        user_id=target_user.id,
        role=payload.role,
        created_at=now,
    )
    db.add(membership)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"User '{payload.email}' is already a member of this organization.",
        )

    db.refresh(membership)
    return OrganizationMemberResponse(
        id=membership.id,
        user_id=membership.user_id,
        email=target_user.email,
        role=membership.role,
        created_at=membership.created_at or now,
    )


@router.patch(
    "/{org_id}/members/{user_id}",
    response_model=OrganizationMemberResponse,
)
async def update_member_role(
    org_id: str,
    user_id: str,
    payload: OrganizationMemberRoleUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OrganizationMemberResponse:
    """
    Change an organization member's role.
    Requires owner or admin authorization, subject to role hierarchy and last-owner protection.
    """
    verify_org_admin_access(org_id, current_user, db)

    target_membership = (
        db.query(OrganizationMembership)
        .filter(
            OrganizationMembership.org_id == org_id,
            OrganizationMembership.user_id == user_id,
        )
        .first()
    )
    if not target_membership:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Member not found in this organization.",
        )

    caller_role = get_caller_role(db, org_id, current_user)
    validate_role_mutation(caller_role, target_membership.role, payload.role)

    # Last-owner safeguard: if demoting an owner, verify there is at least one other owner
    if target_membership.role == "owner" and payload.role != "owner":
        ensure_not_last_owner(db, org_id, user_id, action_desc="demote")

    target_membership.role = payload.role
    db.commit()
    db.refresh(target_membership)

    return OrganizationMemberResponse(
        id=target_membership.id,
        user_id=target_membership.user_id,
        email=target_membership.user.email if target_membership.user else "",
        role=target_membership.role,
        created_at=target_membership.created_at,
    )


@router.delete(
    "/{org_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_organization_member(
    org_id: str,
    user_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """
    Remove a member from the organization.
    Requires owner or admin authorization, subject to role hierarchy and last-owner protection.
    """
    verify_org_admin_access(org_id, current_user, db)

    target_membership = (
        db.query(OrganizationMembership)
        .filter(
            OrganizationMembership.org_id == org_id,
            OrganizationMembership.user_id == user_id,
        )
        .first()
    )
    if not target_membership:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Member not found in this organization.",
        )

    caller_role = get_caller_role(db, org_id, current_user)
    validate_member_removal(
        caller_role,
        target_membership.role,
        is_self=(user_id == current_user.id),
    )

    # Last-owner safeguard: cannot remove the final owner
    if target_membership.role == "owner":
        ensure_not_last_owner(db, org_id, user_id, action_desc="remove")

    db.delete(target_membership)
    db.commit()


@router.post(
    "/{org_id}/leave",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def leave_organization(
    org_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """
    Voluntarily leave the organization.
    Removes caller's membership, preventing the sole owner from leaving until ownership is transferred.
    """
    verify_org_access(org_id, current_user, db)

    caller_membership = (
        db.query(OrganizationMembership)
        .filter(
            OrganizationMembership.org_id == org_id,
            OrganizationMembership.user_id == current_user.id,
        )
        .first()
    )
    if not caller_membership:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not a member of this organization.",
        )

    # Last-owner safeguard: sole owner cannot leave without transferring ownership
    if caller_membership.role == "owner":
        ensure_not_last_owner(db, org_id, current_user.id, action_desc="leave as")

    db.delete(caller_membership)
    db.commit()



