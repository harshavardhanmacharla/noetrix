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


class ParseInstructionsRequest(BaseModel):
    """Request to parse one or more natural-language test instructions."""
    project_id: str
    instructions: Optional[List[str]] = None
    raw_text: Optional[str] = None


class ParsedStepItem(BaseModel):
    """Structured representation of a parsed natural-language step."""
    line_number: int
    raw_instruction: str
    is_valid: bool
    action: Optional[str] = None
    target: Optional[str] = None
    value: Optional[str] = None
    expected_result: Optional[str] = None
    confidence: float = 1.0
    error: Optional[str] = None


class ParseInstructionsResponse(BaseModel):
    """Response containing parsed step details and validation diagnostics."""
    is_valid: bool
    total_lines: int
    valid_steps_count: int
    steps: List[ParsedStepItem] = []
    errors: List[dict] = []


class CreateTestCaseFromInstructionsRequest(BaseModel):
    """Request to persist a new test case parsed from natural-language instructions."""
    project_id: str
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    instructions: Optional[List[str]] = None
    raw_text: Optional[str] = None
