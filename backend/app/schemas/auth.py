"""
Pydantic schemas for authentication and authorization.
"""
import re
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class UserRegisterRequest(BaseModel):
    """Payload for user registration."""

    email: str = Field(..., description="User email address")
    password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Password (minimum 8 characters)",
    )
    full_name: Optional[str] = Field(None, max_length=255)
    organization_name: Optional[str] = Field(None, max_length=255)

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        clean = v.strip().lower()
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", clean):
            raise ValueError("Invalid email address format.")
        return clean


class UserLoginRequest(BaseModel):
    """Payload for user login."""

    email: str = Field(..., description="User email address")
    password: str = Field(..., description="User password")

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        clean = v.strip().lower()
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", clean):
            raise ValueError("Invalid email address format.")
        return clean


class ForgotPasswordRequest(BaseModel):
    """Payload to request password reset."""

    email: str = Field(..., description="User email address")

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        clean = v.strip().lower()
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", clean):
            raise ValueError("Invalid email address format.")
        return clean


class ResetPasswordRequest(BaseModel):
    """Payload to reset password using token."""

    token: str = Field(..., min_length=16, description="Password reset token")
    new_password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="New password (minimum 8 characters)",
    )


class TokenVerificationResponse(BaseModel):
    """Response when verifying a password reset token."""

    valid: bool
    message: Optional[str] = None


class GenericMessageResponse(BaseModel):
    """Generic status message response."""

    message: str


class UserResponse(BaseModel):
    """Public user profile information."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    full_name: Optional[str] = None
    is_active: bool
    is_superuser: bool
    created_at: datetime


class TokenResponse(BaseModel):
    """Authentication token response."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse


class MembershipResponse(BaseModel):
    """Organization membership summary."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    org_id: str
    org_name: str
    org_slug: str
    role: str


class UserProfileResponse(BaseModel):
    """Complete profile of current authenticated user including accessible organizations."""

    user: UserResponse
    memberships: List[MembershipResponse]
