"""
Pydantic schemas for data-driven testing.
"""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class TestCasePlaceholdersResponse(BaseModel):
    """Placeholder metadata extracted from a saved TestCase with project variable exclusion."""
    test_case_id: str
    test_case_name: str
    placeholders: List[str] = Field(
        default_factory=list,
        description="Data entry placeholder columns (excluding project test variables)",
    )
    all_placeholders: List[str] = Field(
        default_factory=list,
        description="All placeholders detected across test case steps",
    )
    project_variables: List[str] = Field(
        default_factory=list,
        description="Names of configured Project Test Variables for this project",
    )
    step_count: int = 0
    has_placeholders: bool = False


class DataDrivenValidationRequest(BaseModel):
    """Request to validate candidate test data records before execution."""
    test_case_id: str
    records: List[Dict[str, Any]] = Field(..., min_length=1)


class DataDrivenValidationResponse(BaseModel):
    """Validation outcome for candidate test data records."""
    is_valid: bool
    errors: List[str] = Field(default_factory=list)
    record_count: int = 0
    placeholders: List[str] = Field(
        default_factory=list,
        description="Required data entry columns after project variable exclusion",
    )
    all_placeholders: List[str] = Field(
        default_factory=list,
        description="All placeholders detected in test case steps",
    )
    project_variables: List[str] = Field(
        default_factory=list,
        description="Names of configured Project Test Variables for this project",
    )


class DataDrivenRunRequest(BaseModel):
    """Request body to launch a data-driven test run across multiple records."""
    test_case_id: str = Field(..., description="Target TestCase ID with placeholders")
    records: List[Dict[str, Any]] = Field(..., min_length=1, description="List of test data records")
    triggered_by: Optional[str] = None
    stop_on_failure: bool = Field(
        default=True,
        description="Halt subsequent records if an execution or submission fails to prevent duplicate records",
    )


class DataDrivenPreviewRequest(BaseModel):
    """Request to preview substituted steps for a specific record without executing."""
    test_case_id: str
    record: Dict[str, Any]


class DataDrivenPreviewResponse(BaseModel):
    """Substituted test steps for a single record."""
    test_case_id: str
    record: Dict[str, Any]
    steps: List[Dict[str, Any]] = Field(default_factory=list)
