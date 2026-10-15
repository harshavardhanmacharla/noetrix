"""
CSV validator service for test case uploads.
Validates structure, content, and business rules of uploaded CSV files.
"""
import csv
import io
import re
from typing import Any, Dict, List, Optional

import pandas as pd
from pydantic import BaseModel

REQUIRED_COLUMNS = [
    "test_case_id",
    "test_name",
    "step_number",
    "action",
    "target",
    "value",
    "expected_result",
]

SUPPORTED_ACTIONS = ["navigate", "fill", "click", "verify_url", "verify_text", "discover_page"]

# Actions that require a non-empty target (CSS selector or URL)
ACTIONS_REQUIRING_TARGET = {"fill", "click", "verify_text"}

# Actions that require a non-empty value
ACTIONS_REQUIRING_VALUE = {"fill"}


class ValidationError(BaseModel):
    """Represents a single validation error tied to a specific CSV row and column."""

    row: int
    column: str
    message: str


class ValidationResult(BaseModel):
    """The complete result of validating a CSV file."""

    is_valid: bool
    errors: List[ValidationError]
    warnings: List[ValidationError]
    row_count: int
    test_case_count: int
    parsed_cases: List[Dict[str, Any]]  # populated only when is_valid is True


def _normalize_header(col_name: str) -> str:
    """Normalize a single column header to lowercase snake_case."""
    s = str(col_name).strip().strip("\ufeff").lower()
    return re.sub(r"[\s\-]+", "_", s)


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalize DataFrame column names to lowercase snake_case (e.g. 'Test Case ID' -> 'test_case_id').
    Raises ValueError if duplicate column names exist after normalization.
    """
    normalized: List[str] = []
    seen: set = set()
    duplicates: List[str] = []

    for col in df.columns:
        norm = _normalize_header(col)
        # Handle pandas duplicate suffix (.1, .2) if present from raw identical headers
        norm_base = re.sub(r"\.\d+$", "", norm) if "." in norm else norm
        if norm in seen or (norm_base in seen and norm != norm_base):
            target_dup = norm_base if norm_base in seen else norm
            if target_dup not in duplicates:
                duplicates.append(target_dup)
        seen.add(norm)
        seen.add(norm_base)
        normalized.append(norm_base)

    if duplicates:
        raise ValueError(
            f"Duplicate column(s) detected after header normalization: {', '.join(duplicates)}"
        )

    df.columns = normalized
    return df


def validate_csv(file_content: bytes, filename: str = "upload.csv") -> ValidationResult:
    """
    Validate the uploaded CSV bytes against the expected schema and business rules.

    Args:
        file_content: Raw bytes of the uploaded CSV file.
        filename: Original filename (used in error messages).

    Returns:
        ValidationResult with is_valid flag, errors, warnings, and parsed cases.
    """
    errors: List[ValidationError] = []
    warnings: List[ValidationError] = []

    # --- Parse CSV ---
    try:
        df = pd.read_csv(io.BytesIO(file_content), dtype=str)
    except Exception as exc:
        return ValidationResult(
            is_valid=False,
            errors=[ValidationError(row=0, column="file", message=f"Could not parse CSV: {exc}")],
            warnings=[],
            row_count=0,
            test_case_count=0,
            parsed_cases=[],
        )

    # --- Check for duplicate headers from raw CSV header line ---
    try:
        reader = csv.reader(io.StringIO(file_content.decode("utf-8", errors="replace")))
        raw_headers = next(reader, [])
    except Exception:
        raw_headers = list(df.columns)

    normalized_raw = [_normalize_header(c) for c in raw_headers]
    seen_raw: set = set()
    duplicate_raw: List[str] = []
    for c in normalized_raw:
        if c in seen_raw and c not in duplicate_raw:
            duplicate_raw.append(c)
        seen_raw.add(c)

    if duplicate_raw:
        return ValidationResult(
            is_valid=False,
            errors=[
                ValidationError(
                    row=0,
                    column=col,
                    message=f"Duplicate column '{col}' detected after header normalization.",
                )
                for col in duplicate_raw
            ],
            warnings=warnings,
            row_count=len(df),
            test_case_count=0,
            parsed_cases=[],
        )

    try:
        df = _normalize_columns(df)
    except ValueError as exc:
        msg = str(exc)
        dup_cols = (
            [c.strip() for c in msg.split(": ", 1)[1].split(",")]
            if ": " in msg
            else ["columns"]
        )
        return ValidationResult(
            is_valid=False,
            errors=[
                ValidationError(
                    row=0,
                    column=col,
                    message=f"Duplicate column '{col}' detected after header normalization.",
                )
                for col in dup_cols
            ],
            warnings=warnings,
            row_count=len(df),
            test_case_count=0,
            parsed_cases=[],
        )

    # --- Check required columns ---
    missing_cols = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing_cols:
        return ValidationResult(
            is_valid=False,
            errors=[
                ValidationError(
                    row=0,
                    column=col,
                    message=f"Required column '{col}' is missing.",
                )
                for col in missing_cols
            ],
            warnings=[],
            row_count=len(df),
            test_case_count=0,
            parsed_cases=[],
        )

    # Warn about extra columns that aren't in required list
    extra_cols = [c for c in df.columns if c not in REQUIRED_COLUMNS]
    for col in extra_cols:
        warnings.append(
            ValidationError(row=0, column=col, message=f"Unexpected column '{col}' will be ignored.")
        )

    if len(df) == 0:
        return ValidationResult(
            is_valid=False,
            errors=[ValidationError(row=0, column="file", message="CSV file is empty (no data rows).")],
            warnings=warnings,
            row_count=0,
            test_case_count=0,
            parsed_cases=[],
        )

    # --- Row-level validation ---
    # Track step numbers per test_case_id for sequential check
    step_tracker: Dict[str, List[int]] = {}

    for idx, row in df.iterrows():
        row_num = int(idx) + 2  # 1-indexed + header row

        test_case_id = str(row.get("test_case_id", "")).strip()
        action = str(row.get("action", "")).strip().lower()
        target = str(row.get("target", "")).strip()
        value = str(row.get("value", "")).strip()
        expected_result = str(row.get("expected_result", "")).strip()
        step_number_raw = str(row.get("step_number", "")).strip()

        # Treat pandas NaN as empty string
        if test_case_id in ("nan", ""):
            errors.append(
                ValidationError(row=row_num, column="test_case_id", message="test_case_id must not be empty.")
            )
            continue  # Can't meaningfully validate this row further

        # Validate step_number is an integer
        try:
            step_number = int(float(step_number_raw))
        except (ValueError, TypeError):
            errors.append(
                ValidationError(
                    row=row_num,
                    column="step_number",
                    message=f"step_number must be an integer, got '{step_number_raw}'.",
                )
            )
            step_number = None

        # Validate action
        if action not in SUPPORTED_ACTIONS:
            errors.append(
                ValidationError(
                    row=row_num,
                    column="action",
                    message=f"Unsupported action '{action}'. Supported: {SUPPORTED_ACTIONS}.",
                )
            )

        # Validate target not empty for actions that need it
        if action in ACTIONS_REQUIRING_TARGET and target in ("", "nan"):
            errors.append(
                ValidationError(
                    row=row_num,
                    column="target",
                    message=f"Action '{action}' requires a non-empty target.",
                )
            )

        # Validate value not empty for fill action
        if action in ACTIONS_REQUIRING_VALUE and value in ("", "nan"):
            errors.append(
                ValidationError(
                    row=row_num,
                    column="value",
                    message=f"Action '{action}' requires a non-empty value.",
                )
            )

        # Track step numbers for sequential check
        if step_number is not None:
            step_tracker.setdefault(test_case_id, []).append(step_number)

    # --- Sequential step number check per test_case_id ---
    for tc_id, step_nums in step_tracker.items():
        sorted_steps = sorted(step_nums)
        expected = list(range(1, len(sorted_steps) + 1))
        if sorted_steps != expected:
            errors.append(
                ValidationError(
                    row=0,
                    column="step_number",
                    message=(
                        f"test_case_id '{tc_id}' has non-sequential step numbers: "
                        f"{sorted_steps}. Expected: {expected}."
                    ),
                )
            )

    is_valid = len(errors) == 0

    # --- Build parsed_cases only when valid ---
    parsed_cases: List[Dict[str, Any]] = []
    if is_valid:
        for tc_id, group in df.groupby("test_case_id", sort=False):
            steps = []
            for _, row in group.sort_values("step_number").iterrows():
                step_number_raw = str(row.get("step_number", "")).strip()
                steps.append(
                    {
                        "step_number": int(float(step_number_raw)),
                        "action": str(row.get("action", "")).strip().lower(),
                        "target": _clean_val(row.get("target")),
                        "value": _clean_val(row.get("value")),
                        "expected_result": _clean_val(row.get("expected_result")),
                    }
                )
            test_name = str(group["test_name"].iloc[0]).strip() if "test_name" in group.columns else tc_id
            parsed_cases.append(
                {
                    "test_case_id": tc_id,
                    "test_name": test_name,
                    "steps": steps,
                }
            )

    unique_test_cases = df["test_case_id"].nunique() if "test_case_id" in df.columns else 0

    return ValidationResult(
        is_valid=is_valid,
        errors=errors,
        warnings=warnings,
        row_count=len(df),
        test_case_count=unique_test_cases,
        parsed_cases=parsed_cases,
    )


def _clean_val(val: Any) -> Optional[str]:
    """Convert pandas NaN / 'nan' string to None; otherwise return stripped string."""
    if val is None:
        return None
    s = str(val).strip()
    if s.lower() == "nan" or s == "":
        return None
    return s
