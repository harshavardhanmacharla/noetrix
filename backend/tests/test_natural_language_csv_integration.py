"""
Integration tests for Natural-Language CSV Ingestion, Validation, and Execution Pipeline.

Tests:
1. Natural language CSV validation and normalization to canonical actions and semantic targets.
2. Synonym normalization with structured columns.
3. Secret reference preservation in natural language instructions.
4. Row-specific validation errors for missing targets/values, unsupported verbs, and ambiguous sentences.
5. Rejection of invalid CSV uploads with persistence safety (zero DB records created on failure).
6. Backward compatibility with existing canonical 7-column CSVs.
7. Full pipeline integration: CSV -> validate_csv -> mock persistence -> playwright_runner + resolve_locator execution.
"""
from __future__ import annotations

import io
import pytest
from app.services.csv_validator import REQUIRED_COLUMNS, validate_csv
from app.services.playwright_runner import _execute_playwright


def make_csv(*rows: str) -> bytes:
    """Build CSV bytes from standard 7-column headers and data rows."""
    header = ",".join(REQUIRED_COLUMNS)
    lines = [header] + list(rows)
    return "\n".join(lines).encode("utf-8")


# =============================================================================
# 1. Natural Language Sentence Ingestion & Normalization
# =============================================================================

def test_natural_language_csv_full_flow_validation():
    """Verify an end-to-end natural-language CSV validates and normalizes all canonical actions."""
    csv_bytes = make_csv(
        'TC001,User Login Flow,1,visit "https://example.com/login",,,',
        'TC001,User Login Flow,2,type "admin" into the "Username" field,,,',
        'TC001,User Login Flow,3,enter "${secret:APEX_PASSWORD}" into "#password",,,',
        'TC001,User Login Flow,4,click the "Sign In" button,,,',
        'TC001,User Login Flow,5,verify that the url contains "/dashboard",,,',
        'TC001,User Login Flow,6,verify that text "Welcome back" is visible,,,',
        'TC001,User Login Flow,7,discover page,,,',
    )

    result = validate_csv(csv_bytes)
    assert result.is_valid is True
    assert result.errors == []
    assert len(result.parsed_cases) == 1

    case = result.parsed_cases[0]
    assert case["test_case_id"] == "TC001"
    assert case["test_name"] == "User Login Flow"
    assert len(case["steps"]) == 7

    steps = case["steps"]

    # Step 1: visit -> navigate
    assert steps[0]["step_number"] == 1
    assert steps[0]["action"] == "navigate"
    assert steps[0]["value"] == "https://example.com/login"

    # Step 2: type into field -> fill with semantic target
    assert steps[1]["step_number"] == 2
    assert steps[1]["action"] == "fill"
    assert steps[1]["target"] == "Username"
    assert steps[1]["value"] == "admin"

    # Step 3: enter into selector with secret -> fill with technical selector
    assert steps[2]["step_number"] == 3
    assert steps[2]["action"] == "fill"
    assert steps[2]["target"] == "#password"
    assert steps[2]["value"] == "${secret:APEX_PASSWORD}"

    # Step 4: click button -> click with semantic target
    assert steps[3]["step_number"] == 4
    assert steps[3]["action"] == "click"
    assert steps[3]["target"] == "Sign In"

    # Step 5: verify url -> verify_url
    assert steps[4]["step_number"] == 5
    assert steps[4]["action"] == "verify_url"
    assert steps[4]["expected_result"] == "/dashboard"

    # Step 6: verify text -> verify_text
    assert steps[5]["step_number"] == 6
    assert steps[5]["action"] == "verify_text"
    assert steps[5]["expected_result"] == "Welcome back"

    # Step 7: discover page -> discover_page
    assert steps[6]["step_number"] == 7
    assert steps[6]["action"] == "discover_page"


def test_action_synonyms_with_structured_columns_normalized():
    """Verify structured CSV columns using verb synonyms normalize to canonical actions."""
    csv_bytes = make_csv(
        "TC002,Synonym Test,1,visit,,https://example.com,",
        "TC002,Synonym Test,2,type,#username,admin,",
        "TC002,Synonym Test,3,press,#submit,,",
        "TC002,Synonym Test,4,check url,,,https://example.com/home",
    )

    result = validate_csv(csv_bytes)
    assert result.is_valid is True
    assert result.errors == []

    steps = result.parsed_cases[0]["steps"]
    assert steps[0]["action"] == "navigate"
    assert steps[0]["value"] == "https://example.com"
    assert steps[1]["action"] == "fill"
    assert steps[1]["target"] == "#username"
    assert steps[1]["value"] == "admin"
    assert steps[2]["action"] == "click"
    assert steps[2]["target"] == "#submit"
    assert steps[3]["action"] == "verify_url"
    assert steps[3]["expected_result"] == "https://example.com/home"


# =============================================================================
# 2. Secret Reference Preservation
# =============================================================================

def test_secret_reference_preserved_without_alteration():
    """Verify ${secret:...} syntax remains strictly literal in parsed steps."""
    secret_ref = "${secret:NOETRIX_PRODUCTION_DATABASE_PASSWORD}"
    csv_bytes = make_csv(
        f'TC003,Secret Test,1,enter "{secret_ref}" into the "Password" field,,,',
    )

    result = validate_csv(csv_bytes)
    assert result.is_valid is True
    assert result.parsed_cases[0]["steps"][0]["value"] == secret_ref


# =============================================================================
# 3. Row-Specific Error Reporting & Edge Cases
# =============================================================================

def test_natural_language_missing_target_error():
    """When a natural-language instruction lacks a target, reporting ties error to row."""
    csv_bytes = make_csv(
        "TC001,Error Test,1,visit https://example.com,,,",
        "TC001,Error Test,2,press the button,,,",  # Missing target button name
    )
    result = validate_csv(csv_bytes)
    assert result.is_valid is False
    target_errors = [e for e in result.errors if e.column == "target" and e.row == 3]
    assert len(target_errors) >= 1
    assert "target" in target_errors[0].message.lower()


def test_natural_language_missing_value_error():
    """When a natural-language instruction lacks a value, reporting ties error to value column."""
    csv_bytes = make_csv(
        'TC001,Error Test,1,type into "#username",,,',  # Missing text value
    )
    result = validate_csv(csv_bytes)
    assert result.is_valid is False
    val_errors = [e for e in result.errors if e.column == "value" and e.row == 2]
    assert len(val_errors) >= 1
    assert "Missing value" in val_errors[0].message


def test_ambiguous_compound_sentence_rejected():
    """Sentences combining multiple command verbs are rejected as ambiguous."""
    csv_bytes = make_csv(
        'TC001,Compound Test,1,type "admin" into "#user" and click "Sign In",,,',
    )
    result = validate_csv(csv_bytes)
    assert result.is_valid is False
    assert any("Ambiguous compound instruction" in e.message for e in result.errors)


def test_unsupported_natural_language_instruction_rejected():
    """Unrecognized natural-language instruction is rejected with supported actions listed."""
    csv_bytes = make_csv(
        "TC001,Unsupported Test,1,order a hot pizza online,,,",
    )
    result = validate_csv(csv_bytes)
    assert result.is_valid is False
    assert any("Unsupported instruction" in e.message for e in result.errors)


# =============================================================================
# 4. Persistence Safety: Invalid CSV Rejection
# =============================================================================

@pytest.mark.asyncio
async def test_invalid_csv_rejected_before_persistence():
    """
    Verify that an invalid CSV upload is rejected immediately with saved=False,
    and zero test cases or steps are written to the database session.
    """
    from unittest.mock import MagicMock
    from fastapi import UploadFile
    from app.models.user import User
    from app.routers.test_cases import upload_test_cases_csv

    mock_db = MagicMock()
    mock_user = User(email="test@example.com", is_superuser=True)

    invalid_csv = make_csv(
        "TC001,Invalid Test,1,order a hot pizza online,,,",
    )

    file = UploadFile(filename="invalid.csv", file=io.BytesIO(invalid_csv))

    # Mock verify_project_access to pass
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.routers.test_cases.verify_project_access", lambda *args, **kwargs: None)
        response = await upload_test_cases_csv(
            project_id="proj-123",
            file=file,
            current_user=mock_user,
            db=mock_db,
        )

    assert response["is_valid"] is False
    assert response["saved"] is False
    assert response["created_test_cases"] == []
    # Verify no records were added or committed to the database
    assert mock_db.add.call_count == 0
    assert mock_db.commit.call_count == 0


@pytest.mark.asyncio
async def test_valid_natural_language_csv_persists_normalized_steps():
    """
    Verify that a valid natural-language CSV upload persists normalized
    TestStep records with canonical action names and semantic targets.
    """
    from unittest.mock import MagicMock
    from fastapi import UploadFile
    from app.models.user import User
    from app.routers.test_cases import upload_test_cases_csv

    mock_db = MagicMock()
    mock_user = User(email="author@example.com", is_superuser=True)

    valid_nl_csv = make_csv(
        'TC001,Natural Flow,1,visit "https://example.com",,,',
        'TC001,Natural Flow,2,type "alice" into the "Username" field,,,',
        'TC001,Natural Flow,3,click the "Login" button,,,',
    )

    file = UploadFile(filename="valid_nl.csv", file=io.BytesIO(valid_nl_csv))

    added_objects = []
    mock_db.add.side_effect = lambda obj: added_objects.append(obj)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.routers.test_cases.verify_project_access", lambda *args, **kwargs: None)
        response = await upload_test_cases_csv(
            project_id="proj-456",
            file=file,
            current_user=mock_user,
            db=mock_db,
        )

    assert response["is_valid"] is True
    assert response["saved"] is True
    assert len(response["created_test_cases"]) == 1
    assert mock_db.commit.call_count == 1

    # Check added objects: 1 TestCase + 3 TestSteps
    assert len(added_objects) == 4
    test_case_obj = added_objects[0]
    assert test_case_obj.name == "Natural Flow"

    step1, step2, step3 = added_objects[1], added_objects[2], added_objects[3]
    # Step 1: visit -> navigate
    assert step1.action == "navigate"
    assert step1.value == "https://example.com"
    # Step 2: type into field -> fill with target "Username"
    assert step2.action == "fill"
    assert step2.target == "Username"
    assert step2.value == "alice"
    # Step 3: click button -> click with target "Login"
    assert step3.action == "click"
    assert step3.target == "Login"


# =============================================================================
# 5. Full Pipeline: CSV Validation -> Execution -> Semantic Locator Resolution
# =============================================================================

@pytest.mark.asyncio
async def test_csv_parsed_steps_reach_locator_resolver_and_execute(monkeypatch, tmp_path):
    """
    End-to-end integration test:
    Validates a natural-language CSV, extracts the normalized parsed_cases,
    passes them directly to _execute_playwright, and verifies that the
    Phase 2 semantic locator resolver resolves the targets and executes the steps.
    """
    from types import ModuleType
    from tests.test_locator_resolver import FullFakePage, FakeBrowser

    # 1. Validate natural-language CSV
    csv_bytes = make_csv(
        'TC001,E2E NL Flow,1,visit "https://example.com/login",,,',
        'TC001,E2E NL Flow,2,type "testuser" into the "Username" field,,,',
        'TC001,E2E NL Flow,3,enter "secretpass" into "#password",,,',
        'TC001,E2E NL Flow,4,click the "Sign In" button,,,',
        'TC001,E2E NL Flow,5,verify that the url contains "/login",,,',
    )
    val_res = validate_csv(csv_bytes)
    assert val_res.is_valid is True
    steps_to_run = val_res.parsed_cases[0]["steps"]

    # 2. Configure mock Playwright environment
    page = FullFakePage()

    class FakeChromium:
        async def launch(self, **_kw):
            return FakeBrowser(page)

    class FakePW:
        chromium = FakeChromium()

    class FakePWManager:
        async def __aenter__(self):
            return FakePW()

        async def __aexit__(self, *_exc):
            pass

    pw_mod = ModuleType("playwright")
    pw_async = ModuleType("playwright.async_api")
    pw_async.async_playwright = lambda: FakePWManager()
    pw_mod.async_api = pw_async
    monkeypatch.setitem(pytest.importorskip("sys").modules, "playwright", pw_mod)
    monkeypatch.setitem(pytest.importorskip("sys").modules, "playwright.async_api", pw_async)

    # 3. Execute through the runner
    outcome = await _execute_playwright(
        steps=steps_to_run,
        app_url="https://example.com",
        artifacts_dir=str(tmp_path),
        run_id="run-nl-csv",
        test_case_id="tc-nl-csv",
    )

    # 4. Assert outcome and element interactions
    assert outcome["status"] == "passed"
    assert outcome["error_message"] is None
    # Semantic target "Username" was resolved via label and filled
    assert page.user_field.filled_with == "testuser"
    # Technical selector "#password" was resolved via locator and filled
    assert page.pass_field.filled_with == "secretpass"
    # Semantic target "Sign In" was resolved via button role and clicked
    assert page.submit_btn.clicked is True
