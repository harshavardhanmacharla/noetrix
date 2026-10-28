"""
Data-driven testing service for Noetrix.

Provides placeholder extraction, dynamic column filtering against project variables,
record validation, safe runtime substitution, and sensitive value masking for UI-based
data-driven test execution.
"""
from __future__ import annotations

import copy
import re
from typing import Any, Collection, Dict, List, Optional, Set, Tuple

# Matches explicit double curly-brace placeholders: {{first_name}}, {{last_name}}, etc.
PLACEHOLDER_PATTERN = re.compile(r"\{\{([a-zA-Z_][a-zA-Z0-9_]*)\}\}")

SENSITIVE_KEY_SUBSTRINGS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "auth",
    "credential",
)


def extract_placeholders_from_text(text: Optional[str]) -> Set[str]:
    """Extract all placeholder variable names from a string."""
    if not text:
        return set()
    return set(PLACEHOLDER_PATTERN.findall(text))


def extract_test_case_placeholders(steps: List[Any]) -> List[str]:
    """
    Extract a sorted list of unique placeholder variable names across all steps
    of a test case (from value, target, and expected_result fields).
    """
    found: Set[str] = set()
    for step in steps:
        if isinstance(step, dict):
            val = step.get("value")
            tgt = step.get("target")
            exp = step.get("expected_result")
        else:
            val = getattr(step, "value", None)
            tgt = getattr(step, "target", None)
            exp = getattr(step, "expected_result", None)

        found.update(extract_placeholders_from_text(str(val) if val is not None else None))
        found.update(extract_placeholders_from_text(str(tgt) if tgt is not None else None))
        found.update(extract_placeholders_from_text(str(exp) if exp is not None else None))

    return sorted(list(found))


def filter_data_columns(
    all_placeholders: List[str],
    configured_project_variables: Optional[Collection[str]] = None,
) -> List[str]:
    """
    Calculate data-entry columns by excluding variables configured at the project level:
    data_columns = detected_placeholders - configured_project_variable_names
    """
    excluded = set(configured_project_variables or [])
    return sorted([p for p in all_placeholders if p not in excluded])


def validate_record_data(
    placeholders: List[str],
    records: List[Dict[str, Any]],
    project_variables: Optional[Collection[str]] = None,
) -> Tuple[bool, List[str]]:
    """
    Validate that:
      1. At least one record is provided.
      2. If project_variables is supplied, only remaining data columns are required.
      3. Every record contains all remaining required placeholder keys.
      4. No required placeholder values are missing, None, or empty whitespace.
    """
    errors: List[str] = []

    if not records:
        errors.append("At least one test data record is required.")
        return False, errors

    proj_var_set = set(project_variables or [])
    required_cols = [p for p in placeholders if p not in proj_var_set]

    if not required_cols:
        if placeholders:
            errors.append(
                "All detected placeholders are configured in Project Test Variables. "
                "Data-driven execution requires at least one custom data column."
            )
        else:
            errors.append("Selected test case has no placeholder variables to map data against.")
        return False, errors

    for idx, rec in enumerate(records, start=1):
        if not isinstance(rec, dict):
            errors.append(f"Record #{idx} is invalid; expected key-value mapping.")
            continue

        for ph in required_cols:
            if ph not in rec:
                errors.append(f"Record #{idx}: missing required field '{{{{{ph}}}}}'.")
            else:
                raw_val = rec[ph]
                if raw_val is None or str(raw_val).strip() == "":
                    errors.append(f"Record #{idx}: field '{{{{{ph}}}}}' cannot be empty.")

    return len(errors) == 0, errors


def substitute_record_placeholders(
    steps: List[Dict[str, Any]],
    record: Dict[str, Any],
    allowed_missing: Optional[Collection[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Create a deep copy of test steps and replace placeholders with record values.
    
    Guarantees:
      - Does NOT mutate the input steps list or its dictionary items.
      - Handles values with spaces, punctuation, symbols, and Unicode strings.
      - If a placeholder is missing from the record:
          * If it is listed in `allowed_missing` (configured at project level),
            it is left untouched so Playwright resolves and decrypts it at runtime.
          * Otherwise, raises ValueError.
    """
    cloned_steps = copy.deepcopy(steps)
    allowed_set = set(allowed_missing or [])

    def _replace_in_text(text: Optional[str]) -> Optional[str]:
        if not text:
            return text

        def _repl(m: re.Match) -> str:
            var_name = m.group(1)
            if var_name not in record:
                if var_name in allowed_set:
                    return m.group(0)  # Preserve {{var_name}} for project variable resolution
                raise ValueError(
                    f"Required data placeholder '{{{{{var_name}}}}}' is missing from test data record "
                    "and is not configured as a project variable."
                )
            val = record[var_name]
            return str(val) if val is not None else ""

        return PLACEHOLDER_PATTERN.sub(_repl, text)

    for step in cloned_steps:
        if "value" in step and step["value"] is not None:
            step["value"] = _replace_in_text(str(step["value"]))
        if "target" in step and step["target"] is not None:
            step["target"] = _replace_in_text(str(step["target"]))
        if "expected_result" in step and step["expected_result"] is not None:
            step["expected_result"] = _replace_in_text(str(step["expected_result"]))

    return cloned_steps


def mask_sensitive_record_values(record: Dict[str, Any]) -> Dict[str, str]:
    """
    Return a copy of the record with sensitive fields (passwords, tokens, keys) redacted.
    Useful for safe diagnostic logging and UI display.
    """
    safe_rec: Dict[str, str] = {}
    for k, v in record.items():
        k_lower = k.lower()
        if any(sens in k_lower for sens in SENSITIVE_KEY_SUBSTRINGS):
            safe_rec[k] = "[REDACTED]"
        else:
            safe_rec[k] = str(v) if v is not None else ""
    return safe_rec
