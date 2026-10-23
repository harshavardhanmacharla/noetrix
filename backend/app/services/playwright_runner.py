"""
Playwright test runner service.
Executes test steps asynchronously using Playwright and captures artifacts.
Supports Windows ProactorEventLoop isolation for async subprocess execution.
"""
import asyncio
import json
import os
import re
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote, quote_plus, unquote_plus

from app.config import get_settings
from app.services.locator_resolver import (
    AmbiguousElementError,
    ElementNotFoundError,
    is_direct_selector,
    resolve_locator,
)

settings = get_settings()

NOT_CONFIGURED_MSG = (
    "Playwright browser not configured. Run: playwright install chromium"
)


def categorize_step_error(exc: Exception, action: str, msg: str) -> tuple[str, str]:
    """
    Categorize a step exception into a clean, human-readable failure category and display label.
    Categories:
      - missing_element: Element could not be found or resolved
      - ambiguous_target: Multiple elements matched the target
      - assertion_failure: Text/URL verification assertion failed
      - timeout: Action or navigation timed out
      - parsing_failure: Invalid input, missing required target/value, or unsupported action
      - execution_error: Unhandled browser or execution error
    """
    msg_lower = msg.lower()
    if isinstance(exc, AmbiguousElementError) or "ambiguous target" in msg_lower:
        return "ambiguous_target", "Ambiguous Target"
    if isinstance(exc, ElementNotFoundError) or ("could not find any" in msg_lower) or ("not found" in msg_lower and "text" not in msg_lower):
        return "missing_element", "Missing Element"
    if isinstance(exc, AssertionError) or "assertion" in msg_lower or "verification failed" in msg_lower or "was not found as visible text" in msg_lower:
        return "assertion_failure", "Assertion Failed"
    if isinstance(exc, asyncio.TimeoutError) or "timeout" in msg_lower or "timed out" in msg_lower:
        return "timeout", "Timeout"
    if isinstance(exc, ValueError) or "unsupported action" in msg_lower or "required" in msg_lower:
        return "parsing_failure", "Syntax / Action Error"
    return "execution_error", "Execution Error"


def reconstruct_instruction(action: str, target: str, val_str: str, expected: str) -> str:
    """Reconstruct a natural-language instruction for display if none was originally recorded."""
    act = (action or "").strip().lower()
    tgt = (target or "").strip()
    val = (val_str or "").strip()
    exp = (expected or "").strip()
    if act == "navigate":
        return f"navigate to {val or tgt or exp or '/'}"
    if act == "fill":
        return f"type '{val}' into '{tgt}'"
    if act == "click":
        return f"click '{tgt}'"
    if act == "verify_url":
        return f"verify current url contains '{exp or tgt or val}'"
    if act == "verify_text":
        return f"verify that '{exp or tgt or val}' is visible"
    if act == "discover_page":
        return "discover page elements"
    return f"{act} {tgt}".strip()

SECRET_REFERENCE_PATTERN = re.compile(r"^\$\{secret:([A-Za-z_][A-Za-z0-9_]*)\}$")
SECRET_REFERENCE_PREFIX = "${secret:"


def _resolve_secret_reference(value: str) -> tuple[str, Optional[str]]:
    """Resolve an exact secret reference from the backend process environment."""
    match = SECRET_REFERENCE_PATTERN.fullmatch(value)
    if match:
        name = match.group(1)
        secret = os.environ.get(name)
        if secret is None or secret == "":
            raise ValueError("Required secret is not configured.")
        return secret, secret

    if SECRET_REFERENCE_PREFIX in value:
        raise ValueError("Invalid secret reference format.")

    return value, None


def _redact_sensitive_text(value: str, sensitive_values: List[str]) -> str:
    """Redact raw and commonly URL-encoded forms of resolved secrets."""
    for secret in sorted(
        (secret for secret in sensitive_values if secret),
        key=len,
        reverse=True,
    ):
        encoded_forms = {
            quote(secret, safe=""),
            quote_plus(secret),
        }
        for encoded in encoded_forms:
            if encoded and encoded != secret:
                value = value.replace(encoded, "[REDACTED]")
                value = value.replace(encoded.lower(), "[REDACTED]")
        value = value.replace(secret, "[REDACTED]")

        decoded = value
        for _ in range(2):
            decoded = unquote_plus(decoded)
            if secret in decoded:
                return "[REDACTED]"
    return value


def _redact_sensitive_values(value: Any, sensitive_values: List[str]) -> Any:
    """Redact resolved secrets from nested discovery data before artifact writes."""
    if isinstance(value, str):
        return _redact_sensitive_text(value, sensitive_values)
    if isinstance(value, list):
        return [_redact_sensitive_values(item, sensitive_values) for item in value]
    if isinstance(value, dict):
        return {
            _redact_sensitive_values(key, sensitive_values): (
                _redact_sensitive_values(item, sensitive_values)
            )
            for key, item in value.items()
        }
    return value


async def _discover_page_elements(page) -> Dict[str, Any]:
    """Collect visible page headings and interactive controls without secrets."""
    return await page.evaluate("""() => {
        const isVisible = (el) => {
            const style = window.getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return style.display !== 'none'
                && style.visibility !== 'hidden'
                && Number(style.opacity) !== 0
                && rect.width > 0
                && rect.height > 0;
        };

        const clean = (value, max = 160) =>
            String(value || '').replace(/\\s+/g, ' ').trim().slice(0, max);

        const headings = Array.from(
            document.querySelectorAll('h1, h2, h3, h4, h5, h6, [role="heading"]')
        ).filter(isVisible).map(el => ({
            tag: el.tagName.toLowerCase(),
            text: clean(el.innerText || el.textContent)
        })).filter(item => item.text);

        const selectorList = [
            'button', 'a[href]', 'input', 'textarea', 'select',
            '[role="button"]', '[role="link"]', '[role="textbox"]',
            '[role="checkbox"]', '[role="combobox"]', '[role="tab"]'
        ];

        const elements = Array.from(document.querySelectorAll(selectorList.join(',')))
            .filter(isVisible)
            .map((el, index) => {
                const tag = el.tagName.toLowerCase();
                const type = clean(el.getAttribute('type')).toLowerCase();
                const isPassword = type === 'password';
                const labels = el.labels ? Array.from(el.labels)
                    .map(label => clean(label.innerText || label.textContent))
                    .filter(Boolean).join(' ') : '';
                const ariaLabel = clean(el.getAttribute('aria-label'));
                const title = clean(el.getAttribute('title'));
                const text = clean(el.innerText || el.textContent ||
                    (isPassword ? '' : el.value));
                const accessibleName = ariaLabel || labels || title || text;

                return {
                    index,
                    tag,
                    type,
                    role: clean(el.getAttribute('role')),
                    text: isPassword ? '' : text,
                    label: labels,
                    accessibleName,
                    placeholder: clean(el.getAttribute('placeholder')),
                    id: clean(el.id),
                    name: clean(el.getAttribute('name')),
                    href: tag === 'a' ? clean(el.getAttribute('href'), 300) : '',
                    required: Boolean(el.required),
                    disabled: Boolean(el.disabled),
                    value: isPassword ? '' :
                        (['input', 'textarea', 'select'].includes(tag)
                            ? clean(el.value, 120) : '')
                };
            });

        return {
            pageTitle: document.title,
            url: window.location.href,
            headings,
            elements
        };
    }""")


async def _execute_playwright(
    steps: List[Dict[str, Any]],
    app_url: str,
    artifacts_dir: str,
    run_id: str,
    test_case_id: str,
) -> Dict[str, Any]:
    """Execute test steps in an isolated asyncio event loop with subprocess support."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return {
            "status": "error",
            "log_lines": [NOT_CONFIGURED_MSG],
            "screenshot_path": None,
            "video_path": None,
            "error_message": NOT_CONFIGURED_MSG,
        }

    log_lines: List[str] = []
    sensitive_values: List[str] = []
    screenshot_path: Optional[str] = None
    video_path: Optional[str] = None
    error_message: Optional[str] = None
    status = "passed"

    result_dir = Path(artifacts_dir) / "runs" / run_id / "results" / test_case_id
    result_dir.mkdir(parents=True, exist_ok=True)
    videos_dir = Path(artifacts_dir) / "runs" / run_id / "videos"
    videos_dir.mkdir(parents=True, exist_ok=True)
    sorted_steps = sorted(
        steps, key=lambda s: int(s.get("step_number") or 0)
    )
    has_secret_reference = any(
        (step.get("action") or "").strip().lower() == "fill"
        and SECRET_REFERENCE_PATTERN.fullmatch(
            str(step.get("value") or "").strip()
        )
        for step in sorted_steps
    )

    def log(msg: str) -> None:
        msg = _redact_sensitive_text(msg, sensitive_values)
        msg = re.sub(
            r"\$\{secret:[^}]*\}?",
            "[REDACTED]",
            msg,
        )

        timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3]
        log_lines.append(f"[{timestamp}] {msg}")

    try:
        log("Initializing Playwright browser context...")
        async with async_playwright() as pw:
            try:
                browser = await pw.chromium.launch(
                    headless=settings.PLAYWRIGHT_HEADLESS,
                )
                log(
                    "Chromium browser launched "
                    f"(headless={settings.PLAYWRIGHT_HEADLESS})"
                )
            except Exception as exc:
                tb = traceback.format_exc()
                detail = (
                    f"{type(exc).__name__}: {exc}"
                    if str(exc)
                    else type(exc).__name__
                )
                log(f"Failed to launch browser: {detail}")
                log(f"Traceback:\n{tb}")
                return {
                    "status": "error",
                    "log_lines": log_lines,
                    "screenshot_path": None,
                    "video_path": None,
                    "error_message": f"{NOT_CONFIGURED_MSG} ({detail})",
                }

            context_options = {}
            if not has_secret_reference:
                context_options = {
                    "record_video_dir": str(videos_dir),
                    "record_video_size": {"width": 1280, "height": 720},
                }
            context = await browser.new_context(**context_options)
            page = await context.new_page()
            page.set_default_timeout(settings.PLAYWRIGHT_TIMEOUT_MS)
            log(
                "Browser page ready with video recording "
                f"{'disabled for secret-reference fill steps' if has_secret_reference else 'enabled'}."
            )
            video_handle = page.video
            step_records: List[Dict[str, Any]] = []

            try:
                log(f"Executing {len(sorted_steps)} test step(s)...")

                for step_idx, step in enumerate(sorted_steps):
                    step_start_time = time.perf_counter()
                    action = (step.get("action") or "").strip().lower()
                    target = (step.get("target") or "").strip()
                    value = step.get("value")
                    expected = (step.get("expected_result") or "").strip()
                    step_num = step.get("step_number", step_idx + 1)
                    val_str = str(value).strip() if value is not None else ""

                    sensitive_target = any(
                        word in target.lower()
                        for word in ("password", "passwd", "secret", "token")
                    )
                    secret_reference = (
                        action == "fill"
                        and SECRET_REFERENCE_PREFIX in val_str
                    )
                    safe_value = (
                        "[REDACTED]"
                        if action == "fill" and (sensitive_target or secret_reference)
                        else val_str
                    )
                    safe_expected = expected
                    orig_instruction = step.get("original_instruction") or reconstruct_instruction(
                        action, target, safe_value, safe_expected
                    )
                    verification_result: Optional[Dict[str, Any]] = None
                    log(
                        f"Step {step_num}: [{action}] target='{target}' "
                        f"value='{safe_value}' expected='{safe_expected}'"
                    )

                    try:
                        if action == "discover_page":
                            log("  → Discovering visible page elements...")
                            inventory = await _discover_page_elements(page)
                            inventory = _redact_sensitive_values(
                                inventory, sensitive_values
                            )
                            discovery_path = result_dir / "discovery.json"
                            discovery_path.write_text(
                                json.dumps(inventory, indent=2, ensure_ascii=False),
                                encoding="utf-8",
                            )
                            log(
                                "  ✓ Discovery complete: "
                                f"{len(inventory.get('elements', []))} interactive "
                                f"elements and {len(inventory.get('headings', []))} headings."
                            )
                            log(f"  Discovery inventory saved: {discovery_path.name}")

                        elif action == "navigate":
                            url = val_str or target or expected or "/"
                            if app_url and (
                                url.startswith("/") or not url.startswith("http")
                            ):
                                base = app_url.rstrip("/")
                                path = url if url.startswith("/") else f"/{url}"
                                url = f"{base}{path}"

                            log(f"  → Navigating to: {url}")
                            await page.goto(url, wait_until="domcontentloaded")
                            log(f"  ✓ Navigated successfully to: {page.url}")

                        elif action == "fill":
                            if not target:
                                raise ValueError(
                                    "Target selector is required for 'fill' action."
                                )
                            fill_value, resolved_secret = _resolve_secret_reference(
                                val_str
                            )
                            if resolved_secret is not None:
                                sensitive_values.append(resolved_secret)
                            elif sensitive_target and val_str:
                                sensitive_values.append(val_str)
                            log(f"  → Filling target '{target}' with '{safe_value}'")
                            if hasattr(page, "locator") or not hasattr(page, "fill"):
                                target_locator = await resolve_locator(
                                    page, target, action="fill", timeout_ms=min(settings.PLAYWRIGHT_TIMEOUT_MS, 5000)
                                )
                                if hasattr(target_locator, "fill"):
                                    await target_locator.fill(
                                        fill_value, timeout=settings.PLAYWRIGHT_TIMEOUT_MS
                                    )
                                else:
                                    await page.fill(
                                        target, fill_value, timeout=settings.PLAYWRIGHT_TIMEOUT_MS
                                    )
                            else:
                                await page.fill(target, fill_value)
                            log(f"  ✓ Filled '{target}'")

                        
                        elif action == "click":
                            if not target:
                                raise ValueError(
                                    "Target selector is required for 'click' action."
                                )

                            log(f"  → Clicking target '{target}'")

                            target_locator = await resolve_locator(
                                page, target, action="click", timeout_ms=min(settings.PLAYWRIGHT_TIMEOUT_MS, 5000)
                            )
                            if hasattr(target_locator, "click"):
                                await target_locator.click(
                                    timeout=settings.PLAYWRIGHT_TIMEOUT_MS
                                )
                            elif hasattr(page, "click"):
                                await page.click(
                                    target, timeout=settings.PLAYWRIGHT_TIMEOUT_MS
                                )
                            else:
                                await page.locator(target).click(
                                    timeout=settings.PLAYWRIGHT_TIMEOUT_MS
                                )

                            # Allow a short opportunity for the page to settle.
                            # Some applications update asynchronously.
                            try:
                                await page.wait_for_load_state(
                                    "domcontentloaded",
                                    timeout=5000,
                                )
                            except Exception:
                                # The page may already be loaded, or the
                                # application may use AJAX without navigation.
                                pass

                            log(f"  ✓ Click action completed for '{target}'")
                            log(f"  Current URL after click: {page.url}")


                        elif action == "verify_url":
                            expected_url = expected or val_str or target or app_url
                            log(
                                "  → Verifying URL "
                                f"(expected contains='{expected_url}', "
                                f"current='{page.url}')"
                            )
                            full_expected = ""
                            if app_url and (
                                expected_url.startswith("/")
                                or not expected_url.startswith("http")
                            ):
                                full_expected = (
                                    f"{app_url.rstrip('/')}/"
                                    f"{expected_url.lstrip('/')}"
                                )

                            url_timeout_s = (
                                min(settings.PLAYWRIGHT_TIMEOUT_MS / 1000.0, 5.0)
                                if hasattr(page, "wait_for_timeout")
                                else 0
                            )
                            start_url = asyncio.get_event_loop().time()
                            match = False
                            current_url = page.url

                            while True:
                                current_url = page.url
                                match = (
                                    expected_url in current_url
                                    or (
                                        bool(full_expected)
                                        and full_expected in current_url
                                    )
                                )
                                if match:
                                    break
                                if (asyncio.get_event_loop().time() - start_url) >= url_timeout_s:
                                    break
                                await asyncio.sleep(0.05)

                            if not match:
                                verification_result = {
                                    "type": "verify_url",
                                    "expected": expected_url,
                                    "actual": current_url,
                                    "matched": False,
                                }
                                raise AssertionError(
                                    "URL verification failed: expected "
                                    f"'{expected_url}' in current URL '{current_url}'"
                                )
                            verification_result = {
                                "type": "verify_url",
                                "expected": expected_url,
                                "actual": current_url,
                                "matched": True,
                            }
                            log(
                                f"  ✓ URL verified successfully: '{expected_url}' "
                                f"matches '{current_url}'"
                            )

                        elif action == "verify_text":
                            text_to_find = (expected or val_str).strip()
                            if not text_to_find:
                                raise ValueError(
                                    "verify_text requires expected_result or value "
                                    "to contain the text to find."
                                )

                            log(f"  → Verifying visible text '{text_to_find}'")

                            # Search for the requested text directly. If target is
                            # supplied, scope the text search to that container.
                            if target:
                                container = page.locator(target)
                                await container.wait_for(
                                    state="visible",
                                    timeout=settings.PLAYWRIGHT_TIMEOUT_MS,
                                )
                                locator = container.get_by_text(
                                    text_to_find, exact=False
                                ).first
                            else:
                                locator = page.get_by_text(
                                    text_to_find, exact=False
                                ).first

                            try:
                                await locator.wait_for(
                                    state="visible",
                                    timeout=settings.PLAYWRIGHT_TIMEOUT_MS,
                                )
                            except Exception as text_exc:
                                page_text = (
                                    await page.locator("body").inner_text()
                                )
                                page_text = _redact_sensitive_text(
                                    page_text, sensitive_values
                                )
                                page_text_preview = " ".join(page_text.split())[:500]
                                verification_result = {
                                    "type": "verify_text",
                                    "expected": text_to_find,
                                    "matched": False,
                                    "preview": page_text_preview,
                                }
                                raise AssertionError(
                                    f"Text '{text_to_find}' was not found as visible "
                                    f"text on the page. Visible page text begins: "
                                    f"'{page_text_preview}'"
                                ) from text_exc

                            verification_result = {
                                "type": "verify_text",
                                "expected": text_to_find,
                                "matched": True,
                            }
                            log(f"  ✓ Text '{text_to_find}' found on page.")

                        else:
                            raise ValueError(
                                f"Unsupported action '{action}'. Supported actions: "
                                "['navigate', 'fill', 'click', 'verify_url', 'verify_text', 'discover_page']."
                            )

                        step_dur = round((time.perf_counter() - step_start_time) * 1000, 2)
                        step_records.append({
                            "step_number": int(step_num) if str(step_num).isdigit() else step_idx + 1,
                            "action": action,
                            "target": target or None,
                            "value": safe_value if safe_value else None,
                            "expected_result": safe_expected if safe_expected else None,
                            "original_instruction": orig_instruction,
                            "status": "passed",
                            "duration_ms": step_dur,
                            "category": None,
                            "failure_reason": None,
                            "verification_result": verification_result,
                        })

                    except Exception as step_exc:
                        step_dur = round((time.perf_counter() - step_start_time) * 1000, 2)
                        tb = traceback.format_exc()
                        exc_msg = str(step_exc) or type(step_exc).__name__
                        log(
                            f"  ✗ FAILED at Step {step_num} ({action}): {exc_msg}"
                        )
                        log(f"Step failure traceback:\n{tb}")
                        status = "failed"
                        cat_code, cat_label = categorize_step_error(step_exc, action, exc_msg)
                        safe_reason = _redact_sensitive_text(exc_msg, sensitive_values)
                        error_message = (
                            f"Step {step_num} ({action}) failed: {safe_reason}"
                        )
                        step_records.append({
                            "step_number": int(step_num) if str(step_num).isdigit() else step_idx + 1,
                            "action": action,
                            "target": target or None,
                            "value": safe_value if safe_value else None,
                            "expected_result": safe_expected if safe_expected else None,
                            "original_instruction": orig_instruction,
                            "status": "failed",
                            "duration_ms": step_dur,
                            "category": cat_code,
                            "failure_reason": safe_reason,
                            "verification_result": verification_result,
                        })

                        # Mark all remaining unexecuted steps as skipped
                        for rem_idx in range(step_idx + 1, len(sorted_steps)):
                            rem_step = sorted_steps[rem_idx]
                            rem_action = (rem_step.get("action") or "").strip().lower()
                            rem_target = (rem_step.get("target") or "").strip()
                            rem_val = rem_step.get("value")
                            rem_val_str = str(rem_val).strip() if rem_val is not None else ""
                            rem_expected = (rem_step.get("expected_result") or "").strip()
                            rem_step_num = rem_step.get("step_number", rem_idx + 1)
                            rem_sensitive = any(
                                w in rem_target.lower()
                                for w in ("password", "passwd", "secret", "token")
                            ) or (rem_action == "fill" and SECRET_REFERENCE_PREFIX in rem_val_str)
                            rem_safe_val = "[REDACTED]" if rem_sensitive else rem_val_str
                            rem_orig = rem_step.get("original_instruction") or reconstruct_instruction(
                                rem_action, rem_target, rem_safe_val, rem_expected
                            )
                            step_records.append({
                                "step_number": int(rem_step_num) if str(rem_step_num).isdigit() else rem_idx + 1,
                                "action": rem_action,
                                "target": rem_target or None,
                                "value": rem_safe_val if rem_safe_val else None,
                                "expected_result": rem_expected or None,
                                "original_instruction": rem_orig,
                                "status": "skipped",
                                "duration_ms": 0.0,
                                "category": None,
                                "failure_reason": None,
                                "verification_result": None,
                            })

                        if sensitive_values:
                            log(
                                "Failure screenshot skipped because a sensitive fill value "
                                "was used in this test case."
                            )
                        else:
                            ss_path = (
                                result_dir / f"screenshot_step{step_num}_failure.png"
                            )
                            try:
                                await page.screenshot(
                                    path=str(ss_path), full_page=True
                                )
                                screenshot_path = str(ss_path)
                                log(f"  📸 Failure screenshot saved: {ss_path.name}")
                            except Exception as ss_exc:
                                log(f"  ⚠ Could not capture failure screenshot: {ss_exc}")

                        break

            finally:
                # Closing the context flushes the video recording to disk.
                await context.close()
                await browser.close()
                log("Browser session closed.")

                if video_handle:
                    try:
                        raw_video_path = await video_handle.path()
                        if (
                            not has_secret_reference
                            and raw_video_path
                            and Path(raw_video_path).exists()
                        ):
                            video_path = str(raw_video_path)
                            log(
                                "  🎬 Video recording saved: "
                                f"{Path(raw_video_path).name}"
                            )
                    except Exception as vid_err:
                        log(f"  ⚠ Could not resolve video path: {vid_err}")

            # Persist structured steps.json artifact
            steps_file = result_dir / "steps.json"
            try:
                steps_file.write_text(
                    json.dumps(step_records, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
            except Exception as steps_err:
                log(f"  ⚠ Could not save steps.json: {steps_err}")

    except Exception as runner_exc:
        tb = traceback.format_exc()
        exc_detail = (
            f"{type(runner_exc).__name__}: {runner_exc}"
            if str(runner_exc)
            else type(runner_exc).__name__
        )
        log(f"Runner error: {exc_detail}")
        log(f"Traceback:\n{tb}")
        status = "error"
        error_message = _redact_sensitive_text(exc_detail, sensitive_values)

    steps_path_str = (
        str(result_dir / "steps.json")
        if (result_dir / "steps.json").exists()
        else None
    )

    return {
        "status": status,
        "log_lines": log_lines,
        "screenshot_path": screenshot_path,
        "video_path": video_path,
        "error_message": error_message,
        "steps": step_records,
        "steps_path": steps_path_str,
        "discovery_path": (
            str(result_dir / "discovery.json")
            if (result_dir / "discovery.json").exists()
            else None
        ),
    }


def _run_in_worker_thread(
    steps: List[Dict[str, Any]],
    app_url: str,
    artifacts_dir: str,
    run_id: str,
    test_case_id: str,
) -> Dict[str, Any]:
    """Run Playwright inside a dedicated thread with a ProactorEventLoop on Windows."""
    if sys.platform == "win32":
        loop = asyncio.ProactorEventLoop()
    else:
        loop = asyncio.new_event_loop()

    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(
            _execute_playwright(
                steps, app_url, artifacts_dir, run_id, test_case_id
            )
        )
    finally:
        try:
            loop.close()
        except Exception:
            pass


async def run_test_case(
    steps: List[Dict[str, Any]],
    app_url: str,
    artifacts_dir: str,
    run_id: str,
    test_case_id: str,
) -> Dict[str, Any]:
    """
    Execute a single test case's steps.
    Offloads to a worker thread with ProactorEventLoop so Windows subprocesses work.
    """
    return await asyncio.to_thread(
        _run_in_worker_thread,
        steps,
        app_url,
        artifacts_dir,
        run_id,
        test_case_id,
    )
