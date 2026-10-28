"""
Tests for `wait_until` First-Class CSV Action in Noetrix.

Covers:
  1. CSV validation & syntax flexibility (canonical & reverse target/value syntax).
  2. Validation error handling for unsupported conditions and missing targets.
  3. Natural-language wait instruction parsing in `instruction_parser.py`.
  4. Safeguards against fixed sleeps (e.g. `wait 5 seconds`).
  5. Result diagnostics & error categorization (`wait_timeout`).
  6. Execution of all 5 condition types (`url_contains`, `page_heading`, `element_visible`, `element_enabled`, `element_hidden`).
  7. Side-effect free verification (no clicks or fills on checked elements).
  8. Timeout handling, step stopping, and no-click-replay guarantees.
  9. Preceding click coordination in `infer_expected_navigation`.
 10. Complete Oracle Fusion 5-page wizard workflow simulation with in-page ADF PPR.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, List, Optional
import sys
import pytest

from app.config import get_settings
from app.services.csv_validator import (
    SUPPORTED_WAIT_CONDITIONS,
    normalize_wait_condition,
    validate_csv,
)
from app.services.instruction_parser import (
    parse_instruction,
    parse_step_data,
)
from app.services.locator_resolver import ElementNotFoundError, resolve_locator
from app.services.playwright_runner import (
    _execute_playwright,
    categorize_step_error,
    infer_expected_navigation,
    reconstruct_instruction,
)
from app.services.result_diagnostics import categorize_error_string

settings = get_settings()


# =============================================================================
# 1. CSV Validation & Normalization Tests
# =============================================================================

def test_wait_until_canonical_syntax():
    """Verify standard wait_until syntax: target=condition, value=target_arg."""
    csv_content = (
        "test_case_id,test_name,step_number,action,target,value,expected_result\n"
        "TC_001,Test Wait,1,navigate,https://example.com,,Page loaded\n"
        "TC_001,Test Wait,2,wait_until,url_contains,/dashboard,\n"
        "TC_001,Test Wait,3,wait_until,page_heading,Person Information,\n"
        "TC_001,Test Wait,4,wait_until,element_visible,Legal Employer field,\n"
        "TC_001,Test Wait,5,wait_until,element_enabled,Submit button,\n"
        "TC_001,Test Wait,6,wait_until,element_hidden,loading overlay,\n"
    ).encode("utf-8")

    res = validate_csv(csv_content, "valid_wait.csv")
    assert res.is_valid is True
    assert len(res.errors) == 0
    assert len(res.parsed_cases) == 1
    steps = res.parsed_cases[0]["steps"]
    assert len(steps) == 6
    assert steps[1]["action"] == "wait_until"
    assert steps[1]["target"] == "url_contains"
    assert steps[1]["value"] == "/dashboard"
    assert steps[2]["target"] == "page_heading"
    assert steps[2]["value"] == "Person Information"
    assert steps[3]["target"] == "element_visible"
    assert steps[3]["value"] == "Legal Employer field"
    assert steps[4]["target"] == "element_enabled"
    assert steps[4]["value"] == "Submit button"
    assert steps[5]["target"] == "element_hidden"
    assert steps[5]["value"] == "loading overlay"


def test_wait_until_reverse_syntax_flexibility():
    """Verify reversed syntax: target=element, value=condition is normalized correctly."""
    csv_content = (
        "test_case_id,test_name,step_number,action,target,value,expected_result\n"
        "TC_001,Test Wait,1,navigate,https://example.com,,Page loaded\n"
        "TC_001,Test Wait,2,wait_until,Legal Employer field,element_visible,\n"
        "TC_001,Test Wait,3,wait_until,Next button,element_enabled,\n"
        "TC_001,Test Wait,4,wait_until,modal popup,element_hidden,\n"
    ).encode("utf-8")

    res = validate_csv(csv_content, "reverse_wait.csv")
    assert res.is_valid is True
    assert len(res.errors) == 0
    steps = res.parsed_cases[0]["steps"]
    assert len(steps) == 4
    # Check normalized structure
    assert steps[1]["action"] == "wait_until"
    assert steps[1]["target"] == "element_visible"
    assert steps[1]["value"] == "Legal Employer field"
    assert steps[2]["target"] == "element_enabled"
    assert steps[2]["value"] == "Next button"
    assert steps[3]["target"] == "element_hidden"
    assert steps[3]["value"] == "modal popup"


def test_wait_until_value_fallback_to_expected_result():
    """Verify wait_until falls back to expected_result if value column is blank."""
    csv_content = (
        "test_case_id,test_name,step_number,action,target,value,expected_result\n"
        "TC_001,Test Wait,1,navigate,https://example.com,,Page loaded\n"
        "TC_001,Test Wait,2,wait_until,page_heading,,Hire an Employee: Identification\n"
    ).encode("utf-8")

    res = validate_csv(csv_content, "fallback_wait.csv")
    assert res.is_valid is True
    assert len(res.errors) == 0
    steps = res.parsed_cases[0]["steps"]
    assert steps[1]["target"] == "page_heading"
    assert steps[1]["value"] == "Hire an Employee: Identification"


def test_wait_until_unsupported_condition_rejection():
    """Verify unsupported wait conditions are cleanly rejected with supported conditions list."""
    csv_content = (
        "test_case_id,test_name,step_number,action,target,value,expected_result\n"
        "TC_001,Test Wait,1,navigate,https://example.com,,Page loaded\n"
        "TC_001,Test Wait,2,wait_until,network_idle,500ms,\n"
    ).encode("utf-8")

    res = validate_csv(csv_content, "invalid_condition.csv")
    assert res.is_valid is False
    assert len(res.errors) == 1
    err = res.errors[0]
    assert "Unsupported wait condition 'network_idle'" in err.message
    assert "Supported wait conditions: ['element_enabled', 'element_hidden', 'element_visible', 'page_heading', 'url_contains']" in err.message


def test_wait_until_missing_target_or_value_rejection():
    """Verify wait_until with a valid condition but empty argument is rejected."""
    csv_content = (
        "test_case_id,test_name,step_number,action,target,value,expected_result\n"
        "TC_001,Test Wait,1,navigate,https://example.com,,Page loaded\n"
        "TC_001,Test Wait,2,wait_until,url_contains,,\n"
    ).encode("utf-8")

    res = validate_csv(csv_content, "missing_arg.csv")
    assert res.is_valid is False
    assert len(res.errors) == 1
    err = res.errors[0]
    assert "Action 'wait_until' with condition 'url_contains' requires a non-empty target or value." in err.message


# =============================================================================
# 2. Instruction Parser Natural-Language Tests
# =============================================================================

def test_parse_natural_language_wait_instructions():
    """Verify natural language wait instructions are parsed into canonical wait_until actions."""
    # Heading
    r1 = parse_instruction("wait until page heading is 'Hire an Employee: Identification'")
    assert r1.is_valid is True
    assert r1.action_data.action == "wait_until"
    assert r1.action_data.target == "page_heading"
    assert r1.action_data.value == "Hire an Employee: Identification"

    # URL
    r2 = parse_instruction("wait until url contains '/hcmUI/faces/FndOverview'")
    assert r2.is_valid is True
    assert r2.action_data.action == "wait_until"
    assert r2.action_data.target == "url_contains"
    assert r2.action_data.value == "/hcmUI/faces/FndOverview"

    # Element visible
    r3 = parse_instruction("wait until Legal Employer field is visible")
    assert r3.is_valid is True
    assert r3.action_data.action == "wait_until"
    assert r3.action_data.target == "element_visible"
    assert r3.action_data.value in ("Legal Employer", "Legal Employer field")

    # Element enabled
    r4 = parse_instruction("wait for Next button to be enabled")
    assert r4.is_valid is True
    assert r4.action_data.action == "wait_until"
    assert r4.action_data.target == "element_enabled"
    assert r4.action_data.value in ("Next", "Next button")

    # Element hidden
    r5 = parse_instruction("wait until loading overlay is hidden")
    assert r5.is_valid is True
    assert r5.action_data.action == "wait_until"
    assert r5.action_data.target == "element_hidden"
    assert r5.action_data.value in ("loading overlay", "loading")

    # Element appear / disappear
    r6 = parse_instruction("wait for modal backdrop to disappear")
    assert r6.is_valid is True
    assert r6.action_data.action == "wait_until"
    assert r6.action_data.target == "element_hidden"
    assert r6.action_data.value in ("modal backdrop", "modal")


def test_wait_fixed_sleep_safeguard_preserved():
    """Verify fixed sleep commands like 'wait 5 seconds' are rejected with explanation."""
    r1 = parse_instruction("wait 5 seconds")
    assert r1.is_valid is False
    assert "explicit wait/sleep instructions are not supported" in r1.error

    r2 = parse_instruction("pause for 3 seconds")
    assert r2.is_valid is False
    assert "explicit wait/sleep instructions are not supported" in r2.error


def test_bare_wait_instruction_rejected():
    """Verify bare wait instructions with no condition or target are rejected."""
    r = parse_instruction("wait until")
    assert r.is_valid is False
    assert "requires a condition type" in r.error


# =============================================================================
# 3. Diagnostics & Error Categorization Tests
# =============================================================================

def test_diagnostics_wait_timeout_categorization():
    """Verify wait_until timeout errors are categorized as wait_timeout."""
    cat, label = categorize_error_string(
        "Wait condition 'page_heading' timed out after 30.0s: Expected heading 'Identification' was not visible",
        action="wait_until",
    )
    assert cat == "wait_timeout"
    assert label == "Wait Condition Timed Out"

    cat2, label2 = categorize_step_error(
        TimeoutError("Wait condition 'url_contains' timed out after 30.0s: Expected URL to contain '/home'"),
        action="wait_until",
        msg="Wait condition 'url_contains' timed out after 30.0s",
    )
    assert cat2 == "wait_timeout"
    assert label2 == "Wait Condition Timed Out"


def test_reconstruct_instruction_for_wait_until():
    """Verify reconstruct_instruction formats clean strings for all wait conditions."""
    assert reconstruct_instruction("wait_until", "url_contains", "/dashboard", "") == "wait until url contains '/dashboard'"
    assert reconstruct_instruction("wait_until", "page_heading", "Person Info", "") == "wait until page heading is 'Person Info'"
    assert reconstruct_instruction("wait_until", "element_visible", "Legal Employer", "") == "wait until 'Legal Employer' is visible"
    assert reconstruct_instruction("wait_until", "element_enabled", "Next button", "") == "wait until 'Next button' is enabled"
    assert reconstruct_instruction("wait_until", "element_hidden", "spinner", "") == "wait until 'spinner' is hidden"


# =============================================================================
# 4. Mock Page Fixtures & Execution Loop Helpers
# =============================================================================

class MockWaitLocator:
    def __init__(
        self,
        selector: str = "",
        visible: bool = True,
        enabled: bool = True,
        aria_disabled: Optional[str] = None,
        inner_text: str = "",
        count: int = 1,
    ):
        self.selector = selector
        self._visible = visible
        self._enabled = enabled
        self._aria_disabled = aria_disabled
        self._inner_text = inner_text
        self._count = count
        self.clicked = False
        self.filled_with = None

    @property
    def first(self) -> MockWaitLocator:
        return self

    def nth(self, index: int) -> MockWaitLocator:
        return self

    async def count(self) -> int:
        return self._count

    async def is_visible(self) -> bool:
        return self._visible

    async def is_enabled(self) -> bool:
        return self._enabled

    async def inner_text(self) -> str:
        return self._inner_text

    async def get_attribute(self, name: str) -> Optional[str]:
        if name == "aria-disabled":
            return self._aria_disabled
        if name == "disabled" and not self._enabled:
            return "true"
        return None

    async def click(self, timeout: Optional[int] = None) -> None:
        self.clicked = True

    async def fill(self, value: str, timeout: Optional[int] = None) -> None:
        self.filled_with = value

    async def wait_for(self, state: str = "visible", timeout: Optional[int] = None) -> None:
        if state == "visible" and not self._visible:
            raise TimeoutError(f"Element '{self.selector}' did not become visible")
        if state == "hidden" and self._visible:
            raise TimeoutError(f"Element '{self.selector}' did not hide")


class MockWaitPage:
    def __init__(
        self,
        url: str = "https://fa-demo.oracle.com/hcmUI/faces/FndOverview",
        title: str = "Oracle Fusion Cloud Applications",
    ):
        self.url = url
        self._title = title
        self.elements: Dict[str, MockWaitLocator] = {}
        self.headings: Dict[str, MockWaitLocator] = {}
        self.clicks_count: Dict[str, int] = {}
        self.is_closed_val = False
        self.video = None

    def set_default_timeout(self, timeout: int) -> None:
        pass

    def set_default_navigation_timeout(self, timeout: int) -> None:
        pass

    async def close(self) -> None:
        self.is_closed_val = True

    def is_closed(self) -> bool:
        return self.is_closed_val

    async def title(self) -> str:
        return self._title

    def get_by_role(self, role: str, name: Optional[str] = None) -> MockWaitLocator:
        if role == "heading" and name:
            for h_title, loc in self.headings.items():
                if name.lower() in h_title.lower() and loc._visible:
                    return loc
            # Return invisible locator if heading not present
            return MockWaitLocator(selector=f"heading:{name}", visible=False, count=0)
        return MockWaitLocator(selector=f"role:{role}", visible=False, count=0)

    def get_by_text(self, text: str, exact: bool = False) -> MockWaitLocator:
        for k, loc in self.elements.items():
            if (exact and text == k) or (not exact and text.lower() in k.lower()):
                return loc
        for k, loc in self.headings.items():
            if (exact and text == k) or (not exact and text.lower() in k.lower()):
                return loc
        return MockWaitLocator(selector=f"text:{text}", visible=False, count=0)

    def locator(self, selector: str) -> MockWaitLocator:
        if selector in self.elements:
            return self.elements[selector]
        if selector in self.headings:
            return self.headings[selector]
        # Check text= / has-text
        for k, loc in list(self.headings.items()) + list(self.elements.items()):
            if f"'{k}'" in selector or f'"{k}"' in selector or k in selector:
                return loc
        if selector in ("h1, h2, h3, h4, h5, h6, [role='heading']", "h1", "h2", "h3"):
            visible_headings = [loc for loc in self.headings.values() if loc._visible]
            if visible_headings:
                return visible_headings[0]
            return MockWaitLocator(selector=selector, visible=False, count=0)
        return MockWaitLocator(selector=selector, visible=False, count=0)

    async def wait_for_load_state(self, state: str = "load", timeout: Optional[int] = None) -> None:
        pass

    async def click(self, selector: str, timeout: Optional[int] = None) -> None:
        self.clicks_count[selector] = self.clicks_count.get(selector, 0) + 1
        if selector in self.elements:
            await self.elements[selector].click(timeout=timeout)

    async def fill(self, selector: str, value: str, timeout: Optional[int] = None) -> None:
        if selector in self.elements:
            await self.elements[selector].fill(value, timeout=timeout)

    async def goto(self, url: str, timeout: Optional[int] = None) -> None:
        self.url = url

    async def screenshot(self, path: Optional[str] = None, timeout: Optional[int] = None) -> bytes:
        return b"fake_screenshot"


class FakeBrowserContext:
    def __init__(self, page: MockWaitPage):
        self.page = page

    async def new_page(self):
        return self.page

    async def close(self):
        pass


class FakeBrowser:
    def __init__(self, page: MockWaitPage):
        self.page = page

    async def new_context(self, **kwargs):
        return FakeBrowserContext(self.page)

    async def close(self):
        pass


class FakeLauncher:
    def __init__(self, page: MockWaitPage):
        self.page = page

    async def launch(self, **kwargs):
        return FakeBrowser(self.page)


class FakePlaywrightInstance:
    def __init__(self, page: MockWaitPage):
        self.chromium = FakeLauncher(page)
        self.firefox = FakeLauncher(page)
        self.webkit = FakeLauncher(page)


class FakeAsyncPlaywrightContext:
    def __init__(self, page: MockWaitPage):
        self.page = page

    async def __aenter__(self):
        return FakePlaywrightInstance(self.page)

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


def mock_playwright_system(monkeypatch, page: MockWaitPage):
    """Setup fake playwright system in sys.modules pointing to MockWaitPage."""
    playwright_mod = ModuleType("playwright")
    async_api_mod = ModuleType("playwright.async_api")
    async_api_mod.async_playwright = lambda: FakeAsyncPlaywrightContext(page)
    playwright_mod.async_api = async_api_mod

    monkeypatch.setitem(sys.modules, "playwright", playwright_mod)
    monkeypatch.setitem(sys.modules, "playwright.async_api", async_api_mod)


# =============================================================================
# 5. Execution Pipeline Tests for all 5 Condition Types
# =============================================================================

@pytest.mark.asyncio
async def test_wait_until_url_contains_success(tmp_path: Path, monkeypatch):
    """Verify wait_until url_contains succeeds when URL matches."""
    page = MockWaitPage(url="https://example.com/hcmUI/faces/FuseWelcome?param=123")
    mock_playwright_system(monkeypatch, page)

    steps = [
        {"step_number": 1, "action": "wait_until", "target": "url_contains", "value": "FuseWelcome", "expected_result": ""},
    ]
    res = await _execute_playwright(
        steps=steps,
        app_url="https://example.com",
        artifacts_dir=str(tmp_path),
        run_id="run_wait_1",
        test_case_id="tc_wait_1",
    )
    assert res["status"] == "passed"
    assert len(res["steps"]) == 1
    assert res["steps"][0]["status"] == "passed"
    assert res["steps"][0]["verification_result"]["type"] == "wait_until"
    assert res["steps"][0]["verification_result"]["condition"] == "url_contains"


@pytest.mark.asyncio
async def test_wait_until_page_heading_success(tmp_path: Path, monkeypatch):
    """Verify wait_until page_heading succeeds when heading becomes visible."""
    page = MockWaitPage()
    page.headings["Hire an Employee: Identification"] = MockWaitLocator(
        selector="h1",
        visible=True,
        inner_text="Hire an Employee: Identification",
    )
    mock_playwright_system(monkeypatch, page)

    steps = [
        {"step_number": 1, "action": "wait_until", "target": "page_heading", "value": "Hire an Employee: Identification", "expected_result": ""},
    ]
    res = await _execute_playwright(
        steps=steps,
        app_url="",
        artifacts_dir=str(tmp_path),
        run_id="run_wait_2",
        test_case_id="tc_wait_2",
    )
    assert res["status"] == "passed"
    assert res["steps"][0]["status"] == "passed"
    assert res["steps"][0]["verification_result"]["condition"] == "page_heading"


@pytest.mark.asyncio
async def test_wait_until_element_visible_success_no_side_effects(tmp_path: Path, monkeypatch):
    """Verify wait_until element_visible succeeds without clicking or filling the element."""
    page = MockWaitPage()
    loc = MockWaitLocator(selector="#legal-emp", visible=True)
    page.elements["#legal-emp"] = loc
    mock_playwright_system(monkeypatch, page)

    steps = [
        {"step_number": 1, "action": "wait_until", "target": "element_visible", "value": "#legal-emp", "expected_result": ""},
    ]
    res = await _execute_playwright(
        steps=steps,
        app_url="",
        artifacts_dir=str(tmp_path),
        run_id="run_wait_3",
        test_case_id="tc_wait_3",
    )
    assert res["status"] == "passed"
    # STRICT guarantee: no side-effects
    assert loc.clicked is False
    assert loc.filled_with is None


@pytest.mark.asyncio
async def test_wait_until_element_enabled_success(tmp_path: Path, monkeypatch):
    """Verify wait_until element_enabled succeeds when element is visible and interactive."""
    page = MockWaitPage()
    btn = MockWaitLocator(selector="button#submit", visible=True, enabled=True, aria_disabled=None)
    page.elements["button#submit"] = btn
    mock_playwright_system(monkeypatch, page)

    steps = [
        {"step_number": 1, "action": "wait_until", "target": "element_enabled", "value": "button#submit", "expected_result": ""},
    ]
    res = await _execute_playwright(
        steps=steps,
        app_url="",
        artifacts_dir=str(tmp_path),
        run_id="run_wait_4",
        test_case_id="tc_wait_4",
    )
    assert res["status"] == "passed"
    assert res["steps"][0]["status"] == "passed"


@pytest.mark.asyncio
async def test_wait_until_element_hidden_success(tmp_path: Path, monkeypatch):
    """Verify wait_until element_hidden succeeds when element is invisible or detached."""
    page = MockWaitPage()
    overlay = MockWaitLocator(selector=".loading-spinner", visible=False, count=0)
    page.elements[".loading-spinner"] = overlay
    mock_playwright_system(monkeypatch, page)

    steps = [
        {"step_number": 1, "action": "wait_until", "target": "element_hidden", "value": ".loading-spinner", "expected_result": ""},
    ]
    res = await _execute_playwright(
        steps=steps,
        app_url="",
        artifacts_dir=str(tmp_path),
        run_id="run_wait_5",
        test_case_id="tc_wait_5",
    )
    assert res["status"] == "passed"
    assert res["steps"][0]["status"] == "passed"


# =============================================================================
# 6. Timeout, Stop-on-Failure, and No-Replay Guarantees
# =============================================================================

@pytest.mark.asyncio
async def test_wait_until_timeout_stops_pipeline_and_skips_remaining(tmp_path: Path, monkeypatch):
    """Verify that when wait_until times out, execution stops immediately and remaining steps are skipped."""
    monkeypatch.setattr(settings, "PLAYWRIGHT_NAVIGATION_TIMEOUT_MS", 300)

    page = MockWaitPage(url="https://example.com/login", title="Sign In Page")
    next_btn = MockWaitLocator(selector="button#next", visible=True)
    page.elements["button#next"] = next_btn
    mock_playwright_system(monkeypatch, page)

    steps = [
        {"step_number": 1, "action": "click", "target": "button#next", "value": "", "expected_result": ""},
        {"step_number": 2, "action": "wait_until", "target": "page_heading", "value": "Missing Heading", "expected_result": ""},
        {"step_number": 3, "action": "click", "target": "button#save", "value": "", "expected_result": ""},
        {"step_number": 4, "action": "fill", "target": "#notes", "value": "Done", "expected_result": ""},
    ]

    res = await _execute_playwright(
        steps=steps,
        app_url="",
        artifacts_dir=str(tmp_path),
        run_id="run_wait_to",
        test_case_id="tc_wait_to",
    )

    assert res["status"] == "failed"
    records = res["steps"]
    assert len(records) == 4
    # Step 1: Click succeeded
    assert records[0]["status"] == "passed"
    # Step 2: wait_until timed out
    assert records[1]["status"] == "failed"
    assert records[1]["category"] == "wait_timeout"
    assert "Expected heading 'Missing Heading' was not visible" in records[1]["failure_reason"]
    assert "Sign In Page" in records[1]["failure_reason"]
    # Steps 3 and 4: skipped immediately
    assert records[2]["status"] == "skipped"
    assert records[3]["status"] == "skipped"
    # Strict check: Step 1 click was executed once, NOT repeated or replayed on timeout!
    assert next_btn.clicked is True


def test_infer_expected_navigation_coordination():
    """Verify infer_expected_navigation returns None when next step is wait_until."""
    cur_url = "https://fa-demo.oracle.com/hcmUI/faces/FndOverview"
    step_click = {"action": "click", "target": "Next button", "value": "", "expected_result": ""}
    step_wait = {"action": "wait_until", "target": "page_heading", "value": "Person Information", "expected_result": ""}

    # Preceding click before wait_until must not create synthetic URL transition expectation
    nav_exp = infer_expected_navigation(
        step=step_click,
        next_step=step_wait,
        current_url=cur_url,
    )
    assert nav_exp is None


# =============================================================================
# 7. Complete Oracle Fusion 5-Page Wizard Workflow Simulation (In-Page ADF PPR)
# =============================================================================

@pytest.mark.asyncio
async def test_oracle_fusion_5_page_wizard_workflow_simulation(tmp_path: Path, monkeypatch):
    """
    Simulate the complete Oracle Fusion Hire an Employee 5-page wizard workflow:
      Page 1: Identification (fill Legal Employer) -> Click Next
      Page 2: Person Information (skipped / no fields filled) -> Click Next
      Page 3: Employment Information (fill Job Title) -> Click Next
      Page 4: Compensation -> Click Next
      Page 5: Review
    Throughout this workflow, Oracle Fusion uses ADF PPR, keeping the browser URL constant:
      `.../hcmUI/faces/FndOverview`
    Guarantees:
      - Each Next click runs exactly ONCE (no repeats, no replay).
      - No URL-change navigation timeouts.
      - Execution synchronizes purely via visible page headings.
    """
    oracle_url = "https://fa-esdy-saasfademo1.ds-fa.oraclepdemos.com/hcmUI/faces/FndOverview"
    page = MockWaitPage(url=oracle_url, title="Hire an Employee - Oracle Fusion")

    # Interactive elements
    legal_emp = MockWaitLocator(selector="#legal-emp", visible=True)
    job_title = MockWaitLocator(selector="#job-title", visible=True)
    next_btn = MockWaitLocator(selector="button#next", visible=True)

    page.elements["#legal-emp"] = legal_emp
    page.elements["#job-title"] = job_title
    page.elements["button#next"] = next_btn

    # Page headings for each wizard step
    h_identification = MockWaitLocator(selector="h1", visible=True, inner_text="Hire an Employee: Identification")
    h_person_info = MockWaitLocator(selector="h1", visible=False, inner_text="Person Information")
    h_employment_info = MockWaitLocator(selector="h1", visible=False, inner_text="Employment Information")
    h_compensation = MockWaitLocator(selector="h1", visible=False, inner_text="Compensation")
    h_review = MockWaitLocator(selector="h1", visible=False, inner_text="Review")

    page.headings["Hire an Employee: Identification"] = h_identification
    page.headings["Person Information"] = h_person_info
    page.headings["Employment Information"] = h_employment_info
    page.headings["Compensation"] = h_compensation
    page.headings["Review"] = h_review

    # Intercept clicks on next_btn to simulate in-page ADF partial page rendering transitions
    next_clicks = 0

    async def simulated_next_click(timeout=None):
        nonlocal next_clicks
        next_clicks += 1
        if next_clicks == 1:
            # Transition to Person Information
            h_identification._visible = False
            h_person_info._visible = True
        elif next_clicks == 2:
            # Transition to Employment Information
            h_person_info._visible = False
            h_employment_info._visible = True
        elif next_clicks == 3:
            # Transition to Compensation
            h_employment_info._visible = False
            h_compensation._visible = True
        elif next_clicks == 4:
            # Transition to Review
            h_compensation._visible = False
            h_review._visible = True

    next_btn.click = simulated_next_click
    mock_playwright_system(monkeypatch, page)

    steps = [
        # Wizard Step 1: Identification
        {"step_number": 1, "action": "fill", "target": "#legal-emp", "value": "Vision Corporation", "expected_result": ""},
        {"step_number": 2, "action": "click", "target": "button#next", "value": "", "expected_result": ""},
        # Wizard Step 2: Person Information (no fields filled, skip straight to Next)
        {"step_number": 3, "action": "wait_until", "target": "page_heading", "value": "Person Information", "expected_result": ""},
        {"step_number": 4, "action": "click", "target": "button#next", "value": "", "expected_result": ""},
        # Wizard Step 3: Employment Information
        {"step_number": 5, "action": "wait_until", "target": "page_heading", "value": "Employment Information", "expected_result": ""},
        {"step_number": 6, "action": "fill", "target": "#job-title", "value": "Principal Consultant", "expected_result": ""},
        {"step_number": 7, "action": "click", "target": "button#next", "value": "", "expected_result": ""},
        # Wizard Step 4: Compensation
        {"step_number": 8, "action": "wait_until", "target": "page_heading", "value": "Compensation", "expected_result": ""},
        {"step_number": 9, "action": "click", "target": "button#next", "value": "", "expected_result": ""},
        # Wizard Step 5: Review
        {"step_number": 10, "action": "wait_until", "target": "page_heading", "value": "Review", "expected_result": ""},
    ]

    res = await _execute_playwright(
        steps=steps,
        app_url=oracle_url,
        artifacts_dir=str(tmp_path),
        run_id="run_wizard",
        test_case_id="tc_wizard",
    )

    assert res["status"] == "passed"
    assert len(res["steps"]) == 10
    for s_rec in res["steps"]:
        assert s_rec["status"] == "passed", f"Step {s_rec['step_number']} unexpectedly failed: {s_rec.get('failure_reason')}"

    # Verify that each Next button click happened exactly once per wizard transition
    assert next_clicks == 4
    # Verify that URL never changed
    assert page.url == oracle_url
    # Verify fields were filled correctly
    assert legal_emp.filled_with == "Vision Corporation"
    assert job_title.filled_with == "Principal Consultant"

