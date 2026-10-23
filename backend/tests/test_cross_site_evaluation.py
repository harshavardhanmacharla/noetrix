"""
Phase 5: Cross-Site Evaluation and Robustness Test Suite for Noetrix.

Tests real Playwright Chromium against diverse HTML DOM structures,
accessible labeling techniques, buttons/links with similar names,
duplicate matching elements (ambiguity), dynamic DOM updates,
assertion failures, and mixed CSS/XPath + natural language workflows.

All tests run locally using ephemeral HTTP servers and isolated databases.
Zero connections to remote Neon.
"""
from __future__ import annotations

import http.server
import socketserver
import threading
import time
from pathlib import Path
import pytest

from app.services.csv_validator import validate_csv
from app.services.locator_resolver import (
    AmbiguousElementError,
    ElementNotFoundError,
    resolve_locator,
)
from app.services.playwright_runner import _execute_playwright


# =============================================================================
# Local Test Server Fixture with Diverse HTML Pages
# =============================================================================

COMPLEX_PAGE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Complex Page Evaluation</title>
    <style>
        .hidden { display: none; }
        .visible { display: block; }
    </style>
</head>
<body>
    <h1>Complex Form & Controls</h1>

    <!-- 1. Diverse Form Labeling Techniques -->
    <form id="accessible-form">
        <!-- Explicit label-for -->
        <div>
            <label for="for-email">Work Email</label>
            <input type="text" id="for-email" name="work_email" />
        </div>

        <!-- Nested/wrapped label -->
        <div>
            <label>
                Office Phone Number
                <input type="text" id="nested-phone" name="office_phone" />
            </label>
        </div>

        <!-- aria-label -->
        <div>
            <input type="text" id="aria-pin" aria-label="Security Token Code" placeholder="000-000" />
        </div>

        <!-- placeholder only -->
        <div>
            <input type="text" id="ph-postal" placeholder="Postal Code / ZIP" />
        </div>

        <!-- textarea with aria-label -->
        <div>
            <textarea id="aria-notes" aria-label="Additional Comments"></textarea>
        </div>

        <!-- 2. Buttons & Links with Similar Names -->
        <div style="margin-top: 15px;">
            <button type="submit" id="btn-submit">Submit Application</button>
            <a href="#help" id="link-submit-help">Submit Application Guide</a>
        </div>
    </form>

    <!-- 3. Duplicate Elements for Ambiguity Detection -->
    <div id="duplicate-actions" style="margin-top: 20px;">
        <button class="dup-btn" id="cancel-1">Cancel Order</button>
        <button class="dup-btn" id="cancel-2">Cancel Order</button>
    </div>

    <!-- 4. Hidden Duplicate Element (Filtered) -->
    <div id="mixed-visibility-actions" style="margin-top: 20px;">
        <button id="discard-hidden" style="display: none;">Discard Draft</button>
        <button id="discard-visible" style="display: inline-block;">Discard Draft</button>
    </div>

    <!-- 5. Dynamic DOM Mutation Target -->
    <div style="margin-top: 20px;">
        <button id="btn-load-async" onclick="triggerAsyncContent()">Load Asynchronous Content</button>
        <div id="async-result" class="hidden">Asynchronous Payload Received Successfully</div>
    </div>

    <script>
        document.getElementById('accessible-form').addEventListener('submit', function(e) {
            e.preventDefault();
            window.location.hash = '#submitted';
        });

        function triggerAsyncContent() {
            setTimeout(function() {
                var el = document.getElementById('async-result');
                el.className = 'visible';
                el.style.display = 'block';
            }, 250);
        }
    </script>
</body>
</html>
"""


class ComplexPageHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/complex.html", "/complex.html#submitted"):
            data = COMPLEX_PAGE_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            self.send_error(404)

    def log_message(self, format, *args):
        pass


@pytest.fixture(scope="module")
def local_web_server():
    """Starts an ephemeral HTTP server on 127.0.0.1:8877 for the test session."""
    server = socketserver.TCPServer(("127.0.0.1", 8877), ComplexPageHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    yield "http://127.0.0.1:8877/complex.html"
    server.shutdown()


# =============================================================================
# 1. Accessible Label & Placeholder Variations (Real Chromium)
# =============================================================================

@pytest.mark.asyncio
async def test_real_chromium_resolves_all_accessible_labeling_styles(local_web_server, tmp_path):
    """
    Verifies that real Chromium correctly fills elements using:
    - Explicit <label for="...">
    - Nested <label><input></label>
    - aria-label
    - placeholder
    - textarea aria-label
    """
    steps = [
        {"step_number": 1, "action": "navigate", "value": local_web_server},
        {"step_number": 2, "action": "fill", "target": "Work Email", "value": "alice@corp.test"},
        {"step_number": 3, "action": "fill", "target": "Office Phone Number", "value": "555-0199"},
        {"step_number": 4, "action": "fill", "target": "Security Token Code", "value": "987-654"},
        {"step_number": 5, "action": "fill", "target": "Postal Code / ZIP", "value": "94105"},
        {"step_number": 6, "action": "fill", "target": "Additional Comments", "value": "Verified all styles"},
        {"step_number": 7, "action": "click", "target": "Submit Application"},
        {"step_number": 8, "action": "verify_url", "expected_result": "complex.html#submitted"},
    ]

    outcome = await _execute_playwright(
        steps=steps,
        app_url="",
        artifacts_dir=str(tmp_path),
        run_id="run-labels",
        test_case_id="tc-labels",
    )

    assert outcome["status"] == "passed", f"Failed with: {outcome.get('error_message')}"
    logs = "\n".join(outcome.get("log_lines", []))
    assert "Filled 'Work Email'" in logs
    assert "Filled 'Office Phone Number'" in logs
    assert "Filled 'Security Token Code'" in logs
    assert "Filled 'Postal Code / ZIP'" in logs
    assert "Filled 'Additional Comments'" in logs
    assert "Click action completed for 'Submit Application'" in logs
    assert "URL verified successfully" in logs


# =============================================================================
# 2. Buttons & Links with Similar Names (Real Chromium)
# =============================================================================

@pytest.mark.asyncio
async def test_real_chromium_distinguishes_button_vs_link_similar_names(local_web_server, tmp_path):
    """
    Tests that:
    - 'Submit Application' resolves to <button> (submits form, URL changes to #submitted).
    - 'Submit Application Guide' resolves to <a> link.
    """
    # Test link resolution
    steps_link = [
        {"step_number": 1, "action": "navigate", "value": local_web_server},
        {"step_number": 2, "action": "click", "target": "Submit Application Guide"},
        {"step_number": 3, "action": "verify_url", "expected_result": "complex.html#help"},
    ]

    outcome_link = await _execute_playwright(
        steps=steps_link,
        app_url="",
        artifacts_dir=str(tmp_path),
        run_id="run-link",
        test_case_id="tc-link",
    )
    assert outcome_link["status"] == "passed"
    assert "Click action completed for 'Submit Application Guide'" in "\n".join(outcome_link["log_lines"])


# =============================================================================
# 3. Duplicate Elements: Ambiguity Detection (Real Chromium)
# =============================================================================

@pytest.mark.asyncio
async def test_real_chromium_detects_ambiguity_on_duplicate_visible_buttons(local_web_server, tmp_path):
    """
    Tests that when two visible buttons share the exact same accessible name ('Cancel Order'),
    the runner safely rejects interaction and raises AmbiguousElementError instead of clicking randomly.
    """
    steps = [
        {"step_number": 1, "action": "navigate", "value": local_web_server},
        {"step_number": 2, "action": "click", "target": "Cancel Order"},
    ]

    outcome = await _execute_playwright(
        steps=steps,
        app_url="",
        artifacts_dir=str(tmp_path),
        run_id="run-ambig",
        test_case_id="tc-ambig",
    )

    assert outcome["status"] == "failed"
    err = outcome.get("error_message", "")
    assert "Ambiguous target 'Cancel Order'" in err
    assert "matches 2 visible elements" in err


# =============================================================================
# 4. Hidden Duplicate Element Filtering (Real Chromium)
# =============================================================================

@pytest.mark.asyncio
async def test_real_chromium_filters_hidden_element_and_clicks_visible_one(local_web_server, tmp_path):
    """
    When two buttons exist with name 'Discard Draft', but one is display:none
    and one is visible, it should automatically select the visible one without ambiguity error.
    """
    steps = [
        {"step_number": 1, "action": "navigate", "value": local_web_server},
        {"step_number": 2, "action": "click", "target": "Discard Draft"},
    ]

    outcome = await _execute_playwright(
        steps=steps,
        app_url="",
        artifacts_dir=str(tmp_path),
        run_id="run-hidden-filter",
        test_case_id="tc-hidden-filter",
    )

    assert outcome["status"] == "passed"
    logs = "\n".join(outcome["log_lines"])
    assert "Click action completed for 'Discard Draft'" in logs


# =============================================================================
# 5. Missing Elements Failure Handling (Real Chromium)
# =============================================================================

@pytest.mark.asyncio
async def test_real_chromium_reports_clear_missing_element_error(local_web_server, tmp_path):
    """
    When target element does not exist anywhere on the page, runner reports ElementNotFoundError
    and captures screenshot if artifacts directory permits.
    """
    steps = [
        {"step_number": 1, "action": "navigate", "value": local_web_server},
        {"step_number": 2, "action": "click", "target": "Completely Nonexistent Button"},
    ]

    outcome = await _execute_playwright(
        steps=steps,
        app_url="",
        artifacts_dir=str(tmp_path),
        run_id="run-missing",
        test_case_id="tc-missing",
    )

    assert outcome["status"] == "failed"
    err = outcome.get("error_message", "")
    assert "Could not find any clickable element matching 'Completely Nonexistent Button'" in err
    # Failure screenshot should be saved
    assert outcome.get("screenshot_path") is not None
    assert Path(outcome["screenshot_path"]).exists()


# =============================================================================
# 6. Dynamic DOM Updates & Client-Side Rendering (Real Chromium)
# =============================================================================

@pytest.mark.asyncio
async def test_real_chromium_handles_dynamic_asynchronous_content(local_web_server, tmp_path):
    """
    Clicks button that asynchronously triggers display:block after 250ms,
    verifying Playwright waits and asserts text visibility successfully.
    """
    steps = [
        {"step_number": 1, "action": "navigate", "value": local_web_server},
        {"step_number": 2, "action": "click", "target": "Load Asynchronous Content"},
        {
            "step_number": 3,
            "action": "verify_text",
            "expected_result": "Asynchronous Payload Received Successfully",
        },
    ]

    outcome = await _execute_playwright(
        steps=steps,
        app_url="",
        artifacts_dir=str(tmp_path),
        run_id="run-async",
        test_case_id="tc-async",
    )

    assert outcome["status"] == "passed"
    logs = "\n".join(outcome["log_lines"])
    assert "Text 'Asynchronous Payload Received Successfully' found on page" in logs


# =============================================================================
# 7. Assertion Failures (Incorrect Text or URL) (Real Chromium)
# =============================================================================

@pytest.mark.asyncio
async def test_real_chromium_reports_assertion_failure_on_incorrect_text(local_web_server, tmp_path):
    """
    Verifies that an incorrect expected text assertion fails with a preview of visible text.
    """
    steps = [
        {"step_number": 1, "action": "navigate", "value": local_web_server},
        {
            "step_number": 2,
            "action": "verify_text",
            "expected_result": "This Exact Phrase Does Not Exist Anywhere",
        },
    ]

    outcome = await _execute_playwright(
        steps=steps,
        app_url="",
        artifacts_dir=str(tmp_path),
        run_id="run-assert-fail",
        test_case_id="tc-assert-fail",
    )

    assert outcome["status"] == "failed"
    err = outcome.get("error_message", "")
    assert "Text 'This Exact Phrase Does Not Exist Anywhere' was not found as visible text" in err
    assert "Visible page text begins:" in err


@pytest.mark.asyncio
async def test_real_chromium_reports_assertion_failure_on_incorrect_url(local_web_server, tmp_path):
    """
    Verifies that an incorrect URL verification fails with expected vs current URL details.
    """
    steps = [
        {"step_number": 1, "action": "navigate", "value": local_web_server},
        {
            "step_number": 2,
            "action": "verify_url",
            "expected_result": "expected-wrong-path.html",
        },
    ]

    outcome = await _execute_playwright(
        steps=steps,
        app_url="",
        artifacts_dir=str(tmp_path),
        run_id="run-url-fail",
        test_case_id="tc-url-fail",
    )

    assert outcome["status"] == "failed"
    err = outcome.get("error_message", "")
    assert "URL verification failed: expected 'expected-wrong-path.html' in current URL" in err


# =============================================================================
# 8. Mixed Workflow: Technical Selectors + Natural Language in Single Test
# =============================================================================

@pytest.mark.asyncio
async def test_real_chromium_mixed_selector_and_natural_language_workflow(local_web_server, tmp_path):
    """
    Verifies full backward compatibility when a single test mixes CSS IDs, XPath,
    and natural-language semantic targets.
    """
    steps = [
        {"step_number": 1, "action": "navigate", "value": local_web_server},
        # Direct CSS ID selector
        {"step_number": 2, "action": "fill", "target": "#for-email", "value": "direct-css@test.com"},
        # Natural language semantic target
        {"step_number": 3, "action": "fill", "target": "Office Phone Number", "value": "123-4567"},
        # Direct XPath selector
        {"step_number": 4, "action": "fill", "target": "//input[@id='aria-pin']", "value": "333-222"},
        # Natural language button click
        {"step_number": 5, "action": "click", "target": "Submit Application"},
        {"step_number": 6, "action": "verify_url", "expected_result": "complex.html#submitted"},
    ]

    outcome = await _execute_playwright(
        steps=steps,
        app_url="",
        artifacts_dir=str(tmp_path),
        run_id="run-mixed",
        test_case_id="tc-mixed",
    )

    assert outcome["status"] == "passed"
    logs = "\n".join(outcome["log_lines"])
    assert "Filling target '#for-email'" in logs
    assert "Filling target 'Office Phone Number'" in logs
    assert "Filling target '//input[@id='aria-pin']'" in logs
    assert "Click action completed for 'Submit Application'" in logs
    assert "URL verified successfully" in logs
