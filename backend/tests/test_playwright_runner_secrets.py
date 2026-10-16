"""Tests for server-side Playwright fill secrets."""
import json
import secrets
import sys
from types import ModuleType
from urllib.parse import quote, quote_plus

import pytest

from app.schemas.test_run import TestResultResponse as RunResultResponse
from app.services.playwright_runner import _execute_playwright


class FakePage:
    def __init__(self, fill_error=None, discovery_inventory=None, url="about:blank"):
        self.fills = []
        self.navigations = []
        self.fill_error = fill_error
        self.video = None
        self.url = url
        self.screenshot_calls = []
        self.context_options = {}
        self.discovery_inventory = discovery_inventory

    def set_default_timeout(self, _timeout):
        pass

    async def evaluate(self, _script):
        return self.discovery_inventory

    async def fill(self, target, value):
        self.fills.append((target, value))
        if self.fill_error:
            raise RuntimeError(self.fill_error(value))

    async def goto(self, url, **_kwargs):
        self.navigations.append(url)
        self.url = url

    async def screenshot(self, **_kwargs):
        self.screenshot_calls.append(_kwargs)


class FakeContext:
    def __init__(self, page):
        self.page = page

    async def new_page(self):
        return self.page

    async def close(self):
        pass


class FakeVideo:
    def __init__(self, path):
        self._path = path

    async def path(self):
        return self._path


class FakeBrowser:
    def __init__(self, page):
        self.context = FakeContext(page)

    async def new_context(self, **_kwargs):
        self.context.page.context_options = _kwargs
        return self.context

    async def close(self):
        pass


class FakeChromium:
    def __init__(self, page):
        self.page = page

    async def launch(self, **_kwargs):
        return FakeBrowser(self.page)


class FakePlaywright:
    def __init__(self, page):
        self.chromium = FakeChromium(page)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc_info):
        pass


def install_fake_playwright(monkeypatch, page):
    playwright_module = ModuleType("playwright")
    async_api_module = ModuleType("playwright.async_api")
    async_api_module.async_playwright = lambda: FakePlaywright(page)
    playwright_module.async_api = async_api_module
    monkeypatch.setitem(sys.modules, "playwright", playwright_module)
    monkeypatch.setitem(sys.modules, "playwright.async_api", async_api_module)


async def execute_steps(tmp_path, steps):
    return await _execute_playwright(
        steps=steps,
        app_url="",
        artifacts_dir=str(tmp_path),
        run_id="run-id",
        test_case_id="result-id",
    )


async def execute_fill(tmp_path, value, target="#username"):
    return await execute_steps(
        tmp_path,
        [
            {
                "step_number": 1,
                "action": "fill",
                "target": target,
                "value": value,
            }
        ],
    )


@pytest.mark.asyncio
async def test_fill_resolves_server_side_secret(monkeypatch, tmp_path):
    secret = secrets.token_urlsafe(24)
    monkeypatch.setenv("NOETRIX_TEST_APEX_USERNAME", secret)
    page = FakePage()
    install_fake_playwright(monkeypatch, page)

    outcome = await execute_fill(tmp_path, "${secret:NOETRIX_TEST_APEX_USERNAME}")

    assert outcome["status"] == "passed"
    assert page.fills == [("#username", secret)]
    assert "record_video_dir" not in page.context_options
    assert secret not in "\n".join(outcome["log_lines"])
    assert "${secret:NOETRIX_TEST_APEX_USERNAME}" not in "\n".join(
        outcome["log_lines"]
    )


@pytest.mark.asyncio
async def test_missing_secret_fails_without_logging_value_or_reference(
    monkeypatch, tmp_path
):
    variable_name = "NOETRIX_TEST_MISSING_SECRET"
    monkeypatch.delenv(variable_name, raising=False)
    page = FakePage()
    install_fake_playwright(monkeypatch, page)

    outcome = await execute_fill(
        tmp_path,
        f"${{secret:{variable_name}}}",
        target="#password",
    )

    logs = "\n".join(outcome["log_lines"])
    report_text = RunResultResponse(
        id="result-id",
        run_id="run-id",
        status="failed",
        error_message=outcome["error_message"],
    ).model_dump_json()
    assert outcome["status"] == "failed"
    assert outcome["error_message"] == "Step 1 (fill) failed: Required secret is not configured."
    assert variable_name not in logs + outcome["error_message"] + report_text
    assert f"${{secret:{variable_name}}}" not in logs + report_text
    assert page.fills == []


@pytest.mark.asyncio
async def test_resolved_secret_is_redacted_from_fill_exception_and_logs(
    monkeypatch, tmp_path
):
    secret = f"{secrets.token_urlsafe(18)}/a b?"
    monkeypatch.setenv("NOETRIX_TEST_APEX_PASSWORD", secret)
    encoded_secret = quote(secret, safe="")
    plus_encoded_secret = quote_plus(secret)
    page = FakePage(
        fill_error=lambda value: (
            f"failed to fill raw={value}, encoded={encoded_secret}, "
            f"form_encoded={plus_encoded_secret}"
        )
    )
    install_fake_playwright(monkeypatch, page)

    outcome = await execute_fill(
        tmp_path,
        "${secret:NOETRIX_TEST_APEX_PASSWORD}",
        target="#password",
    )

    logs = "\n".join(outcome["log_lines"])
    assert outcome["status"] == "failed"
    assert secret not in logs
    assert encoded_secret not in logs
    assert plus_encoded_secret not in logs
    assert secret not in outcome["error_message"]
    assert encoded_secret not in outcome["error_message"]
    assert plus_encoded_secret not in outcome["error_message"]
    assert "${secret:NOETRIX_TEST_APEX_PASSWORD}" not in logs
    assert page.screenshot_calls == []
    assert outcome["screenshot_path"] is None


@pytest.mark.asyncio
async def test_secret_case_does_not_inherit_previous_case_video(
    monkeypatch, tmp_path
):
    secret = secrets.token_urlsafe(24)
    monkeypatch.setenv("NOETRIX_TEST_APEX_USERNAME", secret)
    videos_dir = tmp_path / "runs" / "run-id" / "videos"
    videos_dir.mkdir(parents=True)
    previous_video = videos_dir / "previous-case.webm"
    previous_video.write_bytes(b"previous test video")

    page = FakePage()
    page.video = FakeVideo(str(previous_video))
    install_fake_playwright(monkeypatch, page)
    outcome = await execute_fill(
        tmp_path,
        "${secret:NOETRIX_TEST_APEX_USERNAME}",
    )

    assert "record_video_dir" not in page.context_options
    assert outcome["video_path"] is None
    assert previous_video.exists()
    assert previous_video.read_bytes() == b"previous test video"


@pytest.mark.asyncio
async def test_discovery_and_error_output_redact_resolved_secret(
    monkeypatch, tmp_path
):
    secret = f"{secrets.token_urlsafe(18)}/a b?"
    encoded_secret = quote(secret, safe="")
    plus_encoded_secret = quote_plus(secret)
    monkeypatch.setenv("NOETRIX_TEST_APEX_USERNAME", secret)
    page = FakePage(
        discovery_inventory={
            "url": (
                f"https://example.invalid/?user={secret}&encoded={encoded_secret}"
                f"&form_encoded={plus_encoded_secret}"
            ),
            "elements": [
                {
                    "tag": "input",
                    "accessibleName": "Username",
                    "value": secret,
                }
            ],
            "headings": [{"text": "Time Log"}],
        },
        url=(
            f"https://example.invalid/?user={secret}&encoded={encoded_secret}"
            f"&form_encoded={plus_encoded_secret}"
        ),
    )
    install_fake_playwright(monkeypatch, page)

    outcome = await execute_steps(
        tmp_path,
        [
            {
                "step_number": 1,
                "action": "fill",
                "target": "#username",
                "value": "${secret:NOETRIX_TEST_APEX_USERNAME}",
            },
            {"step_number": 2, "action": "discover_page"},
            {
                "step_number": 3,
                "action": "verify_url",
                "expected_result": "expected-path",
            },
        ],
    )

    discovery = json.loads(
        (tmp_path / "runs" / "run-id" / "results" / "result-id" / "discovery.json")
        .read_text(encoding="utf-8")
    )
    logs = "\n".join(outcome["log_lines"])
    report_text = RunResultResponse(
        id="result-id",
        run_id="run-id",
        status="failed",
        error_message=outcome["error_message"],
    ).model_dump_json()
    assert discovery["elements"][0]["accessibleName"] == "Username"
    assert discovery["headings"][0]["text"] == "Time Log"
    combined_output = (
        json.dumps(discovery) + logs + outcome["error_message"] + report_text
    )
    assert secret not in combined_output
    assert encoded_secret not in combined_output
    assert plus_encoded_secret not in combined_output
    assert outcome["status"] == "failed"


@pytest.mark.asyncio
async def test_fill_preserves_ordinary_literal_value(monkeypatch, tmp_path):
    literal = "ordinary non-secret text"
    page = FakePage()
    install_fake_playwright(monkeypatch, page)

    outcome = await execute_fill(tmp_path, literal, target="#password")

    assert outcome["status"] == "passed"
    assert page.fills == [("#password", literal)]
    assert "record_video_dir" in page.context_options
    assert literal not in "\n".join(outcome["log_lines"])


@pytest.mark.asyncio
async def test_non_fill_secret_reference_remains_literal(monkeypatch, tmp_path):
    secret = secrets.token_urlsafe(24)
    monkeypatch.setenv("NOETRIX_TEST_NAVIGATION_VALUE", secret)
    page = FakePage()
    install_fake_playwright(monkeypatch, page)
    reference = "${secret:NOETRIX_TEST_NAVIGATION_VALUE}"

    outcome = await execute_steps(
        tmp_path,
        [{"step_number": 1, "action": "navigate", "value": reference}],
    )

    assert outcome["status"] == "passed"
    assert page.navigations == [reference]
    assert page.navigations[0] != secret


@pytest.mark.asyncio
async def test_ordinary_literal_fill_keeps_existing_failure_screenshot_behavior(
    monkeypatch, tmp_path
):
    literal = "ordinary username"
    page = FakePage(url="https://example.invalid/current")
    install_fake_playwright(monkeypatch, page)

    outcome = await execute_steps(
        tmp_path,
        [
            {
                "step_number": 1,
                "action": "fill",
                "target": "#username",
                "value": literal,
            },
            {
                "step_number": 2,
                "action": "verify_url",
                "expected_result": "expected-path",
            },
        ],
    )

    assert outcome["status"] == "failed"
    assert page.fills == [("#username", literal)]
    assert page.screenshot_calls
    assert "record_video_dir" in page.context_options


@pytest.mark.asyncio
async def test_sensitive_selector_literal_still_skips_failure_screenshot(
    monkeypatch, tmp_path
):
    literal = f"{secrets.token_urlsafe(16)}-password"
    page = FakePage(url="https://example.invalid/current")
    install_fake_playwright(monkeypatch, page)

    outcome = await execute_steps(
        tmp_path,
        [
            {
                "step_number": 1,
                "action": "fill",
                "target": "#password",
                "value": literal,
            },
            {
                "step_number": 2,
                "action": "verify_url",
                "expected_result": "expected-path",
            },
        ],
    )

    assert outcome["status"] == "failed"
    assert page.fills == [("#password", literal)]
    assert page.screenshot_calls == []
    assert outcome["screenshot_path"] is None
