"""
Tests for the CSV validator service.
"""
import pytest

from app.services.csv_validator import REQUIRED_COLUMNS, SUPPORTED_ACTIONS, validate_csv


def make_csv(*rows: str) -> bytes:
    """Build CSV bytes from a header line and data rows."""
    header = ",".join(REQUIRED_COLUMNS)
    lines = [header] + list(rows)
    return "\n".join(lines).encode("utf-8")


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_valid_csv_is_accepted():
    """A well-formed CSV with valid data should pass validation."""
    content = make_csv(
        "TC001,Login Test,1,navigate,,https://example.com,",
        "TC001,Login Test,2,fill,#user,admin,",
        "TC001,Login Test,3,click,button,,",
        "TC001,Login Test,4,verify_url,,,https://example.com",
    )
    result = validate_csv(content)
    assert result.is_valid is True
    assert result.errors == []
    assert result.row_count == 4
    assert result.test_case_count == 1
    assert len(result.parsed_cases) == 1
    assert result.parsed_cases[0]["test_case_id"] == "TC001"


def test_valid_csv_multiple_test_cases():
    """CSV with multiple test_case_ids should produce separate parsed cases."""
    content = make_csv(
        "TC001,Test A,1,navigate,,https://a.com,",
        "TC002,Test B,1,navigate,,https://b.com,",
        "TC002,Test B,2,click,.btn,,",
    )
    result = validate_csv(content)
    assert result.is_valid is True
    assert result.test_case_count == 2
    assert len(result.parsed_cases) == 2


# ---------------------------------------------------------------------------
# Missing columns
# ---------------------------------------------------------------------------

def test_missing_required_column():
    """CSV missing a required column should fail immediately."""
    # Omit 'action' column
    bad_header = "test_case_id,test_name,step_number,target,value,expected_result\n"
    content = (bad_header + "TC001,Test,1,#btn,,\n").encode("utf-8")
    result = validate_csv(content)
    assert result.is_valid is False
    col_errors = [e.column for e in result.errors]
    assert "action" in col_errors


def test_all_missing_columns():
    """Completely wrong CSV headers should report all missing columns."""
    content = "foo,bar,baz\n1,2,3\n".encode("utf-8")
    result = validate_csv(content)
    assert result.is_valid is False
    assert len(result.errors) == len(REQUIRED_COLUMNS)


# ---------------------------------------------------------------------------
# Bad action
# ---------------------------------------------------------------------------

def test_invalid_action_rejected():
    """An unsupported action value should produce a validation error."""
    content = make_csv(
        "TC001,Test,1,hover,.btn,,",  # 'hover' is not supported
    )
    result = validate_csv(content)
    assert result.is_valid is False
    action_errors = [e for e in result.errors if e.column == "action"]
    assert len(action_errors) >= 1
    assert "hover" in action_errors[0].message


def test_all_supported_actions_are_valid():
    """Each supported action in a minimal valid row should not produce an action error."""
    rows = []
    for i, action in enumerate(SUPPORTED_ACTIONS, start=1):
        target = "#el" if action in ("fill", "click", "verify_text") else ""
        value = "val" if action in ("fill", "navigate") else ""
        expected = "text" if action == "verify_text" else ""
        rows.append(f"TC{i:03d},Test {i},{i},{action},{target},{value},{expected}")

    content = make_csv(*rows)
    result = validate_csv(content)
    action_errors = [e for e in result.errors if e.column == "action"]
    assert action_errors == [], f"Unexpected action errors: {action_errors}"


# ---------------------------------------------------------------------------
# Non-integer step_number
# ---------------------------------------------------------------------------

def test_non_integer_step_number():
    """A non-integer step_number should produce a validation error."""
    content = make_csv(
        "TC001,Test,one,navigate,,https://x.com,",
    )
    result = validate_csv(content)
    assert result.is_valid is False
    step_errors = [e for e in result.errors if e.column == "step_number"]
    assert len(step_errors) >= 1
    assert "one" in step_errors[0].message


def test_float_step_number_coerced():
    """A step_number like '1.0' should be coerced to 1 without error."""
    content = make_csv(
        "TC001,Test,1.0,navigate,,https://x.com,",
    )
    result = validate_csv(content)
    # Should not produce a step_number type error
    step_errors = [e for e in result.errors if e.column == "step_number" and "integer" in e.message]
    assert step_errors == []


# ---------------------------------------------------------------------------
# Empty target
# ---------------------------------------------------------------------------

def test_empty_target_for_fill_action():
    """fill action with an empty target should produce a validation error."""
    content = make_csv(
        "TC001,Test,1,fill,,myvalue,",  # target is empty
    )
    result = validate_csv(content)
    assert result.is_valid is False
    target_errors = [e for e in result.errors if e.column == "target"]
    assert len(target_errors) >= 1


def test_empty_target_for_click_action():
    """click action with an empty target should produce a validation error."""
    content = make_csv(
        "TC001,Test,1,click,,,",  # target is empty
    )
    result = validate_csv(content)
    assert result.is_valid is False
    target_errors = [e for e in result.errors if e.column == "target"]
    assert len(target_errors) >= 1


# ---------------------------------------------------------------------------
# Empty value for fill
# ---------------------------------------------------------------------------

def test_empty_value_for_fill():
    """fill action with an empty value should produce a validation error."""
    content = make_csv(
        "TC001,Test,1,fill,#input,,",  # value is empty
    )
    result = validate_csv(content)
    assert result.is_valid is False
    value_errors = [e for e in result.errors if e.column == "value"]
    assert len(value_errors) >= 1


# ---------------------------------------------------------------------------
# Non-sequential steps
# ---------------------------------------------------------------------------

def test_non_sequential_steps():
    """Step numbers that skip values should produce a sequential-order error."""
    content = make_csv(
        "TC001,Test,1,navigate,,https://x.com,",
        "TC001,Test,3,click,.btn,,",  # skips step 2
    )
    result = validate_csv(content)
    assert result.is_valid is False
    seq_errors = [e for e in result.errors if "sequential" in e.message.lower() or "non-sequential" in e.message.lower()]
    assert len(seq_errors) >= 1


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_empty_csv_body():
    """A CSV with only a header and no data rows should be rejected."""
    header = ",".join(REQUIRED_COLUMNS) + "\n"
    result = validate_csv(header.encode("utf-8"))
    assert result.is_valid is False


def test_unparseable_csv():
    """Garbage bytes should produce a parse error."""
    result = validate_csv(b"\x00\x01\x02\x03garbage")
    # May or may not parse — just must not raise an exception
    assert isinstance(result.is_valid, bool)


# ---------------------------------------------------------------------------
# Phase 4B: Batch 1 - discover_page, template, and header normalization
# ---------------------------------------------------------------------------

def test_discover_page_action_accepted():
    """A row with action 'discover_page' should be valid and accepted."""
    content = make_csv(
        "TC001,Discovery Test,1,navigate,,https://example.com,",
        "TC001,Discovery Test,2,discover_page,,,",
    )
    result = validate_csv(content)
    assert result.is_valid is True
    assert result.errors == []
    assert len(result.parsed_cases) == 1
    assert len(result.parsed_cases[0]["steps"]) == 2
    assert result.parsed_cases[0]["steps"][1]["action"] == "discover_page"


def test_discover_page_invalid_input_rejected():
    """discover_page with invalid input (e.g. non-integer step or empty id or action typo) is rejected."""
    # Bad step number
    content_bad_step = make_csv(
        "TC001,Discovery Test,one,discover_page,,,",
    )
    result_bad_step = validate_csv(content_bad_step)
    assert result_bad_step.is_valid is False
    assert any(e.column == "step_number" for e in result_bad_step.errors)

    # Missing test_case_id
    content_bad_id = make_csv(
        ",Discovery Test,1,discover_page,,,",
    )
    result_bad_id = validate_csv(content_bad_id)
    assert result_bad_id.is_valid is False
    assert any(e.column == "test_case_id" for e in result_bad_id.errors)

    # Action typo / unsupported variant
    content_bad_action = make_csv(
        "TC001,Discovery Test,1,discover_pages,,,",
    )
    result_bad_action = validate_csv(content_bad_action)
    assert result_bad_action.is_valid is False
    assert any("discover_pages" in e.message for e in result_bad_action.errors)


def test_csv_template_passes_own_validation():
    """The built-in CSV template rows must pass validation without errors."""
    from app.routers.test_cases import CSV_TEMPLATE_ROWS

    header = ",".join(REQUIRED_COLUMNS)
    content = (f"{header}\n" + "\n".join(CSV_TEMPLATE_ROWS) + "\n").encode("utf-8")
    result = validate_csv(content)
    assert result.is_valid is True
    assert result.errors == []
    assert result.test_case_count == 2
    assert result.row_count == len(CSV_TEMPLATE_ROWS)


def test_space_and_hyphen_separated_headers_normalize_correctly():
    """Headers using spaces or hyphens should normalize to snake_case and be accepted."""
    custom_header = "Test Case ID,Test-Name,Step Number,Action,Target,Value,Expected-Result\n"
    body = "TC001,Login Test,1,navigate,,https://example.com,\n"
    content = (custom_header + body).encode("utf-8")
    result = validate_csv(content)
    assert result.is_valid is True
    assert result.errors == []
    assert len(result.parsed_cases) == 1
    assert result.parsed_cases[0]["test_case_id"] == "TC001"
    assert result.parsed_cases[0]["test_name"] == "Login Test"


def test_existing_snake_case_csv_continues_to_validate():
    """Standard snake_case headers must continue to validate seamlessly."""
    content = make_csv(
        "TC001,Snake Case Test,1,navigate,,https://example.com,",
        "TC001,Snake Case Test,2,click,#btn,,",
    )
    result = validate_csv(content)
    assert result.is_valid is True
    assert result.errors == []


def test_duplicate_headers_after_normalization_rejected():
    """Duplicate columns (exact or created by normalization) must produce clear validation errors."""
    # Case 1: Variant duplicate ('Test Case ID' and 'test_case_id')
    dup_header1 = "Test Case ID,test_case_id,Step Number,Action,Target,Value,Expected Result\n"
    content1 = (dup_header1 + "TC001,TC001,1,navigate,,,http\n").encode("utf-8")
    result1 = validate_csv(content1)
    assert result1.is_valid is False
    assert any("test_case_id" in e.message.lower() and "duplicate" in e.message.lower() for e in result1.errors)

    # Case 2: Exact duplicate ('step_number' and 'step_number')
    dup_header2 = "test_case_id,test_name,step_number,step_number,action,target,value,expected_result\n"
    content2 = (dup_header2 + "TC001,Test,1,1,navigate,,,http\n").encode("utf-8")
    result2 = validate_csv(content2)
    assert result2.is_valid is False
    assert any("step_number" in e.message.lower() and "duplicate" in e.message.lower() for e in result2.errors)

    # Case 3: Space vs hyphen duplicate ('Step Number' and 'step-number')
    dup_header3 = "test_case_id,test_name,Step Number,step-number,action,target,value,expected_result\n"
    content3 = (dup_header3 + "TC001,Test,1,1,navigate,,,http\n").encode("utf-8")
    result3 = validate_csv(content3)
    assert result3.is_valid is False
    assert any("step_number" in e.message.lower() and "duplicate" in e.message.lower() for e in result3.errors)


def test_action_validation_and_required_fields_remain_enforced():
    """Verify that fill, click, and verify_text still enforce required target/value rules."""
    # Fill missing target
    res_fill_target = validate_csv(make_csv("TC001,Test,1,fill,,val,"))
    assert res_fill_target.is_valid is False
    assert any(e.column == "target" for e in res_fill_target.errors)

    # Fill missing value
    res_fill_val = validate_csv(make_csv("TC001,Test,1,fill,#target,,"))
    assert res_fill_val.is_valid is False
    assert any(e.column == "value" for e in res_fill_val.errors)

    # Click missing target
    res_click_target = validate_csv(make_csv("TC001,Test,1,click,,,"))
    assert res_click_target.is_valid is False
    assert any(e.column == "target" for e in res_click_target.errors)

    # Verify_text missing target
    res_verify_text = validate_csv(make_csv("TC001,Test,1,verify_text,,,expected"))
    assert res_verify_text.is_valid is False
    assert any(e.column == "target" for e in res_verify_text.errors)

