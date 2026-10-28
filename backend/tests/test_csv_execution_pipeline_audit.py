"""
Comprehensive Regression Test Suite for Noetrix's CSV-Driven Playwright Execution Pipeline.

Covers all 15 required audit scenarios:
1. verify_text with a literal value and a descriptive expected_result.
2. verify_text with an empty value and a legacy text fallback.
3. verify_text with no target (page-wide text search).
4. verify_text scoped to a valid CSS selector container.
5. Text locators that contain spaces.
6. Missing target or assertion text.
7. A target that matches no element (ElementNotFoundError).
8. A target that matches multiple elements (AmbiguousElementError).
9. A hidden text element (ElementNotVisibleError).
10. A successful URL redirect followed by page verification.
11. A page that displays an Access Denied message (AccessDeniedError).
12. Boolean configuration parsing for PLAYWRIGHT_HEADLESS.
13. Regression coverage for fill, click, and select_option.
14. Existing secret-redaction behavior.
15. Multi-test execution, individual result reporting, and per-test video association.
"""
from __future__ import annotations

import asyncio
import http.server
import json
import socketserver
import threading
from pathlib import Path
from typing import Any, Dict, List

import pytest
from app.config import Settings
from app.services.csv_validator import validate_csv
from app.services.locator_resolver import (
    AccessDeniedError,
    AmbiguousElementError,
    ElementNotFoundError,
    ElementNotVisibleError,
    InvalidLocatorSyntaxError,
    is_direct_selector,
    resolve_locator,
)
from app.services.playwright_runner import _execute_playwright, categorize_step_error, run_test_case
from app.services.result_diagnostics import categorize_error_string

# =============================================================================
# Ephemeral Test Server with Diverse Multi-Route Endpoints
# =============================================================================

TEST_PAGES_HTML = {
    "/index.html": """<!DOCTYPE html>
<html>
<head><title>Noetrix Audit Testbed</title></head>
<body>
    <h1>Sign in</h1>
    <div id="header-container">
        <h2>Dashboard Header</h2>
        <p>Header Title Subtext</p>
    </div>
    <div id="content-container">
        <p>Main page content with some descriptive text.</p>
        <span class="user-greeting">Welcome Back</span>
    </div>
    <div id="hidden-box" style="display:none;">
        <p>Secret Vault Code</p>
    </div>
    <div id="duplicate-container">
        <button class="dup-action">Duplicate Button</button>
        <button class="dup-action">Duplicate Button</button>
    </div>
    <form id="sample-form">
        <label for="username-input">User Name Field</label>
        <input type="text" id="username-input" name="username" placeholder="Enter your username">

        <label for="password-input">Password Field</label>
        <input type="password" id="password-input" name="password">

        <label for="role-select">Select User Role</label>
        <select id="role-select" name="role">
            <option value="">-- Choose Role --</option>
            <option value="admin">Administrator</option>
            <option value="editor">Content Editor</option>
            <option value="viewer">Standard Viewer</option>
        </select>

        <button type="button" id="submit-btn" onclick="submitForm()">Sign in to your account</button>
    </form>
    <div id="status-message"></div>
    <script>
        function submitForm() {
            var user = document.getElementById('username-input').value;
            var role = document.getElementById('role-select').value;
            document.getElementById('status-message').textContent = 'Submission Success: ' + user + ' as ' + role;
        }
    </script>
</body>
</html>""",
    "/access-denied.html": """<!DOCTYPE html>
<html>
<head><title>403 Forbidden - Access Denied</title></head>
<body>
    <h1>Access Denied</h1>
    <p>You do not have permission to view this application.</p>
</body>
</html>""",
    "/redirect.html": """<!DOCTYPE html>
<html>
<head>
    <meta http-equiv="refresh" content="0; url=/destination.html">
    <title>Redirecting...</title>
</head>
<body>
    <p>Redirecting to destination page...</p>
</body>
</html>""",
    "/destination.html": """<!DOCTYPE html>
<html>
<head><title>Destination Page</title></head>
<body>
    <h1>Arrived at Destination</h1>
    <p>Destination verification text is visible here.</p>
</body>
</html>""",
}


class PipelineAuditHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/access-denied.html":
            data = TEST_PAGES_HTML["/access-denied.html"].encode("utf-8")
            self.send_response(403)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        if path in TEST_PAGES_HTML:
            data = TEST_PAGES_HTML[path].encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        # Fallback to index.html
        data = TEST_PAGES_HTML["/index.html"].encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args):
        pass


@pytest.fixture(scope="module")
def audit_test_server():
    server = socketserver.TCPServer(("127.0.0.1", 0), PipelineAuditHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{port}"
    yield base_url
    server.shutdown()


def make_csv(*rows: str) -> bytes:
    header = "test_case_id,test_name,step_number,action,target,value,expected_result"
    lines = [header] + list(rows)
    return "\n".join(lines).encode("utf-8")


# =============================================================================
# 1. verify_text with a literal value and a descriptive expected_result
# =============================================================================

@pytest.mark.asyncio
async def test_scenario_1_verify_text_literal_value_and_descriptive_expected(audit_test_server, tmp_path):
    """
    Scenario 1: verify_text prefers value as literal text and does NOT treat descriptive
    expected_result sentence as literal page text.
    """
    steps = [
        {"step_number": 1, "action": "navigate", "value": f"{audit_test_server}/index.html"},
        {
            "step_number": 2,
            "action": "verify_text",
            "target": "",
            "value": "Sign in",
            "expected_result": "Sign-in page contains Sign in heading",
        },
    ]
    outcome = await _execute_playwright(
        steps=steps,
        app_url="",
        artifacts_dir=str(tmp_path),
        run_id="run-sc1",
        test_case_id="tc-sc1",
        headless=True,
    )
    assert outcome["status"] == "passed"
    assert outcome["steps"][1]["status"] == "passed"
    assert outcome["steps"][1]["verification_result"]["expected"] == "Sign in"


# =============================================================================
# 2. verify_text with an empty value and a legacy text fallback
# =============================================================================

@pytest.mark.asyncio
async def test_scenario_2_verify_text_empty_value_legacy_fallback(audit_test_server, tmp_path):
    """
    Scenario 2: When value is empty, verify_text falls back to expected_result for legacy CSVs.
    """
    steps = [
        {"step_number": 1, "action": "navigate", "value": f"{audit_test_server}/index.html"},
        {
            "step_number": 2,
            "action": "verify_text",
            "target": "",
            "value": "",
            "expected_result": "Welcome Back",
        },
    ]
    outcome = await _execute_playwright(
        steps=steps,
        app_url="",
        artifacts_dir=str(tmp_path),
        run_id="run-sc2",
        test_case_id="tc-sc2",
        headless=True,
    )
    assert outcome["status"] == "passed"
    assert outcome["steps"][1]["status"] == "passed"
    assert outcome["steps"][1]["verification_result"]["expected"] == "Welcome Back"


# =============================================================================
# 3. verify_text with no target (page-wide search)
# =============================================================================

@pytest.mark.asyncio
async def test_scenario_3_verify_text_with_no_target(audit_test_server, tmp_path):
    """
    Scenario 3: With an empty target, verify_text searches the entire page and succeeds.
    """
    steps = [
        {"step_number": 1, "action": "navigate", "value": f"{audit_test_server}/index.html"},
        {"step_number": 2, "action": "verify_text", "target": "", "value": "Dashboard Header"},
    ]
    outcome = await _execute_playwright(
        steps=steps,
        app_url="",
        artifacts_dir=str(tmp_path),
        run_id="run-sc3",
        test_case_id="tc-sc3",
        headless=True,
    )
    assert outcome["status"] == "passed"
    assert outcome["steps"][1]["status"] == "passed"


# =============================================================================
# 4. verify_text scoped to a valid CSS selector container
# =============================================================================

@pytest.mark.asyncio
async def test_scenario_4_verify_text_scoped_to_css_selector(audit_test_server, tmp_path):
    """
    Scenario 4: When target is a valid CSS selector, text verification is scoped to that element.
    """
    steps = [
        {"step_number": 1, "action": "navigate", "value": f"{audit_test_server}/index.html"},
        {
            "step_number": 2,
            "action": "verify_text",
            "target": "#header-container",
            "value": "Header Title Subtext",
        },
    ]
    outcome = await _execute_playwright(
        steps=steps,
        app_url="",
        artifacts_dir=str(tmp_path),
        run_id="run-sc4",
        test_case_id="tc-sc4",
        headless=True,
    )
    assert outcome["status"] == "passed"
    assert outcome["steps"][1]["status"] == "passed"


# =============================================================================
# 5. Text locators that contain spaces
# =============================================================================

@pytest.mark.asyncio
async def test_scenario_5_text_locators_with_spaces(audit_test_server, tmp_path):
    """
    Scenario 5: Explicit text locators and semantic targets containing spaces resolve cleanly.
    """
    steps = [
        {"step_number": 1, "action": "navigate", "value": f"{audit_test_server}/index.html"},
        {"step_number": 2, "action": "click", "target": "text=Sign in to your account"},
        {
            "step_number": 3,
            "action": "verify_text",
            "target": "",
            "value": "Submission Success",
        },
    ]
    outcome = await _execute_playwright(
        steps=steps,
        app_url="",
        artifacts_dir=str(tmp_path),
        run_id="run-sc5",
        test_case_id="tc-sc5",
        headless=True,
    )
    assert outcome["status"] == "passed"


# =============================================================================
# 6. Missing target or assertion text validation
# =============================================================================

def test_scenario_6_missing_target_or_assertion_text_validation():
    """
    Scenario 6: CSV validator and runner raise actionable errors for missing required fields.
    """
    # 6a. verify_text missing both value and expected_result
    csv_bytes_vt = make_csv("TC001,Test,1,verify_text,#container,,")
    res_vt = validate_csv(csv_bytes_vt)
    assert res_vt.is_valid is False
    assert any("requires text to verify" in e.message for e in res_vt.errors)

    # 6b. fill missing target
    csv_bytes_fill = make_csv("TC001,Test,1,fill,,my_value,")
    res_fill = validate_csv(csv_bytes_fill)
    assert res_fill.is_valid is False
    assert any("requires a non-empty target" in e.message for e in res_fill.errors)

    # 6c. verify_url missing URL pattern
    csv_bytes_vu = make_csv("TC001,Test,1,verify_url,,,")
    res_vu = validate_csv(csv_bytes_vu)
    assert res_vu.is_valid is False
    assert any("requires an expected URL pattern" in e.message for e in res_vu.errors)


# =============================================================================
# 7. A target that matches no element (ElementNotFoundError)
# =============================================================================

@pytest.mark.asyncio
async def test_scenario_7_target_matches_no_element(audit_test_server, tmp_path):
    """
    Scenario 7: Target that matches 0 elements fails cleanly with ElementNotFoundError.
    """
    steps = [
        {"step_number": 1, "action": "navigate", "value": f"{audit_test_server}/index.html"},
        {"step_number": 2, "action": "click", "target": "#completely-nonexistent-btn"},
    ]
    outcome = await _execute_playwright(
        steps=steps,
        app_url="",
        artifacts_dir=str(tmp_path),
        run_id="run-sc7",
        test_case_id="tc-sc7",
        headless=True,
    )
    assert outcome["status"] == "failed"
    failed_step = outcome["steps"][1]
    assert failed_step["status"] == "failed"
    assert failed_step["category"] == "missing_element"
    assert "0 elements" in failed_step["failure_reason"]


# =============================================================================
# 8. A target that matches multiple elements (AmbiguousElementError)
# =============================================================================

@pytest.mark.asyncio
async def test_scenario_8_target_matches_multiple_elements(audit_test_server, tmp_path):
    """
    Scenario 8: Target that matches multiple visible elements fails with AmbiguousElementError.
    """
    steps = [
        {"step_number": 1, "action": "navigate", "value": f"{audit_test_server}/index.html"},
        {"step_number": 2, "action": "click", "target": ".dup-action"},
    ]
    outcome = await _execute_playwright(
        steps=steps,
        app_url="",
        artifacts_dir=str(tmp_path),
        run_id="run-sc8",
        test_case_id="tc-sc8",
        headless=True,
    )
    assert outcome["status"] == "failed"
    failed_step = outcome["steps"][1]
    assert failed_step["category"] == "ambiguous_target"
    assert "Ambiguous target" in failed_step["failure_reason"]


# =============================================================================
# 9. A hidden text element (ElementNotVisibleError)
# =============================================================================

@pytest.mark.asyncio
async def test_scenario_9_hidden_text_element_diagnosed(audit_test_server, tmp_path):
    """
    Scenario 9: Text that is present in the DOM but hidden produces ElementNotVisibleError
    rather than a generic missing-text assertion failure.
    """
    steps = [
        {"step_number": 1, "action": "navigate", "value": f"{audit_test_server}/index.html"},
        {"step_number": 2, "action": "verify_text", "value": "Secret Vault Code"},
    ]
    outcome = await _execute_playwright(
        steps=steps,
        app_url="",
        artifacts_dir=str(tmp_path),
        run_id="run-sc9",
        test_case_id="tc-sc9",
        headless=True,
    )
    assert outcome["status"] == "failed"
    failed_step = outcome["steps"][1]
    assert failed_step["status"] == "failed"
    assert failed_step["category"] == "element_not_visible"
    assert "present in the DOM but is not visible" in failed_step["failure_reason"]


# =============================================================================
# 10. Successful URL redirect followed by page verification
# =============================================================================

@pytest.mark.asyncio
async def test_scenario_10_url_redirect_and_page_verification(audit_test_server, tmp_path):
    """
    Scenario 10: Follows an HTTP redirect and successfully verifies destination URL and text.
    """
    steps = [
        {"step_number": 1, "action": "navigate", "value": f"{audit_test_server}/redirect.html"},
        {"step_number": 2, "action": "verify_url", "value": "/destination.html"},
        {"step_number": 3, "action": "verify_text", "value": "Arrived at Destination"},
    ]
    outcome = await _execute_playwright(
        steps=steps,
        app_url="",
        artifacts_dir=str(tmp_path),
        run_id="run-sc10",
        test_case_id="tc-sc10",
        headless=True,
    )
    assert outcome["status"] == "passed"
    assert outcome["steps"][1]["status"] == "passed"
    assert outcome["steps"][2]["status"] == "passed"


# =============================================================================
# 11. Page that displays an Access Denied message
# =============================================================================

@pytest.mark.asyncio
async def test_scenario_11_access_denied_message_detected(audit_test_server, tmp_path):
    """
    Scenario 11: When a page renders an Access Denied response, failure is categorized
    as access_denied with informative diagnostic details.
    """
    steps = [
        {"step_number": 1, "action": "navigate", "value": f"{audit_test_server}/access-denied.html"},
        {"step_number": 2, "action": "verify_text", "value": "Dashboard Area"},
    ]
    outcome = await _execute_playwright(
        steps=steps,
        app_url="",
        artifacts_dir=str(tmp_path),
        run_id="run-sc11",
        test_case_id="tc-sc11",
        headless=True,
    )
    assert outcome["status"] == "failed"
    failed_step = outcome["steps"][1]
    assert failed_step["category"] == "access_denied"
    assert "access denied" in failed_step["failure_reason"].lower()


# =============================================================================
# 12. Boolean configuration parsing for PLAYWRIGHT_HEADLESS
# =============================================================================

def test_scenario_12_boolean_config_parsing_for_headless(monkeypatch):
    """
    Scenario 12: Robust boolean parsing handles true/false strings, digits, and booleans.
    """
    for false_val in ("False", "false", "0", "no", "off", "f", False):
        monkeypatch.setenv("PLAYWRIGHT_HEADLESS", str(false_val))
        s = Settings()
        assert s.PLAYWRIGHT_HEADLESS is False, f"Failed for {false_val}"

    for true_val in ("True", "true", "1", "yes", "on", "t", True):
        monkeypatch.setenv("PLAYWRIGHT_HEADLESS", str(true_val))
        s = Settings()
        assert s.PLAYWRIGHT_HEADLESS is True, f"Failed for {true_val}"


# =============================================================================
# 13. Regression coverage for fill, click, and select_option
# =============================================================================

@pytest.mark.asyncio
async def test_scenario_13_fill_click_select_option_regression(audit_test_server, tmp_path):
    """
    Scenario 13: End-to-end execution of fill, click, and select_option with assertions.
    """
    steps = [
        {"step_number": 1, "action": "navigate", "value": f"{audit_test_server}/index.html"},
        {"step_number": 2, "action": "fill", "target": "#username-input", "value": "john_doe"},
        {"step_number": 3, "action": "select_option", "target": "#role-select", "value": "Administrator"},
        {"step_number": 4, "action": "click", "target": "#submit-btn"},
        {
            "step_number": 5,
            "action": "verify_text",
            "target": "#status-message",
            "value": "Submission Success: john_doe as admin",
        },
    ]
    outcome = await _execute_playwright(
        steps=steps,
        app_url="",
        artifacts_dir=str(tmp_path),
        run_id="run-sc13",
        test_case_id="tc-sc13",
        headless=True,
    )
    assert outcome["status"] == "passed"
    for s in outcome["steps"]:
        assert s["status"] == "passed"


# =============================================================================
# 14. Existing secret-redaction behavior
# =============================================================================

@pytest.mark.asyncio
async def test_scenario_14_secret_redaction_behavior(audit_test_server, tmp_path):
    """
    Scenario 14: Secret passwords, ${secret:...}, and {{var}} values are redacted from logs and steps.json.
    """
    secret_val = "SuperSecretPassword123"
    steps = [
        {"step_number": 1, "action": "navigate", "value": f"{audit_test_server}/index.html"},
        {
            "step_number": 2,
            "action": "fill",
            "target": "#password-input",
            "value": "{{admin_pass}}",
        },
    ]
    variables = {
        "admin_pass": {"value": secret_val, "is_secret": True}
    }
    outcome = await _execute_playwright(
        steps=steps,
        app_url="",
        artifacts_dir=str(tmp_path),
        run_id="run-sc14",
        test_case_id="tc-sc14",
        variables=variables,
        headless=True,
    )
    assert outcome["status"] == "passed"
    # Verify raw secret is nowhere in logs
    log_text = "\n".join(outcome["log_lines"])
    assert secret_val not in log_text
    assert "[REDACTED]" in log_text

    # Verify steps.json on disk does not leak the secret
    steps_file = Path(outcome["steps_path"])
    disk_content = steps_file.read_text(encoding="utf-8")
    assert secret_val not in disk_content
    assert "[REDACTED]" in disk_content


# =============================================================================
# 15. Multi-test execution, individual result reporting, and per-test video association
# =============================================================================

@pytest.mark.asyncio
async def test_scenario_15_multi_test_execution_and_video_association(audit_test_server, tmp_path):
    """
    Scenario 15: Running multiple distinct test cases preserves individual step records
    and generates separate results and video files.
    """
    tc1_steps = [
        {"step_number": 1, "action": "navigate", "value": f"{audit_test_server}/index.html"},
        {"step_number": 2, "action": "verify_text", "value": "Sign in"},
    ]
    tc2_steps = [
        {"step_number": 1, "action": "navigate", "value": f"{audit_test_server}/destination.html"},
        {"step_number": 2, "action": "verify_text", "value": "Arrived at Destination"},
    ]

    res1 = await run_test_case(
        steps=tc1_steps,
        app_url="",
        artifacts_dir=str(tmp_path),
        run_id="multi-run-15",
        test_case_id="tc-result-1",
        headless=True,
    )
    res2 = await run_test_case(
        steps=tc2_steps,
        app_url="",
        artifacts_dir=str(tmp_path),
        run_id="multi-run-15",
        test_case_id="tc-result-2",
        headless=True,
    )

    assert res1["status"] == "passed"
    assert res2["status"] == "passed"

    # Distinct steps files
    assert res1["steps_path"] != res2["steps_path"]
    assert Path(res1["steps_path"]).exists()
    assert Path(res2["steps_path"]).exists()

    # If videos were recorded, they must be distinct paths
    if res1.get("video_path") and res2.get("video_path"):
        assert res1["video_path"] != res2["video_path"]

