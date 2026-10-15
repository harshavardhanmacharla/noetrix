"""
Pydantic schemas for Project.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, HttpUrl


class ProjectBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")
    description: Optional[str] = None
    app_url: Optional[str] = Field(None, description="Target web application URL for testing")


class ProjectCreate(ProjectBase):
    org_id: Optional[str] = None



class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    app_url: Optional[str] = None


class ProjectResponse(ProjectBase):
    id: str
    org_id: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
