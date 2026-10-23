"""
Phase 7: Dynamic Web Application Reliability Test Suite for Noetrix.

Verifies reliable Playwright execution on dynamic, asynchronous, and SPA web applications:
1. Element appearing after a short delay (setTimeout / asynchronous DOM insertion).
2. Element becoming visible after a modal opens (display: none -> display: block).
3. Form whose submit button becomes enabled after input (disabled -> enabled).
4. SPA client-side route changes (history.pushState asynchronous URL change).
5. DOM element being replaced after an interaction (stale node re-mounting).
6. Permanently missing element timing out cleanly without hanging.
7. Duplicate visible targets producing an explicit AmbiguousElementError.
8. Assertion failing even when preceding click succeeds (distinguishing attempted actions).
9. Secret redaction in logs, errors, and artifact suppression.
10. Existing CSS/XPath and canonical CSV validation and execution compatibility.

All tests run locally using ephemeral HTTP servers and isolated in-memory/temp state.
Zero connections to remote Neon.
"""
from __future__ import annotations

import http.server
import os
import socketserver
import threading
from pathlib import Path
import pytest

from app.services.csv_validator import validate_csv
from app.services.locator_resolver import (
    AmbiguousElementError,
    ElementNotFoundError,
    resolve_locator,
)
from app.services.playwright_runner import _execute_playwright


DYNAMIC_PAGE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Dynamic Web Reliability Testbed</title>
    <style>
        .hidden { display: none; }
        .visible { display: block; }
        #settings-modal {
            display: none;
            padding: 20px;
            background: #f0f0f0;
            border: 1px solid #ccc;
        }
    </style>
</head>
<body>
    <h1>Dynamic Web Reliability Testbed</h1>

    <!-- 1. Delayed Element Insertion -->
    <div id="delay-section">
        <button id="trigger-delay-btn" onclick="triggerDelayedElement()">Start Delayed Job</button>
        <div id="delay-container"></div>
    </div>

    <!-- 2. Modal with Delayed Visibility -->
    <div id="modal-section">
        <button id="open-modal-btn" onclick="openModal()">Open Settings Modal</button>
        <div id="settings-modal">
            <h2>Settings View</h2>
            <button id="modal-save-btn" onclick="saveModal()">Save Settings</button>
            <span id="modal-status"></span>
        </div>
    </div>

    <!-- 3. Form with Input-Dependent Enabled Button -->
    <div id="activation-section">
        <form id="license-form" onsubmit="return false;">
            <label for="license-code">Product License Key</label>
            <input type="text" id="license-code" placeholder="Enter license key" oninput="checkLicenseInput(this.value)" />
            <button id="activate-btn" disabled onclick="activateLicense()">Activate License</button>
            <span id="activation-status"></span>
        </form>
    </div>

    <!-- 4. SPA Client-Side Routing -->
    <div id="spa-section">
        <nav>
            <a href="/spa/home" id="nav-home" onclick="navigateSPA('/spa/home', 'Home Content'); return false;">Home</a>
            <a href="/spa/orders" id="nav-orders" onclick="navigateSPA('/spa/orders', 'Orders Dashboard Content'); return false;">Orders Dashboard</a>
        </nav>
        <div id="spa-view">Home Content</div>
    </div>

    <!-- 5. Replaced DOM Element (Component Re-mount) -->
    <div id="replace-section">
        <div id="mount-container">
            <button id="action-trigger" onclick="replaceMountedElement()">Update Preferences</button>
        </div>
    </div>

    <!-- 6. Duplicate Elements for Ambiguity Detection -->
    <div id="ambiguity-section">
        <button class="dup-delete-btn" onclick="void(0)">Discard Record</button>
        <button class="dup-delete-btn" onclick="void(0)">Discard Record</button>
    </div>

    <script>
        // 1. Delayed Element
        function triggerDelayedElement() {
            setTimeout(function() {
                var btn = document.createElement('button');
                btn.id = 'async-finish-btn';
                btn.textContent = 'Complete Process';
                btn.onclick = function() {
                    document.getElementById('delay-container').textContent = 'Process Succeeded';
                };
                document.getElementById('delay-container').appendChild(btn);
            }, 300);
        }

        // 2. Modal
        function openModal() {
            setTimeout(function() {
                document.getElementById('settings-modal').style.display = 'block';
            }, 150);
        }
        function saveModal() {
            document.getElementById('modal-status').textContent = 'Preferences Saved Successfully';
        }

        // 3. Activation
        function checkLicenseInput(val) {
            var btn = document.getElementById('activate-btn');
            btn.disabled = val.trim().length < 5;
        }
        function activateLicense() {
            document.getElementById('activation-status').textContent = 'License Activated: PRO-TIER';
        }

        // 4. SPA Navigation
        function navigateSPA(path, content) {
            setTimeout(function() {
                window.history.pushState({}, '', path);
                document.getElementById('spa-view').textContent = content;
            }, 100);
        }

        // 5. Replace Mounted Element
        function replaceMountedElement() {
            var container = document.getElementById('mount-container');
            container.innerHTML = '<button id="action-trigger" onclick="acknowledgeUpdate()">Confirm New Preferences</button>';
        }
        function acknowledgeUpdate() {
            document.getElementById('mount-container').textContent = 'Preferences Acknowledged';
        }
    </script>
</body>
</html>
"""


class DynamicPageHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        # Serve the single dynamic testbed HTML for all paths (simulating SPA behavior)
        data = DYNAMIC_PAGE_HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args):
        pass


@pytest.fixture(scope="module")
def dynamic_web_server():
    """Starts an ephemeral loopback HTTP server on an available port."""
    server = socketserver.TCPServer(("127.0.0.1", 0), DynamicPageHandler)
    port = server.server_address[1]
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    base_url = f"http://127.0.0.1:{port}/dynamic.html"
    yield base_url
    server.shutdown()


# =============================================================================
# 1. Element Appearing After Short Delay (Real Chromium)
# =============================================================================

@pytest.mark.asyncio
async def test_dynamic_element_appearing_after_delay(dynamic_web_server, tmp_path):
    steps = [
        {"step_number": 1, "action": "navigate", "value": dynamic_web_server},
        {"step_number": 2, "action": "click", "target": "Start Delayed Job"},
        {"step_number": 3, "action": "click", "target": "Complete Process"},
        {"step_number": 4, "action": "verify_text", "expected_result": "Process Succeeded"},
    ]

    outcome = await _execute_playwright(
        steps=steps,
        app_url="",
        artifacts_dir=str(tmp_path),
        run_id="run-dyn-1",
        test_case_id="tc-delay",
    )

    assert outcome["status"] == "passed", f"Failed with: {outcome.get('error_message')}"
    logs = "\n".join(outcome.get("log_lines", []))
    assert "Click action completed for 'Complete Process'" in logs
    assert "Text 'Process Succeeded' found on page" in logs


# =============================================================================
# 2. Element Becoming Visible After Modal Opens (Real Chromium)
# =============================================================================

@pytest.mark.asyncio
async def test_element_visible_after_modal_opens(dynamic_web_server, tmp_path):
    steps = [
        {"step_number": 1, "action": "navigate", "value": dynamic_web_server},
        {"step_number": 2, "action": "click", "target": "Open Settings Modal"},
        {"step_number": 3, "action": "click", "target": "Save Settings"},
        {"step_number": 4, "action": "verify_text", "expected_result": "Preferences Saved Successfully"},
    ]

    outcome = await _execute_playwright(
        steps=steps,
        app_url="",
        artifacts_dir=str(tmp_path),
        run_id="run-dyn-2",
        test_case_id="tc-modal",
    )

    assert outcome["status"] == "passed", f"Failed with: {outcome.get('error_message')}"
    logs = "\n".join(outcome.get("log_lines", []))
    assert "Click action completed for 'Save Settings'" in logs
    assert "Preferences Saved Successfully" in logs


# =============================================================================
# 3. Form Submit Button Becoming Enabled After Input (Real Chromium)
# =============================================================================

@pytest.mark.asyncio
async def test_button_enabled_after_input(dynamic_web_server, tmp_path):
    steps = [
        {"step_number": 1, "action": "navigate", "value": dynamic_web_server},
        {"step_number": 2, "action": "fill", "target": "Product License Key", "value": "VALID-LICENSE-KEY"},
        {"step_number": 3, "action": "click", "target": "Activate License"},
        {"step_number": 4, "action": "verify_text", "expected_result": "License Activated: PRO-TIER"},
    ]

    outcome = await _execute_playwright(
        steps=steps,
        app_url="",
        artifacts_dir=str(tmp_path),
        run_id="run-dyn-3",
        test_case_id="tc-enable",
    )

    assert outcome["status"] == "passed", f"Failed with: {outcome.get('error_message')}"
    logs = "\n".join(outcome.get("log_lines", []))
    assert "Click action completed for 'Activate License'" in logs
    assert "License Activated: PRO-TIER" in logs


# =============================================================================
# 4. SPA Client-Side Route Changes (Real Chromium)
# =============================================================================

@pytest.mark.asyncio
async def test_spa_route_change_verified(dynamic_web_server, tmp_path):
    steps = [
        {"step_number": 1, "action": "navigate", "value": dynamic_web_server},
        {"step_number": 2, "action": "click", "target": "Orders Dashboard"},
        {"step_number": 3, "action": "verify_url", "expected_result": "/spa/orders"},
        {"step_number": 4, "action": "verify_text", "expected_result": "Orders Dashboard Content"},
    ]

    outcome = await _execute_playwright(
        steps=steps,
        app_url="",
        artifacts_dir=str(tmp_path),
        run_id="run-dyn-4",
        test_case_id="tc-spa",
    )

    assert outcome["status"] == "passed", f"Failed with: {outcome.get('error_message')}"
    logs = "\n".join(outcome.get("log_lines", []))
    assert "URL verified successfully" in logs
    assert "Orders Dashboard Content" in logs


# =============================================================================
# 5. DOM Element Replaced After Interaction (Real Chromium)
# =============================================================================

@pytest.mark.asyncio
async def test_dom_element_replaced_after_interaction(dynamic_web_server, tmp_path):
    steps = [
        {"step_number": 1, "action": "navigate", "value": dynamic_web_server},
        {"step_number": 2, "action": "click", "target": "Update Preferences"},
        {"step_number": 3, "action": "click", "target": "Confirm New Preferences"},
        {"step_number": 4, "action": "verify_text", "expected_result": "Preferences Acknowledged"},
    ]

    outcome = await _execute_playwright(
        steps=steps,
        app_url="",
        artifacts_dir=str(tmp_path),
        run_id="run-dyn-5",
        test_case_id="tc-replace",
    )

    assert outcome["status"] == "passed", f"Failed with: {outcome.get('error_message')}"
    logs = "\n".join(outcome.get("log_lines", []))
    assert "Click action completed for 'Confirm New Preferences'" in logs
    assert "Preferences Acknowledged" in logs


# =============================================================================
# 6. Permanently Missing Element Times Out Cleanly (Real Chromium)
# =============================================================================

@pytest.mark.asyncio
async def test_permanently_missing_element_times_out_cleanly(dynamic_web_server, tmp_path):
    steps = [
        {"step_number": 1, "action": "navigate", "value": dynamic_web_server},
        {"step_number": 2, "action": "click", "target": "CompletelyNonExistentButtonXYZ"},
    ]

    outcome = await _execute_playwright(
        steps=steps,
        app_url="",
        artifacts_dir=str(tmp_path),
        run_id="run-dyn-6",
        test_case_id="tc-missing",
    )

    assert outcome["status"] == "failed"
    assert "Could not find any clickable element matching 'CompletelyNonExistentButtonXYZ'" in (outcome.get("error_message") or "")


# =============================================================================
# 7. Duplicate Visible Targets Produce Ambiguity Error (Real Chromium)
# =============================================================================

@pytest.mark.asyncio
async def test_duplicate_visible_targets_raise_ambiguity(dynamic_web_server, tmp_path):
    steps = [
        {"step_number": 1, "action": "navigate", "value": dynamic_web_server},
        {"step_number": 2, "action": "click", "target": "Discard Record"},
    ]

    outcome = await _execute_playwright(
        steps=steps,
        app_url="",
        artifacts_dir=str(tmp_path),
        run_id="run-dyn-7",
        test_case_id="tc-ambiguity",
    )

    assert outcome["status"] == "failed"
    err = outcome.get("error_message") or ""
    assert "Ambiguous target 'Discard Record'" in err
    assert "matches 2 visible elements" in err


# =============================================================================
# 8. Assertion Fails Even When Preceding Click Succeeds (Real Chromium)
# =============================================================================

@pytest.mark.asyncio
async def test_assertion_fails_after_successful_click(dynamic_web_server, tmp_path):
    steps = [
        {"step_number": 1, "action": "navigate", "value": dynamic_web_server},
        {"step_number": 2, "action": "click", "target": "Open Settings Modal"},
        {"step_number": 3, "action": "verify_text", "expected_result": "NonExistentString12345"},
    ]

    outcome = await _execute_playwright(
        steps=steps,
        app_url="",
        artifacts_dir=str(tmp_path),
        run_id="run-dyn-8",
        test_case_id="tc-assert-fail",
    )

    assert outcome["status"] == "failed"
    logs = "\n".join(outcome.get("log_lines", []))
    # Step 2 click succeeded
    assert "Click action completed for 'Open Settings Modal'" in logs
    # Step 3 assertion failed
    assert "FAILED at Step 3 (verify_text)" in logs
    assert "NonExistentString12345" in (outcome.get("error_message") or "")


# =============================================================================
# 9. Secret Redaction in Failures & Artifacts (Real Chromium)
# =============================================================================

@pytest.mark.asyncio
async def test_secret_redaction_in_failures(dynamic_web_server, tmp_path, monkeypatch):
    secret_value = "super-secret-dyn-token-999"
    monkeypatch.setenv("DYN_AUTH_SECRET", secret_value)

    steps = [
        {"step_number": 1, "action": "navigate", "value": dynamic_web_server},
        {"step_number": 2, "action": "fill", "target": "Product License Key", "value": "${secret:DYN_AUTH_SECRET}"},
        {"step_number": 3, "action": "click", "target": "GhostButtonForFailure"},
    ]

    outcome = await _execute_playwright(
        steps=steps,
        app_url="",
        artifacts_dir=str(tmp_path),
        run_id="run-dyn-9",
        test_case_id="tc-secret-redact",
    )

    assert outcome["status"] == "failed"
    logs = "\n".join(outcome.get("log_lines", []))
    err = outcome.get("error_message") or ""

    # Secret reference and raw value must never appear
    assert secret_value not in logs
    assert secret_value not in err
    assert "${secret:DYN_AUTH_SECRET}" not in logs

    # Failure screenshot should be skipped for secrets
    assert outcome["screenshot_path"] is None
    assert "Failure screenshot skipped because a sensitive fill value was used" in logs


# =============================================================================
# 10. Existing CSS/XPath & Canonical CSV Compatibility
# =============================================================================

@pytest.mark.asyncio
async def test_canonical_csv_compatibility_with_mixed_selectors(dynamic_web_server, tmp_path):
    csv_content = (
        "test_case_id,test_name,step_number,action,target,value,expected_result\n"
        f"TC-DYN-10,Mixed Dynamic Workflow,1,navigate,,{dynamic_web_server},\n"
        "TC-DYN-10,Mixed Dynamic Workflow,2,click,#nav-orders,,\n"
        "TC-DYN-10,Mixed Dynamic Workflow,3,verify_url,,,/spa/orders\n"
        "TC-DYN-10,Mixed Dynamic Workflow,4,fill,//input[@id='license-code'],PRO-999,\n"
        "TC-DYN-10,Mixed Dynamic Workflow,5,click,Activate License,,\n"
        "TC-DYN-10,Mixed Dynamic Workflow,6,verify that text 'License Activated: PRO-TIER' is visible,,,\n"
    )

    val_result = validate_csv(csv_content.encode("utf-8"))
    assert val_result.is_valid is True, f"CSV validation failed: {val_result.errors}"
    assert len(val_result.parsed_cases) == 1

    steps = val_result.parsed_cases[0]["steps"]
    assert len(steps) == 6

    outcome = await _execute_playwright(
        steps=steps,
        app_url="",
        artifacts_dir=str(tmp_path),
        run_id="run-dyn-10",
        test_case_id="tc-csv-compat",
    )

    assert outcome["status"] == "passed", f"Execution failed: {outcome.get('error_message')}"
    logs = "\n".join(outcome.get("log_lines", []))
    assert "Click action completed for '#nav-orders'" in logs
    assert "URL verified successfully" in logs
    assert "Filled '//input[@id='license-code']'" in logs
    assert "Click action completed for 'Activate License'" in logs
    assert "License Activated: PRO-TIER" in logs
