"""
Membership and RBAC safeguards service.

Provides reusable helpers for role validation, last-owner protection,
and tenant membership mutation rules.
"""
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.organization import OrganizationMembership
from app.models.user import User


def count_organization_owners(db: Session, org_id: str) -> int:
    """
    Count the number of active owners in the specified organization.
    """
    return (
        db.query(func.count(OrganizationMembership.id))
        .filter(
            OrganizationMembership.org_id == org_id,
            OrganizationMembership.role == "owner",
        )
        .scalar()
        or 0
    )


def ensure_not_last_owner(
    db: Session,
    org_id: str,
    target_user_id: str,
    action_desc: str = "demote or remove",
) -> None:
    """
    Guard against leaving an organization with zero owners.
    Raises HTTP 409 Conflict if target user is currently an owner and the sole owner.
    """
    target_membership = (
        db.query(OrganizationMembership)
        .filter(
            OrganizationMembership.org_id == org_id,
            OrganizationMembership.user_id == target_user_id,
        )
        .first()
    )
    if target_membership and target_membership.role == "owner":
        owner_count = count_organization_owners(db, org_id)
        if owner_count <= 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cannot {action_desc} the last remaining owner of an organization. Transfer ownership first.",
            )


def get_caller_role(db: Session, org_id: str, user: User) -> Optional[str]:
    """
    Determine the caller's role within the organization.
    Returns 'superuser' if user has platform superuser privileges,
    the membership role string if a membership exists, or None.
    """
    if user.is_superuser:
        return "superuser"
    membership = (
        db.query(OrganizationMembership)
        .filter(
            OrganizationMembership.org_id == org_id,
            OrganizationMembership.user_id == user.id,
        )
        .first()
    )
    return membership.role if membership else None


def validate_role_assignment(caller_role: Optional[str], target_role: str) -> None:
    """
    Validate whether caller has sufficient privilege to assign `target_role` to a new member.
    - Superusers and owners may assign any valid role ('owner', 'admin', 'member').
    - Admins may only assign 'member'.
    - Members and non-members cannot assign roles.
    """
    if caller_role in ("superuser", "owner"):
        return

    if caller_role == "admin":
        if target_role != "member":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: Organization admins may only assign the 'member' role. Granting 'admin' or 'owner' requires owner privileges.",
            )
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Access denied: Insufficient permissions to add organization members.",
    )


def validate_role_mutation(
    caller_role: Optional[str],
    target_current_role: str,
    new_role: str,
) -> None:
    """
    Validate whether caller has sufficient privilege to change a member's role from
    `target_current_role` to `new_role`.
    - Superusers and owners may perform any role modification.
    - Admins cannot modify an owner or another admin.
    - Admins cannot grant 'admin' or 'owner' privileges.
    - Members and non-members cannot modify roles.
    """
    if caller_role in ("superuser", "owner"):
        return

    if caller_role == "admin":
        if target_current_role == "owner":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: Organization admins cannot modify an owner's role.",
            )
        if target_current_role == "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: Organization admins cannot modify another admin's role.",
            )
        if new_role in ("owner", "admin"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: Organization admins cannot grant 'admin' or 'owner' privileges.",
            )
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Access denied: Insufficient permissions to modify organization roles.",
    )


def validate_member_removal(
    caller_role: Optional[str],
    target_current_role: str,
    is_self: bool = False,
) -> None:
    """
    Validate whether caller has sufficient privilege to remove target member.
    - Superusers and owners may remove any member.
    - Admins cannot remove owners or other admins.
    - Regular members cannot remove other members (must use self-departure).
    """
    if caller_role in ("superuser", "owner"):
        return

    if caller_role == "admin":
        if target_current_role == "owner":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: Organization admins cannot remove an owner.",
            )
        if target_current_role == "admin" and not is_self:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: Organization admins cannot remove another admin.",
            )
        return

    if not is_self:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Regular members cannot remove other members.",
        )
