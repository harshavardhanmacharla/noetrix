"""
Tests for Playwright browser lifecycle monitoring, navigation hardening, and resilient teardown.
"""
import asyncio
from pathlib import Path
from typing import Any, Dict, List
import pytest

from app.services.playwright_runner import (
    _execute_playwright,
    categorize_step_error,
)
from tests.test_playwright_runner_secrets import install_fake_playwright, FakePage


class LifecycleTrackingPage(FakePage):
    def __init__(self, goto_error=None, url="https://example.com/login"):
        super().__init__(url=url)
        self.goto_error = goto_error
        self.events: Dict[str, List[Any]] = {}
        self._closed = False
        self.nav_timeout = None
        self.wait_load_called = False

    def on(self, event: str, callback: Any):
        self.events.setdefault(event, []).append(callback)

    def set_default_navigation_timeout(self, timeout: int):
        self.nav_timeout = timeout

    def is_closed(self) -> bool:
        return self._closed

    async def wait_for_load_state(self, state: str, timeout: int = 5000):
        self.wait_load_called = True

    async def goto(self, url: str, **kwargs):
        if self.goto_error:
            self._closed = True
            raise self.goto_error
        self.navigations.append(url)
        self.url = url


class LifecycleTrackingContext:
    def __init__(self, page):
        self.page = page
        self.events: Dict[str, List[Any]] = {}
        self.close_error = None

    def on(self, event: str, callback: Any):
        self.events.setdefault(event, []).append(callback)

    async def new_page(self):
        return self.page

    async def close(self):
        if self.close_error:
            raise self.close_error


class LifecycleTrackingBrowser:
    def __init__(self, page, close_error=None):
        self.page = page
        self.context = LifecycleTrackingContext(page)
        self.events: Dict[str, List[Any]] = {}
        self._connected = True
        self.close_error = close_error

    def on(self, event: str, callback: Any):
        self.events.setdefault(event, []).append(callback)

    def is_connected(self) -> bool:
        return self._connected

    async def new_context(self, **kwargs):
        self.context.page.context_options = kwargs
        return self.context

    async def close(self):
        self._connected = False
        if self.close_error:
            raise self.close_error


class LifecycleTrackingChromium:
    def __init__(self, page, browser_close_error=None):
        self.page = page
        self.browser_close_error = browser_close_error
        self.last_launch_args = None

    async def launch(self, **kwargs):
        self.last_launch_args = kwargs.get("args")
        return LifecycleTrackingBrowser(self.page, close_error=self.browser_close_error)


class LifecycleTrackingPlaywright:
    def __init__(self, page, browser_close_error=None):
        self.chromium = LifecycleTrackingChromium(page, browser_close_error=browser_close_error)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


@pytest.mark.asyncio
async def test_navigation_success_registers_lifecycle_and_stabilizes(monkeypatch, tmp_path):
    """Verify that browser launch args, lifecycle events, and load state stabilization work."""
    page = LifecycleTrackingPage(url="https://oracleapex.com/ords/r/test/login")
    pw = LifecycleTrackingPlaywright(page)

    import sys
    from types import ModuleType
    playwright_module = ModuleType("playwright")
    async_api_module = ModuleType("playwright.async_api")
    async_api_module.async_playwright = lambda: pw
    playwright_module.async_api = async_api_module
    monkeypatch.setitem(sys.modules, "playwright", playwright_module)
    monkeypatch.setitem(sys.modules, "playwright.async_api", async_api_module)

    steps = [
        {
            "step_number": 1,
            "action": "navigate",
            "target": None,
            "value": "https://oracleapex.com/ords/r/test/login",
            "expected_result": "Login page",
        }
    ]

    result = await _execute_playwright(
        steps=steps,
        app_url="",
        artifacts_dir=str(tmp_path),
        run_id="run_lifecycle_test",
        test_case_id="tc_lifecycle_test",
    )

    assert result["status"] == "passed"
    assert "crash" in page.events
    assert "close" in page.events
    assert page.wait_load_called is True
    assert "--no-sandbox" in pw.chromium.last_launch_args
    assert "--disable-gpu" in pw.chromium.last_launch_args
    assert "--disable-dev-shm-usage" in pw.chromium.last_launch_args

    log_text = "\n".join(result["log_lines"])
    assert "Navigated successfully to: https://oracleapex.com/ords/r/test/login" in log_text


@pytest.mark.asyncio
async def test_navigation_target_closed_error_diagnostics(monkeypatch, tmp_path):
    """Verify that TargetClosedError during navigation logs browser/page status cleanly."""
    err = RuntimeError("Page.goto: Target page, context or browser has been closed")
    page = LifecycleTrackingPage(goto_error=err)
    pw = LifecycleTrackingPlaywright(page)

    import sys
    from types import ModuleType
    playwright_module = ModuleType("playwright")
    async_api_module = ModuleType("playwright.async_api")
    async_api_module.async_playwright = lambda: pw
    playwright_module.async_api = async_api_module
    monkeypatch.setitem(sys.modules, "playwright", playwright_module)
    monkeypatch.setitem(sys.modules, "playwright.async_api", async_api_module)

    steps = [
        {
            "step_number": 1,
            "action": "navigate",
            "target": None,
            "value": "https://oracleapex.com/ords/r/test/login",
            "expected_result": "Login page",
        }
    ]

    result = await _execute_playwright(
        steps=steps,
        app_url="",
        artifacts_dir=str(tmp_path),
        run_id="run_nav_err",
        test_case_id="tc_nav_err",
    )

    assert result["status"] == "failed"
    step1 = result["steps"][0]
    assert step1["status"] == "failed"
    assert step1["category"] == "execution_error"
    assert "Target page, context or browser has been closed" in step1["failure_reason"]

    log_text = "\n".join(result["log_lines"])
    assert "Navigation error during goto" in log_text
    assert "browser_connected=" in log_text
    assert "Failure screenshot skipped: browser page is already closed" in log_text


@pytest.mark.asyncio
async def test_cleanup_resilience_on_close_exception(monkeypatch, tmp_path):
    """Verify that exceptions during context.close or browser.close do not crash the runner."""
    page = LifecycleTrackingPage()
    pw = LifecycleTrackingPlaywright(page, browser_close_error=RuntimeError("Browser process already gone"))
    pw.chromium.page = page

    import sys
    from types import ModuleType
    playwright_module = ModuleType("playwright")
    async_api_module = ModuleType("playwright.async_api")
    async_api_module.async_playwright = lambda: pw
    playwright_module.async_api = async_api_module
    monkeypatch.setitem(sys.modules, "playwright", playwright_module)
    monkeypatch.setitem(sys.modules, "playwright.async_api", async_api_module)

    steps = [
        {
            "step_number": 1,
            "action": "navigate",
            "target": None,
            "value": "https://example.com",
            "expected_result": None,
        }
    ]

    result = await _execute_playwright(
        steps=steps,
        app_url="",
        artifacts_dir=str(tmp_path),
        run_id="run_cleanup_err",
        test_case_id="tc_cleanup_err",
    )

    assert result["status"] == "passed"
    log_text = "\n".join(result["log_lines"])
    assert "Notice closing browser: Browser process already gone" in log_text
    assert "Browser session closed." in log_text

