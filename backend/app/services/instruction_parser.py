"""
Natural Language Instruction Parser for Noetrix.

Translates plain-English test instructions and verb synonyms into normalized,
structured test step actions suitable for Playwright execution.

Supported Canonical Actions:
    - navigate: Open, visit, or navigate to a destination URL/path.
    - fill: Enter, type, or fill a field with a specified value.
    - click: Click, tap, or press a button/element.
    - verify_url: Assert that the current page URL matches or contains an expected string.
    - verify_text: Assert that expected text is visible on the page (or within a container).
    - discover_page: Discover interactive elements and headings on the page.
    - clear: Clear or empty an input field.
    - check: Explicitly check a checkbox.
    - uncheck: Explicitly uncheck/deselect a checkbox.
    - verify_not_text: Assert that specified text is NOT visible on the page (or within a container).
    - verify_not_url: Assert that the current page URL does NOT contain an unexpected string.
    - select_option: Select an option from a dropdown or combobox element.

Designed to be pure, deterministic, and independent of external AI APIs or database models.
"""
from __future__ import annotations

import re
from typing import Optional
from pydantic import BaseModel, Field


# Canonical actions matching Playwright runner and database enum
CANONICAL_ACTIONS = {
    "navigate",
    "fill",
    "click",
    "verify_url",
    "verify_text",
    "discover_page",
    "clear",
    "check",
    "uncheck",
    "verify_not_text",
    "verify_not_url",
    "select_option",
    "wait_until",
}

# Synonym mapping for standalone verbs
ACTION_VERB_SYNONYMS = {
    # Synchronization / Wait
    "wait_until": "wait_until",
    "wait until": "wait_until",
    "wait for": "wait_until",
    "wait": "wait_until",
    "await": "wait_until",
    "synchronize": "wait_until",
    # Navigation
    "navigate": "navigate",
    "navigate to": "navigate",
    "open": "navigate",
    "visit": "navigate",
    "go to": "navigate",
    "goto": "navigate",
    "load": "navigate",
    "browse": "navigate",
    "browse to": "navigate",
    "launch": "navigate",
    "access": "navigate",
    # Text entry
    "fill": "fill",
    "fill in": "fill",
    "type": "fill",
    "enter": "fill",
    "input": "fill",
    "write": "fill",
    "put": "fill",
    "populate": "fill",
    "set": "fill",
    "insert": "fill",
    # Clicking
    "click": "click",
    "click on": "click",
    "tap": "click",
    "tap on": "click",
    "press": "click",
    "press on": "click",
    "press the button": "click",
    "press button": "click",
    "submit": "click",
    "select": "click",
    "hit": "click",
    "choose": "click",
    # Dropdown selection
    "select_option": "select_option",
    "select option": "select_option",
    "choose option": "select_option",
    # Field clearing
    "clear": "clear",
    "clear field": "clear",
    "empty": "clear",
    "empty field": "clear",
    "erase": "clear",
    # Checkbox check & uncheck
    "check": "check",
    "check box": "check",
    "mark": "check",
    "mark as checked": "check",
    "uncheck": "uncheck",
    "uncheck box": "uncheck",
    "unmark": "uncheck",
    "deselect": "uncheck",
    # Text verification
    "verify_text": "verify_text",
    "verify text": "verify_text",
    "check text": "verify_text",
    "assert text": "verify_text",
    "ensure text": "verify_text",
    "confirm text": "verify_text",
    # Negative text verification
    "verify_not_text": "verify_not_text",
    "verify not text": "verify_not_text",
    "check not text": "verify_not_text",
    "assert not text": "verify_not_text",
    # URL verification
    "verify_url": "verify_url",
    "verify url": "verify_url",
    "check url": "verify_url",
    "assert url": "verify_url",
    "ensure url": "verify_url",
    "confirm url": "verify_url",
    # Negative URL verification
    "verify_not_url": "verify_not_url",
    "verify not url": "verify_not_url",
    "check not url": "verify_not_url",
    "assert not url": "verify_not_url",
    # Discovery
    "discover_page": "discover_page",
    "discover page": "discover_page",
    "scan page": "discover_page",
    "inspect page": "discover_page",
    "analyze page": "discover_page",
    "catalog page": "discover_page",
}


class ParsedInstruction(BaseModel):
    """Structured representation of an interpreted test action."""

    action: str = Field(
        ...,
        description="Normalized canonical action: navigate, fill, click, verify_url, verify_text, discover_page, clear, check, uncheck, verify_not_text, verify_not_url",
    )
    target: Optional[str] = Field(
        default=None,
        description="Target selector, element name, or container identifier",
    )
    value: Optional[str] = Field(
        default=None,
        description="Text to type, URL to visit, or secret reference",
    )
    expected_result: Optional[str] = Field(
        default=None,
        description="Expected text or URL substring for assertion",
    )
    confidence: float = Field(
        default=1.0,
        description="Parser confidence score between 0.0 and 1.0",
    )
    raw_instruction: str = Field(
        default="",
        description="Original raw instruction text",
    )


class InstructionParseResult(BaseModel):
    """Result of parsing an instruction string."""

    is_valid: bool = Field(..., description="True if instruction was successfully parsed")
    action_data: Optional[ParsedInstruction] = Field(
        default=None, description="Parsed action details if is_valid is True"
    )
    error: Optional[str] = Field(
        default=None, description="Clear explanation when instruction cannot be safely parsed"
    )
    raw_instruction: str = Field(default="", description="Original input string")


def _strip_quotes(text: Optional[str]) -> Optional[str]:
    """Strip matching double, single, or typographical quotes."""
    if text is None:
        return None
    s = text.strip()
    if len(s) >= 2:
        if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
            return s[1:-1].strip()
        if (s.startswith('“') and s.endswith('”')) or (s.startswith('‘') and s.endswith('’')):
            return s[1:-1].strip()
    return s


def _clean_target_descriptor(target: str) -> str:
    """Clean common conversational wrappers from target strings while preserving selectors."""
    t = target.strip()
    # Strip leading prepositions or phrase wrappers (e.g. "the text in", "text in", "in", "into")
    t = re.sub(r"^(?:the\s+text\s+in|text\s+in|in|into)\s+", "", t, flags=re.IGNORECASE).strip()
    t = _strip_quotes(t) or t

    # If it is an explicit CSS/XPath selector or ID, preserve it
    if t.startswith(("#", ".", "[", "//", "xpath=")) or t.endswith("]"):
        return _strip_quotes(t) or t

    # Strip conversational suffixes: "button", "field", "input", "link", "form", "option", "tab", "menuitem", "checkbox", "box", "radio button", "radio"
    t = re.sub(
        r"\s+(?:radio\s+button|radio|button|field|input|link|element|form|option|tab|menuitem|icon|dropdown|checkbox|box)$",
        "",
        t,
        flags=re.IGNORECASE,
    )
    t = _strip_quotes(t) or t
    # Strip conversational prefixes: "the", "the button", "the field", "the form", "the checkbox", "the box", etc.
    t = re.sub(
        r"^(?:the\s+)?(?:radio\s+button|radio|button|field|input|link|element|form|option|tab|menuitem|icon|dropdown|checkbox|box)\s+",
        "",
        t,
        flags=re.IGNORECASE,
    )
    t = re.sub(r"^(?:the\s+)", "", t, flags=re.IGNORECASE)
    return _strip_quotes(t) or t


def _strip_trailing_punctuation(text: str) -> str:
    """
    Safely strip trailing sentence punctuation (. ! ; :) from instructions
    while preserving punctuation enclosed within quotes.
    """
    s = text.strip()
    if not s:
        return s
    if s[-1] in ('"', "'", '”', '’'):
        return s
    return re.sub(r"[\.!;:]+$", "", s).strip()


def _strip_conversational_prefix(text: str) -> str:
    """
    Safely strip polite or conversational prefixes at the start of instructions.
    Examples: 'Please click #btn' -> 'click #btn'
              'Now navigate to /login' -> 'navigate to /login'
              'Next, enter "admin" into "#username"' -> 'enter "admin" into "#username"'
              'And now verify that text "Welcome" is visible' -> 'verify that text "Welcome" is visible'
    """
    s = text.strip()
    prefix_pattern = r"^(?:please\s+|now\s+|next,\s*|next\s+|and\s+then\s+|and\s+now\s+|then\s+)"
    return re.sub(prefix_pattern, "", s, flags=re.IGNORECASE).strip()


def normalize_action_verb(verb: str) -> Optional[str]:
    """Map action verb or phrase to its canonical action name."""
    clean = re.sub(r"\s+", " ", (verb or "").strip().lower())
    if clean in CANONICAL_ACTIONS:
        return clean
    return ACTION_VERB_SYNONYMS.get(clean)


def parse_instruction(instruction: str) -> InstructionParseResult:
    """
    Parse a natural-language test instruction into a structured ParsedInstruction.

    Args:
        instruction: Plain-English sentence or command string.

    Returns:
        InstructionParseResult containing the structured action or a specific error message.
    """
    raw_original = (instruction or "").strip()
    if not raw_original:
        return InstructionParseResult(
            is_valid=False,
            error="Instruction cannot be empty.",
            raw_instruction=raw_original,
        )

    # Clean trailing punctuation outside quotes (e.g. 'Click the "Submit" button.' -> 'Click the "Submit" button')
    raw_clean = _strip_trailing_punctuation(raw_original)

    # -------------------------------------------------------------------------
    # 0. Ambiguity Guard: Detect multiple conflicting command verbs
    # -------------------------------------------------------------------------
    compound_pattern = re.search(
        r"\b(click|tap|press|type|enter|input|fill|navigate|visit|open|verify|assert|check|browse|launch|access|select|hit|choose|put|populate|set|insert|ensure|confirm|clear|empty|uncheck)\b.*?\b(?:and\s+then|and)\s+\b(click|tap|press|type|enter|input|fill|navigate|visit|open|verify|assert|check|browse|launch|access|select|hit|choose|put|populate|set|insert|ensure|confirm|clear|empty|uncheck)\b",
        raw_clean,
        flags=re.IGNORECASE,
    )
    if compound_pattern:
        verb1, verb2 = compound_pattern.group(1), compound_pattern.group(2)
        return InstructionParseResult(
            is_valid=False,
            error=f"Ambiguous compound instruction: detected multiple actions ('{verb1}' and '{verb2}'). Please split into separate step rows.",
            raw_instruction=raw_original,
        )

    # Strip conversational prefixes after compound ambiguity check
    raw = _strip_conversational_prefix(raw_clean)

    # -------------------------------------------------------------------------
    # Explicit Safeguards: Non-linear, dynamic, or unsupported instruction patterns
    # -------------------------------------------------------------------------
    # Guard A: Conditional instructions (if ... then ... / if ...)
    if re.match(r"^if\s+.+$", raw, flags=re.IGNORECASE):
        return InstructionParseResult(
            is_valid=False,
            error=f"Unsupported instruction: conditional instructions ('if ...') are not supported. Test steps must be deterministic linear actions.",
            raw_instruction=raw_original,
        )

    # Guard B: Explicit arbitrary wait/sleep/pause instructions (e.g., "wait 5 seconds", "pause for 3 seconds")
    if re.match(r"^(?:pause|sleep)(?:\s+.+)?$", raw, flags=re.IGNORECASE) or re.match(
        r"^wait(?:\s+for)?\s+\d+\s*(?:s|sec|seconds?|ms|millis|minutes?|m)?$", raw, flags=re.IGNORECASE
    ):
        return InstructionParseResult(
            is_valid=False,
            error=f"Unsupported instruction: explicit wait/sleep instructions are not supported; Noetrix uses automatic bounded dynamic waits during element resolution.",
            raw_instruction=raw_original,
        )

    # -------------------------------------------------------------------------
    # 0. Explicit Wait / Synchronization Instructions (wait_until)
    # -------------------------------------------------------------------------
    # 0a. Explicit wait condition keyword: wait until/for <condition> <target>
    explicit_cond_match = re.match(
        r"^(?:wait\s+(?:until|for)|await)\s+(url_contains|page_heading|element_visible|element_enabled|element_hidden)\s+(.+)$",
        raw,
        flags=re.IGNORECASE,
    )
    if explicit_cond_match:
        cond = explicit_cond_match.group(1).lower()
        val = _strip_quotes(explicit_cond_match.group(2).strip())
        return InstructionParseResult(
            is_valid=True,
            action_data=ParsedInstruction(
                action="wait_until",
                target=cond,
                value=val,
                expected_result=val,
                raw_instruction=raw_original,
            ),
            raw_instruction=raw_original,
        )

    # 0b. URL condition: wait until/for url [to] contains/has/is <target>
    wait_url_match = re.match(
        r"^(?:wait\s+(?:until|for)|await)\s+(?:the\s+)?url(?:\s+to)?\s+(?:contains?|has|matches?|equals?|is)\s+(.+)$",
        raw,
        flags=re.IGNORECASE,
    )
    if wait_url_match:
        val = _strip_quotes(wait_url_match.group(1).strip())
        return InstructionParseResult(
            is_valid=True,
            action_data=ParsedInstruction(
                action="wait_until",
                target="url_contains",
                value=val,
                expected_result=val,
                raw_instruction=raw_original,
            ),
            raw_instruction=raw_original,
        )

    # 0c. Page heading condition: wait until/for [the] [page] heading [is/to be] <target>
    wait_heading_match = re.match(
        r"^(?:wait\s+(?:until|for)|await)\s+(?:the\s+)?(?:page\s+)?heading(?:\s+(?:is|to\s+be|contains?))?\s+(.+)$",
        raw,
        flags=re.IGNORECASE,
    )
    if wait_heading_match:
        val = _strip_quotes(wait_heading_match.group(1).strip())
        return InstructionParseResult(
            is_valid=True,
            action_data=ParsedInstruction(
                action="wait_until",
                target="page_heading",
                value=val,
                expected_result=val,
                raw_instruction=raw_original,
            ),
            raw_instruction=raw_original,
        )

    # 0d. Element state: wait until/for [element] <target> [is/to be] (visible|enabled|hidden|clickable|invisible|detached)
    # or wait until/for [element] <target> to (appear|disappear)
    wait_elem_state_match = re.match(
        r"^(?:wait\s+(?:until|for)|await)\s+(?:the\s+)?(?:element\s+)?(.+?)\s+(?:is|to\s+be)\s+(visible|enabled|hidden|clickable|invisible|detached)$",
        raw,
        flags=re.IGNORECASE,
    )
    if not wait_elem_state_match:
        wait_elem_state_match = re.match(
            r"^(?:wait\s+(?:until|for)|await)\s+(?:the\s+)?(?:element\s+)?(.+?)\s+to\s+(appear|disappear)$",
            raw,
            flags=re.IGNORECASE,
        )
    if wait_elem_state_match:
        elem = _clean_target_descriptor(wait_elem_state_match.group(1).strip())
        state = wait_elem_state_match.group(2).lower()
        if state in ("visible", "appear"):
            cond = "element_visible"
        elif state in ("enabled", "clickable"):
            cond = "element_enabled"
        else:
            cond = "element_hidden"
        return InstructionParseResult(
            is_valid=True,
            action_data=ParsedInstruction(
                action="wait_until",
                target=cond,
                value=elem,
                expected_result=elem,
                raw_instruction=raw_original,
            ),
            raw_instruction=raw_original,
        )

    # 0e. General wait for element: wait for [element] <target>
    wait_elem_match = re.match(
        r"^(?:wait\s+for|await)\s+(?:the\s+)?(?:element\s+)?([\"'].+?[\"']|[a-zA-Z0-9_\-\s]+)$",
        raw,
        flags=re.IGNORECASE,
    )
    if wait_elem_match and not re.match(r"^\d+\s*(?:s|sec|seconds?|ms|minutes?)$", wait_elem_match.group(1).strip(), flags=re.IGNORECASE):
        elem = _clean_target_descriptor(wait_elem_match.group(1).strip())
        return InstructionParseResult(
            is_valid=True,
            action_data=ParsedInstruction(
                action="wait_until",
                target="element_visible",
                value=elem,
                expected_result=elem,
                raw_instruction=raw_original,
            ),
            raw_instruction=raw_original,
        )

    # 0f. Bare wait instructions without target/condition
    if re.match(r"^(?:wait\s+until|wait\s+for|await|wait)$", raw, flags=re.IGNORECASE):
        return InstructionParseResult(
            is_valid=False,
            error="Action 'wait_until' requires a condition type (e.g. 'url_contains', 'page_heading', 'element_visible') and a target.",
            raw_instruction=raw_original,
        )

    # Guard C: Element state assertions (disabled/enabled/checked/unchecked)
    if re.match(
        r"^(?:verify|check|assert|ensure|confirm)(?:\s+that)?\s+.+\s+(?:is|are)\s+(?:disabled|enabled|checked|unchecked|selected|active|inactive)$",
        raw,
        flags=re.IGNORECASE,
    ):
        return InstructionParseResult(
            is_valid=False,
            error=f"Unsupported instruction: element state assertions (disabled/enabled/checked) are not supported. Use visible text or URL verification.",
            raw_instruction=raw_original,
        )

    # -------------------------------------------------------------------------
    # 1. Page Discovery
    # -------------------------------------------------------------------------
    if re.match(
        r"^(?:discover\s+page|discover\s+elements|scan\s+page|inspect\s+page|analyze\s+page|catalog\s+page)$",
        raw,
        flags=re.IGNORECASE,
    ):
        return InstructionParseResult(
            is_valid=True,
            action_data=ParsedInstruction(
                action="discover_page",
                raw_instruction=raw_original,
            ),
            raw_instruction=raw_original,
        )

    # -------------------------------------------------------------------------
    # 2. Navigation
    # Patterns: open <url>, visit <url>, go to <url>, navigate to <url>, browse to <url>, launch <url>, access <url>
    # -------------------------------------------------------------------------
    nav_match = re.match(
        r"^(?:navigate(?:\s+to)?|go\s+to|goto|visit|open(?:\s+url)?|load|browse(?:\s+to)?|launch|access)(?:\s+(.+))?$",
        raw,
        flags=re.IGNORECASE,
    )
    if nav_match:
        dest = nav_match.group(1)
        if not dest or not dest.strip():
            return InstructionParseResult(
                is_valid=False,
                error="Missing destination URL: navigation instruction must specify a URL or path (e.g. 'open https://example.com').",
                raw_instruction=raw_original,
            )
        dest_clean = _strip_quotes(dest.strip())
        return InstructionParseResult(
            is_valid=True,
            action_data=ParsedInstruction(
                action="navigate",
                value=dest_clean,
                raw_instruction=raw_original,
            ),
            raw_instruction=raw_original,
        )

    # -------------------------------------------------------------------------
    # 3. Negative URL Verification
    # Checked before positive URL and general text verification
    # -------------------------------------------------------------------------
    neg_url_match = re.match(
        r"^(?:verify|check|assert|ensure|confirm)(?:\s+that)?(?:\s+the)?(?:\s+current)?\s+url\s+(?:does\s+not\s+contain|is\s+not|does\s+not\s+match|not\s+equals?)(?:\s+(.+))?$",
        raw,
        flags=re.IGNORECASE,
    )
    if neg_url_match:
        unexpected_url = neg_url_match.group(1)
        if not unexpected_url or not unexpected_url.strip():
            return InstructionParseResult(
                is_valid=False,
                error="Missing expected URL: negative URL verification instruction must specify the URL or path substring that should not be present.",
                raw_instruction=raw_original,
            )
        return InstructionParseResult(
            is_valid=True,
            action_data=ParsedInstruction(
                action="verify_not_url",
                expected_result=_strip_quotes(unexpected_url.strip()),
                raw_instruction=raw_original,
            ),
            raw_instruction=raw_original,
        )

    # -------------------------------------------------------------------------
    # 4. Positive URL Verification
    # -------------------------------------------------------------------------
    url_check_match = re.match(
        r"^(?:verify|check|assert|ensure|confirm)(?:\s+that)?(?:\s+the)?(?:\s+current)?\s+url(?:\s+(?:is|contains|matches|equals))?(?:\s+(.+))?$",
        raw,
        flags=re.IGNORECASE,
    )
    if url_check_match:
        expected_url = url_check_match.group(1)
        if not expected_url or not expected_url.strip():
            return InstructionParseResult(
                is_valid=False,
                error="Missing expected URL: URL verification instruction must specify the expected URL or path.",
                raw_instruction=raw_original,
            )
        return InstructionParseResult(
            is_valid=True,
            action_data=ParsedInstruction(
                action="verify_url",
                expected_result=_strip_quotes(expected_url.strip()),
                raw_instruction=raw_original,
            ),
            raw_instruction=raw_original,
        )

    # -------------------------------------------------------------------------
    # 5. Negative Text Verification
    # -------------------------------------------------------------------------
    # Bare negative check with no parameters
    if re.match(
        r"^(?:verify|check|assert|ensure|confirm)(?:\s+that)?(?:\s+text)?(?:\s+(?:is\s+not\s+visible|does\s+not\s+appear|is\s+not\s+displayed|is\s+not\s+shown))?$",
        raw,
        flags=re.IGNORECASE,
    ) and any(neg_phrase in raw.lower() for neg_phrase in ("not visible", "not appear", "not displayed", "not shown", "does not")):
        return InstructionParseResult(
            is_valid=False,
            error="Missing expected text: negative text verification instruction must specify what text to verify.",
            raw_instruction=raw_original,
        )

    neg_text_patterns = [
        # Pattern Neg-A: verify that [the] page does not display/contain [text] "X" [in/on Y]
        (
            r"^(?:verify|check|assert|ensure|confirm)(?:\s+that)?(?:\s+the)?\s+page\s+does\s+not\s+(?:display|contain)\s+(?:text\s+)?(.+?)(?:\s+(?:in|on)\s+(.+))?$",
            False,
        ),
        # Pattern Neg-B: verify [that] text "X" is not visible / does not appear / is not displayed / is not shown [in/on Y]
        (
            r"^(?:verify|check|assert|ensure|confirm)(?:\s+that)?\s+text\s+(.+?)\s+(?:is\s+not\s+visible|does\s+not\s+appear|is\s+not\s+displayed|is\s+not\s+shown)(?:\s+(?:in|on)\s+(.+))?$",
            False,
        ),
        # Pattern Neg-C: verify that "X" is not visible / does not appear / is not displayed [in/on Y]
        (
            r"^(?:verify|check|assert|ensure|confirm)\s+that\s+(.+?)\s+(?:is\s+not\s+visible|does\s+not\s+appear|is\s+not\s+displayed|is\s+not\s+shown)(?:\s+(?:in|on)\s+(.+))?$",
            False,
        ),
        # Pattern Neg-D: ensure/confirm/verify/check "X" is not visible / does not appear [in/on Y]
        (
            r"^(?:verify|check|assert|ensure|confirm)\s+(.+?)\s+(?:is\s+not\s+visible|does\s+not\s+appear|is\s+not\s+displayed|is\s+not\s+shown)(?:\s+(?:in|on)\s+(.+))?$",
            False,
        ),
        # Pattern Neg-Container: verify [that] [the] <container> does not contain / display [text] "X"
        (
            r"^(?:verify|check|assert|ensure|confirm)(?:\s+that)?(?:\s+the)?\s+(.+?)\s+does\s+not\s+(?:contain|display)\s+(?:text\s+)?(.+)$",
            True,
        ),
    ]
    for pattern, is_container_first in neg_text_patterns:
        m = re.match(pattern, raw, flags=re.IGNORECASE)
        if m:
            if is_container_first:
                container = m.group(1)
                text_val = m.group(2)
            else:
                text_val = m.group(1)
                container = m.group(2) if len(m.groups()) >= 2 else None

            if not text_val or not text_val.strip() or text_val.strip().lower() in (
                "is not visible", "does not appear", "is not displayed", "is not shown", "not visible", "not shown"
            ):
                return InstructionParseResult(
                    is_valid=False,
                    error="Missing expected text: negative text verification instruction must specify what text to verify.",
                    raw_instruction=raw_original,
                )

            clean_text = _strip_quotes(text_val.strip())
            clean_container = _clean_target_descriptor(container.strip()) if container else None

            return InstructionParseResult(
                is_valid=True,
                action_data=ParsedInstruction(
                    action="verify_not_text",
                    value=clean_text,
                    expected_result=clean_text,
                    target=clean_container,
                    raw_instruction=raw_original,
                ),
                raw_instruction=raw_original,
            )

    # -------------------------------------------------------------------------
    # 6. Container-First Positive Text Verification
    # (e.g. verify that "#header" contains "Dashboard")
    # -------------------------------------------------------------------------
    container_first_match = re.match(
        r"^(?:verify|check|assert|ensure|confirm)(?:\s+that)?(?:\s+the)?\s+(.+?)\s+(?:contains|displays)\s+(?:text\s+)?(.+)$",
        raw,
        flags=re.IGNORECASE,
    )
    if container_first_match:
        cont_cand = container_first_match.group(1).strip()
        val_cand = container_first_match.group(2).strip()
        if cont_cand.lower() not in ("page", "the page", "url", "current url", "the url"):
            return InstructionParseResult(
                is_valid=True,
                action_data=ParsedInstruction(
                    action="verify_text",
                    value=_strip_quotes(val_cand),
                    expected_result=_strip_quotes(val_cand),
                    target=_clean_target_descriptor(cont_cand),
                    raw_instruction=raw_original,
                ),
                raw_instruction=raw_original,
            )

    # -------------------------------------------------------------------------
    # 7. Standard Positive Text Verification
    # -------------------------------------------------------------------------
    # Checkbox bare keyword
    if raw.lower() in ("check", "uncheck", "mark", "deselect", "mark as checked", "mark as unchecked"):
        return InstructionParseResult(
            is_valid=False,
            error=f"Missing target: '{raw.lower()}' instruction must specify which checkbox to check.",
            raw_instruction=raw_original,
        )

    # Bare verify/check with no parameters
    if re.match(
        r"^(?:verify|check|assert|ensure|confirm)(?:\s+that)?(?:\s+text)?(?:\s+(?:is\s+visible|appears|is\s+displayed|is\s+shown))?$",
        raw,
        flags=re.IGNORECASE,
    ):
        return InstructionParseResult(
            is_valid=False,
            error="Missing expected text: verification instruction must specify what text to verify.",
            raw_instruction=raw_original,
        )

    text_check_patterns = [
        # Pattern A: verify/check/assert/ensure/confirm that [the] page displays/contains [text] "X" [in/on Y]
        r"^(?:verify|check|assert|ensure|confirm)(?:\s+that)?(?:\s+the)?\s+page\s+(?:displays|contains)\s+(?:text\s+)?(.+?)(?:\s+(?:in|on)\s+(.+))?$",
        # Pattern B: verify [that] text "X" is visible / appears / is displayed / is shown [in/on Y]
        r"^(?:verify|check|assert|ensure|confirm)(?:\s+that)?\s+text\s+(.+?)\s+(?:is\s+visible|appears|is\s+displayed|is\s+shown)(?:\s+(?:in|on)\s+(.+))?$",
        # Pattern C: verify/check/assert/ensure/confirm that "X" is visible / appears / is displayed / is shown [in/on Y]
        r"^(?:verify|check|assert|ensure|confirm)\s+that\s+(.+?)\s+(?:is\s+visible|appears|is\s+displayed|is\s+shown)(?:\s+(?:in|on)\s+(.+))?$",
        # Pattern D: ensure/confirm/verify "X" is visible / appears / is displayed / is shown [in/on Y]
        r"^(?:verify|check|assert|ensure|confirm)\s+(.+?)\s+(?:is\s+visible|appears|is\s+displayed|is\s+shown)(?:\s+(?:in|on)\s+(.+))?$",
        # Pattern E: verify/check/assert/ensure/confirm [that] text "X" [in/on Y]
        r"^(?:verify|check|assert|ensure|confirm)(?:\s+that)?\s+text\s+(.+?)(?:\s+(?:in|on)\s+(.+))?$",
    ]
    for pattern in text_check_patterns:
        m = re.match(pattern, raw, flags=re.IGNORECASE)
        if m:
            text_val = m.group(1)
            container = m.group(2) if len(m.groups()) >= 2 else None

            if not text_val or not text_val.strip() or text_val.strip().lower() in (
                "is visible", "appears", "visible", "is displayed", "displayed", "is shown", "shown"
            ):
                return InstructionParseResult(
                    is_valid=False,
                    error="Missing expected text: text verification instruction must specify the text to verify.",
                    raw_instruction=raw_original,
                )

            clean_text = _strip_quotes(text_val.strip())
            clean_container = _clean_target_descriptor(container.strip()) if container else None

            return InstructionParseResult(
                is_valid=True,
                action_data=ParsedInstruction(
                    action="verify_text",
                    value=clean_text,
                    expected_result=clean_text,
                    target=clean_container,
                    raw_instruction=raw_original,
                ),
                raw_instruction=raw_original,
            )

    # -------------------------------------------------------------------------
    # 8. Inverted Input Phrasing
    # (e.g. In the "Username" field, type "admin")
    # -------------------------------------------------------------------------
    inv_type_match = re.match(
        r"^(?:in|on|into)\s+(?:the\s+)?(.+?)(?:\s+(?:field|input|box))?,\s*(?:type|enter|input|write|put|insert|fill|populate)\s+(.+)$",
        raw,
        flags=re.IGNORECASE,
    )
    if inv_type_match:
        target_part = inv_type_match.group(1).strip()
        val_part = inv_type_match.group(2).strip()
        val_part = re.sub(r"^with\s+", "", val_part, flags=re.IGNORECASE).strip()
        return InstructionParseResult(
            is_valid=True,
            action_data=ParsedInstruction(
                action="fill",
                target=_clean_target_descriptor(target_part),
                value=_strip_quotes(val_part),
                raw_instruction=raw_original,
            ),
            raw_instruction=raw_original,
        )

    # -------------------------------------------------------------------------
    # 8b. Inverted Dropdown Selection Phrasing
    # (e.g. In the "Role" dropdown, select "Admin" / From "#state", choose "California")
    # -------------------------------------------------------------------------
    inv_select_match = re.match(
        r"^(?:in|from)\s+(?:the\s+)?(.+?)(?:\s+(?:dropdown|select))?,\s*(?:select_option|select|choose)(?:\s+option)?(?:\s+(.+))?$",
        raw,
        flags=re.IGNORECASE,
    )
    if inv_select_match:
        target_part = inv_select_match.group(1).strip()
        val_part = inv_select_match.group(2)
        if not val_part or not val_part.strip():
            return InstructionParseResult(
                is_valid=False,
                error=f"Missing value: dropdown selection for '{target_part}' must specify which option to select.",
                raw_instruction=raw_original,
            )
        clean_target = _clean_target_descriptor(target_part)
        clean_val = _strip_quotes(val_part.strip())
        if not clean_target:
            return InstructionParseResult(
                is_valid=False,
                error="Missing target: inverted dropdown selection must specify the dropdown element.",
                raw_instruction=raw_original,
            )
        return InstructionParseResult(
            is_valid=True,
            action_data=ParsedInstruction(
                action="select_option",
                target=clean_target,
                value=clean_val,
                raw_instruction=raw_original,
            ),
            raw_instruction=raw_original,
        )

    # -------------------------------------------------------------------------
    # 9. Standard Text Entry (Fill)
    # -------------------------------------------------------------------------
    # Form A: fill [in] / populate [in] <target> with <value>
    fill_with_match = re.match(
        r"^(?:fill|populate)(?:\s+in)?(?:\s+(.+?))?(?:\s+with\s+(.+))?$",
        raw,
        flags=re.IGNORECASE,
    )
    if fill_with_match:
        target_part = fill_with_match.group(1)
        value_part = fill_with_match.group(2)

        if not target_part:
            return InstructionParseResult(
                is_valid=False,
                error="Missing target: 'fill' instruction must specify which field to fill.",
                raw_instruction=raw_original,
            )
        if not value_part:
            return InstructionParseResult(
                is_valid=False,
                error=f"Missing value: 'fill' instruction for '{target_part}' must specify what to fill using 'with <value>'.",
                raw_instruction=raw_original,
            )

        return InstructionParseResult(
            is_valid=True,
            action_data=ParsedInstruction(
                action="fill",
                target=_clean_target_descriptor(target_part),
                value=_strip_quotes(value_part.strip()),
                raw_instruction=raw_original,
            ),
            raw_instruction=raw_original,
        )

    # Form B: set <target> to <value>
    set_to_match = re.match(
        r"^set(?:\s+(.+?))?(?:\s+to\s+(.+))?$",
        raw,
        flags=re.IGNORECASE,
    )
    if set_to_match:
        target_part = set_to_match.group(1)
        value_part = set_to_match.group(2)

        if not target_part:
            return InstructionParseResult(
                is_valid=False,
                error="Missing target: 'set' instruction must specify which field to set.",
                raw_instruction=raw_original,
            )
        if not value_part:
            return InstructionParseResult(
                is_valid=False,
                error=f"Missing value: 'set' instruction for '{target_part}' must specify the value using 'to <value>'.",
                raw_instruction=raw_original,
            )

        return InstructionParseResult(
            is_valid=True,
            action_data=ParsedInstruction(
                action="fill",
                target=_clean_target_descriptor(target_part),
                value=_strip_quotes(value_part.strip()),
                raw_instruction=raw_original,
            ),
            raw_instruction=raw_original,
        )

    # Form C: type/enter/input/write/put/insert <value> into/in <target>
    type_into_match = re.match(
        r"^(?:type|enter|input|write|put|insert)\s+(.+?)\s+(?:into|in)\s+(.+)$",
        raw,
        flags=re.IGNORECASE,
    )
    if type_into_match:
        val_part = type_into_match.group(1).strip()
        target_part = type_into_match.group(2).strip()

        if not val_part:
            return InstructionParseResult(
                is_valid=False,
                error=f"Missing value: no text specified to enter into '{target_part}'.",
                raw_instruction=raw_original,
            )
        if not target_part:
            return InstructionParseResult(
                is_valid=False,
                error=f"Missing target: no destination field specified for value '{val_part}'.",
                raw_instruction=raw_original,
            )

        return InstructionParseResult(
            is_valid=True,
            action_data=ParsedInstruction(
                action="fill",
                target=_clean_target_descriptor(target_part),
                value=_strip_quotes(val_part),
                raw_instruction=raw_original,
            ),
            raw_instruction=raw_original,
        )

    # Malformed text entry checks
    if re.match(r"^(?:type|enter|input|write|put|insert)\s+(?:into|in)\s+(.+)$", raw, flags=re.IGNORECASE):
        t = re.match(r"^(?:type|enter|input|write|put|insert)\s+(?:into|in)\s+(.+)$", raw, flags=re.IGNORECASE).group(1)
        return InstructionParseResult(
            is_valid=False,
            error=f"Missing value: specify what text to enter before 'into {t}'.",
            raw_instruction=raw_original,
        )
    if re.match(r"^(?:type|enter|input|write|put|insert)\s+(.+)$", raw, flags=re.IGNORECASE):
        v = re.match(r"^(?:type|enter|input|write|put|insert)\s+(.+)$", raw, flags=re.IGNORECASE).group(1)
        return InstructionParseResult(
            is_valid=False,
            error=f"Missing target: text entry for '{v}' must specify a destination field (e.g. 'into #username').",
            raw_instruction=raw_original,
        )
    if re.match(r"^(?:type|enter|input|write|put|insert|fill|populate|set)$", raw, flags=re.IGNORECASE):
        return InstructionParseResult(
            is_valid=False,
            error="Missing target and value: text entry instruction must specify what to type and where.",
            raw_instruction=raw_original,
        )

    # -------------------------------------------------------------------------
    # 10. Field Clearing
    # Patterns: clear <target>, empty <target>, erase <target>
    # -------------------------------------------------------------------------
    clear_match = re.match(
        r"^(?:clear|empty|erase)(?:\s+(?:the\s+)?(?:field|input|box))?(?:\s+(.+))?$",
        raw,
        flags=re.IGNORECASE,
    )
    if clear_match:
        target_part = clear_match.group(1)
        if not target_part or not target_part.strip():
            return InstructionParseResult(
                is_valid=False,
                error="Missing target: 'clear/empty' instruction must specify which field to clear.",
                raw_instruction=raw_original,
            )
        return InstructionParseResult(
            is_valid=True,
            action_data=ParsedInstruction(
                action="clear",
                target=_clean_target_descriptor(target_part),
                raw_instruction=raw_original,
            ),
            raw_instruction=raw_original,
        )

    # -------------------------------------------------------------------------
    # 11. Checkbox Check & Uncheck
    # Patterns:
    #   - uncheck [the] [checkbox] <target>
    #   - deselect [the] [checkbox] <target>
    #   - unmark [the] [checkbox] <target>
    #   - check [the] [checkbox] <target>
    #   - mark [the] [checkbox] <target> [as checked]
    # -------------------------------------------------------------------------
    uncheck_match = re.match(
        r"^(?:uncheck|deselect|unmark)(?:\s+(?:the\s+)?(?:checkbox|box))?(?:\s+(.+))?$",
        raw,
        flags=re.IGNORECASE,
    )
    if uncheck_match:
        target_part = uncheck_match.group(1)
        if not target_part or not target_part.strip() or target_part.strip().lower() in ("as unchecked", "unchecked"):
            return InstructionParseResult(
                is_valid=False,
                error="Missing target: 'uncheck' instruction must specify which checkbox to uncheck.",
                raw_instruction=raw_original,
            )
        return InstructionParseResult(
            is_valid=True,
            action_data=ParsedInstruction(
                action="uncheck",
                target=_clean_target_descriptor(target_part),
                raw_instruction=raw_original,
            ),
            raw_instruction=raw_original,
        )

    check_cb_match = re.match(
        r"^(?:check|mark)(?:\s+(?:the\s+)?(?:checkbox|box))?(?:\s+(.+?))?(?:\s+as\s+checked)?$",
        raw,
        flags=re.IGNORECASE,
    )
    if check_cb_match:
        target_part = check_cb_match.group(1)
        if not target_part or not target_part.strip() or target_part.strip().lower() in ("as checked", "checked"):
            return InstructionParseResult(
                is_valid=False,
                error="Missing target: 'check' instruction must specify which checkbox to check.",
                raw_instruction=raw_original,
            )
        return InstructionParseResult(
            is_valid=True,
            action_data=ParsedInstruction(
                action="check",
                target=_clean_target_descriptor(target_part),
                raw_instruction=raw_original,
            ),
            raw_instruction=raw_original,
        )

    # -------------------------------------------------------------------------
    # 11b. Dropdown Selection
    # Patterns:
    #   - select/choose [option] <value> from/in [the] [dropdown] <target>
    # -------------------------------------------------------------------------
    # Incomplete: missing value before from/in
    if re.match(
        r"^(?:select_option|select|choose)(?:\s+option)?\s+(?:from|in)(?:\s+.*)?$",
        raw,
        flags=re.IGNORECASE,
    ):
        return InstructionParseResult(
            is_valid=False,
            error="Missing value: dropdown selection instruction must specify which option to select (e.g. 'select \"California\" from \"#state\"').",
            raw_instruction=raw_original,
        )

    # Incomplete: missing target after from/in
    missing_tgt_match = re.match(
        r"^(?:select_option|select|choose)(?:\s+option)?\s+([\"'“‘].+?[\"'”’]|\S+)\s+(?:from|in)(?:\s+(?:the\s+)?dropdown)?\s*$",
        raw,
        flags=re.IGNORECASE,
    )
    if missing_tgt_match:
        val_cand = _strip_quotes(missing_tgt_match.group(1).strip())
        return InstructionParseResult(
            is_valid=False,
            error=f"Missing target: dropdown selection for '{val_cand}' must specify the dropdown element (e.g. 'from \"#state\"').",
            raw_instruction=raw_original,
        )

    dropdown_select_match = re.match(
        r"^(?:select_option|select|choose)(?:\s+option)?\s+([\"'“‘].+?[\"'”’]|.+?)\s+(?:from|in)\s+(?:the\s+)?(?:dropdown\s+)?(.+)$",
        raw,
        flags=re.IGNORECASE,
    )
    if dropdown_select_match:
        val_cand = dropdown_select_match.group(1).strip()
        target_cand = dropdown_select_match.group(2).strip()

        clean_val = _strip_quotes(val_cand)
        clean_target = _clean_target_descriptor(target_cand)

        if not clean_val:
            return InstructionParseResult(
                is_valid=False,
                error="Missing value: dropdown selection instruction must specify which option to select.",
                raw_instruction=raw_original,
            )
        if not clean_target:
            return InstructionParseResult(
                is_valid=False,
                error=f"Missing target: dropdown selection for '{clean_val}' must specify a specific dropdown element (e.g. 'from \"#state\"').",
                raw_instruction=raw_original,
            )

        return InstructionParseResult(
            is_valid=True,
            action_data=ParsedInstruction(
                action="select_option",
                target=clean_target,
                value=clean_val,
                raw_instruction=raw_original,
            ),
            raw_instruction=raw_original,
        )

    # -------------------------------------------------------------------------
    # 12. Clicking
    # -------------------------------------------------------------------------
    click_match = re.match(
        r"^(?:click(?:\s+on)?|tap(?:\s+on)?|press(?:\s+on)?(?:\s+the)?(?:\s+button)?|submit(?:\s+the)?(?:\s+form)?|select(?:\s+the)?(?:\s+(?:button|link|option|tab|menuitem))?|hit(?:\s+the)?(?:\s+button)?|choose(?:\s+the)?(?:\s+(?:option|button|link|tab))?)(?:\s+(.+))?$",
        raw,
        flags=re.IGNORECASE,
    )
    if click_match:
        target_part = click_match.group(1)
        if not target_part or not target_part.strip():
            return InstructionParseResult(
                is_valid=False,
                error="Missing target: click/press instruction must specify which button or element to click.",
                raw_instruction=raw_original,
            )
        return InstructionParseResult(
            is_valid=True,
            action_data=ParsedInstruction(
                action="click",
                target=_clean_target_descriptor(target_part),
                raw_instruction=raw_original,
            ),
            raw_instruction=raw_original,
        )

    # -------------------------------------------------------------------------
    # 13. Fallback: Unrecognized instruction
    # -------------------------------------------------------------------------
    return InstructionParseResult(
        is_valid=False,
        error=f"Unsupported instruction: could not determine action from '{raw_original}'. Supported actions: open/navigate, type/enter/fill, click/tap/press, clear, check, uncheck, select option, verify text, verify url, discover page.",
        raw_instruction=raw_original,
    )


def parse_step_data(
    action: str,
    target: Optional[str] = None,
    value: Optional[str] = None,
    expected_result: Optional[str] = None,
) -> InstructionParseResult:
    """
    Interpret either a structured step row or a single natural language instruction row.
    """
    raw_action = (action or "").strip()
    if not raw_action:
        return InstructionParseResult(
            is_valid=False,
            error="Action cannot be empty.",
            raw_instruction="",
        )

    # Case 1: action is a canonical keyword
    canonical = normalize_action_verb(raw_action)
    if canonical == "click" and raw_action.lower() in ("select", "choose") and value:
        canonical = "select_option"
    if canonical == "wait_until":
        from app.services.csv_validator import normalize_wait_condition
        norm_cond = normalize_wait_condition(target)
        if norm_cond:
            val_cand = _strip_quotes(value) or _strip_quotes(expected_result)
            return InstructionParseResult(
                is_valid=True,
                action_data=ParsedInstruction(
                    action="wait_until",
                    target=norm_cond,
                    value=val_cand,
                    expected_result=_strip_quotes(expected_result) or val_cand,
                    raw_instruction=raw_action,
                ),
                raw_instruction=raw_action,
            )
        rev_cond = normalize_wait_condition(value)
        if rev_cond:
            elem_cand = _clean_target_descriptor(target) or _strip_quotes(expected_result)
            return InstructionParseResult(
                is_valid=True,
                action_data=ParsedInstruction(
                    action="wait_until",
                    target=rev_cond,
                    value=elem_cand,
                    expected_result=_strip_quotes(expected_result) or elem_cand,
                    raw_instruction=raw_action,
                ),
                raw_instruction=raw_action,
            )
        return InstructionParseResult(
            is_valid=True,
            action_data=ParsedInstruction(
                action="wait_until",
                target=_clean_target_descriptor(target) if target else None,
                value=_strip_quotes(value),
                expected_result=_strip_quotes(expected_result),
                raw_instruction=raw_action,
            ),
            raw_instruction=raw_action,
        )
    if canonical and (target or value or expected_result or canonical in ("discover_page", "clear", "check", "uncheck")):
        return InstructionParseResult(
            is_valid=True,
            action_data=ParsedInstruction(
                action=canonical,
                target=_clean_target_descriptor(target) if target else None,
                value=_strip_quotes(value),
                expected_result=_strip_quotes(expected_result),
                raw_instruction=raw_action,
            ),
            raw_instruction=raw_action,
        )

    # Case 2: Full natural-language sentence provided in action column
    parsed = parse_instruction(raw_action)
    if parsed.is_valid and parsed.action_data:
        action_obj = parsed.action_data
        if target and not action_obj.target:
            action_obj.target = _clean_target_descriptor(target)
        if value and not action_obj.value:
            action_obj.value = _strip_quotes(value)
        if expected_result and not action_obj.expected_result:
            action_obj.expected_result = _strip_quotes(expected_result)
        return parsed

    # Case 3: Action verb synonym with structured target/value
    if canonical:
        return InstructionParseResult(
            is_valid=True,
            action_data=ParsedInstruction(
                action=canonical,
                target=_clean_target_descriptor(target) if target else None,
                value=_strip_quotes(value),
                expected_result=_strip_quotes(expected_result),
                raw_instruction=raw_action,
            ),
            raw_instruction=raw_action,
        )

    return parsed
