"""
Pytest integration for Phase 8 Benchmark Suite.
Runs parser benchmark, browser scenarios, and validates benchmark assertions.
"""
from __future__ import annotations

import pytest
from scripts.run_benchmark import (
    EphemeralBenchmarkServer,
    run_parser_benchmark,
    run_e2e_benchmark,
    run_repeatability_benchmark,
)


@pytest.mark.asyncio
async def test_benchmark_parser_suite_accuracy():
    """Verify that deterministic parser accuracy achieves 100% on ground-truth benchmark cases."""
    report = await run_parser_benchmark()
    assert report["accuracy_pct"] == 100.0, f"Parser accuracy {report['accuracy_pct']}% != 100%"
    assert report["ambiguity_accuracy_pct"] == 100.0, f"Ambiguity accuracy {report['ambiguity_accuracy_pct']}% != 100%"
    assert report["correct_cases"] == report["total_cases"]


@pytest.mark.asyncio
async def test_benchmark_real_browser_e2e_conformance(tmp_path):
    """Verify that all real-browser E2E benchmark scenarios match explicit ground truth."""
    server = EphemeralBenchmarkServer()
    server.start()
    try:
        report = await run_e2e_benchmark(server.base_url, tmp_path)
        assert report["overall_conformance_pct"] == 100.0, f"E2E conformance {report['overall_conformance_pct']}% != 100%"
        assert report["task_success_rate_pct"] == 100.0, f"Task success rate {report['task_success_rate_pct']}% != 100%"
        assert report["false_positive_pass_rate_pct"] == 0.0, f"False-positive pass rate {report['false_positive_pass_rate_pct']}% != 0%"
    finally:
        server.stop()


@pytest.mark.asyncio
async def test_benchmark_repeatability_and_flakiness(tmp_path):
    """Verify that repeated executions across distinct rounds exhibit zero flakiness."""
    server = EphemeralBenchmarkServer()
    server.start()
    try:
        report = await run_repeatability_benchmark(server.base_url, tmp_path, repetitions=3)
        assert report["flakiness_rate_pct"] == 0.0, f"Flakiness rate {report['flakiness_rate_pct']}% != 0%"
        assert report["flaky_scenarios_count"] == 0
    finally:
        server.stop()
