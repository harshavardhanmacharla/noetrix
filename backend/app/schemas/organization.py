"""
Pydantic schemas for Organization and Membership.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class OrganizationBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")
    description: Optional[str] = None


class OrganizationCreate(OrganizationBase):
    pass


class OrganizationUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    slug: Optional[str] = Field(None, min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")
    description: Optional[str] = None


class OrganizationResponse(OrganizationBase):
    id: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MembershipResponse(BaseModel):
    id: str
    org_id: str
    user_id: str
    role: str

    model_config = {"from_attributes": True}


class OrganizationMemberResponse(BaseModel):
    id: str
    user_id: str
    email: str
    role: str
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class OrganizationMemberAdd(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    role: str = Field(..., pattern=r"^(owner|admin|member)$")


class OrganizationMemberRoleUpdate(BaseModel):
    role: str = Field(..., pattern=r"^(owner|admin|member)$")
