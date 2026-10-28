"""
Live Browser Discovery Service for Noetrix.

Provides interactive browser exploration, deep non-secret DOM inventory capture,
SSRF-safe navigation, live intent-target validation, and session lifecycle management.
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import queue
import re
import socket
import sys
import threading
import time
import urllib.parse
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.config import get_settings

logger = logging.getLogger(__name__)

# SSRF Protection: blocked hostnames and IP networks
BLOCKED_HOSTNAMES = {
    "localhost",
    "127.0.0.1",
    "::1",
    "0.0.0.0",
    "metadata.google.internal",
    "169.254.169.254",
}


def validate_discovery_url(url: str, allow_local: Optional[bool] = None) -> str:
    """
    Validate target URL and protect against Server-Side Request Forgery (SSRF).

    Raises:
        ValueError: If URL is malformed, uses unsupported schemes, or targets prohibited internal resources.
    """
    import os
    settings = get_settings()
    if allow_local is None:
        allow_local = (
            settings.ALLOW_LOCAL_DISCOVERY
            or settings.ENVIRONMENT == "test"
            or bool(os.environ.get("PYTEST_CURRENT_TEST"))
        )

    raw_url = (url or "").strip()
    if not raw_url:
        raise ValueError("URL cannot be empty.")

    # Check for prohibited schemes explicitly first
    if ":" in raw_url:
        scheme_candidate = raw_url.split(":", 1)[0].lower().strip()
        if scheme_candidate in ("file", "ftp", "gopher", "data", "blob", "javascript"):
            raise ValueError(f"Prohibited URL scheme '{scheme_candidate}'. Only http and https are allowed.")

    # Auto-prefix http/https if missing
    if not (raw_url.startswith("http://") or raw_url.startswith("https://")):
        raw_url = f"https://{raw_url}"

    parsed = urllib.parse.urlparse(raw_url)
    if parsed.scheme.lower() not in ("http", "https"):
        raise ValueError(f"Prohibited URL scheme '{parsed.scheme}'. Only http and https are allowed.")

    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        raise ValueError("Invalid URL: missing hostname.")

    if not allow_local:
        if hostname in BLOCKED_HOSTNAMES:
            raise ValueError(f"Navigation to internal host '{hostname}' is prohibited.")

        # Check for loopback, private, or link-local IP addresses
        try:
            addr_info = socket.getaddrinfo(hostname, None)
            for item in addr_info:
                ip_str = item[4][0]
                ip_obj = ipaddress.ip_address(ip_str)
                if (
                    ip_obj.is_loopback
                    or ip_obj.is_private
                    or ip_obj.is_link_local
                    or ip_obj.is_reserved
                    or ip_str == "169.254.169.254"
                ):
                    raise ValueError(f"Navigation to prohibited internal network address '{ip_str}' is denied.")
        except socket.gaierror:
            # Domain cannot be resolved yet; allow standard browser to report DNS error
            pass

    return raw_url


JS_INVENTORY_EXTRACTION = """() => {
    const isVisible = (el) => {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style.display !== 'none'
            && style.visibility !== 'hidden'
            && Number(style.opacity) !== 0
            && rect.width > 0
            && rect.height > 0;
    };

    const clean = (val, max = 200) =>
        String(val || '').replace(/\\s+/g, ' ').trim().slice(0, max);

    // 1. Headings
    const headings = Array.from(
        document.querySelectorAll('h1, h2, h3, h4, h5, h6, [role="heading"]')
    ).filter(isVisible).map(el => ({
        tag: el.tagName.toLowerCase(),
        text: clean(el.innerText || el.textContent)
    })).filter(h => h.text);

    // 2. Interactive and semantic elements
    const selectorList = [
        'button', 'a[href]', 'input', 'textarea', 'select',
        '[role="button"]', '[role="link"]', '[role="textbox"]',
        '[role="checkbox"]', '[role="combobox"]', '[role="tab"]',
        '[role="menuitem"]', '[role="menu"]', '[role="option"]',
        '[data-testid]', '[data-qa]', 'img[alt]', 'svg[aria-label]'
    ];

    const elements = [];
    const seenElements = new Set();
    const rawList = Array.from(document.querySelectorAll(selectorList.join(','))).filter(isVisible);

    rawList.forEach((el, index) => {
        if (seenElements.has(el)) return;
        seenElements.add(el);

        const tag = el.tagName.toLowerCase();
        const type = clean(el.getAttribute('type')).toLowerCase();
        const isPassword = type === 'password' || /password/i.test(el.id) || /password/i.test(el.name);

        const labels = el.labels ? Array.from(el.labels)
            .map(l => clean(l.innerText || l.textContent))
            .filter(Boolean).join(' ') : '';
        const ariaLabel = clean(el.getAttribute('aria-label'));
        const ariaLabelledBy = el.getAttribute('aria-labelledby')
            ? clean(document.getElementById(el.getAttribute('aria-labelledby'))?.innerText) : '';
        const title = clean(el.getAttribute('title'));
        const alt = clean(el.getAttribute('alt'));
        const placeholder = clean(el.getAttribute('placeholder'));
        const role = clean(el.getAttribute('role'));
        const testId = clean(el.getAttribute('data-testid') || el.getAttribute('data-qa') || el.getAttribute('data-cy'));
        const idAttr = clean(el.id);
        const nameAttr = clean(el.getAttribute('name'));

        // Visible text: NEVER capture password values
        let text = '';
        if (isPassword) {
            text = '';
        } else if (tag === 'img') {
            text = alt || title || ariaLabel;
        } else if (tag === 'input' || tag === 'textarea') {
            text = ''; // Do not leak typed form values
        } else {
            text = clean(el.innerText || el.textContent);
        }

        const accessibleName = ariaLabel || ariaLabelledBy || labels || alt || title || placeholder || text;

        // Build candidate locators
        const candidateLocators = [];
        if (testId) {
            candidateLocators.push(`[data-testid="${testId}"]`);
        }
        if (idAttr && !/\\d{5,}/.test(idAttr)) {
            candidateLocators.push(`#${idAttr}`);
        }
        if (role && accessibleName) {
            candidateLocators.push(`role=${role}[name="${accessibleName}"]`);
        }
        if (labels) {
            candidateLocators.push(`label=${labels}`);
        }
        if (placeholder) {
            candidateLocators.push(`placeholder=${placeholder}`);
        }
        if (nameAttr) {
            candidateLocators.push(`${tag}[name="${nameAttr}"]`);
        }
        if (tag === 'a' && el.getAttribute('href')) {
            candidateLocators.push(`a[href="${clean(el.getAttribute('href'), 100)}"]`);
        }
        if (text && text.length <= 40) {
            candidateLocators.push(`text="${text}"`);
        }

        // Suggested human-friendly intent description
        let suggestedIntent = '';
        const primaryDescriptor = accessibleName || placeholder || labels || nameAttr || idAttr || text;
        if (isPassword) {
            suggestedIntent = 'password field';
        } else if (['input', 'textarea'].includes(tag) || role === 'textbox') {
            suggestedIntent = primaryDescriptor ? `${primaryDescriptor} field` : 'input field';
        } else if (tag === 'button' || role === 'button') {
            suggestedIntent = primaryDescriptor ? `${primaryDescriptor} button` : 'button';
        } else if (tag === 'a' || role === 'link') {
            suggestedIntent = primaryDescriptor ? `${primaryDescriptor} link` : 'link';
        } else if (tag === 'select' || role === 'combobox') {
            suggestedIntent = primaryDescriptor ? `${primaryDescriptor} dropdown` : 'dropdown';
        } else if (role === 'checkbox' || type === 'checkbox') {
            suggestedIntent = primaryDescriptor ? `${primaryDescriptor} checkbox` : 'checkbox';
        } else if (role === 'tab') {
            suggestedIntent = primaryDescriptor ? `${primaryDescriptor} tab` : 'tab';
        } else if (role === 'menuitem' || role === 'menu') {
            suggestedIntent = primaryDescriptor ? `${primaryDescriptor} menu` : 'menu';
        } else if (tag === 'img' || tag === 'svg') {
            suggestedIntent = primaryDescriptor ? `${primaryDescriptor} logo` : 'image';
        } else {
            suggestedIntent = primaryDescriptor;
        }

        // Check uniqueness of primary candidate
        let isUnique = true;
        if (candidateLocators.length > 0) {
            try {
                const firstSelector = candidateLocators[0];
                if (!firstSelector.startsWith('role=') && !firstSelector.startsWith('label=') && !firstSelector.startsWith('placeholder=') && !firstSelector.startsWith('text=')) {
                    isUnique = (document.querySelectorAll(firstSelector).length === 1);
                }
            } catch (e) {
                isUnique = true;
            }
        }

        elements.push({
            id: `el_${index + 1}`,
            tag,
            type: type || null,
            role: role || null,
            accessible_name: accessibleName || null,
            label: labels || null,
            placeholder: placeholder || null,
            element_id: idAttr || null,
            name: nameAttr || null,
            data_testid: testId || null,
            href: tag === 'a' ? clean(el.getAttribute('href'), 300) : null,
            visible_text: text || null,
            is_visible: true,
            is_enabled: !el.disabled,
            is_unique: isUnique,
            candidate_locators: candidateLocators,
            suggested_intent: suggestedIntent || null
        });
    });

    // Detect iframes
    const frames = Array.from(document.querySelectorAll('iframe, frame')).map((f, idx) => ({
        index: idx,
        id: clean(f.id),
        name: clean(f.name),
        src: clean(f.src, 200)
    }));

    return {
        url: window.location.href,
        page_title: document.title,
        headings,
        elements,
        frames
    };
}"""


class DiscoveryWorker(threading.Thread):
    """
    Dedicated worker thread managing an isolated Playwright browser session.
    All Playwright operations execute inside this thread's event loop.
    """

    def __init__(
        self,
        session_id: str,
        user_id: str,
        project_id: str,
        app_url: str,
        headless: bool = False,
    ):
        super().__init__(name=f"DiscoveryWorker-{session_id[:8]}", daemon=True)
        self.session_id = session_id
        self.user_id = user_id
        self.project_id = project_id
        self.app_url = app_url
        self.headless = headless

        self.cmd_queue: queue.Queue[Tuple[str, Any, queue.Queue]] = queue.Queue()
        self.is_ready_event = threading.Event()
        self.init_error: Optional[Exception] = None
        self.is_active = True
        self.last_activity_time = time.time()
        self.current_url: Optional[str] = None
        self.current_title: Optional[str] = None

    def run(self) -> None:
        if sys.platform == "win32":
            loop = asyncio.ProactorEventLoop()
        else:
            loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            loop.run_until_complete(self._lifecycle_loop())
        finally:
            try:
                loop.close()
            except Exception:
                pass

    async def _lifecycle_loop(self) -> None:
        from playwright.async_api import async_playwright

        playwright = None
        browser = None
        context = None
        page = None

        try:
            playwright = await async_playwright().start()
            launch_args = [
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ]
            browser = await playwright.chromium.launch(
                headless=self.headless,
                args=launch_args,
            )
            context = await browser.new_context(
                viewport={"width": 1280, "height": 850},
                ignore_https_errors=False,
            )
            page = await context.new_page()

            # Navigate to initial URL
            logger.info(f"DiscoveryWorker {self.session_id}: Navigating to {self.app_url}")
            await page.goto(self.app_url, wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(0.5)

            self.current_url = page.url
            self.current_title = await page.title()
            self.last_activity_time = time.time()
            self.is_ready_event.set()

            # Process command queue until stopped or page/browser closed
            while self.is_active:
                try:
                    cmd, args, resp_q = await asyncio.to_thread(self.cmd_queue.get, timeout=0.2)
                except queue.Empty:
                    # Check if browser or page was closed manually by user
                    if page.is_closed() or (hasattr(browser, "is_connected") and not browser.is_connected()):
                        logger.info(f"DiscoveryWorker {self.session_id}: Browser/Page was closed manually.")
                        self.is_active = False
                        break
                    continue

                self.last_activity_time = time.time()

                if cmd == "CAPTURE_INVENTORY":
                    try:
                        res = await self._capture_inventory_async(page)
                        self.current_url = page.url
                        self.current_title = await page.title()
                        resp_q.put((True, res))
                    except Exception as exc:
                        resp_q.put((False, exc))

                elif cmd == "NAVIGATE":
                    try:
                        new_url = args
                        await page.goto(new_url, wait_until="domcontentloaded", timeout=45000)
                        await asyncio.sleep(0.5)
                        self.current_url = page.url
                        self.current_title = await page.title()
                        resp_q.put((True, {"url": self.current_url, "title": self.current_title}))
                    except Exception as exc:
                        resp_q.put((False, exc))

                elif cmd == "VALIDATE_TARGET":
                    try:
                        target, action = args
                        res = await self._validate_target_async(page, target, action)
                        resp_q.put((True, res))
                    except Exception as exc:
                        resp_q.put((False, exc))

                elif cmd == "CLOSE":
                    self.is_active = False
                    resp_q.put((True, "closed"))
                    break

        except Exception as init_exc:
            logger.error(f"DiscoveryWorker {self.session_id} init failed: {init_exc}")
            self.init_error = init_exc
            self.is_active = False
            self.is_ready_event.set()
        finally:
            # Clean teardown
            try:
                if page and not page.is_closed():
                    await page.close()
            except Exception:
                pass
            try:
                if context:
                    await context.close()
            except Exception:
                pass
            try:
                if browser and (not hasattr(browser, "is_connected") or browser.is_connected()):
                    await browser.close()
            except Exception:
                pass
            try:
                if playwright:
                    await playwright.stop()
            except Exception:
                pass
            self.is_active = False
            logger.info(f"DiscoveryWorker {self.session_id}: Shutdown complete.")

    async def _capture_inventory_async(self, page: Any) -> Dict[str, Any]:
        """Execute in-browser evaluation and capture full inventory across frames."""
        data = await page.evaluate(JS_INVENTORY_EXTRACTION)

        # Inspect frames if any accessible frames exist
        if hasattr(page, "frames"):
            for frame in page.frames:
                if frame == page.main_frame:
                    continue
                try:
                    frame_data = await frame.evaluate(JS_INVENTORY_EXTRACTION)
                    if frame_data and frame_data.get("elements"):
                        frame_name = frame.name or frame.url
                        for el in frame_data["elements"]:
                            el["frame_context"] = frame_name
                            el["id"] = f"{el['id']}_f"
                            data["elements"].append(el)
                except Exception:
                    # Inaccessible or cross-origin frame
                    pass

        return data

    async def _validate_target_async(self, page: Any, target: str, action: str) -> Dict[str, Any]:
        """Test how target resolves against live DOM using locator resolver."""
        from app.services.locator_resolver import (
            AmbiguousElementError,
            ElementNotFoundError,
            InvalidLocatorSyntaxError,
            resolve_locator,
        )

        try:
            loc = await resolve_locator(page, target=target, action=action, timeout_ms=1000)
            count = await loc.count() if hasattr(loc, "count") else 1
            rec_selector = target
            try:
                # Suggest recommended CSS / testid if possible
                if hasattr(loc, "evaluate"):
                    elem_info = await loc.evaluate("""el => ({
                        tag: el.tagName.toLowerCase(),
                        id: el.id,
                        testId: el.getAttribute('data-testid'),
                        name: el.getAttribute('name'),
                        role: el.getAttribute('role'),
                        ariaLabel: el.getAttribute('aria-label')
                    })""")
                    if elem_info.get("testId"):
                        rec_selector = f"[data-testid='{elem_info['testId']}']"
                    elif elem_info.get("id"):
                        rec_selector = f"#{elem_info['id']}"
                    elif elem_info.get("ariaLabel"):
                        rec_selector = f"label={elem_info['ariaLabel']}"
            except Exception:
                pass

            return {
                "status": "resolved_unique",
                "target": target,
                "action": action,
                "matched_count": count,
                "candidates": [{"selector": target, "count": count}],
                "recommended_locator": rec_selector,
                "suggested_intent": target,
                "message": f"Successfully resolved to 1 unique {action} element.",
            }
        except AmbiguousElementError as amb_err:
            return {
                "status": "ambiguous",
                "target": target,
                "action": action,
                "matched_count": 2,
                "candidates": [],
                "recommended_locator": None,
                "suggested_intent": None,
                "message": str(amb_err),
            }
        except InvalidLocatorSyntaxError as syn_err:
            return {
                "status": "invalid_syntax",
                "target": target,
                "action": action,
                "matched_count": 0,
                "candidates": [],
                "recommended_locator": None,
                "suggested_intent": None,
                "message": str(syn_err),
            }
        except ElementNotFoundError as not_found_err:
            return {
                "status": "not_found",
                "target": target,
                "action": action,
                "matched_count": 0,
                "candidates": [],
                "recommended_locator": None,
                "suggested_intent": None,
                "message": str(not_found_err),
            }
        except Exception as err:
            return {
                "status": "not_found",
                "target": target,
                "action": action,
                "matched_count": 0,
                "candidates": [],
                "recommended_locator": None,
                "suggested_intent": None,
                "message": str(err),
            }

    def execute_command(self, cmd: str, args: Any = None, timeout: float = 30.0) -> Any:
        """Send command to worker thread and wait for result."""
        if not self.is_active:
            raise RuntimeError(f"Discovery session {self.session_id} is no longer active.")

        resp_q: queue.Queue = queue.Queue()
        self.cmd_queue.put((cmd, args, resp_q))
        try:
            success, result = resp_q.get(timeout=timeout)
            if not success:
                raise result
            return result
        except queue.Empty:
            raise TimeoutError(f"Command '{cmd}' timed out after {timeout} seconds.")


class DiscoverySessionManager:
    """Singleton manager tracking and coordinating all active discovery sessions."""

    _instance: Optional["DiscoverySessionManager"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._workers: Dict[str, DiscoveryWorker] = {}
        self._sweep_thread: Optional[threading.Thread] = None
        self._running = True
        self._start_sweeper()

    @classmethod
    def get_instance(cls) -> "DiscoverySessionManager":
        with cls._lock:
            if cls._instance is None:
                cls._instance = DiscoverySessionManager()
            return cls._instance

    def _start_sweeper(self) -> None:
        def sweep_loop():
            while self._running:
                time.sleep(30)
                self.cleanup_idle_sessions()

        self._sweep_thread = threading.Thread(target=sweep_loop, daemon=True, name="DiscoverySweeper")
        self._sweep_thread.start()

    def start_session(
        self,
        session_id: str,
        user_id: str,
        project_id: str,
        app_url: str,
        headless: Optional[bool] = None,
    ) -> DiscoveryWorker:
        """Create and launch a new live discovery worker session."""
        settings = get_settings()
        clean_url = validate_discovery_url(app_url)

        # Headless precedence: explicit param -> config PLAYWRIGHT_HEADLESS -> False for desktop
        if headless is None:
            # If user didn't specify, default to False for visible manual exploration
            is_headless = False if not settings.ENVIRONMENT == "test" else True
        else:
            is_headless = headless

        worker = DiscoveryWorker(
            session_id=session_id,
            user_id=user_id,
            project_id=project_id,
            app_url=clean_url,
            headless=is_headless,
        )
        self._workers[session_id] = worker
        worker.start()

        # Wait for worker to navigate to initial page
        ready = worker.is_ready_event.wait(timeout=50.0)
        if not ready or worker.init_error:
            self._workers.pop(session_id, None)
            err = worker.init_error or TimeoutError("Browser launch and initial navigation timed out.")
            raise RuntimeError(f"Could not start discovery session: {err}") from worker.init_error

        return worker

    def get_worker(self, session_id: str, user_id: str) -> DiscoveryWorker:
        """Retrieve worker ensuring user isolation."""
        worker = self._workers.get(session_id)
        if not worker or not worker.is_active:
            raise KeyError(f"Discovery session '{session_id}' not found or inactive.")
        if worker.user_id != user_id:
            raise PermissionError("Access denied: You do not own this discovery session.")
        return worker

    def capture_inventory(self, session_id: str, user_id: str) -> Dict[str, Any]:
        """Capture live DOM element inventory for current page."""
        worker = self.get_worker(session_id, user_id)
        return worker.execute_command("CAPTURE_INVENTORY", timeout=30.0)

    def navigate(self, session_id: str, user_id: str, new_url: str) -> Dict[str, Any]:
        """Navigate active discovery session to new URL."""
        worker = self.get_worker(session_id, user_id)
        clean_url = validate_discovery_url(new_url)
        return worker.execute_command("NAVIGATE", clean_url, timeout=45.0)

    def validate_target(self, session_id: str, user_id: str, target: str, action: str) -> Dict[str, Any]:
        """Test target resolution on live page."""
        worker = self.get_worker(session_id, user_id)
        return worker.execute_command("VALIDATE_TARGET", (target, action), timeout=15.0)

    def close_session(self, session_id: str, user_id: Optional[str] = None) -> bool:
        """Close an active discovery session."""
        worker = self._workers.get(session_id)
        if not worker:
            return False
        if user_id and worker.user_id != user_id:
            raise PermissionError("Access denied: You do not own this discovery session.")

        try:
            worker.execute_command("CLOSE", timeout=5.0)
        except Exception:
            pass
        self._workers.pop(session_id, None)
        return True

    def cleanup_idle_sessions(self) -> None:
        """Sweep sessions inactive for longer than configured timeout."""
        settings = get_settings()
        timeout_seconds = settings.DISCOVERY_SESSION_TIMEOUT_MINUTES * 60
        now = time.time()

        for session_id, worker in list(self._workers.items()):
            if not worker.is_active or (now - worker.last_activity_time > timeout_seconds):
                logger.info(f"Cleaning up inactive discovery session: {session_id}")
                try:
                    worker.execute_command("CLOSE", timeout=3.0)
                except Exception:
                    pass
                self._workers.pop(session_id, None)

    def shutdown_all(self) -> None:
        """Terminate all discovery workers cleanly upon application shutdown."""
        self._running = False
        for session_id, worker in list(self._workers.items()):
            try:
                worker.execute_command("CLOSE", timeout=3.0)
            except Exception:
                pass
        self._workers.clear()


def search_saved_snapshots(
    snapshots: List[Any],
    query: str,
    action: Optional[str] = None,
    max_results: int = 25,
) -> List[Dict[str, Any]]:
    """
    Search saved snapshots for candidate elements matching a natural-language query or intent.

    Supports queries such as:
      - "Save button"
      - "Find the Save button on the Hire an Employee page"
      - "username field"
      - "eAppSys logo"

    Returns list of scored candidate element matches.
    """
    clean_q = (query or "").strip().lower()
    if not clean_q:
        return []

    # Tokenize query excluding stop words
    stop_words = {"find", "the", "on", "page", "in", "to", "for", "a", "an", "at", "please", "with", "show"}
    query_tokens = [w for w in re.findall(r"\w+", clean_q) if w not in stop_words]

    # Infer intent type or action from query if action is not explicitly given
    inferred_action = (action or "").lower()
    if not inferred_action:
        if any(w in clean_q for w in ("button", "click", "submit", "press", "tab", "link", "menu", "logo", "icon")):
            inferred_action = "click"
        elif any(w in clean_q for w in ("field", "input", "enter", "type", "fill", "textbox")):
            inferred_action = "fill"
        elif any(w in clean_q for w in ("select", "dropdown", "option", "combobox")):
            inferred_action = "select_option"
        elif any(w in clean_q for w in ("check", "checkbox", "tick")):
            inferred_action = "check"

    matches: List[Dict[str, Any]] = []

    for snap in snapshots:
        snap_id = getattr(snap, "id", None) or (snap.get("id") if isinstance(snap, dict) else "")
        snap_url = getattr(snap, "page_url", None) or (snap.get("page_url") if isinstance(snap, dict) else "")
        snap_title = getattr(snap, "page_title", None) or (snap.get("page_title") if isinstance(snap, dict) else "")

        # Extract inventory data
        inv_data = None
        if hasattr(snap, "inventory_data"):
            inv_raw = snap.inventory_data
            if isinstance(inv_raw, str):
                try:
                    inv_data = json.loads(inv_raw)
                except Exception:
                    inv_data = {}
            elif isinstance(inv_raw, dict):
                inv_data = inv_raw
        elif isinstance(snap, dict):
            inv_data = snap.get("inventory_data") or snap

        if not inv_data or not isinstance(inv_data, dict):
            continue

        elements = inv_data.get("elements", [])
        if not elements:
            continue

        # Page-affinity boost: does query mention this snapshot's title?
        page_boost = 0.0
        if snap_title:
            title_tokens = [w for w in re.findall(r"\w+", snap_title.lower()) if len(w) > 3]
            matched_title_tokens = [t for t in title_tokens if t in clean_q]
            if matched_title_tokens:
                page_boost = 2.5

        for el in elements:
            if not isinstance(el, dict):
                continue

            score = page_boost
            suggested_intent = (el.get("suggested_intent") or "").lower()
            accessible_name = (el.get("accessible_name") or "").lower()
            label = (el.get("label") or "").lower()
            placeholder = (el.get("placeholder") or "").lower()
            visible_text = (el.get("visible_text") or "").lower()
            element_id = (el.get("element_id") or "").lower()
            data_testid = (el.get("data_testid") or "").lower()
            name_attr = (el.get("name") or "").lower()
            tag = (el.get("tag") or "").lower()
            role = (el.get("role") or "").lower()

            # Exact matches on intent or accessible name
            if clean_q == suggested_intent or clean_q == accessible_name:
                score += 8.0
            elif clean_q in suggested_intent or clean_q in accessible_name:
                score += 5.0

            # Token-level matching
            matched_tokens = 0
            for token in query_tokens:
                token_matched = False
                if token in suggested_intent:
                    score += 3.0
                    token_matched = True
                if token in accessible_name:
                    score += 2.5
                    token_matched = True
                if token in label:
                    score += 2.5
                    token_matched = True
                if token in placeholder:
                    score += 2.0
                    token_matched = True
                if token in visible_text:
                    score += 1.5
                    token_matched = True
                if token in element_id or token in data_testid or token in name_attr:
                    score += 2.0
                    token_matched = True
                if token in role or token in tag:
                    score += 1.0
                    token_matched = True

                if token_matched:
                    matched_tokens += 1

            if query_tokens and matched_tokens == len(query_tokens):
                score += 3.0  # Bonus for all tokens matching

            # Role/action affinity
            if inferred_action == "fill" and (tag in ("input", "textarea") or role == "textbox"):
                score += 2.0
            elif inferred_action == "click" and (tag in ("button", "a") or role in ("button", "link", "menuitem", "tab")):
                score += 2.0
            elif inferred_action == "select_option" and (tag == "select" or role == "combobox"):
                score += 2.0
            elif inferred_action == "check" and (role == "checkbox" or el.get("type") == "checkbox"):
                score += 2.0

            if score >= 3.0:
                locators = el.get("candidate_locators") or []
                rec_loc = locators[0] if locators else None
                matches.append({
                    "snapshot_id": snap_id,
                    "snapshot_title": snap_title,
                    "snapshot_url": snap_url,
                    "element": el,
                    "match_score": round(score, 2),
                    "recommended_locator": rec_loc,
                    "live_validated": False,
                    "live_match_count": 0,
                })

    # Sort descending by match_score
    matches.sort(key=lambda m: m["match_score"], reverse=True)
    return matches[:max_results]

