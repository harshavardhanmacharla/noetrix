"""
Pydantic schemas for Live Browser Discovery.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class StartDiscoveryRequest(BaseModel):
    project_id: str = Field(..., description="Project ID to associate this discovery session with")
    url: str = Field(..., description="Target web application URL to open")
    headless: Optional[bool] = Field(
        default=None,
        description="Whether to run in headless mode. Defaults to False for desktop interaction.",
    )


class NavigateDiscoveryRequest(BaseModel):
    url: str = Field(..., description="Target URL to navigate to within active session")


class ValidateTargetRequest(BaseModel):
    target: str = Field(..., description="Target selector or natural-language intent phrase to test")
    action: str = Field(default="click", description="Action to test ('click', 'fill', 'select_option', etc.)")


class CapturedElement(BaseModel):
    id: str = Field(..., description="Stable element identifier within snapshot")
    tag: str
    type: Optional[str] = None
    role: Optional[str] = None
    accessible_name: Optional[str] = None
    label: Optional[str] = None
    placeholder: Optional[str] = None
    element_id: Optional[str] = None
    name: Optional[str] = None
    data_testid: Optional[str] = None
    href: Optional[str] = None
    visible_text: Optional[str] = None
    is_visible: bool = True
    is_enabled: bool = True
    is_unique: bool = True
    frame_context: Optional[str] = None
    candidate_locators: List[str] = Field(default_factory=list)
    suggested_intent: Optional[str] = None


class DiscoverySnapshotResponse(BaseModel):
    id: str
    session_id: str
    page_url: str
    page_title: Optional[str] = None
    elements_count: int
    created_at: datetime
    inventory_data: Optional[Dict[str, Any]] = None


class DiscoverySessionResponse(BaseModel):
    id: str
    project_id: str
    user_id: str
    app_url: str
    current_url: Optional[str] = None
    current_title: Optional[str] = None
    status: str
    created_at: datetime
    updated_at: datetime
    closed_at: Optional[datetime] = None
    snapshots_count: int = 0
    latest_snapshot: Optional[DiscoverySnapshotResponse] = None


class ValidateTargetResponse(BaseModel):
    status: str = Field(..., description="'resolved_unique', 'ambiguous', 'not_found', or 'invalid_syntax'")
    target: str
    action: str
    matched_count: int = 0
    candidates: List[Dict[str, Any]] = Field(default_factory=list)
    recommended_locator: Optional[str] = None
    suggested_intent: Optional[str] = None
    message: str


class SearchInventoryRequest(BaseModel):
    query: str = Field(..., description="Target search query or natural-language intent phrase")
    action: Optional[str] = Field(default=None, description="Optional action type like 'click', 'fill', etc.")
    snapshot_id: Optional[str] = Field(default=None, description="Optional specific snapshot ID to restrict search")


class CandidateElementMatch(BaseModel):
    snapshot_id: str
    snapshot_title: Optional[str] = None
    snapshot_url: str
    element: CapturedElement
    match_score: float
    recommended_locator: Optional[str] = None
    live_validated: bool = False
    live_match_count: int = 0


class SearchInventoryResponse(BaseModel):
    session_id: str
    query: str
    action: Optional[str] = None
    matches: List[CandidateElementMatch]
    total_matches: int


class DiscoverySessionExport(BaseModel):
    schema_version: str = "1.0"
    exported_at: datetime
    session: DiscoverySessionResponse
    snapshots: List[DiscoverySnapshotResponse]
    total_snapshots: int
    total_elements: int


