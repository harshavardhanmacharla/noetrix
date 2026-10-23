"""
Pydantic schemas for TestRun, TestResult, and Artifact.
"""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class RunStartRequest(BaseModel):
    """Request body to start a new test run for a specific project."""
    test_case_ids: List[str] = Field(..., min_length=1, description="List of TestCase IDs to run")
    triggered_by: Optional[str] = None


class RunCreateBody(BaseModel):
    """Request body to start a new test run with project_id in body."""
    project_id: str
    test_case_ids: Optional[List[str]] = None
    triggered_by: Optional[str] = None



class TestRunResponse(BaseModel):
    id: str
    project_id: str
    status: str
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    triggered_by: Optional[str] = None
    total_tests: int
    passed_tests: int
    failed_tests: int
    total_steps: Optional[int] = None
    passed_steps: Optional[int] = None
    failed_steps: Optional[int] = None
    skipped_steps: Optional[int] = None
    error_message: Optional[str] = None
    video_path: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ArtifactResponse(BaseModel):
    id: str
    run_id: str
    result_id: Optional[str] = None
    artifact_type: str
    file_path: str
    file_size: Optional[int] = None
    mime_type: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class StepDetailResponse(BaseModel):
    step_number: int
    action: str
    target: Optional[str] = None
    value: Optional[str] = None
    expected_result: Optional[str] = None
    original_instruction: Optional[str] = None
    status: str = "skipped"  # passed, failed, skipped, running
    duration_ms: Optional[float] = None
    category: Optional[str] = None
    failure_reason: Optional[str] = None
    verification_result: Optional[dict] = None

    model_config = {"from_attributes": True}


class StepSummaryResponse(BaseModel):
    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0

    model_config = {"from_attributes": True}


class TestResultResponse(BaseModel):
    id: str
    run_id: str
    test_case_id: Optional[str] = None
    status: str
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    screenshot_path: Optional[str] = None
    log_output: Optional[str] = None
    steps: List[StepDetailResponse] = []
    step_summary: Optional[StepSummaryResponse] = None
    artifacts: List[ArtifactResponse] = []

    model_config = {"from_attributes": True}


class RunReportResponse(BaseModel):
    """Full report for a test run including all results and artifacts."""
    run: TestRunResponse
    results: List[TestResultResponse] = []
    artifacts: List[ArtifactResponse] = []
    summary: dict = {}
