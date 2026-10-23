"""
Unit tests for Noetrix Semantic Element Resolver.

Tests direct CSS/XPath selector classification, accessibility-first candidate
resolution for click and fill actions, visible element filtering, ambiguity detection,
missing element error handling, and end-to-end integration with the Playwright runner.
"""
from __future__ import annotations

import pytest
from app.services.locator_resolver import (
    AmbiguousElementError,
    ElementNotFoundError,
    is_direct_selector,
    resolve_locator,
)
from app.services.playwright_runner import _execute_playwright


# =============================================================================
# 1. Technical Selector vs. Semantic Target Classification
# =============================================================================

@pytest.mark.parametrize(
    "target",
    [
        "#username",
        "#submit-btn",
        "#login-form",
        ".btn",
        ".btn-primary",
        ".form-control",
        "//button[@id='submit']",
        "//input[@name='email']",
        "./div/button",
        "xpath=//button",
        "css=.btn",
        "id=login-button",
        "text=Welcome",
        "role=button",
        "[name='username']",
        "[data-testid='submit-button']",
        "button[type='submit']",
        "input[type='password']",
        "a[href='/logout']",
        "form > button",
        "div + p",
        "ul ~ li",
        ":first-child",
        "button:disabled",
        "input:nth-child(2)",
        "input#email",
        "button.primary",
        "a.nav-link",
    ],
)
def test_direct_selectors_identified_correctly(target: str):
    assert is_direct_selector(target) is True


@pytest.mark.parametrize(
    "target",
    [
        "Sign In",
        "Submit",
        "Username",
        "Password",
        "Email Address",
        "Save Changes",
        "Next",
        "Previous",
        "Search products...",
        "Enter your phone number",
        "Checkout",
        "I agree to the terms and conditions",
        "Profile",
        "Log Out",
        "Delete Account",
    ],
)
def test_semantic_targets_identified_correctly(target: str):
    assert is_direct_selector(target) is False


def test_empty_or_whitespace_selector_is_not_direct():
    assert is_direct_selector("") is False
    assert is_direct_selector("   ") is False


# =============================================================================
# 2. Mock Classes for Async Playwright Page & Locator
# =============================================================================

class MockLocator:
    def __init__(
        self,
        description: str,
        count: int = 1,
        is_visible: bool = True,
        is_enabled: bool = True,
        children: list[MockLocator] | None = None,
    ):
        self.description = description
        self._count = count
        self._is_visible = is_visible
        self._is_enabled = is_enabled
        self.clicked = False
        self.filled_with: str | None = None
        self._children = children or []

    async def count(self) -> int:
        return self._count

    async def is_visible(self) -> bool:
        return self._is_visible

    async def is_enabled(self) -> bool:
        return self._is_enabled

    def nth(self, idx: int) -> MockLocator:
        if self._children and idx < len(self._children):
            return self._children[idx]
        return MockLocator(
            description=f"{self.description}[{idx}]",
            count=1,
            is_visible=self._is_visible,
            is_enabled=self._is_enabled,
        )

    @property
    def first(self) -> MockLocator:
        return self.nth(0)

    async def click(self, **_kwargs):
        self.clicked = True

    async def fill(self, value: str, **_kwargs):
        self.filled_with = value


class MockPage:
    def __init__(self):
        self.locators: dict[str, MockLocator] = {}
        self.roles: dict[tuple[str, str, bool], MockLocator] = {}
        self.labels: dict[tuple[str, bool], MockLocator] = {}
        self.placeholders: dict[tuple[str, bool], MockLocator] = {}
        self.texts: dict[tuple[str, bool], MockLocator] = {}
        self.url = "https://example.com"

    def locator(self, selector: str) -> MockLocator:
        return self.locators.get(selector, MockLocator(selector, count=0))

    def get_by_role(self, role: str, name: str | None = None, exact: bool = False) -> MockLocator:
        return self.roles.get((role, name or "", exact), MockLocator(f"role={role},name={name}", count=0))

    def get_by_label(self, text: str, exact: bool = False) -> MockLocator:
        return self.labels.get((text, exact), MockLocator(f"label={text}", count=0))

    def get_by_placeholder(self, text: str, exact: bool = False) -> MockLocator:
        return self.placeholders.get((text, exact), MockLocator(f"placeholder={text}", count=0))

    def get_by_text(self, text: str, exact: bool = False) -> MockLocator:
        return self.texts.get((text, exact), MockLocator(f"text={text}", count=0))


# =============================================================================
# 3. Direct Selector Resolution Tests
# =============================================================================

@pytest.mark.asyncio
async def test_direct_css_selector_resolves_single_element():
    page = MockPage()
    btn = MockLocator("#submit-btn", count=1)
    page.locators["#submit-btn"] = btn

    resolved = await resolve_locator(page, "#submit-btn", action="click")
    assert resolved is btn


@pytest.mark.asyncio
async def test_direct_xpath_selector_resolves():
    page = MockPage()
    field = MockLocator("//input[@name='user']", count=1)
    page.locators["//input[@name='user']"] = field

    resolved = await resolve_locator(page, "//input[@name='user']", action="fill")
    assert resolved is field


@pytest.mark.asyncio
async def test_direct_selector_missing_element_fails():
    page = MockPage()
    with pytest.raises(ElementNotFoundError) as exc_info:
        await resolve_locator(page, "#nonexistent", action="click")
    assert "direct selector '#nonexistent' matched 0 elements" in str(exc_info.value)


@pytest.mark.asyncio
async def test_direct_selector_ambiguity_fails():
    page = MockPage()
    page.locators[".duplicate-btn"] = MockLocator(".duplicate-btn", count=3, is_visible=True)

    with pytest.raises(AmbiguousElementError) as exc_info:
        await resolve_locator(page, ".duplicate-btn", action="click")
    assert "matched 3 visible elements" in str(exc_info.value)


# =============================================================================
# 4. Click Action: Semantic Target Resolution Tests
# =============================================================================

@pytest.mark.asyncio
async def test_click_resolves_exact_button_role():
    page = MockPage()
    btn = MockLocator("button[Sign In]", count=1, is_visible=True)
    page.roles[("button", "Sign In", True)] = btn

    resolved = await resolve_locator(page, "Sign In", action="click")
    assert resolved is btn


@pytest.mark.asyncio
async def test_click_resolves_exact_link_role():
    page = MockPage()
    link = MockLocator("link[Register]", count=1, is_visible=True)
    page.roles[("link", "Register", True)] = link

    resolved = await resolve_locator(page, "Register", action="click")
    assert resolved is link


@pytest.mark.asyncio
async def test_click_resolves_tab_role():
    page = MockPage()
    tab = MockLocator("tab[Settings]", count=1, is_visible=True)
    page.roles[("tab", "Settings", True)] = tab

    resolved = await resolve_locator(page, "Settings", action="click")
    assert resolved is tab


@pytest.mark.asyncio
async def test_click_resolves_case_insensitive_button_when_exact_fails():
    page = MockPage()
    # Exact match does not exist
    # Case-insensitive exists
    btn = MockLocator("button[Submit]", count=1, is_visible=True)
    page.roles[("button", "submit", False)] = btn

    resolved = await resolve_locator(page, "submit", action="click")
    assert resolved is btn


@pytest.mark.asyncio
async def test_click_falls_back_to_visible_text():
    page = MockPage()
    # No roles match, but text matches
    text_el = MockLocator("text[Click here]", count=1, is_visible=True)
    page.texts[("Click here", True)] = text_el

    resolved = await resolve_locator(page, "Click here", action="click")
    assert resolved is text_el


@pytest.mark.asyncio
async def test_click_ambiguity_raises_error():
    page = MockPage()
    # Multiple buttons with same name
    page.roles[("button", "Delete", True)] = MockLocator(
        "button[Delete]", count=2, is_visible=True
    )

    with pytest.raises(AmbiguousElementError) as exc_info:
        await resolve_locator(page, "Delete", action="click")
    assert "matches 2 visible elements" in str(exc_info.value)
    assert "Delete" in str(exc_info.value)


@pytest.mark.asyncio
async def test_click_filters_hidden_elements_when_one_visible():
    page = MockPage()
    child_hidden = MockLocator("hidden-btn", count=1, is_visible=False)
    child_visible = MockLocator("visible-btn", count=1, is_visible=True)
    parent = MockLocator(
        "buttons",
        count=2,
        is_visible=True,
        children=[child_hidden, child_visible],
    )
    page.roles[("button", "Save", True)] = parent

    resolved = await resolve_locator(page, "Save", action="click")
    assert resolved is child_visible


@pytest.mark.asyncio
async def test_click_missing_element_fails():
    page = MockPage()
    with pytest.raises(ElementNotFoundError) as exc_info:
        await resolve_locator(page, "NonExistentButton", action="click")
    assert "Could not find any clickable element matching 'NonExistentButton'" in str(exc_info.value)


# =============================================================================
# 5. Fill Action: Semantic Target Resolution Tests
# =============================================================================

@pytest.mark.asyncio
async def test_fill_resolves_exact_form_label():
    page = MockPage()
    input_el = MockLocator("input[Email Address]", count=1, is_visible=True)
    page.labels[("Email Address", True)] = input_el

    resolved = await resolve_locator(page, "Email Address", action="fill")
    assert resolved is input_el


@pytest.mark.asyncio
async def test_fill_resolves_placeholder_when_label_missing():
    page = MockPage()
    search_input = MockLocator("input[search-placeholder]", count=1, is_visible=True)
    page.placeholders[("Search users...", True)] = search_input

    resolved = await resolve_locator(page, "Search users...", action="fill")
    assert resolved is search_input


@pytest.mark.asyncio
async def test_fill_resolves_textbox_role():
    page = MockPage()
    notes_box = MockLocator("textarea[Notes]", count=1, is_visible=True)
    page.roles[("textbox", "Notes", True)] = notes_box

    resolved = await resolve_locator(page, "Notes", action="fill")
    assert resolved is notes_box


@pytest.mark.asyncio
async def test_fill_ambiguity_raises_error():
    page = MockPage()
    # Multiple fields with the same placeholder
    page.placeholders[("Enter name", True)] = MockLocator(
        "inputs", count=2, is_visible=True
    )

    with pytest.raises(AmbiguousElementError) as exc_info:
        await resolve_locator(page, "Enter name", action="fill")
    assert "matches 2 visible elements" in str(exc_info.value)
    assert "Enter name" in str(exc_info.value)


@pytest.mark.asyncio
async def test_fill_missing_field_fails():
    page = MockPage()
    with pytest.raises(ElementNotFoundError) as exc_info:
        await resolve_locator(page, "Credit Card Number", action="fill")
    assert "Could not find any input field matching 'Credit Card Number'" in str(exc_info.value)


# =============================================================================
# 6. Edge Cases & Validation Errors
# =============================================================================

@pytest.mark.asyncio
async def test_empty_target_raises_value_error():
    page = MockPage()
    with pytest.raises(ValueError) as exc_info:
        await resolve_locator(page, "", action="click")
    assert "Target is required" in str(exc_info.value)

    with pytest.raises(ValueError):
        await resolve_locator(page, "   ", action="fill")


@pytest.mark.asyncio
async def test_quoted_target_strings_are_unwrapped():
    page = MockPage()
    btn = MockLocator("button[Sign In]", count=1, is_visible=True)
    page.roles[("button", "Sign In", True)] = btn

    # Target wrapped in double quotes
    resolved = await resolve_locator(page, '"Sign In"', action="click")
    assert resolved is btn

    # Target wrapped in single quotes
    resolved2 = await resolve_locator(page, "'Sign In'", action="click")
    assert resolved2 is btn


# =============================================================================
# 7. Runner Integration Tests with Semantic Targets & Fallbacks
# =============================================================================

class FullFakePage:
    """Mock page supporting both locator navigation and standard Playwright events."""

    def __init__(self):
        self.url = "https://example.com/login"
        self.navigations: list[str] = []
        self.fills: list[tuple[str, str]] = []
        self.clicks: list[str] = []
        self.screenshot_calls: list[dict] = []
        self.video = None

        # Build mock locators
        self._page_mock = MockPage()

        # Add username field via label
        self.user_field = MockLocator("input[Username]", count=1, is_visible=True)
        self._page_mock.labels[("Username", True)] = self.user_field

        # Add password field via direct selector
        self.pass_field = MockLocator("#password", count=1, is_visible=True)
        self._page_mock.locators["#password"] = self.pass_field

        # Add button via role
        self.submit_btn = MockLocator("button[Sign In]", count=1, is_visible=True)
        self._page_mock.roles[("button", "Sign In", True)] = self.submit_btn

    def set_default_timeout(self, _timeout):
        pass

    async def goto(self, url, **_kwargs):
        self.navigations.append(url)
        self.url = url

    def locator(self, sel):
        return self._page_mock.locator(sel)

    def get_by_role(self, role, name=None, exact=False):
        return self._page_mock.get_by_role(role, name, exact)

    def get_by_label(self, text, exact=False):
        return self._page_mock.get_by_label(text, exact)

    def get_by_placeholder(self, text, exact=False):
        return self._page_mock.get_by_placeholder(text, exact)

    def get_by_text(self, text, exact=False):
        return self._page_mock.get_by_text(text, exact)

    async def wait_for_load_state(self, *_args, **_kwargs):
        pass

    async def screenshot(self, **kwargs):
        self.screenshot_calls.append(kwargs)


class FakeContext:
    def __init__(self, page):
        self.page = page

    async def new_page(self):
        return self.page

    async def close(self):
        pass


class FakeBrowser:
    def __init__(self, page):
        self.context = FakeContext(page)

    async def new_context(self, **_kwargs):
        return self.context

    async def close(self):
        pass


class FakePlaywrightManager:
    def __init__(self, page):
        self.page = page

    async def __aenter__(self):
        page = self.page

        class FakeChromium:
            async def launch(self, **_kwargs):
                return FakeBrowser(page)

        class PW:
            chromium = FakeChromium()

        return PW()

    async def __aexit__(self, *_exc):
        pass


@pytest.mark.asyncio
async def test_runner_executes_semantic_and_direct_steps(monkeypatch, tmp_path):
    page = FullFakePage()
    import sys
    from types import ModuleType

    pw_mod = ModuleType("playwright")
    pw_async = ModuleType("playwright.async_api")
    pw_async.async_playwright = lambda: FakePlaywrightManager(page)
    pw_mod.async_api = pw_async
    monkeypatch.setitem(sys.modules, "playwright", pw_mod)
    monkeypatch.setitem(sys.modules, "playwright.async_api", pw_async)

    steps = [
        {"step_number": 1, "action": "navigate", "value": "https://example.com/login"},
        {"step_number": 2, "action": "fill", "target": "Username", "value": "admin"},
        {"step_number": 3, "action": "fill", "target": "#password", "value": "secret123"},
        {"step_number": 4, "action": "click", "target": "Sign In"},
        {"step_number": 5, "action": "verify_url", "expected_result": "/login"},
    ]

    outcome = await _execute_playwright(
        steps=steps,
        app_url="https://example.com",
        artifacts_dir=str(tmp_path),
        run_id="run-sem-1",
        test_case_id="tc-sem-1",
    )

    assert outcome["status"] == "passed"
    assert page.user_field.filled_with == "admin"
    assert page.pass_field.filled_with == "secret123"
    assert page.submit_btn.clicked is True
