"""
Tests for Playwright Navigation Timing, Condition-Based Page Transitions, and Delayed Redirects.

Covers:
  1. Unit tests for `infer_expected_navigation` across all navigation criteria and non-navigating actions.
  2. Condition-based wait for delayed redirects (e.g. Oracle Identity sign-in redirect to landing page).
  3. Immediate navigation after click without artificial lag.
  4. Non-navigating in-page clicks (tabs, accordions, checkboxes) without blocking or navigation timeouts.
  5. Navigation timeout diagnostics when redirect fails to occur (e.g. invalid credentials), preventing blind step progression.
  6. Integration with saved discovery inventory across page transitions.
  7. Whitespace preservation in semantic locator resolver candidates for multi-word titles/labels.
"""
import asyncio
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, List, Optional
import sys
import pytest

from app.config import get_settings
from app.services.locator_resolver import (
    ElementNotFoundError,
    normalize_intent_target,
    resolve_locator,
)
from app.services.playwright_runner import (
    NavigationTimeoutError,
    _execute_playwright,
    categorize_step_error,
    infer_expected_navigation,
    wait_for_page_transition,
)
from tests.test_navigation_lifecycle import (
    LifecycleTrackingBrowser,
    LifecycleTrackingContext,
    LifecycleTrackingPlaywright,
)
from tests.test_playwright_runner_secrets import FakePage


class MockLocator:
    def __init__(self, selector: str = "", visible: bool = True, count: int = 1, page: Any = None):
        self.selector = selector
        self._visible = visible
        self._count = count
        self.clicked = False
        self.filled_with = None
        self.page = page

    async def count(self) -> int:
        return self._count

    async def is_visible(self) -> bool:
        return self._visible

    @property
    def first(self):
        return self

    def __call__(self):
        return self

    def nth(self, idx: int):
        return self

    async def click(self, **kwargs):
        self.clicked = True
        if self.page and hasattr(self.page, "_on_locator_click"):
            await self.page._on_locator_click(self.selector)

    async def fill(self, val: str, **kwargs):
        self.filled_with = val

    async def wait_for(self, **kwargs):
        pass


class NavigationTimingPage(FakePage):
    """
    Simulates browser page behavior with support for delayed redirects,
    element lookups, and load state tracking.
    """

    def __init__(
        self,
        initial_url: str = "https://idcs-test.identity.oraclecloud.com/ui/v1/signin",
        redirect_delay_s: float = 0.0,
        redirect_to_url: Optional[str] = None,
        page_title: str = "Cloud Sign In",
        elements: Optional[Dict[str, MockLocator]] = None,
    ):
        super().__init__(url=initial_url)
        self.page_title = page_title
        self.redirect_delay_s = redirect_delay_s
        self.redirect_to_url = redirect_to_url
        self.elements = elements or {}
        for loc in self.elements.values():
            loc.page = self
        self.events: Dict[str, List[Any]] = {}
        self.wait_load_called = False
        self._closed = False
        self.clicks: List[str] = []

    def on(self, event: str, callback: Any):
        self.events.setdefault(event, []).append(callback)

    def set_default_navigation_timeout(self, timeout: int):
        pass

    def is_closed(self) -> bool:
        return self._closed

    async def title(self) -> str:
        return self.page_title

    async def wait_for_load_state(self, state: str, timeout: int = 5000):
        self.wait_load_called = True

    async def _on_locator_click(self, selector: str):
        self.clicks.append(selector)
        if self.redirect_to_url:
            if self.redirect_delay_s > 0:
                async def _delayed():
                    await asyncio.sleep(self.redirect_delay_s)
                    self.url = self.redirect_to_url
                    self.page_title = "Welcome"
                asyncio.create_task(_delayed())
            else:
                self.url = self.redirect_to_url
                self.page_title = "Welcome"

    def locator(self, selector: str) -> Any:
        if self.elements:
            # 1. Exact match
            for key, loc in self.elements.items():
                if key.lower() == selector.lower():
                    loc.page = self
                    return loc

            # 2. Match longest keys first, avoiding cross-matching form headings with task links
            for key, loc in sorted(self.elements.items(), key=lambda item: len(item[0]), reverse=True):
                if "identification" in selector.lower() and "identification" not in key.lower():
                    continue
                if "legal employer" in selector.lower() and "legal employer" not in key.lower():
                    continue
                if key.lower() in selector.lower() or selector.lower() in key.lower():
                    loc.page = self
                    return loc
            return MockLocator(selector=selector, visible=False, count=0, page=self)
        return MockLocator(selector=selector, visible=True, count=1, page=self)

    def get_by_role(self, role: str, name: str = "", exact: bool = False) -> Any:
        target_name = (name or "").lower()
        for key, loc in self.elements.items():
            if target_name and (target_name in key.lower() or key.lower() in target_name):
                loc.page = self
                return loc
        return MockLocator(selector=f"role={role}[name='{name}']", visible=True, count=1, page=self)

    def get_by_label(self, label: str, exact: bool = False) -> Any:
        return self.get_by_role("any", name=label)

    def get_by_text(self, text: str, exact: bool = False) -> Any:
        return self.get_by_role("text", name=text)

    async def click(self, target: str, **kwargs):
        await self._on_locator_click(target)


def _patch_playwright(monkeypatch, page: NavigationTimingPage):
    pw = LifecycleTrackingPlaywright(page)
    playwright_module = ModuleType("playwright")
    async_api_module = ModuleType("playwright.async_api")
    async_api_module.async_playwright = lambda: pw
    playwright_module.async_api = async_api_module
    monkeypatch.setitem(sys.modules, "playwright", playwright_module)
    monkeypatch.setitem(sys.modules, "playwright.async_api", async_api_module)


# ---------------------------------------------------------------------------
# Test 1: Unit tests for infer_expected_navigation
# ---------------------------------------------------------------------------

def test_infer_expected_navigation_criteria():
    """Verify all 5 navigation inference criteria and non-navigating checks."""
    # Condition 1: Explicit URL or path in current step
    step_url = {"action": "click", "target": "Login", "value": "https://app.example.com/home"}
    inf1 = infer_expected_navigation(step_url, None, "https://example.com/login")
    assert inf1 is not None
    assert inf1["type"] == "explicit_url"
    assert inf1["expected_pattern"] == "https://app.example.com/home"

    step_path = {"action": "click", "target": "Go", "value": "/dashboard"}
    inf1b = infer_expected_navigation(step_path, None, "https://example.com/login")
    assert inf1b is not None
    assert inf1b["type"] == "explicit_path"
    assert inf1b["expected_pattern"] == "/dashboard"

    step_redirect_txt = {"action": "click", "target": "Submit", "expected_result": "redirects to /welcome"}
    inf1c = infer_expected_navigation(step_redirect_txt, None, "https://example.com/login")
    assert inf1c is not None
    assert inf1c["type"] == "explicit_redirect"
    assert inf1c["expected_pattern"] == "/welcome"

    # Condition 2: Next step is verify_url
    step_btn = {"action": "click", "target": "Submit"}
    next_v_url = {"action": "verify_url", "value": "https://app.example.com/home"}
    inf2 = infer_expected_navigation(step_btn, next_v_url, "https://example.com/login")
    assert inf2 is not None
    assert inf2["type"] == "verify_url_target"
    assert inf2["expected_pattern"] == "https://app.example.com/home"

    # Condition 3: Next step expects landing page transition
    next_landing = {"action": "click", "target": "Oracle Logo Home link", "expected_result": "eAppSys landing page is opened"}
    inf3 = infer_expected_navigation(
        {"action": "click", "target": "Next"},
        next_landing,
        "https://idcs-test.identity.oraclecloud.com/ui/v1/signin",
        app_url="https://fa-demo.oraclecloud.com/fscmUI/faces/AtkHomePageWelcome",
    )
    assert inf3 is not None
    assert inf3["type"] == "landing_page_transition"

    # Condition 4: Next step target exists in saved inventory on a different URL
    saved_inv = [
        {
            "page_url": "https://fa-demo.oraclecloud.com/fscmUI/faces/AtkHomePageWelcome",
            "inventory_data": {
                "elements": [
                    {
                        "element_id": "pt1:_UIScil1u",
                        "accessible_name": "Oracle Logo Home",
                        "suggested_intent": "Oracle Logo Home link",
                        "candidate_locators": ["#pt1:_UIScil1u"],
                    }
                ]
            },
        }
    ]
    next_step_inv = {"action": "click", "target": "Oracle Logo Home link"}
    inf4 = infer_expected_navigation(
        {"action": "click", "target": "Next"},
        next_step_inv,
        "https://idcs-test.identity.oraclecloud.com/ui/v1/signin",
        saved_inventory=saved_inv,
    )
    assert inf4 is not None
    assert inf4["type"] == "saved_inventory_target"

    # Condition 5: Progression/Submit button on an authentication or identity page
    inf5 = infer_expected_navigation(
        {"action": "click", "target": "Next"},
        {"action": "click", "target": "Header icon"},
        "https://idcs-test.identity.oraclecloud.com/ui/v1/signin",
    )
    assert inf5 is not None
    assert inf5["type"] == "auth_progression"

    # Non-navigating actions return None
    assert infer_expected_navigation({"action": "click", "target": "button[data-otel-label='LAST_WEEK']"}, None, "https://app.example.com/timesheet") is None
    assert infer_expected_navigation({"action": "click", "target": "input.project-select"}, None, "https://app.example.com/timesheet") is None
    assert infer_expected_navigation({"action": "click", "target": "Tab 2"}, None, "https://app.example.com/dashboard") is None
    assert infer_expected_navigation({"action": "fill", "target": "Username", "value": "test"}, None, "https://example.com") is None


# ---------------------------------------------------------------------------
# Test 2: Delayed Redirect Execution Flow (Step 5 Next -> Delayed Redirect -> Step 6 Oracle Logo Home link)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delayed_redirect_navigates_and_resolves_landing_element(monkeypatch, tmp_path):
    """
    Test the exact Oracle IDCS scenario:
      Step 5: click 'Next' on identity sign-in page.
      Page takes 150ms to redirect from identity sign-in to Oracle Fusion landing page.
      Runner waits condition-based for the redirect to finish.
      Step 6: click 'Oracle Logo Home link' resolves successfully on the new page.
    """
    landing_url = "https://fa-demo.oraclecloud.com/fscmUI/faces/AtkHomePageWelcome"
    oracle_logo = MockLocator(selector="#pt1:_UIScil1u", visible=True, count=1)
    next_btn = MockLocator(selector="button:has-text('Next')", visible=True, count=1)

    elements = {
        "Next": next_btn,
        "next": next_btn,
        "Oracle Logo Home": oracle_logo,
        "Oracle Logo Home link": oracle_logo,
        "#pt1:_UIScil1u": oracle_logo,
    }

    page = NavigationTimingPage(
        initial_url="https://idcs-test.identity.oraclecloud.com/ui/v1/signin",
        redirect_delay_s=0.15,
        redirect_to_url=landing_url,
        page_title="Cloud Sign In",
        elements=elements,
    )
    _patch_playwright(monkeypatch, page)

    steps = [
        {
            "step_number": 5,
            "action": "click",
            "target": "Next",
            "value": "",
            "expected_result": "Next button is clicked",
        },
        {
            "step_number": 6,
            "action": "click",
            "target": "Oracle Logo Home link",
            "value": "",
            "expected_result": "eAppSys landing page is opened",
        },
    ]

    result = await _execute_playwright(
        steps=steps,
        app_url=landing_url,
        artifacts_dir=str(tmp_path),
        run_id="run_delayed_redirect",
        test_case_id="tc_delayed_redirect",
    )

    assert result["status"] == "passed", f"Execution failed: {result.get('error_message')}"
    log_text = "\n".join(result["log_lines"])
    assert "Waiting for page transition" in log_text
    assert "Navigation transition completed: https://fa-demo.oraclecloud.com/fscmUI/faces/AtkHomePageWelcome" in log_text
    assert "Click action completed for 'Oracle Logo Home link'" in log_text
    assert oracle_logo.clicked is True


# ---------------------------------------------------------------------------
# Test 3: Standard Immediate Navigation (No lag, completes instantly)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_immediate_navigation_completes_without_delay(monkeypatch, tmp_path):
    """Verify that an immediate URL change transitions instantly without waiting."""
    page = NavigationTimingPage(
        initial_url="https://example.com/login",
        redirect_delay_s=0.0,
        redirect_to_url="https://example.com/dashboard",
        page_title="Dashboard",
    )
    _patch_playwright(monkeypatch, page)

    steps = [
        {
            "step_number": 1,
            "action": "click",
            "target": "Sign In",
            "value": "",
            "expected_result": "navigates to https://example.com/dashboard",
        }
    ]

    start = asyncio.get_event_loop().time()
    result = await _execute_playwright(
        steps=steps,
        app_url="https://example.com/dashboard",
        artifacts_dir=str(tmp_path),
        run_id="run_immediate_nav",
        test_case_id="tc_immediate_nav",
    )
    elapsed = asyncio.get_event_loop().time() - start

    assert result["status"] == "passed"
    assert elapsed < 1.0  # Should be very fast (< 1s)
    log_text = "\n".join(result["log_lines"])
    assert "Navigation transition completed: https://example.com/dashboard" in log_text


# ---------------------------------------------------------------------------
# Test 4: Non-Navigating Clicks (Tabs, accordions, checkboxes)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_non_navigating_clicks_do_not_wait_or_timeout(monkeypatch, tmp_path):
    """
    Verify that in-page actions (e.g. Last Week, This Week, project dropdown)
    do not trigger navigation waits or timeouts.
    """
    page = NavigationTimingPage(
        initial_url="https://oracleapex.com/ords/r/task1/time-log-2",
        redirect_delay_s=0.0,
        redirect_to_url=None,  # No redirect
        page_title="Time Log 2",
    )
    _patch_playwright(monkeypatch, page)

    steps = [
        {
            "step_number": 1,
            "action": "click",
            "target": "button[data-otel-label='LAST_WEEK']",
            "value": "",
            "expected_result": "Last week timesheet is displayed",
        },
        {
            "step_number": 2,
            "action": "click",
            "target": "button[data-otel-label='THIS_WEEK']",
            "value": "",
            "expected_result": "Current week timesheet is displayed",
        },
    ]

    start = asyncio.get_event_loop().time()
    result = await _execute_playwright(
        steps=steps,
        app_url="https://oracleapex.com/ords/r/task1/time-log-2",
        artifacts_dir=str(tmp_path),
        run_id="run_non_navigating",
        test_case_id="tc_non_navigating",
    )
    elapsed = asyncio.get_event_loop().time() - start

    assert result["status"] == "passed"
    assert elapsed < 1.5
    log_text = "\n".join(result["log_lines"])
    assert "Waiting for page transition" not in log_text
    assert "Click action completed for 'button[data-otel-label='LAST_WEEK']'" in log_text
    assert "Click action completed for 'button[data-otel-label='THIS_WEEK']'" in log_text


# ---------------------------------------------------------------------------
# Test 5: Redirect Timeout Diagnostics (When credentials or submit fails)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_redirect_timeout_aborts_with_clear_diagnostics(monkeypatch, tmp_path):
    """
    Verify that if a click on an auth page fails to navigate (e.g. invalid credentials),
    the runner raises NavigationTimeoutError, categorizes as navigation_timeout,
    provides clear diagnostic URL logs, and stops without executing subsequent landing steps.
    """
    from app.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "PLAYWRIGHT_NAVIGATION_TIMEOUT_MS", 300)  # 300ms timeout for fast testing

    next_btn = MockLocator(selector="button:has-text('Next')", visible=True, count=1)
    page = NavigationTimingPage(
        initial_url="https://idcs-test.identity.oraclecloud.com/ui/v1/signin",
        redirect_delay_s=0.0,
        redirect_to_url=None,  # Never redirects (e.g. login failed)
        page_title="Cloud Sign In",
        elements={"Next": next_btn},
    )
    _patch_playwright(monkeypatch, page)

    steps = [
        {
            "step_number": 5,
            "action": "click",
            "target": "Next",
            "value": "",
            "expected_result": "Next button is clicked",
        },
        {
            "step_number": 6,
            "action": "click",
            "target": "Oracle Logo Home link",
            "value": "",
            "expected_result": "eAppSys landing page is opened",
        },
    ]

    result = await _execute_playwright(
        steps=steps,
        app_url="https://fa-demo.oraclecloud.com/fscmUI/faces/AtkHomePageWelcome",
        artifacts_dir=str(tmp_path),
        run_id="run_redirect_timeout",
        test_case_id="tc_redirect_timeout",
    )

    assert result["status"] == "failed"
    err_msg = result.get("error_message", "")
    assert "Navigation timed out" in err_msg
    assert "Expected redirect away from 'https://idcs-test.identity.oraclecloud.com/ui/v1/signin'" in err_msg
    assert "browser remained at 'https://idcs-test.identity.oraclecloud.com/ui/v1/signin'" in err_msg
    assert "Cloud Sign In" in err_msg

    # Step 6 must NOT have been executed
    log_text = "\n".join(result["log_lines"])
    assert "Step 6" not in log_text
    assert "FAILED at Step 5" in log_text

    # Category must be navigation_timeout
    cat, label = categorize_step_error(NavigationTimeoutError(err_msg), "click", err_msg)
    assert cat == "navigation_timeout"
    assert label == "Navigation Timeout"


# ---------------------------------------------------------------------------
# Test 6: Semantic Locator Resolver Whitespace Preservation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resolver_preserves_spaces_in_logo_attributes():
    """
    Verify that normalize_intent_target and resolve_locator retain phrase whitespace
    so that selectors like a[title*='Oracle Logo Home' i] match correctly.
    """
    core, intent, variants = normalize_intent_target("Oracle Logo Home link")
    assert core == "Oracle Logo Home"
    assert intent == "link"

    # Verify that a locator with title="Oracle Logo Home" is matched
    matched_locators: List[str] = []

    class FakeResolverPage:
        def locator(self, sel: str):
            matched_locators.append(sel)
            if "Oracle Logo Home" in sel:
                return MockLocator(selector=sel, visible=True, count=1)
            return MockLocator(selector=sel, visible=False, count=0)

    p = FakeResolverPage()
    loc = await resolve_locator(p, "Oracle Logo Home link", action="click", timeout_ms=50)
    assert loc is not None
    # Ensure one of the tested locators preserved the space in 'Oracle Logo Home'
    assert any("Oracle Logo Home" in s for s in matched_locators), f"No spaced locator tested: {matched_locators}"


# ---------------------------------------------------------------------------
# Test 7: Intermediate New Person Task Page Auto-Navigation to Creation Form
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_intermediate_new_person_task_page_auto_navigates_to_creation_form(monkeypatch, tmp_path):
    """
    Verify that if the browser lands on the intermediate New Person task page,
    attempting to interact with an employee creation field (Legal Employer)
    automatically detects the intermediate task page, clicks 'Hire an Employee',
    waits for the 'Hire an Employee: Identification' form, and resolves Legal Employer.
    """
    new_person_url = "https://fa-demo.oraclecloud.com/hcmUI/faces/FndOverview?fndGlobalItemNodeId=itemNode_workforce_management_new_person"
    creation_url = "https://fa-demo.oraclecloud.com/hcmUI/faces/FndOverview?task=hire_an_employee"

    legal_employer_input = MockLocator(
        selector="#_FOpt1:_FOr1:0:_FONSr2:0:MAnt2:1:pt1:pt_r1:0:SP1:selectOneChoice3::content",
        visible=False,
        count=1,
    )
    hire_employee_task_link = MockLocator(
        selector="#_FOpt1:_FOr1:0:_FONSr2:0:_FOTsr1:0:cl01Upl:UPsp1:cl01Pce:cl01Lv:1:cl01Pse:cl01Cl",
        visible=True,
        count=1,
    )
    heading_new_person = MockLocator(selector="h1:has-text('New Person')", visible=True, count=1)
    heading_identification = MockLocator(selector="h1:has-text('Hire an Employee: Identification')", visible=False, count=0)

    class NewPersonFlowPage(NavigationTimingPage):
        async def _on_locator_click(self, selector: str):
            await super()._on_locator_click(selector)
            if "Hire an Employee" in selector or "cl01Pse:cl01Cl" in selector:
                # Transition to employee creation form
                self.url = creation_url
                self.page_title = "Hire an Employee - New Person - Oracle Fusion Cloud Applications"
                heading_new_person._visible = False
                heading_new_person._count = 0
                heading_identification._visible = True
                heading_identification._count = 1
                legal_employer_input._visible = True

    page = NewPersonFlowPage(
        initial_url=new_person_url,
        redirect_delay_s=0.0,
        page_title="New Person - Oracle Fusion Cloud Applications",
        elements={
            "New Person": heading_new_person,
            "Hire an Employee": hire_employee_task_link,
            "Legal Employer": legal_employer_input,
            "Hire an Employee: Identification": heading_identification,
        },
    )
    _patch_playwright(monkeypatch, page)

    steps = [
        {
            "step_number": 10,
            "action": "fill",
            "target": "Legal Employer field",
            "value": "ABS India Legal Employer 01",
            "expected_result": "Legal Employer is filled",
        }
    ]

    result = await _execute_playwright(
        steps=steps,
        app_url=new_person_url,
        artifacts_dir=str(tmp_path),
        run_id="run_new_person_auto_nav",
        test_case_id="tc_new_person_auto_nav",
    )

    assert result["status"] == "passed", f"Execution failed: {result.get('error_message')}"
    log_text = "\n".join(result["log_lines"])
    assert "Detected intermediate Oracle Fusion New Person task page" in log_text
    assert "Advancing to employee creation form by clicking 'Hire an Employee' task link" in log_text
    assert "Employee creation form confirmed ready" in log_text
    assert "Filled 'Legal Employer field'" in log_text
    assert legal_employer_input.filled_with == "ABS India Legal Employer 01"


# ---------------------------------------------------------------------------
# Test 8: Two-Step Navigation Workflow (FuseWelcome -> New Person -> Creation Form)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_two_step_navigation_workflow_fusewelcome_to_new_person_to_creation_form(monkeypatch, tmp_path):
    """
    Verify the two-step workflow:
      Step 8: Click 'New Person link' on FuseWelcome -> opens New Person task page.
      Step 9: Click 'Hire an Employee link' on New Person page -> opens creation form.
      Step 10: Fill 'Legal Employer field' on creation form.
    """
    fuse_url = "https://fa-demo.oraclecloud.com/fscmUI/faces/FuseWelcome"
    new_person_url = "https://fa-demo.oraclecloud.com/hcmUI/faces/FndOverview?fndGlobalItemNodeId=itemNode_workforce_management_new_person"
    creation_url = "https://fa-demo.oraclecloud.com/hcmUI/faces/FndOverview?task=hire_an_employee"

    new_person_springboard_link = MockLocator(selector="a:has-text('New Person')", visible=True, count=1)
    hire_employee_task_link = MockLocator(selector="a:has-text('Hire an Employee')", visible=True, count=1)
    legal_employer_input = MockLocator(selector="role=combobox[name='Legal Employer']", visible=False, count=1)
    heading_identification = MockLocator(selector="h1:has-text('Hire an Employee: Identification')", visible=False, count=0)

    class TwoStepFlowPage(NavigationTimingPage):
        async def _on_locator_click(self, selector: str):
            await super()._on_locator_click(selector)
            if "New Person" in selector:
                self.url = new_person_url
                self.page_title = "New Person - Oracle Fusion Cloud Applications"
            elif "Hire an Employee" in selector:
                self.url = creation_url
                self.page_title = "Hire an Employee - New Person - Oracle Fusion Cloud Applications"
                heading_identification._visible = True
                heading_identification._count = 1
                legal_employer_input._visible = True

    page = TwoStepFlowPage(
        initial_url=fuse_url,
        page_title="Oracle Fusion Cloud Applications",
        elements={
            "New Person link": new_person_springboard_link,
            "New Person": new_person_springboard_link,
            "Hire an Employee link": hire_employee_task_link,
            "Hire an Employee": hire_employee_task_link,
            "Legal Employer field": legal_employer_input,
            "Legal Employer": legal_employer_input,
            "Hire an Employee: Identification": heading_identification,
        },
    )
    _patch_playwright(monkeypatch, page)

    steps = [
        {
            "step_number": 8,
            "action": "click",
            "target": "New Person link",
            "value": "",
            "expected_result": "New Person task page is opened",
        },
        {
            "step_number": 9,
            "action": "click",
            "target": "Hire an Employee link",
            "value": "",
            "expected_result": "Hire an Employee creation form is opened",
        },
        {
            "step_number": 10,
            "action": "fill",
            "target": "Legal Employer field",
            "value": "ABS India Legal Employer 01",
            "expected_result": "",
        },
    ]

    result = await _execute_playwright(
        steps=steps,
        app_url=fuse_url,
        artifacts_dir=str(tmp_path),
        run_id="run_two_step_nav",
        test_case_id="tc_two_step_nav",
    )

    assert result["status"] == "passed", f"Execution failed: {result.get('error_message')}"
    log_text = "\n".join(result["log_lines"])
    assert "Click action completed for 'New Person link'" in log_text
    assert "Click action completed for 'Hire an Employee link'" in log_text
    assert "Filled 'Legal Employer field'" in log_text
    assert legal_employer_input.filled_with == "ABS India Legal Employer 01"


# ---------------------------------------------------------------------------
# Test 9: Legal Employer Combobox Role and Label Resolution
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_legal_employer_combobox_locator_resolution():
    """
    Verify that resolve_locator finds an ADF combobox input element
    (tag='input', role='combobox', aria-label='Legal Employer')
    when target is 'Legal Employer field' or 'Legal Employer'.
    """
    combobox_loc = MockLocator(selector="input[role='combobox'][aria-label='Legal Employer']", visible=True, count=1)
    searched_roles = []

    class FakeComboboxPage:
        def get_by_role(self, role: str, name: str = "", exact: bool = False):
            searched_roles.append((role, name))
            if role == "combobox" and "Legal Employer" in name:
                return combobox_loc
            return MockLocator(selector="none", visible=False, count=0)

        def get_by_label(self, label: str, exact: bool = False):
            if "Legal Employer" in label:
                return combobox_loc
            return MockLocator(selector="none", visible=False, count=0)

        def get_by_placeholder(self, *args, **kwargs):
            return MockLocator(selector="none", visible=False, count=0)

        def locator(self, sel: str):
            if "Legal Employer" in sel:
                return combobox_loc
            return MockLocator(selector="none", visible=False, count=0)

    page = FakeComboboxPage()
    loc = await resolve_locator(page, "Legal Employer field", action="fill", timeout_ms=50)
    assert loc is not None
    assert any(role == "combobox" for role, _ in searched_roles)


# ---------------------------------------------------------------------------
# Test 10: Form Readiness Polling Waits for Heading Before Fill
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_form_readiness_waits_for_identification_heading_before_fill(monkeypatch, tmp_path):
    """
    Verify that if the employee creation form takes 200ms to render its headings,
    ensure_hire_employee_form_ready condition-based polls and does not fail prematurely.
    """
    creation_url = "https://fa-demo.oraclecloud.com/hcmUI/faces/FndOverview?task=hire_an_employee"
    heading = MockLocator(selector="h1:has-text('Hire an Employee: Identification')", visible=False, count=0)
    legal_emp = MockLocator(selector="role=combobox[name='Legal Employer']", visible=False, count=1)

    async def _delayed_render():
        await asyncio.sleep(0.15)
        heading._visible = True
        heading._count = 1
        legal_emp._visible = True

    page = NavigationTimingPage(
        initial_url=creation_url,
        page_title="Hire an Employee - New Person - Oracle Fusion Cloud Applications",
        elements={
            "Hire an Employee: Identification": heading,
            "Legal Employer": legal_emp,
        },
    )
    _patch_playwright(monkeypatch, page)

    # Trigger async form render
    asyncio.create_task(_delayed_render())

    steps = [
        {
            "step_number": 1,
            "action": "fill",
            "target": "Legal Employer",
            "value": "ABS India Legal Employer 01",
            "expected_result": "Legal Employer is filled",
        }
    ]

    result = await _execute_playwright(
        steps=steps,
        app_url=creation_url,
        artifacts_dir=str(tmp_path),
        run_id="run_form_readiness",
        test_case_id="tc_form_readiness",
    )

    assert result["status"] == "passed"
    log_text = "\n".join(result["log_lines"])
    assert "Employee creation form confirmed ready" in log_text
    assert "Filled 'Legal Employer'" in log_text
    assert legal_emp.filled_with == "ABS India Legal Employer 01"


# ---------------------------------------------------------------------------
# Test 11: In-Page Content Transition with Identical URL (FndOverview PPR)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_click_changes_page_content_while_url_remains_unchanged(monkeypatch, tmp_path):
    """
    Verify that when clicking 'Hire an Employee link' on the New Person overview page,
    the transition succeeds via in-page content confirmation (form heading and Legal Employer)
    even when the browser URL remains identical (Oracle ADF partial-page update).
    """
    fnd_url = "https://fa-demo.oraclecloud.com/hcmUI/faces/FndOverview?fndGlobalItemNodeId=itemNode_workforce_management_new_person"

    task_link = MockLocator(selector="a:has-text('Hire an Employee')", visible=True, count=1)
    heading_id = MockLocator(selector="h1:has-text('Hire an Employee: Identification')", visible=False, count=0)
    legal_emp = MockLocator(selector="role=combobox[name='Legal Employer']", visible=False, count=1)

    class InPageTransitionPage(NavigationTimingPage):
        async def _on_locator_click(self, selector: str):
            await super()._on_locator_click(selector)
            if "Hire an Employee" in selector:
                # Oracle ADF partial-page rendering: URL does NOT change
                assert self.url == fnd_url
                self.page_title = "Hire an Employee - New Person - Oracle Fusion Cloud Applications"
                heading_id._visible = True
                heading_id._count = 1
                legal_emp._visible = True

    page = InPageTransitionPage(
        initial_url=fnd_url,
        page_title="New Person - Oracle Fusion Cloud Applications",
        elements={
            "Hire an Employee link": task_link,
            "Hire an Employee": task_link,
            "Hire an Employee: Identification": heading_id,
            "Legal Employer field": legal_emp,
            "Legal Employer": legal_emp,
        },
    )
    _patch_playwright(monkeypatch, page)

    steps = [
        {
            "step_number": 9,
            "action": "click",
            "target": "Hire an Employee link",
            "value": "",
            "expected_result": "Hire an Employee creation form is opened",
        },
        {
            "step_number": 10,
            "action": "fill",
            "target": "Legal Employer field",
            "value": "ABS India Legal Employer 01",
            "expected_result": "Legal Employer is filled",
        },
    ]

    result = await _execute_playwright(
        steps=steps,
        app_url=fnd_url,
        artifacts_dir=str(tmp_path),
        run_id="run_in_page_transition",
        test_case_id="tc_in_page_transition",
    )

    assert result["status"] == "passed", f"Execution failed: {result.get('error_message')}"
    log_text = "\n".join(result["log_lines"])
    assert "In-page content transition confirmed" in log_text or "Employee creation form confirmed ready" in log_text
    assert "Click action completed for 'Hire an Employee link'" in log_text
    assert "Filled 'Legal Employer field'" in log_text
    # Verify the URL never changed away from fnd_url
    assert page.url == fnd_url
    assert legal_emp.filled_with == "ABS India Legal Employer 01"


# ---------------------------------------------------------------------------
# Test 12: New Person Task Menu Replacement by Employee Form
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_new_person_menu_transitions_to_employee_creation_form(monkeypatch, tmp_path):
    """
    Verify that the runner confirms the New Person task menu prompt
    ('What do you want to do or manage?') is dismissed and replaced by the
    employee creation form heading and Legal Employer control.
    """
    fnd_url = "https://fa-demo.oraclecloud.com/hcmUI/faces/FndOverview?fndGlobalItemNodeId=itemNode_workforce_management_new_person"

    task_link = MockLocator(selector="a:has-text('Hire an Employee')", visible=True, count=1)
    menu_prompt = MockLocator(selector="text='What do you want to do or manage?'", visible=True, count=1)
    task_list_item = MockLocator(selector="a:has-text('Add a Contingent Worker')", visible=True, count=1)
    heading_id = MockLocator(selector="h1:has-text('Hire an Employee: Identification')", visible=False, count=0)
    legal_emp = MockLocator(selector="role=combobox[name='Legal Employer']", visible=False, count=1)

    class MenuReplacementPage(NavigationTimingPage):
        async def _on_locator_click(self, selector: str):
            await super()._on_locator_click(selector)
            if "Hire an Employee" in selector:
                # Simulate ADF PPR replacing the menu
                menu_prompt._visible = False
                menu_prompt._count = 0
                task_list_item._visible = False
                task_list_item._count = 0
                heading_id._visible = True
                heading_id._count = 1
                legal_emp._visible = True

    page = MenuReplacementPage(
        initial_url=fnd_url,
        page_title="New Person - Oracle Fusion Cloud Applications",
        elements={
            "Hire an Employee link": task_link,
            "Hire an Employee": task_link,
            "What do you want to do or manage?": menu_prompt,
            "Add a Contingent Worker": task_list_item,
            "Hire an Employee: Identification": heading_id,
            "Legal Employer": legal_emp,
        },
    )
    _patch_playwright(monkeypatch, page)

    steps = [
        {
            "step_number": 1,
            "action": "click",
            "target": "Hire an Employee link",
            "value": "",
            "expected_result": "Hire an Employee creation form is opened",
        }
    ]

    result = await _execute_playwright(
        steps=steps,
        app_url=fnd_url,
        artifacts_dir=str(tmp_path),
        run_id="run_menu_replacement",
        test_case_id="tc_menu_replacement",
    )

    assert result["status"] == "passed"
    log_text = "\n".join(result["log_lines"])
    assert "In-page content transition confirmed" in log_text
    assert "New Person menu replaced" in log_text


# ---------------------------------------------------------------------------
# Test 13: Missing Form State Correctly Times Out with Diagnostics
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_missing_form_state_correctly_times_out_with_diagnostics(monkeypatch, tmp_path):
    """
    Verify that if the browser remains on FndOverview and the expected employee creation form
    never renders, wait_for_page_transition times out, raises NavigationTimeoutError with
    clear diagnostics (URL, title, expected state), and categorizes as 'navigation_timeout'.
    """
    from app.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "PLAYWRIGHT_NAVIGATION_TIMEOUT_MS", 200)

    fnd_url = "https://fa-demo.oraclecloud.com/hcmUI/faces/FndOverview?fndGlobalItemNodeId=itemNode_workforce_management_new_person"
    task_link = MockLocator(selector="a:has-text('Hire an Employee')", visible=True, count=1)

    # Note: employee form headings and controls are deliberately NEVER rendered
    page = NavigationTimingPage(
        initial_url=fnd_url,
        page_title="New Person - Oracle Fusion Cloud Applications",
        elements={
            "Hire an Employee link": task_link,
            "Hire an Employee": task_link,
        },
    )
    _patch_playwright(monkeypatch, page)

    steps = [
        {
            "step_number": 9,
            "action": "click",
            "target": "Hire an Employee link",
            "value": "",
            "expected_result": "Hire an Employee creation form is opened",
        },
        {
            "step_number": 10,
            "action": "fill",
            "target": "Legal Employer field",
            "value": "ABS India Legal Employer 01",
            "expected_result": "Legal Employer is filled",
        },
    ]

    result = await _execute_playwright(
        steps=steps,
        app_url=fnd_url,
        artifacts_dir=str(tmp_path),
        run_id="run_missing_form_timeout",
        test_case_id="tc_missing_form_timeout",
    )

    assert result["status"] == "failed"
    step_9 = result["steps"][0]
    assert step_9["status"] == "failed"
    assert step_9["category"] == "navigation_timeout"
    reason = step_9["failure_reason"]
    assert "Navigation timed out" in reason or "Page transition timed out" in reason
    assert fnd_url in reason
    assert "Employee creation form" in reason
    assert "New Person - Oracle Fusion Cloud Applications" in reason
    # Subsequent step 10 was skipped
    assert len(result["steps"]) == 2
    assert result["steps"][1]["status"] == "skipped"
