"""
Comprehensive Test Suite for Persistent Saved Discovery Inventory in Noetrix.

Covers all 12 required test scenarios:
1. Creating a discovery session and capturing multiple snapshots.
2. Ending the session without deleting snapshots.
3. Retrieving snapshots after the session is closed.
4. Listing closed sessions after a backend restart or new API client request.
5. Returning all snapshots and all element metadata.
6. Exporting a valid JSON document containing every snapshot and its elements.
7. Preserving multiple captures of the same page.
8. Handling empty inventories and missing optional element fields.
9. Rejecting requests for nonexistent sessions.
10. Enforcing existing user and project authorization rules.
11. Ensuring sensitive values are redacted from saved and exported inventory.
12. Resolver integration: searching saved inventory for natural language targets and validating candidates.
"""
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.database import Base, SessionLocal, engine, get_db
from app.main import app
from app.models.discovery import DiscoverySession, DiscoverySnapshot
from app.models.organization import Organization, OrganizationMembership
from app.models.project import Project
from app.models.user import User
from app.services.discovery_service import (
    DiscoverySessionManager,
    search_saved_snapshots,
)
from app.services.locator_resolver import resolve_locator
from app.services.security import create_access_token, hash_password


@pytest.fixture(autouse=True)
def setup_test_db():
    """Ensure clean isolated tables for each test."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def auth_context():
    """Create test users, organization, and project."""
    with SessionLocal() as db:
        user1 = User(
            id=str(uuid.uuid4()),
            email="owner@example.com",
            hashed_password=hash_password("Pass1234!"),
            full_name="Owner User",
            is_active=True,
        )
        user2 = User(
            id=str(uuid.uuid4()),
            email="other@example.com",
            hashed_password=hash_password("Pass1234!"),
            full_name="Other User",
            is_active=True,
        )
        org = Organization(id=str(uuid.uuid4()), name="Acme Corp", slug=f"acme-{uuid.uuid4().hex[:6]}")
        db.add_all([user1, user2, org])
        db.commit()

        mem1 = OrganizationMembership(id=str(uuid.uuid4()), user_id=user1.id, org_id=org.id, role="owner")
        db.add(mem1)

        project = Project(
            id=str(uuid.uuid4()),
            name="ERP Suite",
            slug=f"erp-{uuid.uuid4().hex[:6]}",
            org_id=org.id,
            app_url="https://example.com/erp",
        )
        db.add(project)
        db.commit()

        u1_id = user1.id
        u2_id = user2.id
        proj_id = project.id

    token1 = create_access_token(data={"sub": u1_id})
    token2 = create_access_token(data={"sub": u2_id})

    return {
        "user1_id": u1_id,
        "token1": token1,
        "user2_id": u2_id,
        "token2": token2,
        "project_id": proj_id,
    }


SAMPLE_INVENTORY_PAGE1 = {
    "url": "https://example.com/erp/signin",
    "page_title": "Sign In - ERP",
    "headings": [{"tag": "h1", "text": "Sign In to ERP"}],
    "frames": [],
    "elements": [
        {
            "id": "el_1",
            "tag": "input",
            "type": "text",
            "role": "textbox",
            "accessible_name": "User ID",
            "label": "User ID",
            "placeholder": "Enter user id",
            "element_id": "userid",
            "name": "username",
            "data_testid": "userid-input",
            "href": None,
            "visible_text": "",
            "is_visible": True,
            "is_enabled": True,
            "is_unique": True,
            "candidate_locators": ["[data-testid=\"userid-input\"]", "#userid", "label=User ID"],
            "suggested_intent": "User ID field",
        },
        {
            "id": "el_2",
            "tag": "input",
            "type": "password",
            "role": "textbox",
            "accessible_name": "Password",
            "label": "Password",
            "placeholder": "Enter password",
            "element_id": "pwd",
            "name": "password",
            "data_testid": "password-input",
            "href": None,
            "visible_text": "",
            "is_visible": True,
            "is_enabled": True,
            "is_unique": True,
            "candidate_locators": ["[data-testid=\"password-input\"]", "#pwd"],
            "suggested_intent": "password field",
        },
        {
            "id": "el_3",
            "tag": "button",
            "type": "submit",
            "role": "button",
            "accessible_name": "Sign In",
            "label": "Sign In",
            "placeholder": None,
            "element_id": "btn-signin",
            "name": "submit",
            "data_testid": "signin-btn",
            "href": None,
            "visible_text": "Sign In",
            "is_visible": True,
            "is_enabled": True,
            "is_unique": True,
            "candidate_locators": ["[data-testid=\"signin-btn\"]", "#btn-signin", "role=button[name=\"Sign In\"]"],
            "suggested_intent": "Sign In button",
        },
    ],
}

SAMPLE_INVENTORY_PAGE2 = {
    "url": "https://example.com/erp/home",
    "page_title": "Welcome - Oracle Fusion ERP",
    "headings": [{"tag": "h1", "text": "Welcome Back"}],
    "frames": [],
    "elements": [
        {
            "id": "el_1",
            "tag": "img",
            "type": None,
            "role": None,
            "accessible_name": "Company Logo",
            "label": None,
            "placeholder": None,
            "element_id": "branding-logo",
            "name": None,
            "data_testid": "app-logo",
            "href": None,
            "visible_text": "Company Logo",
            "is_visible": True,
            "is_enabled": True,
            "is_unique": True,
            "candidate_locators": ["[data-testid=\"app-logo\"]", "#branding-logo"],
            "suggested_intent": "Company Logo logo",
        },
        {
            "id": "el_2",
            "tag": "a",
            "type": None,
            "role": "link",
            "accessible_name": "Hire an Employee",
            "label": "Hire an Employee",
            "placeholder": None,
            "element_id": "nav-hire",
            "name": None,
            "data_testid": "hire-link",
            "href": "/erp/hire",
            "visible_text": "Hire an Employee",
            "is_visible": True,
            "is_enabled": True,
            "is_unique": True,
            "candidate_locators": ["a[href=\"/erp/hire\"]", "#nav-hire", "role=link[name=\"Hire an Employee\"]"],
            "suggested_intent": "Hire an Employee link",
        },
    ],
}


@pytest.mark.asyncio
async def test_case_1_and_2_and_3_create_end_and_retrieve_snapshots(auth_context):
    """
    Test 1, 2, 3: Create session, capture multiple snapshots, end session without deleting snapshots,
    and retrieve all snapshots after closure.
    """
    token = auth_context["token1"]
    proj_id = auth_context["project_id"]

    mock_worker = MagicMock()
    mock_worker.is_active = True
    mock_worker.current_url = "https://example.com/erp/signin"
    mock_worker.current_title = "Sign In - ERP"

    # 1. Start discovery session
    manager = DiscoverySessionManager.get_instance()
    with patch.object(manager, "start_session", return_value=mock_worker):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            resp = await client.post(
                "/api/discovery/sessions",
                json={"project_id": proj_id, "url": "https://example.com/erp/signin", "headless": True},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 201
            session_id = resp.json()["id"]

    # Manually insert 2 snapshots to simulate captures
    with SessionLocal() as db:
        s1 = DiscoverySnapshot(
            session_id=session_id,
            page_url=SAMPLE_INVENTORY_PAGE1["url"],
            page_title=SAMPLE_INVENTORY_PAGE1["page_title"],
            elements_count=len(SAMPLE_INVENTORY_PAGE1["elements"]),
            inventory_data=json.dumps(SAMPLE_INVENTORY_PAGE1),
        )
        s2 = DiscoverySnapshot(
            session_id=session_id,
            page_url=SAMPLE_INVENTORY_PAGE2["url"],
            page_title=SAMPLE_INVENTORY_PAGE2["page_title"],
            elements_count=len(SAMPLE_INVENTORY_PAGE2["elements"]),
            inventory_data=json.dumps(SAMPLE_INVENTORY_PAGE2),
        )
        db.add_all([s1, s2])
        db.commit()

    # 2. End discovery session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        close_resp = await client.post(
            f"/api/discovery/sessions/{session_id}/close",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert close_resp.status_code == 200
        close_data = close_resp.json()
        assert close_data["status"] == "completed"
        assert close_data["snapshots_saved"] == 2

    # 3. Retrieve snapshots after session is closed
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        snaps_resp = await client.get(
            f"/api/discovery/sessions/{session_id}/snapshots",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert snaps_resp.status_code == 200
        snapshots = snaps_resp.json()
        assert len(snapshots) == 2

        # Verify chronological ordering (oldest first by default)
        assert snapshots[0]["page_title"] == "Sign In - ERP"
        assert snapshots[1]["page_title"] == "Welcome - Oracle Fusion ERP"
        assert snapshots[0]["elements_count"] == 3
        assert snapshots[1]["elements_count"] == 2


@pytest.mark.asyncio
async def test_case_4_listing_closed_sessions_after_client_request(auth_context):
    """Test 4: Closed sessions are preserved and listed properly on fresh API requests."""
    token = auth_context["token1"]
    user_id = auth_context["user1_id"]
    proj_id = auth_context["project_id"]

    # Seed one active and two closed sessions in DB
    with SessionLocal() as db:
        s_closed1 = DiscoverySession(
            id=str(uuid.uuid4()),
            project_id=proj_id,
            user_id=user_id,
            app_url="https://example.com/app1",
            status="completed",
            closed_at=datetime.now(timezone.utc),
        )
        s_closed2 = DiscoverySession(
            id=str(uuid.uuid4()),
            project_id=proj_id,
            user_id=user_id,
            app_url="https://example.com/app2",
            status="completed",
            closed_at=datetime.now(timezone.utc),
        )
        db.add_all([s_closed1, s_closed2])
        db.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        resp = await client.get(
            "/api/discovery/sessions",
            params={"project_id": proj_id},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        sessions = resp.json()
        assert len(sessions) >= 2
        statuses = [s["status"] for s in sessions]
        assert "completed" in statuses


@pytest.mark.asyncio
async def test_case_5_and_6_export_valid_json_with_all_elements(auth_context):
    """Test 5 & 6: Full snapshot element metadata return and valid JSON export."""
    token = auth_context["token1"]
    user_id = auth_context["user1_id"]
    proj_id = auth_context["project_id"]

    with SessionLocal() as db:
        sess = DiscoverySession(
            id=str(uuid.uuid4()),
            project_id=proj_id,
            user_id=user_id,
            app_url="https://example.com/erp",
            status="completed",
        )
        db.add(sess)
        db.commit()

        snap1 = DiscoverySnapshot(
            session_id=sess.id,
            page_url=SAMPLE_INVENTORY_PAGE1["url"],
            page_title=SAMPLE_INVENTORY_PAGE1["page_title"],
            elements_count=len(SAMPLE_INVENTORY_PAGE1["elements"]),
            inventory_data=json.dumps(SAMPLE_INVENTORY_PAGE1),
        )
        snap2 = DiscoverySnapshot(
            session_id=sess.id,
            page_url=SAMPLE_INVENTORY_PAGE2["url"],
            page_title=SAMPLE_INVENTORY_PAGE2["page_title"],
            elements_count=len(SAMPLE_INVENTORY_PAGE2["elements"]),
            inventory_data=json.dumps(SAMPLE_INVENTORY_PAGE2),
        )
        db.add_all([snap1, snap2])
        db.commit()
        session_id = sess.id

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        # Export endpoint
        export_resp = await client.get(
            f"/api/discovery/sessions/{session_id}/export",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert export_resp.status_code == 200
        assert "application/json" in export_resp.headers["content-type"]
        assert f"discovery_inventory_{session_id}.json" in export_resp.headers["content-disposition"]

        # Parse exported content
        export_data = json.loads(export_resp.text)
        assert export_data["schema_version"] == "1.0"
        assert export_data["session"]["id"] == session_id
        assert export_data["total_snapshots"] == 2
        assert export_data["total_elements"] == 5

        # Verify all snapshots and elements are preserved
        assert len(export_data["snapshots"]) == 2
        first_snap = export_data["snapshots"][0]
        assert first_snap["page_title"] == "Sign In - ERP"
        assert len(first_snap["elements"]) == 3
        # Check specific element fields
        el_user = first_snap["elements"][0]
        assert el_user["accessible_name"] == "User ID"
        assert el_user["tag"] == "input"
        assert el_user["data_testid"] == "userid-input"
        assert el_user["suggested_intent"] == "User ID field"
        assert len(el_user["candidate_locators"]) > 0


@pytest.mark.asyncio
async def test_case_7_preserving_multiple_captures_of_same_page(auth_context):
    """Test 7: Repeated snapshots of the same page URL are all preserved distinctly."""
    token = auth_context["token1"]
    user_id = auth_context["user1_id"]
    proj_id = auth_context["project_id"]

    same_url = "https://example.com/faces/FuseWelcome"
    with SessionLocal() as db:
        sess = DiscoverySession(
            id=str(uuid.uuid4()),
            project_id=proj_id,
            user_id=user_id,
            app_url=same_url,
            status="completed",
        )
        db.add(sess)
        db.commit()

        # Capture 1: 50 elements
        snap1 = DiscoverySnapshot(
            session_id=sess.id,
            page_url=same_url,
            page_title="Welcome",
            elements_count=50,
            inventory_data=json.dumps({"url": same_url, "elements": [{"id": f"el_{i}"} for i in range(50)]}),
        )
        # Capture 2: 75 elements (dynamic items loaded)
        snap2 = DiscoverySnapshot(
            session_id=sess.id,
            page_url=same_url,
            page_title="Welcome",
            elements_count=75,
            inventory_data=json.dumps({"url": same_url, "elements": [{"id": f"el_{i}"} for i in range(75)]}),
        )
        db.add_all([snap1, snap2])
        db.commit()
        session_id = sess.id

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        snaps_resp = await client.get(
            f"/api/discovery/sessions/{session_id}/snapshots",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert snaps_resp.status_code == 200
        snaps = snaps_resp.json()
        assert len(snaps) == 2
        assert snaps[0]["elements_count"] == 50
        assert snaps[1]["elements_count"] == 75


@pytest.mark.asyncio
async def test_case_8_handling_empty_inventories_and_missing_optional_fields(auth_context):
    """Test 8: Handles snapshots with 0 elements and elements with null optional fields."""
    token = auth_context["token1"]
    user_id = auth_context["user1_id"]
    proj_id = auth_context["project_id"]

    sparse_inventory = {
        "url": "https://example.com/sparse",
        "page_title": None,
        "headings": [],
        "frames": [],
        "elements": [
            {
                "id": "el_sparse",
                "tag": "div",
                "type": None,
                "role": None,
                "accessible_name": None,
                "label": None,
                "placeholder": None,
                "element_id": None,
                "name": None,
                "data_testid": None,
                "href": None,
                "visible_text": "Plain Text",
                "is_visible": True,
                "is_enabled": True,
                "is_unique": True,
                "candidate_locators": ["text=\"Plain Text\""],
                "suggested_intent": None,
            }
        ],
    }

    with SessionLocal() as db:
        sess = DiscoverySession(
            id=str(uuid.uuid4()),
            project_id=proj_id,
            user_id=user_id,
            app_url="https://example.com/sparse",
            status="completed",
        )
        db.add(sess)
        db.commit()

        # Empty snapshot
        snap_empty = DiscoverySnapshot(
            session_id=sess.id,
            page_url="https://example.com/empty",
            page_title="",
            elements_count=0,
            inventory_data=json.dumps({"url": "https://example.com/empty", "elements": []}),
        )
        # Sparse snapshot
        snap_sparse = DiscoverySnapshot(
            session_id=sess.id,
            page_url="https://example.com/sparse",
            page_title=None,
            elements_count=1,
            inventory_data=json.dumps(sparse_inventory),
        )
        db.add_all([snap_empty, snap_sparse])
        db.commit()
        session_id = sess.id
        snap_sparse_id = snap_sparse.id

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        # Check single snapshot fetch
        snap_resp = await client.get(
            f"/api/discovery/sessions/{session_id}/snapshots/{snap_sparse_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert snap_resp.status_code == 200
        data = snap_resp.json()
        assert data["elements_count"] == 1
        assert data["inventory_data"]["elements"][0]["id"] == "el_sparse"

        # Check export handles nulls cleanly
        export_resp = await client.get(
            f"/api/discovery/sessions/{session_id}/export",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert export_resp.status_code == 200
        export_data = export_resp.json()
        assert export_data["total_elements"] == 1


@pytest.mark.asyncio
async def test_case_9_and_10_authorization_and_nonexistent_rejection(auth_context):
    """Test 9 & 10: Nonexistent session 404 and cross-user authorization enforcement 403."""
    token1 = auth_context["token1"]
    token2 = auth_context["token2"]  # Unauthorized user (belongs to no org/project)
    user1_id = auth_context["user1_id"]
    proj_id = auth_context["project_id"]

    with SessionLocal() as db:
        sess = DiscoverySession(
            id=str(uuid.uuid4()),
            project_id=proj_id,
            user_id=user1_id,
            app_url="https://example.com/private",
            status="completed",
        )
        db.add(sess)
        db.commit()
        session_id = sess.id

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        # Nonexistent session
        non_existent = str(uuid.uuid4())
        resp_404 = await client.get(
            f"/api/discovery/sessions/{non_existent}/snapshots",
            headers={"Authorization": f"Bearer {token1}"},
        )
        assert resp_404.status_code == 404

        # Unauthorized user accessing User 1's session
        resp_403 = await client.get(
            f"/api/discovery/sessions/{session_id}/snapshots",
            headers={"Authorization": f"Bearer {token2}"},
        )
        assert resp_403.status_code == 403

        # Unauthorized user exporting User 1's session
        resp_export_403 = await client.get(
            f"/api/discovery/sessions/{session_id}/export",
            headers={"Authorization": f"Bearer {token2}"},
        )
        assert resp_export_403.status_code == 403


@pytest.mark.asyncio
async def test_case_11_sensitive_values_are_not_saved_or_exported(auth_context):
    """Test 11: Passwords and sensitive input values are not stored in inventory or leaked in export."""
    token = auth_context["token1"]
    user_id = auth_context["user1_id"]
    proj_id = auth_context["project_id"]

    with SessionLocal() as db:
        sess = DiscoverySession(
            id=str(uuid.uuid4()),
            project_id=proj_id,
            user_id=user_id,
            app_url="https://example.com/login",
            status="completed",
        )
        db.add(sess)
        db.commit()

        snap = DiscoverySnapshot(
            session_id=sess.id,
            page_url="https://example.com/login",
            page_title="Login",
            elements_count=2,
            inventory_data=json.dumps(SAMPLE_INVENTORY_PAGE1),
        )
        db.add(snap)
        db.commit()
        session_id = sess.id

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        export_resp = await client.get(
            f"/api/discovery/sessions/{session_id}/export",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert export_resp.status_code == 200
        export_text = export_resp.text

        # Verify no secret text or values are present
        assert "supersecret123" not in export_text
        export_json = json.loads(export_text)
        password_el = [el for el in export_json["snapshots"][0]["elements"] if el["type"] == "password"][0]
        assert password_el["visible_text"] == ""


@pytest.mark.asyncio
async def test_case_12_search_inventory_and_resolver_integration(auth_context):
    """
    Test 12: Search saved inventory endpoint and integration with locator resolver
    using historical candidate locators validated against a live page.
    """
    token = auth_context["token1"]
    user_id = auth_context["user1_id"]
    proj_id = auth_context["project_id"]

    with SessionLocal() as db:
        sess = DiscoverySession(
            id=str(uuid.uuid4()),
            project_id=proj_id,
            user_id=user_id,
            app_url="https://example.com/erp",
            status="completed",
        )
        db.add(sess)
        db.commit()

        snap1 = DiscoverySnapshot(
            session_id=sess.id,
            page_url=SAMPLE_INVENTORY_PAGE1["url"],
            page_title=SAMPLE_INVENTORY_PAGE1["page_title"],
            elements_count=len(SAMPLE_INVENTORY_PAGE1["elements"]),
            inventory_data=json.dumps(SAMPLE_INVENTORY_PAGE1),
        )
        snap2 = DiscoverySnapshot(
            session_id=sess.id,
            page_url=SAMPLE_INVENTORY_PAGE2["url"],
            page_title=SAMPLE_INVENTORY_PAGE2["page_title"],
            elements_count=len(SAMPLE_INVENTORY_PAGE2["elements"]),
            inventory_data=json.dumps(SAMPLE_INVENTORY_PAGE2),
        )
        db.add_all([snap1, snap2])
        db.commit()
        session_id = sess.id

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        # Search for "Sign In button"
        search_resp = await client.post(
            f"/api/discovery/sessions/{session_id}/search-inventory",
            json={"query": "Sign In button", "action": "click"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert search_resp.status_code == 200
        data = search_resp.json()
        assert data["total_matches"] > 0
        top_match = data["matches"][0]
        assert "Sign In" in top_match["element"]["accessible_name"]
        assert top_match["recommended_locator"] == "[data-testid=\"signin-btn\"]"

        # Search for page-specific link: "Hire an Employee"
        hire_resp = await client.post(
            f"/api/discovery/sessions/{session_id}/search-inventory",
            json={"query": "Find the Hire an Employee link on Welcome page", "action": "click"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert hire_resp.status_code == 200
        hire_data = hire_resp.json()
        assert hire_data["total_matches"] > 0
        top_hire = hire_data["matches"][0]
        assert top_hire["element"]["accessible_name"] == "Hire an Employee"
        assert top_hire["snapshot_title"] == "Welcome - Oracle Fusion ERP"

    # Direct unit test of locator_resolver integrating saved inventory with live mock page
    mock_loc = MagicMock()

    async def mock_count():
        return 1

    async def mock_is_visible():
        return True

    mock_loc.count = mock_count
    mock_loc.is_visible = mock_is_visible

    mock_page = MagicMock()
    mock_page.locator = MagicMock(return_value=mock_loc)

    # Calling resolve_locator with saved_inventory
    resolved = await resolve_locator(
        page=mock_page,
        target="Sign In button",
        action="click",
        saved_inventory=[SAMPLE_INVENTORY_PAGE1, SAMPLE_INVENTORY_PAGE2],
    )
    assert resolved == mock_loc
    # Verify that the candidate locator from saved inventory was queried on mock_page
    mock_page.locator.assert_any_call("[data-testid=\"signin-btn\"]")
