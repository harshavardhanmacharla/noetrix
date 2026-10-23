"""
Semantic Locator Resolver for Noetrix Playwright Runner.

Translates natural-language element targets and technical CSS/XPath selectors
into actionable Playwright Locators using accessibility-first strategies,
strict ambiguity checks, and graceful visible-text fallbacks.

Design Principles:
    1. Accessibility-first: Prioritizes accessible roles, labels, and placeholders over generic text.
    2. Zero guesswork on ambiguity: Fails with a clear error if multiple visible elements match.
    3. Strict separation: Distinguishes direct CSS/XPath selectors from semantic targets.
    4. Deterministic: No external AI/LLM APIs, embedding models, or vector databases.
"""
from __future__ import annotations

import asyncio
import re
from typing import Any, List, Optional, Tuple


class AmbiguousElementError(ValueError):
    """Raised when a semantic target or selector matches multiple visible elements."""
    pass


class ElementNotFoundError(ValueError):
    """Raised when no matching element can be found for a target."""
    pass


def is_direct_selector(target: str) -> bool:
    """
    Determine whether a target string is an explicit CSS/XPath selector
    rather than a natural-language semantic target descriptor.

    Direct selectors include:
        - Explicit Playwright selector engines: xpath=, css=, id=, text=, role=
        - XPath expressions: starting with //, ./, ../, (/
        - CSS ID selectors: starting with #
        - CSS Class selectors: starting with .
        - Attribute selectors: containing [ and ] (e.g. [name='x'], button[type='submit'])
        - CSS combinators: containing ' > ', ' + ', ' ~ '
        - CSS pseudo-classes: :first-child, :last-child, :nth-, :not(, :has(, :disabled, :checked
        - Tag-qualified selectors: e.g. input#email, button.btn, form > input

    Semantic descriptors include:
        - Plain names/phrases: "Sign In", "Submit", "Username", "Email Address", "Save Changes"
    """
    t = (target or "").strip()
    if not t:
        return False

    # 1. Explicit Playwright selector engine prefixes
    if re.match(r"^(?:xpath=|css=|id=|text=|role=)", t, flags=re.IGNORECASE):
        return True

    # 2. XPath expressions
    if t.startswith(("//", "./", "../", "(/")):
        return True

    # 3. CSS ID or Class selectors
    if t.startswith(("#", ".")):
        return True

    # 4. Attribute selectors or attribute-qualified selectors
    if "[" in t and "]" in t:
        return True

    # 5. CSS combinators indicating structural selectors
    if re.search(r"\s+[>+~]\s+", t):
        return True

    # 6. CSS pseudo-classes
    if re.search(r":(?:first-child|last-child|nth-|not\(|has\(|checked|disabled|visible|focus)", t):
        return True

    # 7. HTML tag qualified by class, id, attribute, pseudo, or child
    if re.match(r"^(?:input|button|a|select|textarea|div|span|p|label|form|table|tr|td|th|ul|li|section|header|nav)[#.[:>+~]", t):
        return True

    return False


def _clean_target_string(target: str) -> str:
    """Strip extraneous wrapping quotes and extra whitespace."""
    s = (target or "").strip()
    if len(s) >= 2:
        if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
            return s[1:-1].strip()
        if (s.startswith('“') and s.endswith('”')) or (s.startswith('‘') and s.endswith('’')):
            return s[1:-1].strip()
    return s


async def _count_and_filter_visible(locator: Any) -> Tuple[int, int]:
    """
    Count matching elements and determine how many are currently visible.

    Returns:
        (visible_count, first_visible_index)
        If no elements are visible, returns (0, -1).
    """
    if not hasattr(locator, "count"):
        return 1, 0

    count = await locator.count()
    if count == 0:
        return 0, -1

    visible_indices: List[int] = []
    for i in range(count):
        try:
            item = locator.nth(i) if hasattr(locator, "nth") else locator
            is_vis = await item.is_visible() if hasattr(item, "is_visible") else True
            if is_vis:
                visible_indices.append(i)
        except Exception:
            continue

    if not visible_indices:
        return 0, -1

    return len(visible_indices), visible_indices[0]


async def resolve_locator(
    page: Any,
    target: str,
    action: str,
    timeout_ms: Optional[int] = None,
) -> Any:
    """
    Resolve a target string into a single actionable Playwright Locator.

    Args:
        page: Playwright Page instance (or duck-typed mock).
        target: Target selector or natural-language descriptor.
        action: The action being executed ("click", "fill", etc.).
        timeout_ms: Maximum milliseconds to wait for dynamic element appearance.

    Returns:
        A Playwright Locator pointing to exactly one appropriate element.

    Raises:
        ValueError: If target is empty.
        AmbiguousElementError: If multiple visible elements match the target.
        ElementNotFoundError: If no matching element is found.
    """
    raw_target = (target or "").strip()
    if not raw_target:
        raise ValueError(f"Target is required for '{action}' action.")

    clean_target = _clean_target_string(raw_target)
    normalized_action = (action or "").strip().lower()

    if timeout_ms is None:
        timeout_ms = 4000 if hasattr(page, "wait_for_timeout") else 0

    # -------------------------------------------------------------------------
    # Case 1: Direct CSS or XPath Selector
    # -------------------------------------------------------------------------
    if is_direct_selector(clean_target):
        if not hasattr(page, "locator"):
            # If the page object does not implement locator(), return candidate as is
            return clean_target

        candidate = page.locator(clean_target)
        if not hasattr(candidate, "count"):
            return candidate

        start_time = asyncio.get_event_loop().time()
        timeout_s = max(0, timeout_ms or 0) / 1000.0

        while True:
            count = await candidate.count()
            if count == 1:
                try:
                    is_vis = (
                        await candidate.is_visible()
                        if hasattr(candidate, "is_visible")
                        else True
                    )
                except Exception:
                    is_vis = True

                if is_vis:
                    return candidate
            elif count > 1:
                vis_count, first_vis_idx = await _count_and_filter_visible(candidate)
                if vis_count > 1:
                    raise AmbiguousElementError(
                        f"Ambiguous target '{clean_target}' for action '{action}': "
                        f"direct selector matched {vis_count} visible elements. "
                        "Please use a more specific selector or ID."
                    )
                if vis_count == 1:
                    return candidate.nth(first_vis_idx)

            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed >= timeout_s:
                break
            await asyncio.sleep(0.05)

        # Final check after timeout loop
        count = await candidate.count()
        if count == 0:
            raise ElementNotFoundError(
                f"Element not found: direct selector '{clean_target}' matched 0 elements."
            )
        if count == 1:
            return candidate

        # Check visibility for multiple matches
        vis_count, first_vis_idx = await _count_and_filter_visible(candidate)
        if vis_count > 1:
            raise AmbiguousElementError(
                f"Ambiguous target '{clean_target}' for action '{action}': "
                f"direct selector matched {vis_count} visible elements. "
                "Please use a more specific selector or ID."
            )
        if vis_count == 1:
            return candidate.nth(first_vis_idx)

        # All matched elements are currently hidden; return candidate.first
        # so Playwright actionability can wait for attachment/visibility within timeout
        return candidate.first

    # -------------------------------------------------------------------------
    # Case 2: Semantic Target Resolution
    # Build candidate strategies based on the action
    # -------------------------------------------------------------------------
    candidates: List[Tuple[str, Any]] = []

    if normalized_action in ("check", "uncheck"):
        # Prioritize checkboxes by accessible role and label
        if hasattr(page, "get_by_role"):
            candidates.append(
                ("checkbox role (exact)", page.get_by_role("checkbox", name=clean_target, exact=True))
            )
            candidates.append(
                ("checkbox role (case-insensitive)", page.get_by_role("checkbox", name=clean_target, exact=False))
            )

        if hasattr(page, "get_by_label"):
            candidates.append(
                ("checkbox label (exact)", page.get_by_label(clean_target, exact=True))
            )
            candidates.append(
                ("checkbox label (case-insensitive)", page.get_by_label(clean_target, exact=False))
            )

        if hasattr(page, "locator"):
            safe_id = re.sub(r"[^\w\-]", "", clean_target)
            if safe_id:
                candidates.append(
                    (
                        "checkbox input attribute",
                        page.locator(
                            f"input[type='checkbox'][name='{safe_id}' i], input[type='checkbox'][id='{safe_id}' i]"
                        ),
                    )
                )

        if hasattr(page, "get_by_text"):
            candidates.append(
                ("visible text (exact)", page.get_by_text(clean_target, exact=True))
            )
            candidates.append(
                ("visible text (case-insensitive)", page.get_by_text(clean_target, exact=False))
            )

    elif normalized_action == "click":
        # Prioritize buttons and links by accessible name
        if hasattr(page, "get_by_role"):
            candidates.append(
                ("button role (exact)", page.get_by_role("button", name=clean_target, exact=True))
            )
            candidates.append(
                ("link role (exact)", page.get_by_role("link", name=clean_target, exact=True))
            )
            candidates.append(
                ("tab role (exact)", page.get_by_role("tab", name=clean_target, exact=True))
            )
            candidates.append(
                ("menuitem role (exact)", page.get_by_role("menuitem", name=clean_target, exact=True))
            )
            candidates.append(
                ("checkbox role (exact)", page.get_by_role("checkbox", name=clean_target, exact=True))
            )
            candidates.append(
                ("button role (case-insensitive)", page.get_by_role("button", name=clean_target, exact=False))
            )
            candidates.append(
                ("link role (case-insensitive)", page.get_by_role("link", name=clean_target, exact=False))
            )

        if hasattr(page, "get_by_label"):
            candidates.append(
                ("accessible label (exact)", page.get_by_label(clean_target, exact=True))
            )
            candidates.append(
                ("accessible label (case-insensitive)", page.get_by_label(clean_target, exact=False))
            )

        # Fallback to visible text
        if hasattr(page, "get_by_text"):
            candidates.append(
                ("visible text (exact)", page.get_by_text(clean_target, exact=True))
            )
            candidates.append(
                ("visible text (case-insensitive)", page.get_by_text(clean_target, exact=False))
            )

    elif normalized_action in ("fill", "clear"):
        # Prioritize form labels, placeholders, and textbox roles
        if hasattr(page, "get_by_label"):
            candidates.append(
                ("form label (exact)", page.get_by_label(clean_target, exact=True))
            )
            candidates.append(
                ("form label (case-insensitive)", page.get_by_label(clean_target, exact=False))
            )

        if hasattr(page, "get_by_placeholder"):
            candidates.append(
                ("placeholder (exact)", page.get_by_placeholder(clean_target, exact=True))
            )
            candidates.append(
                ("placeholder (case-insensitive)", page.get_by_placeholder(clean_target, exact=False))
            )

        if hasattr(page, "get_by_role"):
            candidates.append(
                ("textbox role (exact)", page.get_by_role("textbox", name=clean_target, exact=True))
            )
            candidates.append(
                ("textbox role (case-insensitive)", page.get_by_role("textbox", name=clean_target, exact=False))
            )
            candidates.append(
                ("searchbox role (exact)", page.get_by_role("searchbox", name=clean_target, exact=True))
            )
            candidates.append(
                ("searchbox role (case-insensitive)", page.get_by_role("searchbox", name=clean_target, exact=False))
            )

        # Fallback: common input name/id attributes
        if hasattr(page, "locator"):
            safe_id = re.sub(r"[^\w\-]", "", clean_target)
            if safe_id:
                candidates.append(
                    (
                        "input name or id attribute",
                        page.locator(
                            f"input[name='{safe_id}' i], textarea[name='{safe_id}' i], "
                            f"input[id='{safe_id}' i], textarea[id='{safe_id}' i]"
                        ),
                    )
                )

    elif normalized_action == "select_option":
        # Prioritize combobox / select elements by accessible role and label
        if hasattr(page, "get_by_role"):
            candidates.append(
                ("combobox role (exact)", page.get_by_role("combobox", name=clean_target, exact=True))
            )
            candidates.append(
                ("combobox role (case-insensitive)", page.get_by_role("combobox", name=clean_target, exact=False))
            )

        if hasattr(page, "get_by_label"):
            candidates.append(
                ("dropdown label (exact)", page.get_by_label(clean_target, exact=True))
            )
            candidates.append(
                ("dropdown label (case-insensitive)", page.get_by_label(clean_target, exact=False))
            )

        if hasattr(page, "locator"):
            safe_id = re.sub(r"[^\w\-]", "", clean_target)
            if safe_id:
                candidates.append(
                    (
                        "select name or id attribute",
                        page.locator(
                            f"select[name='{safe_id}' i], select[id='{safe_id}' i]"
                        ),
                    )
                )

        if hasattr(page, "get_by_text"):
            candidates.append(
                ("visible text (exact)", page.get_by_text(clean_target, exact=True))
            )
            candidates.append(
                ("visible text (case-insensitive)", page.get_by_text(clean_target, exact=False))
            )

    else:
        # Generic semantic fallback for other actions
        if hasattr(page, "get_by_label"):
            candidates.append(("label", page.get_by_label(clean_target, exact=False)))
        if hasattr(page, "get_by_text"):
            candidates.append(("visible text", page.get_by_text(clean_target, exact=False)))

    # -------------------------------------------------------------------------
    # Evaluate candidates in priority order with ambiguity checks and dynamic retry
    # -------------------------------------------------------------------------
    start_time = asyncio.get_event_loop().time()
    timeout_s = max(0, timeout_ms or 0) / 1000.0

    while True:
        fallback_single: Optional[Tuple[str, Any]] = None

        for strategy_name, candidate_locator in candidates:
            if not hasattr(candidate_locator, "count"):
                return candidate_locator

            try:
                count = await candidate_locator.count()
            except Exception:
                continue

            if count == 0:
                continue

            if count == 1:
                try:
                    is_vis = (
                        await candidate_locator.is_visible()
                        if hasattr(candidate_locator, "is_visible")
                        else True
                    )
                except Exception:
                    is_vis = True

                if is_vis:
                    return candidate_locator

                if fallback_single is None:
                    fallback_single = (strategy_name, candidate_locator)
                continue

            # count > 1: check for visible elements to detect ambiguity
            vis_count, first_vis_idx = await _count_and_filter_visible(candidate_locator)
            if vis_count == 1:
                return candidate_locator.nth(first_vis_idx)

            if vis_count > 1:
                raise AmbiguousElementError(
                    f"Ambiguous target '{clean_target}' for action '{action}': "
                    f"matches {vis_count} visible elements using {strategy_name}. "
                    "Please specify a unique element label, text, or selector."
                )

        elapsed = asyncio.get_event_loop().time() - start_time
        if elapsed >= timeout_s:
            if fallback_single is not None:
                return fallback_single[1]
            break

        await asyncio.sleep(0.05)

    # No elements matched any strategy
    if normalized_action in ("check", "uncheck"):
        raise ElementNotFoundError(
            f"Could not find any checkbox matching '{clean_target}'. "
            "Searched checkbox roles, accessible labels, and input attributes."
        )
    if normalized_action == "click":
        raise ElementNotFoundError(
            f"Could not find any clickable element matching '{clean_target}'. "
            "Searched button roles, link roles, accessible labels, and visible text."
        )
    if normalized_action in ("fill", "clear"):
        raise ElementNotFoundError(
            f"Could not find any input field matching '{clean_target}'. "
            "Searched form labels, placeholders, textbox roles, and input attributes."
        )
    if normalized_action == "select_option":
        raise ElementNotFoundError(
            f"Could not find any dropdown matching '{clean_target}'. "
            "Searched combobox roles, accessible labels, and select element attributes."
        )

    raise ElementNotFoundError(
        f"Could not find any element matching '{clean_target}' for action '{action}'."
    )
