"""
Authentication router: user registration, login, logout, profile retrieval, and password reset.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import secrets
from typing import List, Optional
import uuid

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models.organization import Organization, OrganizationMembership
from app.models.user import PasswordResetToken, User
from app.schemas.auth import (
    ForgotPasswordRequest,
    GenericMessageResponse,
    MembershipResponse,
    ResetPasswordRequest,
    TokenResponse,
    TokenVerificationResponse,
    UserLoginRequest,
    UserProfileResponse,
    UserRegisterRequest,
    UserResponse,
)
from app.services.email import get_latest_dev_reset_url, send_password_reset_email
from app.services.rate_limiter import (
    login_rate_limiter,
    password_reset_confirm_rate_limiter,
    password_reset_request_rate_limiter,
    register_rate_limiter,
)
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
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> TokenResponse:
    """Register a new platform user when public registration is explicitly enabled."""
    client_ip = request.client.host if request.client else "unknown"
    rate_key = f"{client_ip}:{payload.email.lower()}"

    if register_rate_limiter.is_rate_limited(client_ip) or register_rate_limiter.is_rate_limited(rate_key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many registration attempts. Please wait before trying again.",
        )

    register_rate_limiter.record_attempt(client_ip)
    register_rate_limiter.record_attempt(rate_key)

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
    custom_org = payload.organization_name.strip() if payload.organization_name else None
    if custom_org:
        org_name = custom_org
        base_slug = "".join(c if c.isalnum() or c in ("-", "_") else "-" for c in custom_org.lower()).strip("-")
        if not base_slug:
            base_slug = payload.email.split("@")[0].lower()
    else:
        email_base = payload.email.split("@")[0].lower()
        clean_slug = "".join(c if c.isalnum() or c in ("-", "_") else "-" for c in email_base).strip("-")
        base_slug = clean_slug or "workspace"
        org_name = (payload.full_name or email_base.capitalize()) + "'s Workspace"

    slug = base_slug
    counter = 1
    while db.query(Organization).filter(Organization.slug == slug).first():
        slug = f"{base_slug}-{counter}"
        counter += 1

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


@router.post(
    "/forgot-password",
    response_model=GenericMessageResponse,
    summary="Request a password reset link",
)
async def forgot_password(
    payload: ForgotPasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> GenericMessageResponse:
    """
    Initiate a password reset flow. Generates a secure, single-use, time-limited token.
    Always returns a generic success message to prevent account enumeration.
    """
    client_ip = request.client.host if request.client else "unknown"
    email_key = payload.email.lower()
    rate_key = f"{client_ip}:{email_key}"

    if (
        password_reset_request_rate_limiter.is_rate_limited(client_ip)
        or password_reset_request_rate_limiter.is_rate_limited(rate_key)
    ):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many password reset requests. Please wait before trying again.",
        )

    # Record attempt for rate limiting
    password_reset_request_rate_limiter.record_attempt(client_ip)
    password_reset_request_rate_limiter.record_attempt(rate_key)

    is_prod = settings.ENVIRONMENT.lower() == "production"
    if is_prod and not settings.SMTP_HOST:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Password reset service is temporarily unavailable. Please contact support.",
        )

    user = db.query(User).filter(User.email == email_key).first()
    if user and user.is_active:
        # Invalidate any existing unused reset tokens for this user
        db.query(PasswordResetToken).filter(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.used == False,  # noqa: E712
        ).update({"used": True})

        # Generate high-entropy single-use token (256 bits)
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        expires_at = datetime.now(timezone.utc) + timedelta(
            minutes=settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES
        )

        token_record = PasswordResetToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=expires_at,
            used=False,
        )
        db.add(token_record)
        db.commit()

        sent = send_password_reset_email(user.email, raw_token)
        if not sent and is_prod:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to send password reset email. Please try again later.",
            )

    return GenericMessageResponse(
        message="If that email address is associated with an account, password reset instructions have been sent."
    )


@router.get(
    "/verify-reset-token",
    response_model=TokenVerificationResponse,
    summary="Check whether a password reset token is valid and unexpired",
)
async def verify_reset_token(
    token: str,
    db: Session = Depends(get_db),
) -> TokenVerificationResponse:
    """Validate token state prior to displaying reset password form."""
    if not token or len(token) < 16:
        return TokenVerificationResponse(
            valid=False, message="Invalid password reset token."
        )

    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    reset_record = (
        db.query(PasswordResetToken)
        .filter(PasswordResetToken.token_hash == token_hash)
        .first()
    )

    if not reset_record:
        return TokenVerificationResponse(
            valid=False, message="Invalid password reset token."
        )

    if reset_record.used:
        return TokenVerificationResponse(
            valid=False,
            message="This password reset token has already been used.",
        )

    now = datetime.now(timezone.utc)
    exp = reset_record.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)

    if exp < now:
        return TokenVerificationResponse(
            valid=False, message="This password reset token has expired."
        )

    user = db.query(User).filter(User.id == reset_record.user_id).first()
    if not user or not user.is_active:
        return TokenVerificationResponse(
            valid=False, message="Account is inactive or not found."
        )

    return TokenVerificationResponse(valid=True, message=None)


@router.post(
    "/reset-password",
    response_model=GenericMessageResponse,
    summary="Reset password using a valid reset token",
)
async def reset_password(
    payload: ResetPasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> GenericMessageResponse:
    """
    Verify single-use token, update user password, and invalidate the token.
    """
    client_ip = request.client.host if request.client else "unknown"

    if password_reset_confirm_rate_limiter.is_rate_limited(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many password reset attempts. Please wait before trying again.",
        )

    token_hash = hashlib.sha256(payload.token.encode("utf-8")).hexdigest()
    reset_record = (
        db.query(PasswordResetToken)
        .filter(PasswordResetToken.token_hash == token_hash)
        .first()
    )

    if not reset_record:
        password_reset_confirm_rate_limiter.record_failure(client_ip)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired password reset token.",
        )

    if reset_record.used:
        password_reset_confirm_rate_limiter.record_failure(client_ip)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This password reset token has already been used.",
        )

    now = datetime.now(timezone.utc)
    exp = reset_record.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)

    if exp < now:
        password_reset_confirm_rate_limiter.record_failure(client_ip)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password reset token has expired.",
        )

    user = db.query(User).filter(User.id == reset_record.user_id).first()
    if not user or not user.is_active:
        password_reset_confirm_rate_limiter.record_failure(client_ip)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired password reset token.",
        )

    # Update user password using project's bcrypt hashing
    user.hashed_password = hash_password(payload.new_password)

    # Consume this token and invalidate all other reset tokens for this user
    reset_record.used = True
    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.used == False,  # noqa: E712
    ).update({"used": True})

    db.commit()

    # Reset rate limiter upon successful reset
    password_reset_confirm_rate_limiter.reset(client_ip)

    return GenericMessageResponse(
        message="Your password has been successfully reset. You can now log in with your new password."
    )


@router.get(
    "/dev/latest-reset-link",
    summary="[DEV ONLY] Retrieve latest password reset link for local testing",
)
async def get_dev_latest_reset_link(
    email: str,
    db: Session = Depends(get_db),
):
    """
    Development-only helper endpoint to retrieve the active reset link for a test user.
    Strictly disabled in production (returns 404 Not Found).
    """
    if settings.ENVIRONMENT.lower() == "production":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Endpoint not found",
        )

    clean_email = email.strip().lower()
    dev_url = get_latest_dev_reset_url(clean_email)

    user = db.query(User).filter(User.email == clean_email).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User '{clean_email}' does not exist in local database. Please create this user first (e.g. via python -m scripts.create_admin).",
        )

    if not dev_url:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No pending reset link found for '{clean_email}'. Submit the forgot-password form first.",
        )

    return {
        "email": clean_email,
        "reset_url": dev_url,
    }

