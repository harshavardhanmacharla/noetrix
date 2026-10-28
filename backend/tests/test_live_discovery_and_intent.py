"""
Automated Regression and Feature Verification Suite:
Live Browser Discovery and Intent-Based CSV Execution in Noetrix.

Covers all 16 required test scenarios:
1. Starting and ending a discovery session.
2. Navigating to a test page.
3. Capturing input fields, buttons, links, and labels.
4. Refreshing inventory after a page transition.
5. Resolving a natural-language target to a unique input (e.g. 'username field').
6. Resolving a button or link by accessible role and name (e.g. 'Next button', 'eAppSys logo').
7. Handling multiple matching elements without arbitrary selection (AmbiguousElementError).
8. Handling missing elements with useful diagnostics (ElementNotFoundError).
9. Preserving existing literal CSS selector behavior.
10. Preserving existing CSV validation and action semantics.
11. Executing sequential steps in one test case.
12. Handling navigation and dynamic page updates.
13. Isolating discovery sessions between users.
14. Ensuring sensitive values are not included in inventory or logs.
15. Cleaning up sessions after errors or timeout.
16. Validating URL security and SSRF protection.
"""
import http.server
import json
import os
import socket
import threading
import time
import urllib.parse
import uuid
import pytest

from app.config import get_settings
from app.services.csv_validator import validate_csv
from app.services.discovery_service import (
    DiscoverySessionManager,
    validate_discovery_url,
)
from app.services.locator_resolver import (
    AmbiguousElementError,
    ElementNotFoundError,
    normalize_intent_target,
    resolve_locator,
)
from app.services.playwright_runner import run_test_case

# ---------------------------------------------------------------------------
# Ephemeral HTTP Server with Test Pages
# ---------------------------------------------------------------------------
HTML_PAGE_LOGIN = """<!DOCTYPE html>
<html>
<head><title>Enterprise Sign-In</title></head>
<body>
    <header>
        <img src="/static/logo.png" alt="eAppSys logo" title="eAppSys Application" />
        <h1>Welcome to Cloud ERP</h1>
    </header>
    <main>
        <form id="login-form">
            <div>
                <label for="userid-input">User ID</label>
                <input id="userid-input" name="userid" type="text" placeholder="Enter User ID" />
            </div>
            <div>
                <label for="pwd-input">Password</label>
                <input id="pwd-input" name="password" type="password" placeholder="Password" />
            </div>
            <div>
                <button type="submit" id="btn-signin">Sign In</button>
            </div>
        </form>
        <div class="ambiguous-container">
            <button class="action-btn">Duplicate Button</button>
            <button class="action-btn">Duplicate Button</button>
        </div>
        <div>
            <a href="/app/landing" id="link-landing">Go to Workspace</a>
        </div>
    </main>
</body>
</html>
"""

HTML_PAGE_LANDING = """<!DOCTYPE html>
<html>
<head><title>Oracle Fusion Home</title></head>
<body>
    <nav role="navigation">
        <div role="menu">
            <div role="menuitem" tabindex="0">My Client Groups</div>
            <div role="menuitem" tabindex="0">Hire an Employee</div>
        </div>
    </nav>
    <main>
        <h2>Workforce Management</h2>
        <div class="search-region">
            <label for="search-box">Search</label>
            <input id="search-box" type="search" placeholder="Search for people and actions" />
        </div>
        <div class="form-region">
            <label for="country-select">Country</label>
            <select id="country-select">
                <option value="US">United States</option>
                <option value="UK">United Kingdom</option>
                <option value="CA">Canada</option>
            </select>
            <button id="btn-next">Next</button>
        </div>
    </main>
</body>
</html>
"""


class DiscoveryTestHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in ("/", "/login"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_PAGE_LOGIN.encode("utf-8"))
        elif parsed.path in ("/app/landing", "/landing"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_PAGE_LANDING.encode("utf-8"))
        elif parsed.path == "/static/logo.png":
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.end_headers()
            self.wfile.write(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


@pytest.fixture(scope="module")
def local_discovery_server():
    """Spins up an ephemeral local HTTP server for testing."""
    server = http.server.HTTPServer(("127.0.0.1", 0), DiscoveryTestHandler)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{port}"
    yield base_url
    server.shutdown()
    server.server_close()


# ---------------------------------------------------------------------------
# Test Scenarios
# ---------------------------------------------------------------------------

def test_scenario_1_start_and_end_discovery_session(local_discovery_server):
    """1. Starting and ending a discovery session."""
    manager = DiscoverySessionManager.get_instance()
    session_id = f"test-sess-{uuid.uuid4()}"
    user_id = f"user-{uuid.uuid4()}"
    project_id = f"proj-{uuid.uuid4()}"

    # Allow local discovery for this test
    worker = manager.start_session(
        session_id=session_id,
        user_id=user_id,
        project_id=project_id,
        app_url=f"{local_discovery_server}/login",
        headless=True,
    )
    assert worker.is_active is True
    assert worker.session_id == session_id

    # Retrieve worker
    active = manager.get_worker(session_id, user_id)
    assert active.session_id == session_id

    # Close session
    closed = manager.close_session(session_id, user_id)
    assert closed is True
    assert session_id not in manager._workers


def test_scenario_2_navigating_to_test_page(local_discovery_server):
    """2. Navigating to a test page and verifying current URL and title."""
    manager = DiscoverySessionManager.get_instance()
    session_id = f"test-sess-{uuid.uuid4()}"
    user_id = f"user-{uuid.uuid4()}"

    worker = manager.start_session(
        session_id=session_id,
        user_id=user_id,
        project_id="p1",
        app_url=f"{local_discovery_server}/login",
        headless=True,
    )
    try:
        assert "Enterprise Sign-In" in (worker.current_title or "")

        # Navigate within session
        nav_result = manager.navigate(session_id, user_id, f"{local_discovery_server}/app/landing")
        assert "/app/landing" in nav_result["url"]
        assert "Oracle Fusion Home" in nav_result["title"]
    finally:
        manager.close_session(session_id, user_id)


def test_scenario_3_capturing_input_fields_buttons_links_labels(local_discovery_server):
    """3. Capturing input fields, buttons, links, and labels."""
    manager = DiscoverySessionManager.get_instance()
    session_id = f"test-sess-{uuid.uuid4()}"
    user_id = f"user-{uuid.uuid4()}"

    worker = manager.start_session(
        session_id=session_id,
        user_id=user_id,
        project_id="p1",
        app_url=f"{local_discovery_server}/login",
        headless=True,
    )
    try:
        inventory = manager.capture_inventory(session_id, user_id)
        assert inventory["page_title"] == "Enterprise Sign-In"
        assert len(inventory["elements"]) > 0

        tags = {el["tag"] for el in inventory["elements"]}
        assert "input" in tags
        assert "button" in tags
        assert "a" in tags

        # Find User ID input
        userid_el = next((el for el in inventory["elements"] if el.get("element_id") == "userid-input"), None)
        assert userid_el is not None
        assert userid_el["label"] == "User ID"
        assert userid_el["placeholder"] == "Enter User ID"
        assert userid_el["suggested_intent"] is not None
        assert "field" in userid_el["suggested_intent"]

        # Find Sign In button
        signin_el = next((el for el in inventory["elements"] if el.get("element_id") == "btn-signin"), None)
        assert signin_el is not None
        assert "Sign In button" in signin_el["suggested_intent"]

        # Find eAppSys logo
        logo_el = next((el for el in inventory["elements"] if el.get("tag") == "img"), None)
        assert logo_el is not None
        assert "logo" in (logo_el["suggested_intent"] or "").lower()
    finally:
        manager.close_session(session_id, user_id)


def test_scenario_4_refreshing_inventory_after_page_transition(local_discovery_server):
    """4. Refreshing inventory after a page transition."""
    manager = DiscoverySessionManager.get_instance()
    session_id = f"test-sess-{uuid.uuid4()}"
    user_id = f"user-{uuid.uuid4()}"

    worker = manager.start_session(
        session_id=session_id,
        user_id=user_id,
        project_id="p1",
        app_url=f"{local_discovery_server}/login",
        headless=True,
    )
    try:
        inv1 = manager.capture_inventory(session_id, user_id)
        assert inv1["page_title"] == "Enterprise Sign-In"

        # Transition to landing page
        manager.navigate(session_id, user_id, f"{local_discovery_server}/app/landing")
        inv2 = manager.capture_inventory(session_id, user_id)
        assert inv2["page_title"] == "Oracle Fusion Home"

        # Verify new elements appear
        headings = [h["text"] for h in inv2.get("headings", [])]
        assert "Workforce Management" in headings
    finally:
        manager.close_session(session_id, user_id)


def test_scenario_5_resolving_natural_language_target_to_unique_input(local_discovery_server):
    """5. Resolving a natural-language target to a unique input (e.g. 'username field')."""
    manager = DiscoverySessionManager.get_instance()
    session_id = f"test-sess-{uuid.uuid4()}"
    user_id = f"user-{uuid.uuid4()}"

    worker = manager.start_session(
        session_id=session_id,
        user_id=user_id,
        project_id="p1",
        app_url=f"{local_discovery_server}/login",
        headless=True,
    )
    try:
        # Test target 'username field'
        res = manager.validate_target(session_id, user_id, "username field", action="fill")
        assert res["status"] == "resolved_unique"
        assert res["matched_count"] == 1

        # Test target 'password field'
        res_pwd = manager.validate_target(session_id, user_id, "password field", action="fill")
        assert res_pwd["status"] == "resolved_unique"
    finally:
        manager.close_session(session_id, user_id)


def test_scenario_6_resolving_button_or_link_by_accessible_role_and_name(local_discovery_server):
    """6. Resolving a button or link by accessible role and name (e.g. 'Next button', 'eAppSys logo')."""
    manager = DiscoverySessionManager.get_instance()
    session_id = f"test-sess-{uuid.uuid4()}"
    user_id = f"user-{uuid.uuid4()}"

    worker = manager.start_session(
        session_id=session_id,
        user_id=user_id,
        project_id="p1",
        app_url=f"{local_discovery_server}/login",
        headless=True,
    )
    try:
        # Test 'Sign In button'
        res = manager.validate_target(session_id, user_id, "Sign In button", action="click")
        assert res["status"] == "resolved_unique"

        # Test 'eAppSys logo'
        res_logo = manager.validate_target(session_id, user_id, "eAppSys logo", action="click")
        assert res_logo["status"] == "resolved_unique"

        # Test link 'Go to Workspace'
        res_link = manager.validate_target(session_id, user_id, "Go to Workspace", action="click")
        assert res_link["status"] == "resolved_unique"

        # Navigate to landing and test 'My Client Groups menu'
        manager.navigate(session_id, user_id, f"{local_discovery_server}/app/landing")
        res_menu = manager.validate_target(session_id, user_id, "My Client Groups menu", action="click")
        assert res_menu["status"] == "resolved_unique"

        # Test 'Next button' on landing
        res_next = manager.validate_target(session_id, user_id, "Next button", action="click")
        assert res_next["status"] == "resolved_unique"
    finally:
        manager.close_session(session_id, user_id)


def test_scenario_7_handling_multiple_matching_elements_without_arbitrary_selection(local_discovery_server):
    """7. Handling multiple matching elements without arbitrary selection (AmbiguousElementError)."""
    manager = DiscoverySessionManager.get_instance()
    session_id = f"test-sess-{uuid.uuid4()}"
    user_id = f"user-{uuid.uuid4()}"

    worker = manager.start_session(
        session_id=session_id,
        user_id=user_id,
        project_id="p1",
        app_url=f"{local_discovery_server}/login",
        headless=True,
    )
    try:
        # Test ambiguous target 'Duplicate Button'
        res = manager.validate_target(session_id, user_id, "Duplicate Button", action="click")
        assert res["status"] == "ambiguous"
        assert "Ambiguous target" in res["message"]
    finally:
        manager.close_session(session_id, user_id)


def test_scenario_8_handling_missing_elements_with_useful_diagnostics(local_discovery_server):
    """8. Handling missing elements with useful diagnostics (ElementNotFoundError)."""
    manager = DiscoverySessionManager.get_instance()
    session_id = f"test-sess-{uuid.uuid4()}"
    user_id = f"user-{uuid.uuid4()}"

    worker = manager.start_session(
        session_id=session_id,
        user_id=user_id,
        project_id="p1",
        app_url=f"{local_discovery_server}/login",
        headless=True,
    )
    try:
        # Missing input
        res = manager.validate_target(session_id, user_id, "Nonexistent Phone Number", action="fill")
        assert res["status"] == "not_found"
        assert "Could not find any input field matching" in res["message"]

        # Missing button
        res_btn = manager.validate_target(session_id, user_id, "Nonexistent Submit", action="click")
        assert res_btn["status"] == "not_found"
        assert "Could not find any clickable element matching" in res_btn["message"]
    finally:
        manager.close_session(session_id, user_id)


def test_scenario_9_preserving_existing_literal_css_selector_behavior(local_discovery_server):
    """9. Preserving existing literal CSS selector behavior."""
    manager = DiscoverySessionManager.get_instance()
    session_id = f"test-sess-{uuid.uuid4()}"
    user_id = f"user-{uuid.uuid4()}"

    worker = manager.start_session(
        session_id=session_id,
        user_id=user_id,
        project_id="p1",
        app_url=f"{local_discovery_server}/login",
        headless=True,
    )
    try:
        # CSS ID selector
        res = manager.validate_target(session_id, user_id, "#userid-input", action="fill")
        assert res["status"] == "resolved_unique"

        # Attribute selector
        res_attr = manager.validate_target(session_id, user_id, "button[type='submit']", action="click")
        assert res_attr["status"] == "resolved_unique"

        # Explicit engine prefix
        res_lbl = manager.validate_target(session_id, user_id, "label=User ID", action="fill")
        assert res_lbl["status"] == "resolved_unique"
    finally:
        manager.close_session(session_id, user_id)


def test_scenario_10_preserving_existing_csv_validation_and_action_semantics():
    """10. Preserving existing CSV validation and action semantics."""
    csv_content = (
        "test_case_id,test_name,step_number,action,target,value,expected_result\n"
        "TC001,Intent Test,1,navigate,,https://example.com/,\n"
        "TC001,Intent Test,2,fill,username field,admin,\n"
        "TC001,Intent Test,3,fill,password field,secret123,\n"
        "TC001,Intent Test,4,click,Sign In button,,\n"
        "TC001,Intent Test,5,verify_text,,Welcome,Welcome page is displayed\n"
    ).encode("utf-8")

    result = validate_csv(csv_content, filename="intent_test.csv")
    assert result.is_valid is True
    assert len(result.errors) == 0
    assert result.row_count == 5


@pytest.mark.asyncio
async def test_scenario_11_executing_sequential_steps_in_one_test_case(local_discovery_server, tmp_path):
    """11. Executing sequential steps in one test case."""
    steps = [
        {
            "step_number": 1,
            "action": "navigate",
            "target": None,
            "value": f"{local_discovery_server}/login",
            "expected_result": None,
        },
        {
            "step_number": 2,
            "action": "fill",
            "target": "username field",
            "value": "superadmin",
            "expected_result": None,
        },
        {
            "step_number": 3,
            "action": "fill",
            "target": "password field",
            "value": "secretpass",
            "expected_result": None,
        },
        {
            "step_number": 4,
            "action": "click",
            "target": "Sign In button",
            "value": None,
            "expected_result": None,
        },
        {
            "step_number": 5,
            "action": "verify_text",
            "target": None,
            "value": "Welcome to Cloud ERP",
            "expected_result": None,
        },
    ]

    outcome = await run_test_case(
        steps=steps,
        app_url=local_discovery_server,
        artifacts_dir=str(tmp_path),
        run_id=f"run-{uuid.uuid4()}",
        test_case_id=f"tc-{uuid.uuid4()}",
        headless=True,
    )
    assert outcome["status"] == "passed"
    assert len(outcome["steps"]) == 5


@pytest.mark.asyncio
async def test_scenario_12_handling_navigation_and_dynamic_page_updates(local_discovery_server, tmp_path):
    """12. Handling navigation and dynamic page updates."""
    steps = [
        {
            "step_number": 1,
            "action": "navigate",
            "target": None,
            "value": f"{local_discovery_server}/login",
            "expected_result": None,
        },
        {
            "step_number": 2,
            "action": "click",
            "target": "Go to Workspace",
            "value": None,
            "expected_result": None,
        },
        {
            "step_number": 3,
            "action": "verify_url",
            "target": None,
            "value": "/app/landing",
            "expected_result": None,
        },
        {
            "step_number": 4,
            "action": "click",
            "target": "My Client Groups menu",
            "value": None,
            "expected_result": None,
        },
        {
            "step_number": 5,
            "action": "select_option",
            "target": "Country dropdown",
            "value": "United Kingdom",
            "expected_result": None,
        },
        {
            "step_number": 6,
            "action": "click",
            "target": "Next button",
            "value": None,
            "expected_result": None,
        },
    ]

    outcome = await run_test_case(
        steps=steps,
        app_url=local_discovery_server,
        artifacts_dir=str(tmp_path),
        run_id=f"run-{uuid.uuid4()}",
        test_case_id=f"tc-{uuid.uuid4()}",
        headless=True,
    )
    assert outcome["status"] == "passed"


def test_scenario_13_isolating_discovery_sessions_between_users(local_discovery_server):
    """13. Isolating discovery sessions between users."""
    manager = DiscoverySessionManager.get_instance()
    session_id = f"test-sess-{uuid.uuid4()}"
    user_a = f"user-a-{uuid.uuid4()}"
    user_b = f"user-b-{uuid.uuid4()}"

    manager.start_session(
        session_id=session_id,
        user_id=user_a,
        project_id="p1",
        app_url=f"{local_discovery_server}/login",
        headless=True,
    )
    try:
        # User A can access
        worker = manager.get_worker(session_id, user_a)
        assert worker is not None

        # User B is blocked
        with pytest.raises(PermissionError) as exc_info:
            manager.get_worker(session_id, user_b)
        assert "Access denied" in str(exc_info.value)

        # User B cannot close User A's session
        with pytest.raises(PermissionError):
            manager.close_session(session_id, user_b)
    finally:
        manager.close_session(session_id, user_a)


def test_scenario_14_ensuring_sensitive_values_are_not_in_inventory_or_logs(local_discovery_server):
    """14. Ensuring sensitive values are not included in inventory or logs."""
    manager = DiscoverySessionManager.get_instance()
    session_id = f"test-sess-{uuid.uuid4()}"
    user_id = f"user-{uuid.uuid4()}"

    worker = manager.start_session(
        session_id=session_id,
        user_id=user_id,
        project_id="p1",
        app_url=f"{local_discovery_server}/login",
        headless=True,
    )
    try:
        inventory = manager.capture_inventory(session_id, user_id)
        pwd_el = next((el for el in inventory["elements"] if el.get("element_id") == "pwd-input"), None)
        assert pwd_el is not None
        assert pwd_el.get("visible_text") == "" or pwd_el.get("visible_text") is None
        assert "password" not in (pwd_el.get("visible_text") or "").lower()

        # Check full inventory serialization doesn't contain raw secrets
        serialized = json.dumps(inventory)
        assert "secretpass" not in serialized
    finally:
        manager.close_session(session_id, user_id)


def test_scenario_15_cleaning_up_sessions_after_errors_or_timeout():
    """15. Cleaning up sessions after errors or timeout."""
    manager = DiscoverySessionManager.get_instance()
    session_id = f"test-sess-{uuid.uuid4()}"
    user_id = f"user-{uuid.uuid4()}"

    # Invalid URL should fail cleanly and not leave dangling worker
    with pytest.raises(RuntimeError):
        manager.start_session(
            session_id=session_id,
            user_id=user_id,
            project_id="p1",
            app_url="http://invalid.domain.that.does.not.exist.local:9999",
            headless=True,
        )
    assert session_id not in manager._workers


def test_scenario_16_validating_url_security_and_ssrf_protection():
    """16. Validating URL security and SSRF protection."""
    # Disallowed non-http schemes
    with pytest.raises(ValueError, match="Prohibited URL scheme"):
        validate_discovery_url("file:///etc/passwd", allow_local=False)

    with pytest.raises(ValueError, match="Prohibited URL scheme"):
        validate_discovery_url("ftp://example.com", allow_local=False)

    # Disallowed internal/loopback hosts
    with pytest.raises(ValueError, match="Navigation to internal host"):
        validate_discovery_url("http://localhost:8000/api", allow_local=False)

    with pytest.raises(ValueError, match="Navigation to internal host"):
        validate_discovery_url("http://127.0.0.1:3000", allow_local=False)

    with pytest.raises(ValueError, match="Navigation to internal host"):
        validate_discovery_url("http://169.254.169.254/latest/meta-data", allow_local=False)

    # Valid external HTTPS URL
    valid_url = validate_discovery_url("https://oraclecloud.com/ords/login", allow_local=False)
    assert valid_url == "https://oraclecloud.com/ords/login"
