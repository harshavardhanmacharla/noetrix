"""
Result Diagnostics & Step Details Service for Noetrix.

Extracts, enriches, and structures step-level execution details,
durations, verification outcomes, and failure categorization
from disk artifacts (steps.json) and database records.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.test_case import TestCase
from app.models.test_run import Artifact, TestResult, TestRun
from app.schemas.test_run import (
    ArtifactResponse,
    RunReportResponse,
    StepDetailResponse,
    StepSummaryResponse,
    TestResultResponse,
    TestRunResponse,
)

settings = get_settings()


def categorize_error_string(error_msg: str, action: Optional[str] = None) -> tuple[str, str]:
    """
    Categorize an error message string into a clean failure category code and human-readable label.
    """
    if not error_msg:
        return "execution_error", "Execution Error"
    
    msg_lower = error_msg.lower()
    if "ambiguous target" in msg_lower or "matches" in msg_lower and "visible elements" in msg_lower:
        return "ambiguous_target", "Ambiguous Target"
    if "could not find any" in msg_lower or ("not found" in msg_lower and "text" not in msg_lower):
        return "missing_element", "Missing Element"
    if "url verification failed" in msg_lower or "was not found as visible text" in msg_lower or "assertion" in msg_lower or "unexpectedly" in msg_lower or "negative" in msg_lower:
        return "assertion_failure", "Assertion Failed"
    if "timeout" in msg_lower or "timed out" in msg_lower:
        return "timeout", "Timeout"
    if "unsupported action" in msg_lower or "requires" in msg_lower or "syntax" in msg_lower:
        return "parsing_failure", "Syntax / Action Error"
    return "execution_error", "Execution Error"


import re

def sanitize_secret_text(val: Optional[str]) -> Optional[str]:
    """Redact secret placeholder patterns and references from text."""
    if val is None:
        return None
    return re.sub(r"\$\{secret:[^}]*\}?", "[REDACTED]", str(val))


def load_result_step_details(
    result: TestResult, db: Session
) -> tuple[List[StepDetailResponse], StepSummaryResponse]:
    """
    Load structured step details and step summary for a TestResult.
    Checks:
      1. steps.json on disk in settings.ARTIFACTS_DIR / runs / <run_id> / results / <result_id> / steps.json
      2. Artifact record pointing to steps.json
      3. Fallback: synthesize step details from TestCase.steps + result status/error
    """
    steps_responses: List[StepDetailResponse] = []
    
    # 1. Try disk path
    base_dir = Path(settings.ARTIFACTS_DIR).resolve()
    possible_paths = [
        base_dir / "runs" / result.run_id / "results" / result.id / "steps.json",
    ]
    
    # Also check artifacts in DB
    for art in result.artifacts:
        if art.file_path and "steps.json" in art.file_path:
            p = Path(art.file_path)
            if not p.is_absolute():
                p = base_dir / art.file_path
            possible_paths.append(p)
            
    loaded_from_artifact = False
    for p in possible_paths:
        if p.exists() and p.is_file():
            try:
                content = p.read_text(encoding="utf-8")
                raw_steps = json.loads(content)
                if isinstance(raw_steps, list):
                    for s in raw_steps:
                        if isinstance(s, dict):
                            # Ensure defense-in-depth redaction
                            s_clean = dict(s)
                            s_clean["value"] = sanitize_secret_text(s_clean.get("value"))
                            s_clean["target"] = sanitize_secret_text(s_clean.get("target"))
                            s_clean["expected_result"] = sanitize_secret_text(s_clean.get("expected_result"))
                            s_clean["original_instruction"] = sanitize_secret_text(s_clean.get("original_instruction"))
                            s_clean["failure_reason"] = sanitize_secret_text(s_clean.get("failure_reason"))
                            steps_responses.append(StepDetailResponse(**s_clean))
                    loaded_from_artifact = True
                    break
            except Exception:
                pass

    # 2. Fallback if no steps.json exists (e.g. legacy test runs or mock runs)
    if not loaded_from_artifact:
        tc = result.test_case
        if not tc and result.test_case_id:
            tc = db.query(TestCase).filter(TestCase.id == result.test_case_id).first()

        if tc and tc.steps:
            sorted_tc_steps = sorted(tc.steps, key=lambda s: s.step_number)
            failed_step_num = None
            if result.status in ("failed", "error") and result.error_message:
                # Look for "Step X (action) failed:"
                m = re.search(r"Step\s+(\d+)", result.error_message, re.IGNORECASE)
                if m:
                    failed_step_num = int(m.group(1))

            for tc_s in sorted_tc_steps:
                s_num = tc_s.step_number
                raw_val = str(tc_s.value or "")
                raw_target = str(tc_s.target or "")
                is_sensitive = (
                    tc_s.action == "fill"
                    and (
                        "${secret:" in raw_val
                        or any(w in raw_target.lower() for w in ("password", "passwd", "secret", "token"))
                    )
                )
                safe_val = "[REDACTED]" if is_sensitive else sanitize_secret_text(tc_s.value)
                safe_target = sanitize_secret_text(tc_s.target)
                safe_exp = sanitize_secret_text(tc_s.expected_result)
                safe_orig = sanitize_secret_text(f"{tc_s.action} {safe_target or ''}".strip())

                if result.status == "passed":
                    s_status = "passed"
                    cat = None
                    reason = None
                elif failed_step_num is not None:
                    if s_num < failed_step_num:
                        s_status = "passed"
                        cat = None
                        reason = None
                    elif s_num == failed_step_num:
                        s_status = "failed"
                        cat, _ = categorize_error_string(result.error_message or "", tc_s.action)
                        reason = sanitize_secret_text(result.error_message)
                    else:
                        s_status = "skipped"
                        cat = None
                        reason = None
                else:
                    # No specific step identified
                    if s_num == 1 and result.status in ("failed", "error"):
                        s_status = "failed"
                        cat, _ = categorize_error_string(result.error_message or "", tc_s.action)
                        reason = sanitize_secret_text(result.error_message)
                    else:
                        s_status = "skipped" if result.status in ("failed", "error") else "passed"
                        cat = None
                        reason = None

                steps_responses.append(
                    StepDetailResponse(
                        step_number=s_num,
                        action=tc_s.action,
                        target=safe_target,
                        value=safe_val,
                        expected_result=safe_exp,
                        original_instruction=safe_orig,
                        status=s_status,
                        duration_ms=None,
                        category=cat,
                        failure_reason=reason,
                        verification_result=None,
                    )
                )

    # 3. Compute StepSummaryResponse
    total = len(steps_responses)
    passed = sum(1 for s in steps_responses if s.status == "passed")
    failed = sum(1 for s in steps_responses if s.status in ("failed", "error"))
    skipped = sum(1 for s in steps_responses if s.status == "skipped")

    summary = StepSummaryResponse(
        total=total,
        passed=passed,
        failed=failed,
        skipped=skipped,
    )

    return steps_responses, summary


def build_test_result_response(result: TestResult, db: Session) -> TestResultResponse:
    """Build a complete TestResultResponse including steps and step summary."""
    steps, summary = load_result_step_details(result, db)
    resp = TestResultResponse.model_validate(result)
    resp.steps = steps
    resp.step_summary = summary
    for art in result.artifacts:
        if art.artifact_type == 'video' and art.file_path:
            resp.video_path = art.file_path
            break
    return resp


def enrich_test_run_response(
    run: TestRun, results: Optional[List[TestResult]], db: Session
) -> TestRunResponse:
    """Build a TestRunResponse with aggregated step counts across all test results."""
    resp = TestRunResponse.model_validate(run)
    if results is None:
        results = db.query(TestResult).filter(TestResult.run_id == run.id).all()

    total_steps = 0
    passed_steps = 0
    failed_steps = 0
    skipped_steps = 0

    for r in results:
        _, s_sum = load_result_step_details(r, db)
        total_steps += s_sum.total
        passed_steps += s_sum.passed
        failed_steps += s_sum.failed
        skipped_steps += s_sum.skipped

    resp.total_steps = total_steps
    resp.passed_steps = passed_steps
    resp.failed_steps = failed_steps
    resp.skipped_steps = skipped_steps
    return resp


def build_run_report_response(
    run: TestRun,
    results: List[TestResult],
    artifacts: List[Artifact],
    db: Session,
) -> RunReportResponse:
    """Build a comprehensive RunReportResponse with enriched results, step metrics, and summary."""
    enriched_results: List[TestResultResponse] = []
    total_steps = 0
    passed_steps = 0
    failed_steps = 0
    skipped_steps = 0

    for r in results:
        res_resp = build_test_result_response(r, db)
        enriched_results.append(res_resp)
        if res_resp.step_summary:
            total_steps += res_resp.step_summary.total
            passed_steps += res_resp.step_summary.passed
            failed_steps += res_resp.step_summary.failed
            skipped_steps += res_resp.step_summary.skipped

    # Run summary
    total = len(results)
    passed = sum(1 for r in results if r.status == "passed")
    failed = sum(1 for r in results if r.status == "failed")
    errors = sum(1 for r in results if r.status == "error")
    skipped = sum(1 for r in results if r.status == "skipped")

    duration_sec = None
    if run.started_at and run.completed_at:
        duration_sec = (run.completed_at - run.started_at).total_seconds()

    summary: Dict[str, Any] = {
        "total": total,
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "skipped": skipped,
        "pass_rate": round(passed / total * 100, 2) if total > 0 else 0.0,
        "duration_seconds": duration_sec,
        "total_steps": total_steps,
        "passed_steps": passed_steps,
        "failed_steps": failed_steps,
        "skipped_steps": skipped_steps,
        "step_pass_rate": round(passed_steps / total_steps * 100, 2) if total_steps > 0 else 0.0,
    }

    run_resp = enrich_test_run_response(run, results, db)

    return RunReportResponse(
        run=run_resp,
        results=enriched_results,
        artifacts=[ArtifactResponse.model_validate(a) for a in artifacts],
        summary=summary,
    )
