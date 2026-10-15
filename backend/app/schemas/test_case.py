"""
Pydantic schemas for TestCase and TestStep.
"""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class TestStepResponse(BaseModel):
    id: str
    test_case_id: str
    step_number: int
    action: str
    target: Optional[str] = None
    value: Optional[str] = None
    expected_result: Optional[str] = None

    model_config = {"from_attributes": True}


class TestCaseBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    csv_filename: Optional[str] = None
    is_active: bool = True


class TestCaseCreate(TestCaseBase):
    created_by: Optional[str] = None


class TestCaseResponse(TestCaseBase):
    id: str
    project_id: str
    created_by: Optional[str] = None
    steps: List[TestStepResponse] = []
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CSVTemplateInfo(BaseModel):
    """Information about the CSV template format."""
    columns: List[str]
    supported_actions: List[str]
    example_rows: List[dict]
