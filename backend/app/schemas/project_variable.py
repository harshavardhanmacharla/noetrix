"""
Pydantic schemas for ProjectVariable.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class ProjectVariableBase(BaseModel):
    name: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Variable name (e.g. user_name, password, base_url)",
    )
    is_secret: bool = Field(
        False,
        description="Whether this variable stores an encrypted sensitive secret",
    )
    description: Optional[str] = Field(None, max_length=1000)

    @field_validator("name")
    @classmethod
    def validate_variable_name(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("Variable name cannot be empty.")
        if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", s):
            raise ValueError(
                "Variable name must start with a letter or underscore and contain only "
                "alphanumeric characters and underscores (e.g. user_name, password)."
            )
        return s


class ProjectVariableCreate(ProjectVariableBase):
    value: str = Field(
        ...,
        description="Plaintext value for the variable, or secret to encrypt at rest",
    )


class ProjectVariableUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=128)
    value: Optional[str] = Field(
        None,
        description="New value; for an existing secret, omit to keep current value unchanged",
    )
    is_secret: Optional[bool] = None
    description: Optional[str] = Field(None, max_length=1000)

    @field_validator("name")
    @classmethod
    def validate_variable_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        s = v.strip()
        if not s:
            raise ValueError("Variable name cannot be empty.")
        if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", s):
            raise ValueError(
                "Variable name must start with a letter or underscore and contain only "
                "alphanumeric characters and underscores."
            )
        return s


class ProjectVariableResponse(BaseModel):
    id: str
    project_id: str
    name: str
    value: Optional[str] = None
    is_secret: bool
    description: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @model_validator(mode="after")
    def mask_secret_value(self) -> "ProjectVariableResponse":
        if self.is_secret:
            self.value = None
        return self

    @classmethod
    def from_orm_model(cls, model: Any) -> "ProjectVariableResponse":
        return cls(
            id=model.id,
            project_id=model.project_id,
            name=model.name,
            # CRITICAL SECURITY RULE: Secret values are NEVER returned in API responses
            value=None if model.is_secret else model.value,
            is_secret=model.is_secret,
            description=model.description,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
