"""
Authentication router: user registration, login, logout, and profile retrieval.
"""
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models.organization import Organization, OrganizationMembership
from app.models.user import User
from app.schemas.auth import (
    MembershipResponse,
    TokenResponse,
    UserLoginRequest,
    UserProfileResponse,
    UserRegisterRequest,
    UserResponse,
)
from app.services.rate_limiter import login_rate_limiter
from app.services.security import create_access_token, hash_password, revoke_token, verify_password

router = APIRouter(prefix="/api/auth", tags=["Authentication"])
settings = get_settings()


def _set_auth_cookie(response: Response, token: str) -> None:
    """Set secure HttpOnly authentication cookie."""
    is_prod = settings.ENVIRONMENT.lower() == "production"
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        samesite="lax",
        secure=is_prod,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
)
async def register(
    payload: UserRegisterRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> TokenResponse:
    """Register a new platform user when public registration is explicitly enabled."""
    if not settings.ALLOW_PUBLIC_REGISTRATION:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Public registration is disabled. Please contact your system administrator.",
        )

    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email address already exists.",
        )

    # Public self-registration NEVER grants superuser privileges
    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        is_active=True,
        is_superuser=False,
    )
    db.add(user)
    db.flush()

    # Create an initial organization workspace for the user
    base_slug = payload.email.split("@")[0].lower()
    clean_slug = "".join(c if c.isalnum() or c in ("-", "_") else "-" for c in base_slug)
    slug = clean_slug
    counter = 1
    while db.query(Organization).filter(Organization.slug == slug).first():
        slug = f"{clean_slug}-{counter}"
        counter += 1

    org_name = (payload.full_name or base_slug.capitalize()) + "'s Workspace"
    org = Organization(
        name=org_name,
        slug=slug,
        description="Default organization workspace",
    )
    db.add(org)
    db.flush()

    membership = OrganizationMembership(
        org_id=org.id,
        user_id=user.id,
        role="owner",
        created_at=datetime.now(timezone.utc),
    )
    db.add(membership)
    db.commit()
    db.refresh(user)

    token = create_access_token(
        data={"sub": user.id, "email": user.email, "is_superuser": user.is_superuser}
    )
    _set_auth_cookie(response, token)

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=UserResponse.model_validate(user),
    )


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Log in with email and password",
)
async def login(
    payload: UserLoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> TokenResponse:
    """Authenticate with email and password, returning a JWT token and HttpOnly session cookie."""
    client_ip = request.client.host if request.client else "unknown"
    rate_key = f"{client_ip}:{payload.email.lower()}"

    if login_rate_limiter.is_rate_limited(client_ip) or login_rate_limiter.is_rate_limited(rate_key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Please wait before trying again.",
        )

    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        login_rate_limiter.record_failure(client_ip)
        login_rate_limiter.record_failure(rate_key)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive. Please contact your administrator.",
        )

    # Reset rate limiting counters on successful authentication
    login_rate_limiter.reset(client_ip)
    login_rate_limiter.reset(rate_key)

    token = create_access_token(
        data={"sub": user.id, "email": user.email, "is_superuser": user.is_superuser}
    )
    _set_auth_cookie(response, token)

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=UserResponse.model_validate(user),
    )


@router.post(
    "/logout",
    summary="Log out, invalidate active token, and clear session cookie",
)
async def logout(
    response: Response,
    authorization: Optional[str] = Header(None),
    access_token: Optional[str] = Cookie(None),
) -> dict:
    """Clear session authentication cookie and invalidate the active JWT token."""
    token: Optional[str] = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split("Bearer ", 1)[1].strip()
    elif access_token:
        token = access_token.strip()

    if token:
        revoke_token(token)

    response.delete_cookie(key="access_token")
    return {"status": "ok", "message": "Logged out successfully."}


@router.get(
    "/me",
    response_model=UserProfileResponse,
    summary="Get current user profile and memberships",
)
async def get_me(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserProfileResponse:
    """Return the profile and organization memberships of the authenticated user."""
    memberships = (
        db.query(OrganizationMembership)
        .filter(OrganizationMembership.user_id == current_user.id)
        .all()
    )

    membership_summaries = []
    for m in memberships:
        org = db.query(Organization).filter(Organization.id == m.org_id).first()
        if org:
            membership_summaries.append(
                MembershipResponse(
                    id=m.id,
                    org_id=org.id,
                    org_name=org.name,
                    org_slug=org.slug,
                    role=m.role,
                )
            )

    return UserProfileResponse(
        user=UserResponse.model_validate(current_user),
        memberships=membership_summaries,
    )
