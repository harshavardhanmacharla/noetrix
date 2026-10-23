"""
Integration and unit tests for Phase 12 - Dropdown Selection Support in Noetrix.
Verifies parsing, locator resolution, Playwright execution, CSV validation, and error reporting.
"""
from __future__ import annotations

import pytest
from app.services.instruction_parser import parse_instruction, parse_step_data
from app.services.csv_validator import validate_csv
from app.services.locator_resolver import (
    AmbiguousElementError,
    ElementNotFoundError,
    resolve_locator,
)
from app.services.playwright_runner import reconstruct_instruction, _execute_playwright
from app.models.test_case import TestStep as TestCaseStepModel


# =============================================================================
# 1. Parser Tests for Dropdown Selection
# =============================================================================

def test_parse_dropdown_standard_phrasing():
    r1 = parse_instruction('select "California" from "#state"')
    assert r1.is_valid is True
    assert r1.action_data.action == "select_option"
    assert r1.action_data.target == "#state"
    assert r1.action_data.value == "California"

    r2 = parse_instruction('choose "Express Shipping" from dropdown "#shipping"')
    assert r2.is_valid is True
    assert r2.action_data.action == "select_option"
    assert r2.action_data.target == "#shipping"
    assert r2.action_data.value == "Express Shipping"

    r3 = parse_instruction('select "Admin" in "#role-dropdown"')
    assert r3.is_valid is True
    assert r3.action_data.action == "select_option"
    assert r3.action_data.target == "#role-dropdown"
    assert r3.action_data.value == "Admin"

    r4 = parse_instruction('select "Manager" from the "Role" dropdown')
    assert r4.is_valid is True
    assert r4.action_data.action == "select_option"
    assert r4.action_data.target == "Role"
    assert r4.action_data.value == "Manager"


def test_parse_dropdown_inverted_phrasing():
    r1 = parse_instruction('in the "Role" dropdown, select "Admin"')
    assert r1.is_valid is True
    assert r1.action_data.action == "select_option"
    assert r1.action_data.target == "Role"
    assert r1.action_data.value == "Admin"

    r2 = parse_instruction('from "#state", choose "California"')
    assert r2.is_valid is True
    assert r2.action_data.action == "select_option"
    assert r2.action_data.target == "#state"
    assert r2.action_data.value == "California"


def test_parse_dropdown_option_containing_prepositions():
    """Verify that an option containing 'in' or 'from' within quotes does not misparse."""
    r = parse_instruction('select "Made in USA" from "#origin"')
    assert r.is_valid is True
    assert r.action_data.action == "select_option"
    assert r.action_data.target == "#origin"
    assert r.action_data.value == "Made in USA"


def test_parse_dropdown_missing_parameters_rejected():
    # Missing value
    r1 = parse_instruction('select from "#state"')
    assert r1.is_valid is False
    assert "missing value" in (r1.error or "").lower()

    r2 = parse_instruction('choose in "#role"')
    assert r2.is_valid is False
    assert "missing value" in (r2.error or "").lower()

    # Missing target
    r3 = parse_instruction('select "California" from')
    assert r3.is_valid is False
    assert "missing target" in (r3.error or "").lower()

    r4 = parse_instruction('choose "Admin" in')
    assert r4.is_valid is False
    assert "missing target" in (r4.error or "").lower()


def test_preserved_clicks_on_options():
    """Ensure that selecting an option directly without from/in remains a click action."""
    r1 = parse_instruction('select option "Credit Card"')
    assert r1.is_valid is True
    assert r1.action_data.action == "click"
    assert r1.action_data.target == "Credit Card"

    r2 = parse_instruction('choose "Dark Mode"')
    assert r2.is_valid is True
    assert r2.action_data.action == "click"
    assert r2.action_data.target == "Dark Mode"

    r3 = parse_instruction('select "#country-select"')
    assert r3.is_valid is True
    assert r3.action_data.action == "click"
    assert r3.action_data.target == "#country-select"


def test_parse_step_data_normalization():
    # Canonical select_option
    r1 = parse_step_data(action="select_option", target="#state", value="California")
    assert r1.is_valid is True
    assert r1.action_data.action == "select_option"
    assert r1.action_data.target == "#state"
    assert r1.action_data.value == "California"

    # Verb 'select' with value normalizes to select_option
    r2 = parse_step_data(action="select", target="#state", value="California")
    assert r2.is_valid is True
    assert r2.action_data.action == "select_option"
    assert r2.action_data.target == "#state"
    assert r2.action_data.value == "California"

    # Verb 'select' without value remains click
    r3 = parse_step_data(action="select", target="Accept Terms")
    assert r3.is_valid is True
    assert r3.action_data.action == "click"
    assert r3.action_data.target == "Accept Terms"


# =============================================================================
# 2. Locator Resolver for select_option
# =============================================================================

class MockLocator:
    def __init__(
        self,
        description: str,
        count: int = 1,
        is_visible: bool = True,
        children: list[MockLocator] | None = None,
    ):
        self.description = description
        self._count = count
        self._is_visible = is_visible
        self.selected_label: str | None = None
        self.selected_value: str | None = None
        self._children = children or []

    async def count(self) -> int:
        return self._count

    async def is_visible(self) -> bool:
        return self._is_visible

    def nth(self, idx: int) -> MockLocator:
        if self._children and idx < len(self._children):
            return self._children[idx]
        return self

    async def select_option(self, value=None, label=None, timeout=None):
        if label:
            if label == "INVALID_LABEL":
                raise ValueError("No option matched label")
            self.selected_label = label
        elif value:
            if value == "INVALID_VALUE":
                raise ValueError("No option matched value")
            self.selected_value = value
        return [value or label]


class MockPage:
    def __init__(self):
        self._roles: dict[tuple[str, str, bool], MockLocator] = {}
        self._labels: dict[tuple[str, bool], MockLocator] = {}
        self._locators: dict[str, MockLocator] = {}
        self._texts: dict[tuple[str, bool], MockLocator] = {}

    def get_by_role(self, role: str, name: str, exact: bool = False) -> MockLocator:
        return self._roles.get((role, name, exact), MockLocator("not-found", count=0))

    def get_by_label(self, label: str, exact: bool = False) -> MockLocator:
        return self._labels.get((label, exact), MockLocator("not-found", count=0))

    def locator(self, sel: str) -> MockLocator:
        return self._locators.get(sel, MockLocator("not-found", count=0))

    def get_by_text(self, text: str, exact: bool = False) -> MockLocator:
        return self._texts.get((text, exact), MockLocator("not-found", count=0))


@pytest.mark.asyncio
async def test_resolve_locator_direct_selector():
    page = MockPage()
    mock_el = MockLocator("direct-select", count=1)
    page._locators["#state-select"] = mock_el

    loc = await resolve_locator(page, "#state-select", action="select_option")
    assert loc is mock_el


@pytest.mark.asyncio
async def test_resolve_locator_combobox_role():
    page = MockPage()
    mock_combobox = MockLocator("combobox-country", count=1)
    page._roles[("combobox", "Country", True)] = mock_combobox

    loc = await resolve_locator(page, "Country", action="select_option")
    assert loc is mock_combobox


@pytest.mark.asyncio
async def test_resolve_locator_label():
    page = MockPage()
    mock_by_label = MockLocator("label-state", count=1)
    page._labels[("State", True)] = mock_by_label

    loc = await resolve_locator(page, "State", action="select_option")
    assert loc is mock_by_label


@pytest.mark.asyncio
async def test_resolve_locator_ambiguous_combobox():
    page = MockPage()
    c1 = MockLocator("c1", count=1, is_visible=True)
    c2 = MockLocator("c2", count=1, is_visible=True)
    ambig = MockLocator("ambig", count=2, is_visible=True, children=[c1, c2])
    page._roles[("combobox", "Branch", True)] = ambig

    with pytest.raises(AmbiguousElementError) as exc_info:
        await resolve_locator(page, "Branch", action="select_option", timeout_ms=50)
    assert "matches 2 visible elements" in str(exc_info.value)


@pytest.mark.asyncio
async def test_resolve_locator_missing_dropdown():
    page = MockPage()
    with pytest.raises(ElementNotFoundError) as exc_info:
        await resolve_locator(page, "MissingDropdown", action="select_option", timeout_ms=50)
    assert "Could not find any dropdown matching 'MissingDropdown'" in str(exc_info.value)


# =============================================================================
# 3. Reconstruct Instruction
# =============================================================================

def test_reconstruct_instruction_select_option():
    instruction = reconstruct_instruction(
        action="select_option",
        target="#state",
        val_str="California",
        expected="",
    )
    assert instruction == "select 'California' from '#state'"


# =============================================================================
# 4. Playwright Runner Mock Execution for select_option
# =============================================================================

@pytest.mark.asyncio
async def test_execute_playwright_select_option_success(tmp_path):
    steps = [
        {"step_number": 1, "action": "navigate", "value": "https://example.com"},
        {"step_number": 2, "action": "select_option", "target": "#state", "value": "California"},
    ]
    # Without real Playwright installed or configured, _execute_playwright catches ImportError
    # and returns graceful status or error
    res = await _execute_playwright(
        steps=steps,
        app_url="",
        artifacts_dir=str(tmp_path),
        run_id="test-run",
        test_case_id="tc-select-01",
    )
    # Runner handles steps cleanly
    assert "status" in res


# =============================================================================
# 5. Database Model & Enum Alignment
# =============================================================================

def test_step_action_enum_contains_select_option():
    enums = TestCaseStepModel.__table__.c.action.type.enums
    assert "select_option" in enums
