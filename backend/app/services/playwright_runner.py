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
    AccessDeniedError,
    AmbiguousElementError,
    ElementNotFoundError,
    ElementNotVisibleError,
    InvalidLocatorSyntaxError,
    is_direct_selector,
    resolve_locator,
)

settings = get_settings()

NOT_CONFIGURED_MSG = (
    "Playwright browser not configured. Run: playwright install chromium"
)


class NavigationTimeoutError(TimeoutError):
    """Raised when an expected page transition or redirect times out."""
    pass


SUBMIT_PROGRESSION_KEYWORDS = {
    "next", "sign in", "signin", "log in", "login", "submit", "continue", "proceed", "sso", "authenticate"
}

AUTH_URL_KEYWORDS = {
    "identity", "signin", "login", "auth", "oauth", "sso", "idp", "session", "access"
}


def infer_expected_navigation(
    step: Dict[str, Any],
    next_step: Optional[Dict[str, Any]],
    current_url: str,
    app_url: Optional[str] = None,
    saved_inventory: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Infer whether an action (typically 'click') is expected to trigger a page transition or redirect.

    Returns a dict with navigation expectations, or None if the action is expected to be an in-page interaction.
    """
    action = (step.get("action") or "").strip().lower()
    if action != "click":
        return None

    raw_target = (step.get("target") or "").strip()
    tgt = raw_target.lower()
    val = str(step.get("value") or "").strip()
    exp = (step.get("expected_result") or "").strip()
    cur_url = (current_url or "").strip()
    cur_url_lower = cur_url.lower()
    app_url_clean = (app_url or "").strip()

    # 1. Explicit destination URL or redirect keyword in current step value or expected_result
    for text in (val, exp):
        if not text:
            continue
        if text.startswith("http://") or text.startswith("https://"):
            return {
                "type": "explicit_url",
                "expected_pattern": text,
                "from_url": cur_url,
                "reason": f"Step explicitly specifies destination URL '{text}'",
            }
        if text.startswith("/") and len(text) > 1 and not text.startswith("//"):
            return {
                "type": "explicit_path",
                "expected_pattern": text,
                "from_url": cur_url,
                "reason": f"Step explicitly specifies destination path '{text}'",
            }
        m = re.search(r"(?:redirects?|navigates?|leads?)\s+to\s+([^\s,;]+)", text, flags=re.IGNORECASE)
        if m:
            pattern = m.group(1).strip()
            return {
                "type": "explicit_redirect",
                "expected_pattern": pattern,
                "from_url": cur_url,
                "reason": f"Step describes redirect to '{pattern}'",
            }

    # 2. Next step explicitly synchronizes or verifies
    if next_step:
        next_act = (next_step.get("action") or "").strip().lower()
        if next_act == "wait_until":
            # The next step is an explicit synchronization step (wait_until).
            # Avoid synthetic navigation inferences that could conflict or hang.
            return None

    # 3. Next step explicitly verifies URL
    if next_step:
        next_act = (next_step.get("action") or "").strip().lower()
        if next_act == "verify_url":
            exp_url = (
                next_step.get("expected_result")
                or next_step.get("value")
                or next_step.get("target")
                or app_url_clean
                or ""
            ).strip()
            # If the current URL already matches the expected URL pattern, the click
            # does not require a redirect away from the current URL.
            if exp_url and exp_url.lower() in cur_url_lower:
                return None
            return {
                "type": "verify_url_target",
                "expected_pattern": exp_url or None,
                "from_url": cur_url,
                "reason": f"Next step ({next_act}) verifies URL '{exp_url}'",
            }

    # 3. Next step expected_result indicates landing page / home page / redirection
    if next_step:
        next_exp = (next_step.get("expected_result") or "").strip().lower()
        if any(
            phrase in next_exp
            for phrase in (
                "landing page",
                "home page",
                "dashboard",
                "welcome page",
                "redirected",
                "navigates to",
                "logged in",
                "signed in",
                "main page",
            )
        ):
            is_auth_page = any(k in cur_url_lower for k in AUTH_URL_KEYWORDS)
            is_diff_than_app = bool(app_url_clean) and not cur_url_lower.startswith(app_url_clean.lower().rstrip("/"))
            is_progression = any(
                re.search(rf"\b{re.escape(k)}\b", tgt) for k in SUBMIT_PROGRESSION_KEYWORDS
            )
            if is_auth_page or is_diff_than_app or is_progression:
                return {
                    "type": "landing_page_transition",
                    "expected_pattern": app_url_clean or None,
                    "from_url": cur_url,
                    "reason": f"Next step expects landing page transition ('{next_step.get('expected_result')}')",
                }

    # 4. Next step target matches a saved inventory snapshot belonging to a different URL
    if saved_inventory and next_step:
        try:
            from app.services.discovery_service import search_saved_snapshots
            next_tgt = (next_step.get("target") or "").strip()
            next_act = (next_step.get("action") or "").strip().lower()
            if next_tgt and not is_direct_selector(next_tgt):
                matches = search_saved_snapshots(saved_inventory, next_tgt, action=next_act, max_results=1)
                if matches:
                    snap_url = (matches[0].get("snapshot_url") or "").strip()
                    if snap_url and cur_url:
                        cur_base = cur_url.split("?")[0].rstrip("/")
                        snap_base = snap_url.split("?")[0].rstrip("/")
                        if cur_base != snap_base:
                            return {
                                "type": "saved_inventory_target",
                                "expected_pattern": snap_base,
                                "from_url": cur_url,
                                "reason": f"Next target '{next_tgt}' is from saved page '{snap_base}'",
                            }
        except Exception:
            pass

    # 5. Progression / Submit button on an authentication or identity page
    is_progression_target = any(
        re.search(rf"\b{re.escape(k)}\b", tgt) for k in SUBMIT_PROGRESSION_KEYWORDS
    )
    is_auth_page = any(k in cur_url_lower for k in AUTH_URL_KEYWORDS)
    is_diff_than_app = bool(app_url_clean) and not cur_url_lower.startswith(app_url_clean.lower().rstrip("/"))

    if is_progression_target and (is_auth_page or is_diff_than_app):
        next_act = (next_step.get("action") or "").strip().lower() if next_step else ""
        if next_act == "verify_url":
            next_exp_url = (
                next_step.get("expected_result")
                or next_step.get("value")
                or next_step.get("target")
                or ""
            ).strip()
            if next_exp_url and next_exp_url.lower() in cur_url_lower:
                return None
        if next_act not in ("fill", "clear"):
            return {
                "type": "auth_progression",
                "expected_pattern": app_url_clean or None,
                "from_url": cur_url,
                "reason": f"Progression click '{raw_target}' on authentication page '{cur_url}'",
            }

    # 6. Task / Sub-module Navigation link (e.g. "New Person link", "Hire an Employee link")
    if any(k in tgt for k in ("new person", "hire an employee")):
        next_act = (next_step.get("action") or "").strip().lower() if next_step else ""
        next_tgt = (next_step.get("target") or "").lower() if next_step else ""
        next_exp = (next_step.get("expected_result") or "").lower() if next_step else ""

        is_already_on_task_page = (
            "fndoverview" in cur_url_lower
            or "new_person" in cur_url_lower
            or "itemnode_workforce_management_new_person" in cur_url_lower
        )
        is_targeting_employee_form = (
            any(k in next_tgt for k in ("legal employer", "last name", "first name", "hire date", "hire action", "business unit"))
            or any(k in (exp.lower() + next_exp) for k in ("creation form", "identification", "employee creation", "form is opened", "form is displayed"))
            or ("hire an employee" in tgt and is_already_on_task_page)
        )

        if is_targeting_employee_form and ("hire an employee" in tgt or is_already_on_task_page):
            # In-page content transition within Oracle Fusion (URL typically remains at FndOverview via PPR)
            return {
                "type": "in_page_form_transition",
                "expected_pattern": None,
                "requires_url_change": False,
                "in_page_transition": True,
                "transition_verifier": "employee_creation_form",
                "expected_state": "Employee creation form ('Hire an Employee: Identification' or live 'Legal Employer' control, replacing New Person task menu)",
                "from_url": cur_url,
                "reason": f"Task link '{raw_target}' transitions in-page to employee creation form ('Hire an Employee: Identification')",
            }

        if (
            "fusewelcome" in cur_url_lower
            or "atkhomepage" in cur_url_lower
            or any(k in next_tgt for k in ("legal employer", "hire an employee", "last name", "hire date"))
            or any(k in next_exp for k in ("hire", "task", "form", "selected", "opened"))
        ):
            return {
                "type": "task_page_navigation",
                "expected_pattern": "fndoverview" if ("fusewelcome" in cur_url_lower or "atkhomepage" in cur_url_lower) else None,
                "requires_url_change": True if ("fusewelcome" in cur_url_lower or "atkhomepage" in cur_url_lower) else False,
                "in_page_transition": False,
                "from_url": cur_url,
                "reason": f"Task navigation link '{raw_target}' to sub-module/form",
            }

    # 7. Explicit in-page transition expectation (e.g. modal, drawer, tab, or dialog opening without URL change)
    if exp:
        exp_lower = exp.lower()
        if any(w in exp_lower for w in ("modal is opened", "dialog is opened", "drawer is opened", "popup is displayed", "tab is selected")):
            return {
                "type": "in_page_content_transition",
                "expected_pattern": None,
                "requires_url_change": False,
                "in_page_transition": True,
                "transition_verifier": "generic_in_page",
                "expected_state": exp,
                "from_url": cur_url,
                "reason": f"In-page content transition expected: '{exp}'",
            }

    return None


def _get_first_locator(loc: Any) -> Any:
    """Helper to retrieve the first locator element regardless of whether 'first' is a property or method."""
    first_attr = getattr(loc, "first", loc)
    if callable(first_attr):
        try:
            return first_attr()
        except TypeError:
            return first_attr
    return first_attr


async def check_employee_form_state(page: Any) -> tuple[bool, str]:
    """
    Check whether the Oracle Fusion Employee Creation Form ('Hire an Employee: Identification')
    is ready and confirmed to have replaced the New Person task menu.

    Reliable conditions (Requirements 2, 3, 4):
    1. Heading 'Hire an Employee: Identification' is visible; OR
       Live 'Legal Employer' control is present and usable (visible & enabled).
    2. Confirmation that the New Person task menu has been replaced:
       - The New Person task menu prompt ('What do you want to do or manage?') is not visible, OR
       - The intermediate task list links are gone/hidden, OR
       - The employee form identification container is attached and visible.
    """
    if not hasattr(page, "locator"):
        return False, "page does not support locator"

    # Step 1: Check form headings
    heading_found = False
    try:
        h_loc = page.locator(
            "h1:has-text('Hire an Employee: Identification'), "
            "h2:has-text('Hire an Employee: Identification'), "
            "h1:has-text('Identification'), "
            ":text('Hire an Employee: Identification')"
        )
        if await h_loc.count() > 0:
            first_h = _get_first_locator(h_loc)
            if hasattr(first_h, "is_visible") and await first_h.is_visible():
                heading_found = True
            elif not hasattr(first_h, "is_visible"):
                heading_found = True
    except Exception:
        pass

    # Step 2: Check live Legal Employer control
    control_found = False
    try:
        le_loc = page.locator(
            "#_FOpt1\\:_FOr1\\:0\\:_FONSr2\\:0\\:MAnt2\\:1\\:pt1\\:pt_r1\\:0\\:SP1\\:selectOneChoice3\\:\\:content, "
            "input[role='combobox'][aria-label*='Legal Employer' i], "
            "label:has-text('Legal Employer')"
        )
        if await le_loc.count() > 0:
            first_le = _get_first_locator(le_loc)
            is_vis = await first_le.is_visible() if hasattr(first_le, "is_visible") else True
            if is_vis:
                is_usable = True
                if hasattr(first_le, "is_enabled"):
                    try:
                        is_usable = await first_le.is_enabled()
                    except Exception:
                        is_usable = True
                if is_usable:
                    control_found = True
    except Exception:
        pass

    if not (heading_found or control_found):
        return False, "neither employee form heading nor Legal Employer control is visible yet"

    # Step 3: Confirm that the New Person task menu has been replaced
    try:
        menu_prompt = page.locator("text='What do you want to do or manage?'")
        if await menu_prompt.count() > 0:
            first_p = _get_first_locator(menu_prompt)
            if hasattr(first_p, "is_visible") and await first_p.is_visible():
                task_list = page.locator(
                    "#_FOpt1\\:_FOr1\\:0\\:_FONSr2\\:0\\:_FOTsr1\\:0\\:cl01Upl\\:UPsp1\\:cl01Pce\\:cl01Lv\\:1\\:cl01Pse\\:cl01Cl, "
                    "a:has-text('Add a Contingent Worker')"
                )
                if await task_list.count() > 0:
                    first_tl = _get_first_locator(task_list)
                    if hasattr(first_tl, "is_visible") and await first_tl.is_visible():
                        return False, "New Person task menu is still active and has not been replaced"
    except Exception:
        pass

    details = []
    if heading_found:
        details.append("heading 'Hire an Employee: Identification' is visible")
    if control_found:
        details.append("live 'Legal Employer' control is present and usable")
    return True, f"{', '.join(details)} and New Person menu replaced"


async def ensure_hire_employee_form_ready(
    page: Any,
    target: str,
    action: str,
    log: Any,
) -> bool:
    """
    Ensure the actual Oracle Fusion Employee Creation Form ('Hire an Employee: Identification')
    is loaded and ready before interacting with form fields like 'Legal Employer'.

    If the browser is currently on the intermediate New Person task page, automatically clicks
    the 'Hire an Employee' task link to advance to the actual form and verifies form readiness.
    """
    clean_target = (target or "").strip().lower()

    form_fields = (
        "legal employer", "hire date", "hire action", "hire reason",
        "last name", "first name", "business unit", "person details", "national identifier"
    )

    if not any(f in clean_target for f in form_fields):
        return False

    # Check if form is already confirmed ready
    is_ready, details = await check_employee_form_state(page)
    if is_ready:
        log(f"  ✓ Employee creation form confirmed ready ({details}).")
        return True

    cur_url = (page.url if hasattr(page, "url") else "").lower()
    page_title = ""
    try:
        if hasattr(page, "title"):
            page_title = await page.title()
    except Exception:
        pass
    title_lower = page_title.lower()

    is_new_person_url = "itemnode_workforce_management_new_person" in cur_url or "fndoverview" in cur_url
    is_new_person_title = "new person" in title_lower and "hire an employee: identification" not in title_lower

    is_new_person_task_page = False
    if is_new_person_url or is_new_person_title:
        try:
            if hasattr(page, "locator"):
                heading_count = await page.locator(
                    "h1:has-text('New Person'), h2:has-text('New Person'), text='What do you want to do or manage?'"
                ).count()
                task_link = page.locator(
                    "#_FOpt1\\:_FOr1\\:0\\:_FONSr2\\:0\\:_FOTsr1\\:0\\:cl01Upl\\:UPsp1\\:cl01Pce\\:cl01Lv\\:1\\:cl01Pse\\:cl01Cl, "
                    "a:has-text('Hire an Employee')"
                ).first
                if heading_count > 0 or (await task_link.count() > 0 and await task_link.is_visible()):
                    is_new_person_task_page = True
        except Exception:
            pass

    if is_new_person_task_page:
        log("  ℹ Detected intermediate Oracle Fusion New Person task page.")
        log("  → Advancing to employee creation form by clicking 'Hire an Employee' task link...")
        try:
            task_link = page.locator(
                "#_FOpt1\\:_FOr1\\:0\\:_FONSr2\\:0\\:_FOTsr1\\:0\\:cl01Upl\\:UPsp1\\:cl01Pce\\:cl01Lv\\:1\\:cl01Pse\\:cl01Cl, "
                "a:has-text('Hire an Employee')"
            ).first
            if hasattr(task_link, "click"):
                await task_link.click(timeout=settings.PLAYWRIGHT_TIMEOUT_MS)
            elif hasattr(page, "click"):
                await page.click("text='Hire an Employee'", timeout=settings.PLAYWRIGHT_TIMEOUT_MS)
        except Exception as click_err:
            log(f"  ⚠ Notice clicking Hire an Employee task link: {click_err}")

    # Condition-based wait for the employee creation form to be ready
    form_timeout_s = min(settings.PLAYWRIGHT_NAVIGATION_TIMEOUT_MS / 1000.0, 15.0)
    start_t = asyncio.get_event_loop().time()

    while True:
        is_ready, details = await check_employee_form_state(page)
        if is_ready:
            log(f"  ✓ Employee creation form confirmed ready ({details}).")
            return True

        if (asyncio.get_event_loop().time() - start_t) >= form_timeout_s:
            break
        await asyncio.sleep(0.1)

    return False


async def wait_for_page_transition(
    page: Any,
    url_before: str,
    nav_expectation: Dict[str, Any],
    timeout_ms: int,
    log: Any,
) -> str:
    """
    Condition-based wait for page navigation or in-page content transition to complete.
    
    Supports:
      1. URL-based navigation: Monitors URL transitions away from `url_before` and waits for page readiness.
      2. In-page content transitions: Monitors DOM state changes (such as form appearance, heading changes,
         and dismissal of previous task menus) where the URL remains unchanged (e.g. Oracle ADF PPR).

    If neither a URL transition nor the expected form/content state occurs within timeout_ms,
    raises NavigationTimeoutError with descriptive diagnostics.
    """
    timeout_s = max(timeout_ms / 1000.0, 1.0)
    start_time = asyncio.get_event_loop().time()
    expected_pattern = nav_expectation.get("expected_pattern")
    reason = nav_expectation.get("reason", "Expected page transition")
    requires_url_change = nav_expectation.get("requires_url_change", True)
    in_page_transition = nav_expectation.get("in_page_transition", False)
    transition_verifier = nav_expectation.get("transition_verifier")
    expected_state = nav_expectation.get("expected_state") or expected_pattern or reason

    log(f"  ⏳ Waiting for page transition ({reason}; timeout={timeout_s:.1f}s)...")

    transition_succeeded = False
    success_details = ""
    last_url = page.url if hasattr(page, "url") else url_before

    while True:
        curr_url = page.url if hasattr(page, "url") else ""
        if curr_url:
            last_url = curr_url

        # Check 1: In-page transition verifier (e.g. Oracle Fusion employee creation form)
        if in_page_transition or not requires_url_change or transition_verifier:
            if transition_verifier == "employee_creation_form":
                is_ready, details = await check_employee_form_state(page)
                if is_ready:
                    transition_succeeded = True
                    success_details = details
                    log(f"  ✓ In-page content transition confirmed: {details}")
                    break
            elif transition_verifier == "generic_in_page":
                exp_target = nav_expectation.get("expected_target")
                if exp_target and hasattr(page, "locator"):
                    loc = page.locator(exp_target).first
                    if await loc.count() > 0 and await loc.is_visible():
                        transition_succeeded = True
                        success_details = f"target '{exp_target}' is visible"
                        break

        # Check 2: URL change
        if curr_url and curr_url != url_before:
            if expected_pattern:
                if expected_pattern.lower() in curr_url.lower():
                    transition_succeeded = True
                    success_details = f"URL transitioned to match '{expected_pattern}' ({curr_url})"
                    break
                curr_lower = curr_url.lower()
                is_auth_intermediary = any(k in curr_lower for k in ("oauth", "authorize", "saml", "sso", "callback", "redirect"))
                if not is_auth_intermediary:
                    transition_succeeded = True
                    success_details = f"URL transitioned to '{curr_url}'"
                    break
            else:
                curr_lower = curr_url.lower()
                is_auth_intermediary = any(k in curr_lower for k in ("oauth", "authorize", "saml", "sso", "callback"))
                if not is_auth_intermediary:
                    transition_succeeded = True
                    success_details = f"URL transitioned to '{curr_url}'"
                    break

        elapsed = asyncio.get_event_loop().time() - start_time
        if elapsed >= timeout_s:
            break

        await asyncio.sleep(0.05)

    curr_url = page.url if hasattr(page, "url") else last_url
    if not transition_succeeded:
        page_title = await page.title() if hasattr(page, "title") else ""
        if requires_url_change and not in_page_transition:
            error_msg = (
                f"Navigation timed out after {timeout_s:.1f}s: Expected redirect away from '{url_before}' "
                f"({reason}), but browser remained at '{curr_url}' (title: '{page_title}'). "
                f"Expected state: '{expected_state}'. "
                "Validation errors or missing credentials may have prevented navigation."
            )
        else:
            error_msg = (
                f"Navigation timed out after {timeout_s:.1f}s: Expected page/content transition "
                f"({reason}) from '{url_before}', but browser remained at '{curr_url}' (title: '{page_title}'). "
                f"Expected state: {expected_state}. "
                "The page content did not transition to the expected state within the timeout."
            )
        raise NavigationTimeoutError(error_msg)

    # Allow the new page DOM to load and stabilize
    try:
        if hasattr(page, "wait_for_load_state"):
            await page.wait_for_load_state("domcontentloaded", timeout=min(timeout_ms, 10000))
    except Exception:
        pass

    final_url = page.url if hasattr(page, "url") else last_url
    return final_url


def categorize_step_error(exc: Exception, action: str, msg: str) -> tuple[str, str]:
    """
    Categorize a step exception into a clean, human-readable failure category and display label.
    Categories:
      - access_denied: Website Access Denied / 403 Forbidden
      - invalid_locator_syntax: Invalid selector syntax
      - ambiguous_target: Multiple elements matched target
      - element_not_visible: Element present in DOM but hidden
      - missing_element: Element could not be found or resolved (0 matches)
      - assertion_failure: Text/URL verification assertion failed
      - navigation_timeout: Navigation or page-readiness timeout
      - timeout: Action timeout
      - unsupported_action: Unsupported action
      - parsing_failure: Invalid CSV or missing required target/value
      - browser_launch_error: Browser launch error or process disconnect
      - execution_error: Unhandled browser or execution error
    """
    msg_lower = msg.lower()
    act = (action or "").strip().lower()

    if isinstance(exc, AccessDeniedError) or "access denied" in msg_lower or "403 forbidden" in msg_lower:
        return "access_denied", "Website Access Denied"

    if isinstance(exc, InvalidLocatorSyntaxError) or "invalid locator syntax" in msg_lower or "while parsing selector" in msg_lower or "not a valid selector" in msg_lower:
        return "invalid_locator_syntax", "Invalid Locator Syntax"

    if isinstance(exc, AmbiguousElementError) or "ambiguous target" in msg_lower or ("matches" in msg_lower and "visible elements" in msg_lower):
        return "ambiguous_target", "Ambiguous Target"

    if isinstance(exc, ElementNotVisibleError) or "element is not visible" in msg_lower or "present in dom but is not visible" in msg_lower or "present in the dom but is not visible" in msg_lower or "present in dom but hidden" in msg_lower:
        return "element_not_visible", "Element Present But Hidden"

    if isinstance(exc, ElementNotFoundError) or ("could not find any" in msg_lower) or ("not found" in msg_lower and "text" not in msg_lower and "url" not in msg_lower):
        return "missing_element", "Element Not Found"

    if isinstance(exc, AssertionError) or "assertion" in msg_lower or "verification failed" in msg_lower or "was not found as visible text" in msg_lower or "unexpectedly" in msg_lower or "negative" in msg_lower:
        return "assertion_failure", "Assertion Failed"

    if (
        isinstance(exc, NavigationTimeoutError)
        or (act == "navigate" and ("timeout" in msg_lower or "timed out" in msg_lower))
        or "navigation timed out" in msg_lower
        or "expected redirect away from" in msg_lower
        or "page transition timed out" in msg_lower
    ):
        return "navigation_timeout", "Navigation Timeout"

    if (act == "wait_until" or "wait condition" in msg_lower) and (
        isinstance(exc, (TimeoutError, asyncio.TimeoutError)) or "timeout" in msg_lower or "timed out" in msg_lower
    ):
        return "wait_timeout", "Wait Condition Timed Out"

    if "browser not configured" in msg_lower or "failed to launch browser" in msg_lower or "browser page crashed" in msg_lower or "browser process disconnected" in msg_lower:
        return "browser_launch_error", "Browser Launch Error"

    if "unsupported action" in msg_lower:
        return "parsing_failure", "Unsupported Action"

    if isinstance(exc, ValueError) or "required" in msg_lower or "requires" in msg_lower:
        return "parsing_failure", "Invalid CSV / Missing Fields"

    if isinstance(exc, asyncio.TimeoutError) or "timeout" in msg_lower or "timed out" in msg_lower:
        return "timeout", "Timeout"

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
    if act == "clear":
        return f"clear '{tgt}'"
    if act == "check":
        return f"check '{tgt}'"
    if act == "uncheck":
        return f"uncheck '{tgt}'"
    if act == "verify_not_url":
        return f"verify current url does not contain '{exp or tgt or val}'"
    if act == "verify_not_text":
        if tgt:
            return f"verify that '{exp or tgt or val}' is not visible in '{tgt}'"
        return f"verify that '{exp or tgt or val}' is not visible"
    if act == "select_option":
        return f"select '{val}' from '{tgt}'"
    if act == "wait_until":
        if tgt == "url_contains":
            return f"wait until url contains '{val or exp}'"
        if tgt == "page_heading":
            return f"wait until page heading is '{val or exp}'"
        if tgt == "element_visible":
            return f"wait until '{val or exp}' is visible"
        if tgt == "element_enabled":
            return f"wait until '{val or exp}' is enabled"
        if tgt == "element_hidden":
            return f"wait until '{val or exp}' is hidden"
        return f"wait until {tgt} '{val or exp}'".strip()
    if act == "discover_page":
        return "discover page elements"
    return f"{act} {tgt}".strip()

SECRET_REFERENCE_PATTERN = re.compile(r"^\$\{secret:([A-Za-z_][A-Za-z0-9_]*)\}$")
SECRET_REFERENCE_PREFIX = "${secret:"
PLACEHOLDER_PATTERN = re.compile(r"\{\{([a-zA-Z_][a-zA-Z0-9_]*)\}\}")

BLOCKED_SYSTEM_ENV_VARS = {
    "DATABASE_URL",
    "SECRET_KEY",
    "SECRET_ENCRYPTION_KEY",
    "JWT_SECRET",
    "PASSWORD",
    "SMTP_PASSWORD",
    "PATH",
    "TOKEN",
    "KEY",
    "SECRET",
    "PORT",
    "PYTHONPATH",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_ACCESS_KEY_ID",
}

ALLOWED_SECRET_PREFIXES = (
    "NOETRIX_",
    "BENCHMARK_",
    "APEX_",
    "TEST_",
    "DYN_",
    "CSV_",
)


def resolve_placeholders(
    text: Optional[str],
    variables: Optional[Dict[str, Any]] = None,
    project_id: Optional[str] = None,
) -> tuple[str, List[str]]:
    """
    Interpolate {{variable_name}} placeholders at runtime using project-scoped variables.

    Returns:
        (interpolated_string, list_of_secret_values_used)
    Raises:
        ValueError if a variable is missing or no project context is provided.
    """
    if not text:
        return text or "", []

    matches = list(PLACEHOLDER_PATTERN.finditer(text))
    if not matches:
        return text, []

    if variables is None:
        raise ValueError(
            f"Cannot resolve variable placeholders in '{text}': no project variable context provided."
        )

    secrets_used: List[str] = []

    def replace_match(m: re.Match) -> str:
        var_name = m.group(1)
        if var_name not in variables:
            proj_hint = f" for project '{project_id}'" if project_id else ""
            raise ValueError(
                f"Required test variable '{{{{{var_name}}}}}' is not configured{proj_hint}."
            )
        var_info = variables[var_name]
        val = var_info.get("value") if isinstance(var_info, dict) else str(var_info)
        val_str = str(val) if val is not None else ""
        if isinstance(var_info, dict) and var_info.get("is_secret"):
            if val_str:
                secrets_used.append(val_str)
        return val_str

    resolved = PLACEHOLDER_PATTERN.sub(replace_match, text)
    return resolved, secrets_used


def _resolve_secret_reference(
    value: str,
    variables: Optional[Dict[str, Any]] = None,
) -> tuple[str, Optional[str]]:
    """
    Resolve an exact secret reference.
    First checks project variables. If falling back to host environment variables,
    strictly enforces that arbitrary system secrets (DATABASE_URL, SECRET_KEY, etc.)
    cannot be accessed, permitting only allowed test-prefixed environment variables.
    """
    match = SECRET_REFERENCE_PATTERN.fullmatch(value)
    if match:
        name = match.group(1)
        # 1. Project variables precedence
        if variables and name in variables:
            var_info = variables[name]
            val = var_info.get("value") if isinstance(var_info, dict) else str(var_info)
            val_str = str(val) if val is not None else ""
            return val_str, val_str

        # 2. Block system environment variables
        upper_name = name.upper()
        if upper_name in BLOCKED_SYSTEM_ENV_VARS or (
            any(w in upper_name for w in ("DATABASE", "JWT", "ENCRYPTION"))
            and not upper_name.startswith(ALLOWED_SECRET_PREFIXES)
        ):
            raise ValueError(f"Access to host environment variable '{name}' is denied.")

        # 3. Allow test-prefixed environment variables for backward compatibility
        if upper_name.startswith(ALLOWED_SECRET_PREFIXES):
            secret = os.environ.get(name)
            if secret is None or secret == "":
                raise ValueError("Required secret is not configured.")
            return secret, secret

        raise ValueError(
            f"Access to host environment variable '{name}' is denied. "
            "Please configure this secret in Project Settings Test Variables."
        )

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
    project_id: Optional[str] = None,
    variables: Optional[Dict[str, Any]] = None,
    headless: Optional[bool] = None,
    saved_inventory: Optional[Any] = None,
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
    step_records: List[Dict[str, Any]] = []

    result_dir = Path(artifacts_dir) / "runs" / run_id / "results" / test_case_id
    result_dir.mkdir(parents=True, exist_ok=True)
    videos_dir = Path(artifacts_dir) / "runs" / run_id / "videos"
    videos_dir.mkdir(parents=True, exist_ok=True)
    # Load and decrypt project variables from DB if project_id is provided and variables is None
    if variables is None and project_id is not None:
        try:
            from app.database import SessionLocal
            from app.models.project_variable import ProjectVariable
            from app.services.encryption import decrypt_secret
            with SessionLocal() as db:
                db_vars = db.query(ProjectVariable).filter(ProjectVariable.project_id == project_id).all()
                variables = {}
                for v in db_vars:
                    val = v.value
                    if v.is_secret and val:
                        try:
                            val = decrypt_secret(val)
                        except Exception:
                            val = ""
                    variables[v.name] = {"value": val, "is_secret": v.is_secret}
        except Exception:
            variables = None

    # Load saved discovery inventory snapshots for project if available and not explicitly provided
    if saved_inventory is None and project_id is not None:
        try:
            from app.database import SessionLocal
            from app.models.discovery import DiscoverySession, DiscoverySnapshot
            with SessionLocal() as db:
                snaps = (
                    db.query(DiscoverySnapshot)
                    .join(DiscoverySession, DiscoverySnapshot.session_id == DiscoverySession.id)
                    .filter(DiscoverySession.project_id == project_id)
                    .all()
                )
                if snaps:
                    saved_inventory = [
                        {
                            "id": s.id,
                            "page_url": s.page_url,
                            "page_title": s.page_title,
                            "inventory_data": s.inventory_data,
                        }
                        for s in snaps
                    ]
        except Exception:
            saved_inventory = None

    sorted_steps = sorted(
        steps, key=lambda s: int(s.get("step_number") or 0)
    )
    def _step_contains_secret(s: Dict[str, Any]) -> bool:
        for fld in (str(s.get("value") or ""), str(s.get("target") or ""), str(s.get("expected_result") or "")):
            if SECRET_REFERENCE_PREFIX in fld:
                return True
            if variables:
                for m in PLACEHOLDER_PATTERN.finditer(fld):
                    var_name = m.group(1)
                    if var_name in variables and variables[var_name].get("is_secret"):
                        return True
        return False

    has_secret_reference = any(_step_contains_secret(step) for step in sorted_steps)

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
                browser_args = [
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ]
                effective_headless = settings.PLAYWRIGHT_HEADLESS if headless is None else headless
                browser = await pw.chromium.launch(
                    headless=effective_headless,
                    args=browser_args,
                )
                if hasattr(browser, "on"):
                    browser.on("disconnected", lambda: log("⚠ Playwright lifecycle: Browser process disconnected."))
                log(
                    "Chromium browser launched "
                    f"(headless={effective_headless})"
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
            if hasattr(context, "on"):
                context.on("close", lambda: log("ℹ Playwright lifecycle: Browser context closed."))
            page = await context.new_page()
            if hasattr(page, "on"):
                page.on("crash", lambda: log("⚠ Playwright lifecycle: Browser page crashed (renderer process terminated)!"))
                page.on("close", lambda: log("ℹ Playwright lifecycle: Browser page closed."))
            page.set_default_timeout(settings.PLAYWRIGHT_TIMEOUT_MS)
            if hasattr(page, "set_default_navigation_timeout"):
                page.set_default_navigation_timeout(settings.PLAYWRIGHT_TIMEOUT_MS)
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
                    raw_target = (step.get("target") or "").strip()
                    raw_value = step.get("value")
                    raw_val_str = str(raw_value).strip() if raw_value is not None else ""
                    raw_expected = (step.get("expected_result") or "").strip()
                    step_num = step.get("step_number", step_idx + 1)

                    target = raw_target
                    val_str = raw_val_str
                    expected = raw_expected
                    safe_value = raw_val_str
                    safe_target = raw_target
                    safe_expected = raw_expected
                    orig_instruction = step.get("original_instruction") or reconstruct_instruction(
                        action, raw_target, raw_val_str, raw_expected
                    )
                    verification_result: Optional[Dict[str, Any]] = None

                    try:
                        resolved_target, s_target = resolve_placeholders(raw_target, variables, project_id)
                        resolved_val, s_val = resolve_placeholders(raw_val_str, variables, project_id)
                        resolved_expected, s_expected = resolve_placeholders(raw_expected, variables, project_id)

                        for s in s_target + s_val + s_expected:
                            if s and s not in sensitive_values:
                                sensitive_values.append(s)

                        target = resolved_target
                        val_str = resolved_val
                        expected = resolved_expected

                        sensitive_target = any(
                            word in raw_target.lower()
                            for word in ("password", "passwd", "secret", "token")
                        ) or bool(s_target)
                        secret_reference = (
                            (action in ("fill", "select_option"))
                            and (SECRET_REFERENCE_PREFIX in raw_val_str or bool(s_val))
                        )
                        safe_value = (
                            "[REDACTED]"
                            if (sensitive_target or secret_reference or bool(s_val))
                            else val_str
                        )
                        safe_target = "[REDACTED]" if bool(s_target) else target
                        safe_expected = "[REDACTED]" if bool(s_expected) else expected
                        orig_instruction = step.get("original_instruction") or reconstruct_instruction(
                            action, safe_target, safe_value, safe_expected
                        )
                        log(
                            f"Step {step_num}: [{action}] target='{safe_target}' "
                            f"value='{safe_value}' expected='{safe_expected}'"
                        )
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
                            if not (val_str or target or expected):
                                raise ValueError(
                                    "Action 'navigate' requires a destination URL in 'value' or 'target'."
                                )
                            if app_url and (
                                url.startswith("/") or not url.startswith("http")
                            ):
                                base = app_url.rstrip("/")
                                path = url if url.startswith("/") else f"/{url}"
                                url = f"{base}{path}"

                            log(f"  → Navigating to: {url}")
                            nav_timeout = settings.PLAYWRIGHT_TIMEOUT_MS
                            try:
                                response = await page.goto(url, wait_until="domcontentloaded", timeout=nav_timeout)
                            except Exception as nav_exc:
                                browser_conn = browser.is_connected() if hasattr(browser, "is_connected") else "unknown"
                                page_closed = page.is_closed() if hasattr(page, "is_closed") else "unknown"
                                log(
                                    f"  ⚠ Navigation error during goto: {type(nav_exc).__name__}: {nav_exc} "
                                    f"(browser_connected={browser_conn}, page_closed={page_closed})"
                                )
                                raise

                            # Allow page to settle and stabilize after initial DOM load
                            try:
                                if hasattr(page, "wait_for_load_state"):
                                    await page.wait_for_load_state("domcontentloaded", timeout=min(nav_timeout, 5000))
                            except Exception:
                                pass

                            current_page_url = page.url if hasattr(page, "url") else url
                            page_title = await page.title() if hasattr(page, "title") else ""
                            log(f"  ✓ Navigated successfully to: {current_page_url} (title: '{page_title}')")

                            # Check for Access Denied / 403 Forbidden
                            status_code = response.status if (response and hasattr(response, "status")) else None
                            title_lower = page_title.lower()
                            if status_code in (401, 403) or "access denied" in title_lower or "403 forbidden" in title_lower:
                                log(f"  ⚠ Notice: Destination rendered Access Denied (status={status_code}, title='{page_title}')")

                        elif action == "fill":
                            if not target:
                                raise ValueError(
                                    "Target selector is required for 'fill' action."
                                )
                            fill_value, resolved_secret = _resolve_secret_reference(
                                val_str, variables
                            )
                            if resolved_secret is not None:
                                sensitive_values.append(resolved_secret)
                            elif sensitive_target and val_str:
                                sensitive_values.append(val_str)
                            log(f"  → Filling target '{safe_target}' with '{safe_value}'")
                            # Ensure employee creation form is loaded if targeting form controls
                            await ensure_hire_employee_form_ready(page, target, action, log)
                            if hasattr(page, "locator") or not hasattr(page, "fill"):
                                target_locator = await resolve_locator(
                                    page,
                                    target,
                                    action="fill",
                                    timeout_ms=min(settings.PLAYWRIGHT_TIMEOUT_MS, 15000),
                                    saved_inventory=saved_inventory,
                                )
                                if hasattr(target_locator, "fill"):
                                    try:
                                        await target_locator.fill(
                                            fill_value, timeout=settings.PLAYWRIGHT_TIMEOUT_MS
                                        )
                                    except Exception as fill_err:
                                        if hasattr(target_locator, "click") and hasattr(target_locator, "press_sequentially"):
                                            log(f"  ℹ Combobox fill fallback: clicking and typing into '{safe_target}'...")
                                            await target_locator.click(timeout=5000)
                                            await target_locator.press_sequentially(fill_value, timeout=5000)
                                        else:
                                            raise fill_err
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

                            url_before = page.url if hasattr(page, "url") else ""
                            next_step = sorted_steps[step_idx + 1] if (step_idx + 1 < len(sorted_steps)) else None
                            nav_expectation = infer_expected_navigation(
                                step,
                                next_step,
                                current_url=url_before,
                                app_url=app_url,
                                saved_inventory=saved_inventory,
                            )

                            log(f"  → Clicking target '{target}'")

                            target_locator = await resolve_locator(
                                page,
                                target,
                                action="click",
                                timeout_ms=min(settings.PLAYWRIGHT_TIMEOUT_MS, 15000),
                                saved_inventory=saved_inventory,
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

                            # Condition-based wait for expected page transition or redirect
                            if nav_expectation:
                                nav_timeout = getattr(settings, "PLAYWRIGHT_NAVIGATION_TIMEOUT_MS", 30000)
                                new_url = await wait_for_page_transition(
                                    page,
                                    url_before=url_before,
                                    nav_expectation=nav_expectation,
                                    timeout_ms=nav_timeout,
                                    log=log,
                                )
                                log(f"  ✓ Navigation transition completed: {new_url}")
                            else:
                                # Non-navigating click: quick non-blocking settle
                                try:
                                    if hasattr(page, "wait_for_load_state"):
                                        await page.wait_for_load_state(
                                            "domcontentloaded",
                                            timeout=500,
                                        )
                                except Exception:
                                    pass

                            log(f"  ✓ Click action completed for '{target}'")
                            log(f"  Current URL after click: {page.url if hasattr(page, 'url') else ''}")


                        elif action == "verify_url":
                            expected_url = expected or val_str or target or app_url
                            if not expected_url:
                                raise ValueError(
                                    "Action 'verify_url' requires an expected URL pattern in 'value', 'expected_result', or 'target'."
                                )
                            curr_url = page.url if hasattr(page, "url") else ""
                            log(
                                "  → Verifying URL "
                                f"(expected contains='{expected_url}', "
                                f"current='{curr_url}')"
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
                            current_url = curr_url

                            while True:
                                current_url = page.url if hasattr(page, "url") else ""
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
                                page_title = await page.title() if hasattr(page, "title") else ""
                                title_lower = page_title.lower()
                                if "access denied" in title_lower or "403 forbidden" in title_lower:
                                    raise AccessDeniedError(
                                        f"Website access denied: Expected URL '{expected_url}', but current page rendered Access Denied "
                                        f"(current URL: '{current_url}', title: '{page_title}')."
                                    )
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
                            # Contract: prefer value as literal text; fallback to expected_result for legacy CSVs
                            text_to_find = val_str.strip() if val_str else expected.strip()
                            if not text_to_find:
                                raise ValueError(
                                    "Action 'verify_text' requires text to verify in 'value' (preferred) or 'expected_result' (legacy fallback)."
                                )

                            log(
                                f"  → Verifying visible text '{text_to_find}'"
                                + (f" scoped to target '{target}'" if target else "")
                            )

                            container = None
                            if target:
                                container = await resolve_locator(
                                    page,
                                    target,
                                    action="verify_text",
                                    timeout_ms=min(settings.PLAYWRIGHT_TIMEOUT_MS, 15000),
                                    saved_inventory=saved_inventory,
                                )
                                if hasattr(container, "get_by_text"):
                                    locator = container.get_by_text(text_to_find, exact=False).first
                                elif hasattr(container, "locator"):
                                    locator = container.locator(f"text={text_to_find}").first
                                else:
                                    locator = page.get_by_text(text_to_find, exact=False).first
                            else:
                                locator = (
                                    page.get_by_text(text_to_find, exact=False).first
                                    if hasattr(page, "get_by_text")
                                    else page.locator(f"text={text_to_find}").first
                                )

                            found_in_frame = False
                            try:
                                if hasattr(locator, "wait_for"):
                                    await locator.wait_for(
                                        state="visible",
                                        timeout=settings.PLAYWRIGHT_TIMEOUT_MS,
                                    )
                            except Exception as text_exc:
                                # Check frames if target was empty and main page search timed out
                                if not target and hasattr(page, "frames"):
                                    for frame in page.frames:
                                        if hasattr(page, "main_frame") and frame == page.main_frame:
                                            continue
                                        try:
                                            frame_loc = frame.get_by_text(text_to_find, exact=False).first
                                            if hasattr(frame_loc, "is_visible") and await frame_loc.is_visible():
                                                locator = frame_loc
                                                found_in_frame = True
                                                break
                                        except Exception:
                                            continue

                                if not found_in_frame:
                                    curr_url = page.url if hasattr(page, "url") else "unknown"
                                    page_title = await page.title() if hasattr(page, "title") else ""
                                    page_text = ""
                                    try:
                                        if hasattr(page, "locator"):
                                            page_text = await page.locator("body").inner_text()
                                    except Exception:
                                        pass
                                    page_text = _redact_sensitive_text(page_text, sensitive_values)
                                    page_text_preview = " ".join(page_text.split())[:500]

                                    title_l = page_title.lower()
                                    text_l = page_text.lower()
                                    if "access denied" in title_l or "access denied" in text_l or "403 forbidden" in title_l or "403 forbidden" in text_l:
                                        verification_result = {
                                            "type": "verify_text",
                                            "expected": text_to_find,
                                            "matched": False,
                                            "access_denied": True,
                                            "current_url": curr_url,
                                            "page_title": page_title,
                                            "preview": page_text_preview,
                                        }
                                        raise AccessDeniedError(
                                            f"Website access denied: The page at '{curr_url}' rendered an Access Denied / Forbidden response "
                                            f"(title: '{page_title}'). Visible text begins: '{page_text_preview[:200]}'"
                                        )

                                    # Check if text is present in DOM but hidden
                                    element_present_in_dom = False
                                    try:
                                        scope = container if container is not None else page
                                        if hasattr(scope, "get_by_text"):
                                            dom_count = await scope.get_by_text(text_to_find, exact=False).count()
                                            if dom_count > 0:
                                                element_present_in_dom = True
                                    except Exception:
                                        pass

                                    if element_present_in_dom:
                                        verification_result = {
                                            "type": "verify_text",
                                            "expected": text_to_find,
                                            "matched": False,
                                            "element_hidden": True,
                                            "preview": page_text_preview,
                                        }
                                        raise ElementNotVisibleError(
                                            f"Text '{text_to_find}' is present in the DOM but is not visible (hidden). "
                                            f"Target scope: '{target or 'page'}'. Current URL: '{curr_url}'."
                                        )

                                    verification_result = {
                                        "type": "verify_text",
                                        "expected": text_to_find,
                                        "matched": False,
                                        "preview": page_text_preview,
                                    }
                                    target_info = f" within target '{target}'" if target else ""
                                    raise AssertionError(
                                        f"Text '{text_to_find}' was not found as visible text{target_info} on the page "
                                        f"(current URL: '{curr_url}', title: '{page_title}'). "
                                        f"Visible page text begins: '{page_text_preview}'"
                                    ) from text_exc

                            verification_result = {
                                "type": "verify_text",
                                "expected": text_to_find,
                                "matched": True,
                            }
                            log(f"  ✓ Text '{text_to_find}' found on page.")

                        elif action == "clear":
                            if not target:
                                raise ValueError(
                                    "Target selector is required for 'clear' action."
                                )
                            log(f"  → Clearing target '{target}'")
                            target_locator = await resolve_locator(
                                page,
                                target,
                                action="clear",
                                timeout_ms=min(settings.PLAYWRIGHT_TIMEOUT_MS, 15000),
                                saved_inventory=saved_inventory,
                            )
                            if hasattr(target_locator, "clear"):
                                await target_locator.clear(timeout=settings.PLAYWRIGHT_TIMEOUT_MS)
                            elif hasattr(target_locator, "fill"):
                                await target_locator.fill("", timeout=settings.PLAYWRIGHT_TIMEOUT_MS)
                            elif hasattr(page, "fill"):
                                await page.fill(target, "", timeout=settings.PLAYWRIGHT_TIMEOUT_MS)
                            log(f"  ✓ Cleared target '{target}'")

                        elif action == "check":
                            if not target:
                                raise ValueError(
                                    "Target selector is required for 'check' action."
                                )
                            log(f"  → Checking checkbox '{target}'")
                            target_locator = await resolve_locator(
                                page,
                                target,
                                action="check",
                                timeout_ms=min(settings.PLAYWRIGHT_TIMEOUT_MS, 15000),
                                saved_inventory=saved_inventory,
                            )
                            if hasattr(target_locator, "check"):
                                await target_locator.check(timeout=settings.PLAYWRIGHT_TIMEOUT_MS)
                            elif hasattr(target_locator, "click"):
                                await target_locator.click(timeout=settings.PLAYWRIGHT_TIMEOUT_MS)
                            elif hasattr(page, "check"):
                                await page.check(target, timeout=settings.PLAYWRIGHT_TIMEOUT_MS)
                            else:
                                await page.locator(target).click(timeout=settings.PLAYWRIGHT_TIMEOUT_MS)
                            log(f"  ✓ Checked checkbox '{target}'")

                        elif action == "uncheck":
                            if not target:
                                raise ValueError(
                                    "Target selector is required for 'uncheck' action."
                                )
                            log(f"  → Unchecking checkbox '{target}'")
                            target_locator = await resolve_locator(
                                page,
                                target,
                                action="uncheck",
                                timeout_ms=min(settings.PLAYWRIGHT_TIMEOUT_MS, 15000),
                                saved_inventory=saved_inventory,
                            )
                            if hasattr(target_locator, "uncheck"):
                                await target_locator.uncheck(timeout=settings.PLAYWRIGHT_TIMEOUT_MS)
                            elif hasattr(target_locator, "click"):
                                await target_locator.click(timeout=settings.PLAYWRIGHT_TIMEOUT_MS)
                            elif hasattr(page, "uncheck"):
                                await page.uncheck(target, timeout=settings.PLAYWRIGHT_TIMEOUT_MS)
                            else:
                                await page.locator(target).click(timeout=settings.PLAYWRIGHT_TIMEOUT_MS)
                            log(f"  ✓ Unchecked checkbox '{target}'")

                        elif action == "verify_not_url":
                            unexpected_url = expected or val_str or target
                            if not unexpected_url:
                                raise ValueError(
                                    "verify_not_url requires expected_result, value, or target to specify the unexpected URL."
                                )
                            log(
                                f"  → Verifying URL does not contain '{unexpected_url}' "
                                f"(current='{page.url}')"
                            )
                            url_timeout_s = (
                                min(settings.PLAYWRIGHT_TIMEOUT_MS / 1000.0, 3.0)
                                if hasattr(page, "wait_for_timeout")
                                else 0
                            )
                            start_url = asyncio.get_event_loop().time()
                            current_url = page.url
                            contains_unexpected = True

                            while True:
                                current_url = page.url
                                contains_unexpected = (unexpected_url in current_url)
                                if not contains_unexpected:
                                    break
                                if (asyncio.get_event_loop().time() - start_url) >= url_timeout_s:
                                    break
                                await asyncio.sleep(0.05)

                            if contains_unexpected:
                                verification_result = {
                                    "type": "verify_not_url",
                                    "unexpected": unexpected_url,
                                    "actual": current_url,
                                    "matched": False,
                                }
                                raise AssertionError(
                                    "Negative URL verification failed: unexpected substring "
                                    f"'{unexpected_url}' was found in current URL '{current_url}'"
                                )
                            verification_result = {
                                "type": "verify_not_url",
                                "unexpected": unexpected_url,
                                "actual": current_url,
                                "matched": True,
                            }
                            log(
                                f"  ✓ Negative URL verified: '{unexpected_url}' is not in '{current_url}'"
                            )

                        elif action == "verify_not_text":
                            text_to_avoid = val_str.strip() if val_str else expected.strip()
                            if not text_to_avoid:
                                raise ValueError(
                                    "Action 'verify_not_text' requires text to verify in 'value' (preferred) or 'expected_result' (legacy fallback)."
                                )
                            log(f"  → Verifying visible text does NOT contain '{text_to_avoid}'" + (f" in '{target}'" if target else ""))

                            if target:
                                container = await resolve_locator(
                                    page,
                                    target,
                                    action="verify_not_text",
                                    timeout_ms=min(settings.PLAYWRIGHT_TIMEOUT_MS, 15000),
                                    saved_inventory=saved_inventory,
                                )
                                if hasattr(container, "get_by_text"):
                                    locator = container.get_by_text(text_to_avoid, exact=False).first
                                elif hasattr(container, "locator"):
                                    locator = container.locator(f"text={text_to_avoid}").first
                                else:
                                    locator = page.get_by_text(text_to_avoid, exact=False).first
                            else:
                                locator = (
                                    page.get_by_text(text_to_avoid, exact=False).first
                                    if hasattr(page, "get_by_text")
                                    else page.locator(f"text={text_to_avoid}").first
                                )

                            check_timeout_ms = min(settings.PLAYWRIGHT_TIMEOUT_MS, 3000)
                            start_check = asyncio.get_event_loop().time()
                            timeout_s = check_timeout_ms / 1000.0

                            is_currently_visible = False
                            while True:
                                try:
                                    if hasattr(locator, "is_visible"):
                                        is_currently_visible = await locator.is_visible()
                                    else:
                                        is_currently_visible = False
                                except Exception:
                                    is_currently_visible = False

                                if not is_currently_visible:
                                    break
                                if (asyncio.get_event_loop().time() - start_check) >= timeout_s:
                                    break
                                await asyncio.sleep(0.05)

                            if is_currently_visible:
                                page_text = (
                                    await page.locator("body").inner_text()
                                    if hasattr(page, "locator")
                                    else ""
                                )
                                page_text = _redact_sensitive_text(
                                    page_text, sensitive_values
                                )
                                page_text_preview = " ".join(page_text.split())[:500]
                                verification_result = {
                                    "type": "verify_not_text",
                                    "unexpected": text_to_avoid,
                                    "matched": False,
                                    "preview": page_text_preview,
                                }
                                raise AssertionError(
                                    f"Negative text verification failed: text '{text_to_avoid}' "
                                    f"was unexpectedly found visible on the page."
                                )

                            verification_result = {
                                "type": "verify_not_text",
                                "unexpected": text_to_avoid,
                                "matched": True,
                            }
                            log(f"  ✓ Negative text verified: '{text_to_avoid}' is not visible on page.")

                        elif action == "select_option":
                            if not target:
                                raise ValueError(
                                    "Target selector is required for 'select_option' action."
                                )
                            if not val_str:
                                raise ValueError(
                                    "Option value is required for 'select_option' action."
                                )
                            val_to_select, resolved_secret = _resolve_secret_reference(
                                val_str, variables
                            )
                            if resolved_secret is not None:
                                sensitive_values.append(resolved_secret)
                            elif sensitive_target and val_str:
                                sensitive_values.append(val_str)

                            log(f"  → Selecting option '{safe_value}' in '{safe_target}'")
                            target_locator = await resolve_locator(
                                page,
                                target,
                                action="select_option",
                                timeout_ms=min(settings.PLAYWRIGHT_TIMEOUT_MS, 15000),
                                saved_inventory=saved_inventory,
                            )
                            select_done = False
                            last_select_err = None
                            if hasattr(target_locator, "select_option"):
                                try:
                                    await target_locator.select_option(
                                        label=val_to_select, timeout=settings.PLAYWRIGHT_TIMEOUT_MS
                                    )
                                    select_done = True
                                except Exception as e1:
                                    last_select_err = e1
                                    try:
                                        await target_locator.select_option(
                                            value=val_to_select, timeout=settings.PLAYWRIGHT_TIMEOUT_MS
                                        )
                                        select_done = True
                                    except Exception as e2:
                                        last_select_err = e2
                            elif hasattr(page, "select_option"):
                                try:
                                    await page.select_option(
                                        target, label=val_to_select, timeout=settings.PLAYWRIGHT_TIMEOUT_MS
                                    )
                                    select_done = True
                                except Exception as e1:
                                    last_select_err = e1
                                    try:
                                        await page.select_option(
                                            target, value=val_to_select, timeout=settings.PLAYWRIGHT_TIMEOUT_MS
                                        )
                                        select_done = True
                                    except Exception as e2:
                                        last_select_err = e2
                            else:
                                loc = page.locator(target) if hasattr(page, "locator") else target_locator
                                if hasattr(loc, "select_option"):
                                    try:
                                        await loc.select_option(
                                            label=val_to_select, timeout=settings.PLAYWRIGHT_TIMEOUT_MS
                                        )
                                        select_done = True
                                    except Exception as e1:
                                        last_select_err = e1
                                        try:
                                            await loc.select_option(
                                                value=val_to_select, timeout=settings.PLAYWRIGHT_TIMEOUT_MS
                                            )
                                            select_done = True
                                        except Exception as e2:
                                            last_select_err = e2

                            if not select_done and last_select_err:
                                raise last_select_err

                            log(f"  ✓ Selected option '{safe_value}' in '{target}'")

                        elif action == "wait_until":
                            from app.services.csv_validator import (
                                SUPPORTED_WAIT_CONDITIONS,
                                normalize_wait_condition,
                            )

                            norm_cond = normalize_wait_condition(target)
                            cond_arg = ""
                            if norm_cond:
                                cond_arg = val_str.strip() if val_str else expected.strip()
                            else:
                                rev_cond = normalize_wait_condition(val_str)
                                if rev_cond:
                                    norm_cond = rev_cond
                                    cond_arg = target.strip() if target else expected.strip()
                                else:
                                    bad_cond = target or val_str or "(empty)"
                                    raise ValueError(
                                        f"Unsupported wait condition '{bad_cond}'. Supported wait conditions: {sorted(list(SUPPORTED_WAIT_CONDITIONS))}."
                                    )

                            if not cond_arg:
                                raise ValueError(
                                    f"Action 'wait_until' with condition '{norm_cond}' requires a non-empty target or value."
                                )

                            log(f"  → Waiting until condition '{norm_cond}' for '{cond_arg}'")

                            timeout_ms = getattr(settings, "PLAYWRIGHT_NAVIGATION_TIMEOUT_MS", 30000)
                            timeout_s = timeout_ms / 1000.0
                            start_wait = asyncio.get_event_loop().time()
                            condition_met = False
                            condition_detail = ""

                            while True:
                                elapsed = asyncio.get_event_loop().time() - start_wait
                                if elapsed >= timeout_s:
                                    break

                                if norm_cond == "url_contains":
                                    curr_url = page.url if hasattr(page, "url") else ""
                                    if (
                                        cond_arg in curr_url
                                        or cond_arg in urllib.parse.unquote(curr_url)
                                        or (app_url and cond_arg.startswith("/") and f"{app_url.rstrip('/')}{cond_arg}" in curr_url)
                                    ):
                                        condition_met = True
                                        condition_detail = f"Current URL '{curr_url}' contains '{cond_arg}'"
                                        break

                                elif norm_cond == "page_heading":
                                    # 1. Accessible role heading
                                    try:
                                        if hasattr(page, "get_by_role"):
                                            h_loc = page.get_by_role("heading", name=cond_arg)
                                            cnt = await h_loc.count() if hasattr(h_loc, "count") else 0
                                            if cnt > 0:
                                                first_h = _get_first_locator(h_loc)
                                                if hasattr(first_h, "is_visible") and await first_h.is_visible():
                                                    condition_met = True
                                                    condition_detail = f"Heading matching '{cond_arg}' found via get_by_role"
                                                    break
                                    except Exception:
                                        pass

                                    # 2. Heading tag selectors: h1-h6, [role="heading"]
                                    if not condition_met:
                                        try:
                                            if hasattr(page, "locator"):
                                                heading_loc = page.locator("h1, h2, h3, h4, h5, h6, [role='heading']")
                                                h_count = await heading_loc.count() if hasattr(heading_loc, "count") else 0
                                                for h_i in range(h_count):
                                                    item = heading_loc.nth(h_i) if hasattr(heading_loc, "nth") else heading_loc
                                                    if hasattr(item, "is_visible") and await item.is_visible():
                                                        txt = await item.inner_text() if hasattr(item, "inner_text") else ""
                                                        if cond_arg.lower() in txt.lower():
                                                            condition_met = True
                                                            condition_detail = f"Heading '{txt.strip()}' is visible"
                                                            break
                                                if condition_met:
                                                    break
                                        except Exception:
                                            pass

                                    # 3. Direct text-has selectors or mock locator selectors
                                    if not condition_met:
                                        try:
                                            if hasattr(page, "locator"):
                                                direct_loc = page.locator(f"h1:has-text('{cond_arg}'), h2:has-text('{cond_arg}'), h3:has-text('{cond_arg}'), [role='heading']:has-text('{cond_arg}')")
                                                if hasattr(direct_loc, "count") and await direct_loc.count() > 0:
                                                    first_d = _get_first_locator(direct_loc)
                                                    if hasattr(first_d, "is_visible") and await first_d.is_visible():
                                                        condition_met = True
                                                        condition_detail = f"Heading locator matching '{cond_arg}' is visible"
                                                        break
                                        except Exception:
                                            pass

                                    # 4. Fallback: check visible text via get_by_text
                                    if not condition_met:
                                        try:
                                            txt_loc = (
                                                page.get_by_text(cond_arg, exact=False).first
                                                if hasattr(page, "get_by_text")
                                                else (page.locator(f"text={cond_arg}").first if hasattr(page, "locator") else None)
                                            )
                                            if txt_loc and hasattr(txt_loc, "is_visible") and await txt_loc.is_visible():
                                                condition_met = True
                                                condition_detail = f"Visible text matching heading '{cond_arg}' found on page"
                                                break
                                        except Exception:
                                            pass

                                elif norm_cond == "element_visible":
                                    try:
                                        rem_time = max(int((timeout_s - elapsed) * 1000), 200)
                                        loc = await resolve_locator(
                                            page,
                                            cond_arg,
                                            action="verify_text",
                                            timeout_ms=min(rem_time, 2000),
                                            saved_inventory=saved_inventory,
                                        )
                                        if loc is not None:
                                            first_loc = _get_first_locator(loc)
                                            if hasattr(first_loc, "is_visible") and await first_loc.is_visible():
                                                condition_met = True
                                                condition_detail = f"Element matching '{cond_arg}' is visible"
                                                break
                                    except Exception:
                                        pass

                                elif norm_cond == "element_enabled":
                                    try:
                                        rem_time = max(int((timeout_s - elapsed) * 1000), 200)
                                        loc = await resolve_locator(
                                            page,
                                            cond_arg,
                                            action="click",
                                            timeout_ms=min(rem_time, 2000),
                                            saved_inventory=saved_inventory,
                                        )
                                        if loc is not None:
                                            first_loc = _get_first_locator(loc)
                                            is_vis = await first_loc.is_visible() if hasattr(first_loc, "is_visible") else False
                                            if is_vis:
                                                is_en = await first_loc.is_enabled() if hasattr(first_loc, "is_enabled") else True
                                                aria_dis = await first_loc.get_attribute("aria-disabled") if hasattr(first_loc, "get_attribute") else None
                                                dis_attr = await first_loc.get_attribute("disabled") if hasattr(first_loc, "get_attribute") else None
                                                cls_attr = await first_loc.get_attribute("class") if hasattr(first_loc, "get_attribute") else ""
                                                if aria_dis == "true" or dis_attr is not None or "disabled" in (cls_attr or "").lower():
                                                    is_en = False
                                                if is_en:
                                                    condition_met = True
                                                    condition_detail = f"Element matching '{cond_arg}' is visible and enabled"
                                                    break
                                    except Exception:
                                        pass

                                elif norm_cond == "element_hidden":
                                    try:
                                        rem_time = max(int((timeout_s - elapsed) * 1000), 200)
                                        loc = None
                                        try:
                                            loc = await resolve_locator(
                                                page,
                                                cond_arg,
                                                action="verify_text",
                                                timeout_ms=min(rem_time, 1000),
                                                saved_inventory=saved_inventory,
                                            )
                                        except (ElementNotFoundError, Exception):
                                            loc = None

                                        if loc is None:
                                            condition_met = True
                                            condition_detail = f"Element matching '{cond_arg}' is detached/absent from DOM"
                                            break
                                        else:
                                            first_loc = _get_first_locator(loc)
                                            cnt = await loc.count() if hasattr(loc, "count") else 1
                                            if cnt == 0:
                                                condition_met = True
                                                condition_detail = f"Element matching '{cond_arg}' has count 0"
                                                break
                                            is_vis = await first_loc.is_visible() if hasattr(first_loc, "is_visible") else True
                                            if not is_vis:
                                                condition_met = True
                                                condition_detail = f"Element matching '{cond_arg}' is not visible"
                                                break
                                    except Exception:
                                        pass

                                await asyncio.sleep(0.1)

                            if not condition_met:
                                curr_url = page.url if hasattr(page, "url") else "unknown"
                                page_title = await page.title() if hasattr(page, "title") else ""
                                if norm_cond == "url_contains":
                                    err_msg = (
                                        f"Wait condition 'url_contains' timed out after {timeout_s:.1f}s: "
                                        f"Expected URL to contain '{cond_arg}', but current URL is '{curr_url}' (page title: '{page_title}')."
                                    )
                                elif norm_cond == "page_heading":
                                    err_msg = (
                                        f"Wait condition 'page_heading' timed out after {timeout_s:.1f}s: "
                                        f"Expected heading '{cond_arg}' was not visible on the page (current URL: '{curr_url}', title: '{page_title}')."
                                    )
                                elif norm_cond == "element_visible":
                                    err_msg = (
                                        f"Wait condition 'element_visible' timed out after {timeout_s:.1f}s: "
                                        f"Element matching '{cond_arg}' did not become visible (current URL: '{curr_url}', title: '{page_title}')."
                                    )
                                elif norm_cond == "element_enabled":
                                    err_msg = (
                                        f"Wait condition 'element_enabled' timed out after {timeout_s:.1f}s: "
                                        f"Element matching '{cond_arg}' did not become enabled and interactive (current URL: '{curr_url}', title: '{page_title}')."
                                    )
                                elif norm_cond == "element_hidden":
                                    err_msg = (
                                        f"Wait condition 'element_hidden' timed out after {timeout_s:.1f}s: "
                                        f"Element matching '{cond_arg}' remained visible and did not hide or detach (current URL: '{curr_url}', title: '{page_title}')."
                                    )
                                else:
                                    err_msg = f"Wait condition '{norm_cond}' timed out after {timeout_s:.1f}s for '{cond_arg}' (current URL: '{curr_url}', title: '{page_title}')."
                                raise TimeoutError(err_msg)

                            verification_result = {
                                "type": "wait_until",
                                "condition": norm_cond,
                                "target": cond_arg,
                                "matched": True,
                                "detail": condition_detail,
                            }
                            log(f"  ✓ Wait condition satisfied: {condition_detail}")

                        else:
                            raise ValueError(
                                f"Unsupported action '{action}'. Supported actions: "
                                "['navigate', 'fill', 'click', 'verify_url', 'verify_text', 'discover_page', 'clear', 'check', 'uncheck', 'verify_not_text', 'verify_not_url', 'select_option', 'wait_until']."
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
                        elif hasattr(page, "is_closed") and page.is_closed():
                            log("  ⚠ Failure screenshot skipped: browser page is already closed.")
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
                try:
                    if context:
                        await context.close()
                except Exception as ctx_close_exc:
                    log(f"  ⚠ Notice closing browser context: {ctx_close_exc}")
                try:
                    if browser and (not hasattr(browser, "is_connected") or browser.is_connected()):
                        await browser.close()
                except Exception as br_close_exc:
                    log(f"  ⚠ Notice closing browser: {br_close_exc}")
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
    project_id: Optional[str] = None,
    variables: Optional[Dict[str, Any]] = None,
    headless: Optional[bool] = None,
    saved_inventory: Optional[Any] = None,
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
                steps,
                app_url,
                artifacts_dir,
                run_id,
                test_case_id,
                project_id=project_id,
                variables=variables,
                headless=headless,
                saved_inventory=saved_inventory,
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
    project_id: Optional[str] = None,
    variables: Optional[Dict[str, Any]] = None,
    headless: Optional[bool] = None,
    saved_inventory: Optional[Any] = None,
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
        project_id,
        variables,
        headless,
        saved_inventory,
    )
