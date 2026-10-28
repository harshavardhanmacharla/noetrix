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


class ElementNotVisibleError(ValueError):
    """Raised when an element matching target is present in the DOM but not visible (hidden)."""
    pass


class InvalidLocatorSyntaxError(ValueError):
    """Raised when a CSS or XPath selector has invalid syntax."""
    pass


class AccessDeniedError(AssertionError):
    """Raised when the target website or page returns an Access Denied / 403 Forbidden response."""
    pass


STANDARD_HTML_TAGS = {
    "h1", "h2", "h3", "h4", "h5", "h6",
    "header", "nav", "main", "footer", "section", "article", "aside",
    "form", "table", "thead", "tbody", "tfoot", "tr", "th", "td",
    "ul", "ol", "li", "body",
}


def is_direct_selector(target: str) -> bool:
    """
    Determine whether a target string is an explicit CSS/XPath selector
    rather than a natural-language semantic target descriptor.

    Direct selectors include:
        - Explicit Playwright selector engines: xpath=, css=, id=, text=, role=, label=, placeholder=
        - XPath expressions: starting with //, ./, ../, (/
        - CSS ID selectors: starting with #
        - CSS Class selectors: starting with .
        - Attribute selectors: containing [ and ] (e.g. [name='x'], button[type='submit'])
        - CSS combinators: containing ' > ', ' + ', ' ~ '
        - CSS pseudo-classes: :first-child, :last-child, :nth-, :not(, :has(, :disabled, :checked
        - Tag-qualified selectors: e.g. input#email, button.btn, form > input
        - Standalone HTML tags: e.g. h1, header, main, nav, section, table, form

    Semantic descriptors include:
        - Plain names/phrases: "Sign In", "Submit", "Username", "Email Address", "Save Changes"
    """
    t = (target or "").strip()
    if not t:
        return False

    # 1. Explicit Playwright selector engine prefixes
    if re.match(r"^(?:xpath=|css=|id=|text=|role=|label=|placeholder=)", t, flags=re.IGNORECASE):
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

    # 8. Standard HTML standalone tag names
    if t.lower() in STANDARD_HTML_TAGS:
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


COMMON_SYNONYMS: dict[str, list[str]] = {
    "username": ["username", "user name", "user id", "userid", "login", "user", "email", "email address"],
    "user": ["user", "username", "user id", "user name", "login"],
    "password": ["password", "passcode", "secret", "pin", "pwd"],
    "search": ["search", "find", "query", "search for people and actions", "search for people", "search for"],
    "submit": ["submit", "sign in", "login", "log in", "continue", "next"],
}

INTENT_SUFFIX_PATTERNS: list[tuple[str, str]] = [
    (r"\s+(?:input\s+field|input|field|box|textbox|area|textarea)$", "field"),
    (r"\s+(?:button|btn|action)$", "button"),
    (r"\s+(?:hyperlink|link)$", "link"),
    (r"\s+(?:dropdown\s+menu|dropdown|combobox|select)$", "dropdown"),
    (r"\s+(?:menu\s+item|menuitem|menu|nav\s+item)$", "menu"),
    (r"\s+(?:check\s+box|checkbox)$", "checkbox"),
    (r"\s+(?:tab)$", "tab"),
    (r"\s+(?:logo|icon|image|img|pic|picture)$", "logo"),
]


def normalize_intent_target(target: str) -> Tuple[str, Optional[str], List[str]]:
    """
    Decompose a natural-language target into core search term, detected intent type, and candidate variants.

    Examples:
        'username field'        -> ('username', 'field', ['username', 'user name', 'user id', 'userid', 'login', 'user', 'email', 'email address'])
        'Next button'           -> ('Next', 'button', ['Next'])
        'eAppSys logo'          -> ('eAppSys', 'logo', ['eAppSys'])
        'My Client Groups menu' -> ('My Client Groups', 'menu', ['My Client Groups'])
        'Hire an Employee'      -> ('Hire an Employee', None, ['Hire an Employee'])
    """
    clean = _clean_target_string(target)
    for pattern, intent_type in INTENT_SUFFIX_PATTERNS:
        match = re.search(pattern, clean, flags=re.IGNORECASE)
        if match:
            core = clean[:match.start()].strip()
            if core:
                variants = [core]
                syns = COMMON_SYNONYMS.get(core.lower())
                if syns:
                    for s in syns:
                        if s.lower() != core.lower():
                            variants.append(s)
                return core, intent_type, variants

    # No suffix detected; check synonyms for direct term
    variants = [clean]
    syns = COMMON_SYNONYMS.get(clean.lower())
    if syns:
        for s in syns:
            if s.lower() != clean.lower():
                variants.append(s)
    return clean, None, variants


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
    saved_inventory: Optional[Any] = None,
) -> Any:
    """
    Resolve a target string into a single actionable Playwright Locator.

    Args:
        page: Playwright Page instance (or duck-typed mock).
        target: Target selector or natural-language descriptor.
        action: The action being executed ("click", "fill", etc.).
        timeout_ms: Maximum milliseconds to wait for dynamic element appearance.
        saved_inventory: Optional historical saved discovery inventory (list of snapshots or dict).

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

        # Check explicit engine prefixes: label= and placeholder=
        if clean_target.lower().startswith("label="):
            lbl = _clean_target_string(clean_target[6:].strip())
            candidate = (
                page.get_by_label(lbl, exact=False)
                if hasattr(page, "get_by_label")
                else page.locator(clean_target)
            )
        elif clean_target.lower().startswith("placeholder="):
            ph = _clean_target_string(clean_target[12:].strip())
            candidate = (
                page.get_by_placeholder(ph, exact=False)
                if hasattr(page, "get_by_placeholder")
                else page.locator(clean_target)
            )
        else:
            try:
                candidate = page.locator(clean_target)
            except Exception as loc_err:
                raise InvalidLocatorSyntaxError(
                    f"Invalid locator syntax '{clean_target}': {loc_err}"
                ) from loc_err

        if not hasattr(candidate, "count"):
            return candidate

        start_time = asyncio.get_event_loop().time()
        timeout_s = max(0, timeout_ms or 0) / 1000.0

        while True:
            try:
                count = await candidate.count()
            except Exception as count_err:
                err_str = str(count_err).lower()
                if "parsing selector" in err_str or "not a valid selector" in err_str or "unexpected token" in err_str:
                    raise InvalidLocatorSyntaxError(
                        f"Invalid locator syntax '{clean_target}': {count_err}"
                    ) from count_err
                raise

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
        try:
            count = await candidate.count()
        except Exception as count_err:
            err_str = str(count_err).lower()
            if "parsing selector" in err_str or "not a valid selector" in err_str or "unexpected token" in err_str:
                raise InvalidLocatorSyntaxError(
                    f"Invalid locator syntax '{clean_target}': {count_err}"
                ) from count_err
            raise

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
    # Case 2: Semantic Target Resolution with Intent Normalization
    # Build candidate strategies based on action and decomposed intent
    # -------------------------------------------------------------------------
    candidates: List[Tuple[str, Any]] = []

    # If saved historical inventory is provided, test high-scoring candidate locators first
    if saved_inventory and not is_direct_selector(clean_target):
        try:
            from app.services.discovery_service import search_saved_snapshots
            inv_list = saved_inventory if isinstance(saved_inventory, list) else [saved_inventory]
            saved_matches = search_saved_snapshots(inv_list, clean_target, action=normalized_action, max_results=3)
            for sm in saved_matches:
                rec_loc = sm.get("recommended_locator")
                if rec_loc and hasattr(page, "locator"):
                    candidates.append((f"saved inventory candidate ('{rec_loc}')", page.locator(rec_loc)))
        except Exception:
            pass

    core_target, intent_type, search_variants = normalize_intent_target(clean_target)
    terms_to_try = [clean_target]
    if core_target.lower() != clean_target.lower():
        terms_to_try.append(core_target)
    for syn in search_variants:
        if syn.lower() not in [t.lower() for t in terms_to_try]:
            terms_to_try.append(syn)

    if normalized_action in ("check", "uncheck"):
        # Prioritize checkboxes by accessible role and label
        for term in terms_to_try:
            safe_term = re.sub(r"[^\w\-]", "", term)
            if hasattr(page, "get_by_role"):
                candidates.append(
                    (f"checkbox role (exact: '{term}')", page.get_by_role("checkbox", name=term, exact=True))
                )
                candidates.append(
                    (f"checkbox role (case-insensitive: '{term}')", page.get_by_role("checkbox", name=term, exact=False))
                )
            if hasattr(page, "get_by_label"):
                candidates.append(
                    (f"checkbox label (exact: '{term}')", page.get_by_label(term, exact=True))
                )
                candidates.append(
                    (f"checkbox label (case-insensitive: '{term}')", page.get_by_label(term, exact=False))
                )
            if safe_term and hasattr(page, "locator"):
                candidates.append(
                    (
                        f"checkbox data-testid ('{term}')",
                        page.locator(f"[data-testid*='{safe_term}' i][type='checkbox'], [data-qa*='{safe_term}' i]"),
                    )
                )
                candidates.append(
                    (
                        f"checkbox input attribute ('{term}')",
                        page.locator(
                            f"input[type='checkbox'][name='{safe_term}' i], input[type='checkbox'][id='{safe_term}' i]"
                        ),
                    )
                )
            if hasattr(page, "get_by_text"):
                candidates.append(
                    (f"checkbox visible text (exact: '{term}')", page.get_by_text(term, exact=True))
                )
                candidates.append(
                    (f"checkbox visible text (case-insensitive: '{term}')", page.get_by_text(term, exact=False))
                )

    elif normalized_action == "click":
        # Check logo / icon intent first
        if intent_type == "logo" or "logo" in clean_target.lower() or "icon" in clean_target.lower():
            safe_core = " ".join(re.sub(r"[^\w\-\s]", "", core_target).split())
            if hasattr(page, "locator") and safe_core:
                candidates.append(
                    (f"logo/icon alt attribute ('{core_target}')", page.locator(f"img[alt*='{safe_core}' i]"))
                )
                candidates.append(
                    (f"logo/icon aria-label ('{core_target}')", page.locator(f"[aria-label*='{safe_core}' i]"))
                )
                candidates.append(
                    (f"logo/icon svg label ('{core_target}')", page.locator(f"svg[aria-label*='{safe_core}' i]"))
                )
                candidates.append(
                    (f"logo/icon clickable container ('{core_target}')", page.locator(f"a:has(img[alt*='{safe_core}' i]), button:has(img[alt*='{safe_core}' i])"))
                )
                candidates.append(
                    (f"logo/icon title attribute ('{core_target}')", page.locator(f"a[title*='{safe_core}' i], button[title*='{safe_core}' i], img[title*='{safe_core}' i]"))
                )
                candidates.append(
                    (f"logo/icon img src ('{core_target}')", page.locator(f"img[src*='{safe_core}' i]"))
                )
                safe_core_nospace = re.sub(r"[^\w\-]", "", core_target)
                if safe_core_nospace and safe_core_nospace.lower() != safe_core.lower():
                    candidates.append(
                        (f"logo/icon alt attribute nospace ('{core_target}')", page.locator(f"img[alt*='{safe_core_nospace}' i]"))
                    )
                    candidates.append(
                        (f"logo/icon img src nospace ('{core_target}')", page.locator(f"img[src*='{safe_core_nospace}' i]"))
                    )

        # Check menu intent
        if intent_type == "menu" or "menu" in clean_target.lower():
            if hasattr(page, "get_by_role"):
                candidates.append(
                    (f"menuitem role (exact: '{core_target}')", page.get_by_role("menuitem", name=core_target, exact=True))
                )
                candidates.append(
                    (f"menuitem role (case-insensitive: '{core_target}')", page.get_by_role("menuitem", name=core_target, exact=False))
                )
                candidates.append(
                    (f"menu role (case-insensitive: '{core_target}')", page.get_by_role("menu", name=core_target, exact=False))
                )
            if hasattr(page, "locator"):
                candidates.append(
                    (f"menu container text ('{core_target}')", page.locator(f"[role='menuitem']:has-text('{core_target}'), .menu-item:has-text('{core_target}')"))
                )

        # Button, link, and interactive roles
        for term in terms_to_try:
            safe_term = re.sub(r"[^\w\-]", "", term)
            if hasattr(page, "get_by_role"):
                candidates.append(
                    (f"button role (exact: '{term}')", page.get_by_role("button", name=term, exact=True))
                )
                candidates.append(
                    (f"link role (exact: '{term}')", page.get_by_role("link", name=term, exact=True))
                )
                candidates.append(
                    (f"tab role (exact: '{term}')", page.get_by_role("tab", name=term, exact=True))
                )
                candidates.append(
                    (f"menuitem role (exact: '{term}')", page.get_by_role("menuitem", name=term, exact=True))
                )
                candidates.append(
                    (f"checkbox role (exact: '{term}')", page.get_by_role("checkbox", name=term, exact=True))
                )
                candidates.append(
                    (f"button role (case-insensitive: '{term}')", page.get_by_role("button", name=term, exact=False))
                )
                candidates.append(
                    (f"link role (case-insensitive: '{term}')", page.get_by_role("link", name=term, exact=False))
                )

            if hasattr(page, "get_by_label"):
                candidates.append(
                    (f"accessible label (exact: '{term}')", page.get_by_label(term, exact=True))
                )
                candidates.append(
                    (f"accessible label (case-insensitive: '{term}')", page.get_by_label(term, exact=False))
                )

            if safe_term and hasattr(page, "locator"):
                candidates.append(
                    (f"clickable data-testid ('{term}')", page.locator(f"[data-testid*='{safe_term}' i], [data-qa*='{safe_term}' i]"))
                )
                candidates.append(
                    (f"button/link id attribute ('{term}')", page.locator(f"button[id*='{safe_term}' i], a[id*='{safe_term}' i], button[name*='{safe_term}' i]"))
                )

            # Fallback to visible text
            if hasattr(page, "get_by_text"):
                candidates.append(
                    (f"visible text (exact: '{term}')", page.get_by_text(term, exact=True))
                )
                candidates.append(
                    (f"visible text (case-insensitive: '{term}')", page.get_by_text(term, exact=False))
                )

    elif normalized_action in ("fill", "clear"):
        # Prioritize form labels, placeholders, and textbox roles
        for term in terms_to_try:
            safe_term = re.sub(r"[^\w\-]", "", term)
            if hasattr(page, "get_by_label"):
                candidates.append(
                    (f"form label (exact: '{term}')", page.get_by_label(term, exact=True))
                )
                candidates.append(
                    (f"form label (case-insensitive: '{term}')", page.get_by_label(term, exact=False))
                )

            if hasattr(page, "get_by_placeholder"):
                candidates.append(
                    (f"placeholder (exact: '{term}')", page.get_by_placeholder(term, exact=True))
                )
                candidates.append(
                    (f"placeholder (case-insensitive: '{term}')", page.get_by_placeholder(term, exact=False))
                )

            if hasattr(page, "get_by_role"):
                candidates.append(
                    (f"textbox role (exact: '{term}')", page.get_by_role("textbox", name=term, exact=True))
                )
                candidates.append(
                    (f"combobox role (exact: '{term}')", page.get_by_role("combobox", name=term, exact=True))
                )
                candidates.append(
                    (f"textbox role (case-insensitive: '{term}')", page.get_by_role("textbox", name=term, exact=False))
                )
                candidates.append(
                    (f"combobox role (case-insensitive: '{term}')", page.get_by_role("combobox", name=term, exact=False))
                )
                candidates.append(
                    (f"searchbox role (exact: '{term}')", page.get_by_role("searchbox", name=term, exact=True))
                )
                candidates.append(
                    (f"searchbox role (case-insensitive: '{term}')", page.get_by_role("searchbox", name=term, exact=False))
                )

            # Stable testid and input name/id/aria-label attributes
            if hasattr(page, "locator"):
                safe_core_attr = " ".join(re.sub(r"[^\w\-\s]", "", term).split())
                if safe_term:
                    candidates.append(
                        (
                            f"input data-testid ('{term}')",
                            page.locator(f"[data-testid*='{safe_term}' i], [data-qa*='{safe_term}' i]"),
                        )
                    )
                    candidates.append(
                        (
                            f"input name or id attribute ('{term}')",
                            page.locator(
                                f"input[name='{safe_term}' i], textarea[name='{safe_term}' i], "
                                f"input[id='{safe_term}' i], textarea[id='{safe_term}' i]"
                            ),
                        )
                    )
                if safe_core_attr:
                    candidates.append(
                        (
                            f"input aria-label attribute ('{term}')",
                            page.locator(f"input[aria-label*='{safe_core_attr}' i], textarea[aria-label*='{safe_core_attr}' i]"),
                        )
                    )

        # Special fallback for password fields
        if "password" in clean_target.lower() or "password" in core_target.lower():
            if hasattr(page, "locator"):
                candidates.append(
                    ("password input element", page.locator("input[type='password']"))
                )

    elif normalized_action == "select_option":
        # Prioritize combobox / select elements by accessible role and label
        for term in terms_to_try:
            safe_term = re.sub(r"[^\w\-]", "", term)
            if hasattr(page, "get_by_role"):
                candidates.append(
                    (f"combobox role (exact: '{term}')", page.get_by_role("combobox", name=term, exact=True))
                )
                candidates.append(
                    (f"combobox role (case-insensitive: '{term}')", page.get_by_role("combobox", name=term, exact=False))
                )

            if hasattr(page, "get_by_label"):
                candidates.append(
                    (f"dropdown label (exact: '{term}')", page.get_by_label(term, exact=True))
                )
                candidates.append(
                    (f"dropdown label (case-insensitive: '{term}')", page.get_by_label(term, exact=False))
                )

            if safe_term and hasattr(page, "locator"):
                candidates.append(
                    (
                        f"dropdown data-testid ('{term}')",
                        page.locator(f"[data-testid*='{safe_term}' i], [data-qa*='{safe_term}' i]"),
                    )
                )
                candidates.append(
                    (
                        f"select name or id attribute ('{term}')",
                        page.locator(
                            f"select[name='{safe_term}' i], select[id='{safe_term}' i]"
                        ),
                    )
                )

            if hasattr(page, "get_by_text"):
                candidates.append(
                    (f"dropdown visible text (exact: '{term}')", page.get_by_text(term, exact=True))
                )
                candidates.append(
                    (f"dropdown visible text (case-insensitive: '{term}')", page.get_by_text(term, exact=False))
                )

    elif normalized_action in ("verify_text", "verify_not_text"):
        # Scoped container resolution: heading, region/main, section, label, or visible text
        for term in terms_to_try:
            if hasattr(page, "get_by_role"):
                candidates.append(
                    (f"heading role (exact: '{term}')", page.get_by_role("heading", name=term, exact=True))
                )
                candidates.append(
                    (f"heading role (case-insensitive: '{term}')", page.get_by_role("heading", name=term, exact=False))
                )
                candidates.append(
                    (f"region/main role ('{term}')", page.get_by_role("region", name=term, exact=False))
                )
                candidates.append(
                    (f"main role ('{term}')", page.get_by_role("main", name=term, exact=False))
                )
            if hasattr(page, "get_by_label"):
                candidates.append((f"container label (exact: '{term}')", page.get_by_label(term, exact=True)))
                candidates.append((f"container label (case-insensitive: '{term}')", page.get_by_label(term, exact=False)))
            if hasattr(page, "get_by_text"):
                candidates.append((f"container text (exact: '{term}')", page.get_by_text(term, exact=True)))
                candidates.append((f"container text (case-insensitive: '{term}')", page.get_by_text(term, exact=False)))

    else:
        # Generic semantic fallback for other actions
        for term in terms_to_try:
            if hasattr(page, "get_by_label"):
                candidates.append((f"label ('{term}')", page.get_by_label(term, exact=False)))
            if hasattr(page, "get_by_text"):
                candidates.append((f"visible text ('{term}')", page.get_by_text(term, exact=False)))

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

    if normalized_action in ("verify_text", "verify_not_text"):
        raise ElementNotFoundError(
            f"Could not find any container matching '{clean_target}' for action '{action}'. "
            "Searched heading roles, region/main roles, accessible labels, and visible text."
        )

    raise ElementNotFoundError(
        f"Could not find any element matching '{clean_target}' for action '{action}'."
    )
