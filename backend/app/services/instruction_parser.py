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
}

# Synonym mapping for standalone verbs
ACTION_VERB_SYNONYMS = {
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
    # Text verification
    "verify_text": "verify_text",
    "verify text": "verify_text",
    "check text": "verify_text",
    "assert text": "verify_text",
    "ensure text": "verify_text",
    "confirm text": "verify_text",
    # URL verification
    "verify_url": "verify_url",
    "verify url": "verify_url",
    "check url": "verify_url",
    "assert url": "verify_url",
    "ensure url": "verify_url",
    "confirm url": "verify_url",
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
        description="Normalized canonical action: navigate, fill, click, verify_url, verify_text, discover_page",
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
    # Strip leading "in " or "into " preposition if left over
    t = re.sub(r"^(?:in|into)\s+", "", t, flags=re.IGNORECASE).strip()
    t = _strip_quotes(t) or t

    # If it is an explicit CSS/XPath selector or ID, preserve it
    if t.startswith(("#", ".", "[", "//", "xpath=")) or t.endswith("]"):
        return _strip_quotes(t) or t

    # Strip conversational prefixes: "the", "the button", "the field", "the form", "the option", etc.
    t = re.sub(
        r"^(?:the\s+)?(?:button|field|input|link|element|form|option|tab|menuitem|icon|dropdown)\s+",
        "",
        t,
        flags=re.IGNORECASE,
    )
    t = re.sub(r"^(?:the\s+)", "", t, flags=re.IGNORECASE)
    # Strip conversational suffixes: "button", "field", "input", "link", "form", "option", "tab", "menuitem"
    t = re.sub(
        r"\s+(?:button|field|input|link|element|form|option|tab|menuitem|icon|dropdown)$",
        "",
        t,
        flags=re.IGNORECASE,
    )
    return _strip_quotes(t) or t


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
    raw = (instruction or "").strip()
    if not raw:
        return InstructionParseResult(
            is_valid=False,
            error="Instruction cannot be empty.",
            raw_instruction=raw,
        )

    # -------------------------------------------------------------------------
    # 0. Ambiguity Guard: Detect multiple conflicting command verbs
    # -------------------------------------------------------------------------
    compound_pattern = re.search(
        r"\b(click|tap|press|type|enter|input|fill|navigate|visit|open|verify|assert|check|browse|launch|access|select|hit|choose|put|populate|set|insert|ensure|confirm)\b.*?\b(?:and\s+then|and)\s+\b(click|tap|press|type|enter|input|fill|navigate|visit|open|verify|assert|check|browse|launch|access|select|hit|choose|put|populate|set|insert|ensure|confirm)\b",
        raw,
        flags=re.IGNORECASE,
    )
    if compound_pattern:
        verb1, verb2 = compound_pattern.group(1), compound_pattern.group(2)
        return InstructionParseResult(
            is_valid=False,
            error=f"Ambiguous compound instruction: detected multiple actions ('{verb1}' and '{verb2}'). Please split into separate step rows.",
            raw_instruction=raw,
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
                raw_instruction=raw,
            ),
            raw_instruction=raw,
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
                raw_instruction=raw,
            )
        dest_clean = _strip_quotes(dest.strip())
        return InstructionParseResult(
            is_valid=True,
            action_data=ParsedInstruction(
                action="navigate",
                value=dest_clean,
                raw_instruction=raw,
            ),
            raw_instruction=raw,
        )

    # -------------------------------------------------------------------------
    # 3. URL Verification
    # Checked before general text verification so 'verify url' is never parsed as verify_text
    # Patterns: verify url <url>, check current url is <url>, verify that the url contains <url>, ensure url is <url>
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
                raw_instruction=raw,
            )
        return InstructionParseResult(
            is_valid=True,
            action_data=ParsedInstruction(
                action="verify_url",
                expected_result=_strip_quotes(expected_url.strip()),
                raw_instruction=raw,
            ),
            raw_instruction=raw,
        )

    # -------------------------------------------------------------------------
    # 4. Text Verification
    # -------------------------------------------------------------------------
    # Bare verify/check with no parameters check first
    if re.match(
        r"^(?:verify|check|assert|ensure|confirm)(?:\s+that)?(?:\s+text)?(?:\s+(?:is\s+visible|appears|is\s+displayed|is\s+shown))?$",
        raw,
        flags=re.IGNORECASE,
    ):
        return InstructionParseResult(
            is_valid=False,
            error="Missing expected text: verification instruction must specify what text to verify.",
            raw_instruction=raw,
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
                    raw_instruction=raw,
                )

            clean_text = _strip_quotes(text_val.strip())
            clean_container = _strip_quotes(container.strip()) if container else None

            return InstructionParseResult(
                is_valid=True,
                action_data=ParsedInstruction(
                    action="verify_text",
                    expected_result=clean_text,
                    target=clean_container,
                    raw_instruction=raw,
                ),
                raw_instruction=raw,
            )

    # -------------------------------------------------------------------------
    # 5. Text Entry (Fill)
    # Patterns:
    #   - fill [in] / populate <target> with <value>
    #   - set <target> to <value>
    #   - type/enter/input/write/put/insert <value> into/in [the] <target> [field]
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
                raw_instruction=raw,
            )
        if not value_part:
            return InstructionParseResult(
                is_valid=False,
                error=f"Missing value: 'fill' instruction for '{target_part}' must specify what to fill using 'with <value>'.",
                raw_instruction=raw,
            )

        return InstructionParseResult(
            is_valid=True,
            action_data=ParsedInstruction(
                action="fill",
                target=_clean_target_descriptor(target_part),
                value=_strip_quotes(value_part.strip()),
                raw_instruction=raw,
            ),
            raw_instruction=raw,
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
                raw_instruction=raw,
            )
        if not value_part:
            return InstructionParseResult(
                is_valid=False,
                error=f"Missing value: 'set' instruction for '{target_part}' must specify the value using 'to <value>'.",
                raw_instruction=raw,
            )

        return InstructionParseResult(
            is_valid=True,
            action_data=ParsedInstruction(
                action="fill",
                target=_clean_target_descriptor(target_part),
                value=_strip_quotes(value_part.strip()),
                raw_instruction=raw,
            ),
            raw_instruction=raw,
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
                raw_instruction=raw,
            )
        if not target_part:
            return InstructionParseResult(
                is_valid=False,
                error=f"Missing target: no destination field specified for value '{val_part}'.",
                raw_instruction=raw,
            )

        return InstructionParseResult(
            is_valid=True,
            action_data=ParsedInstruction(
                action="fill",
                target=_clean_target_descriptor(target_part),
                value=_strip_quotes(val_part),
                raw_instruction=raw,
            ),
            raw_instruction=raw,
        )

    # Malformed text entry checks:
    if re.match(r"^(?:type|enter|input|write|put|insert)\s+(?:into|in)\s+(.+)$", raw, flags=re.IGNORECASE):
        t = re.match(r"^(?:type|enter|input|write|put|insert)\s+(?:into|in)\s+(.+)$", raw, flags=re.IGNORECASE).group(1)
        return InstructionParseResult(
            is_valid=False,
            error=f"Missing value: specify what text to enter before 'into {t}'.",
            raw_instruction=raw,
        )
    if re.match(r"^(?:type|enter|input|write|put|insert)\s+(.+)$", raw, flags=re.IGNORECASE):
        v = re.match(r"^(?:type|enter|input|write|put|insert)\s+(.+)$", raw, flags=re.IGNORECASE).group(1)
        return InstructionParseResult(
            is_valid=False,
            error=f"Missing target: text entry for '{v}' must specify a destination field (e.g. 'into #username').",
            raw_instruction=raw,
        )
    if re.match(r"^(?:type|enter|input|write|put|insert|fill|populate|set)$", raw, flags=re.IGNORECASE):
        return InstructionParseResult(
            is_valid=False,
            error="Missing target and value: text entry instruction must specify what to type and where.",
            raw_instruction=raw,
        )

    # -------------------------------------------------------------------------
    # 6. Clicking
    # Patterns:
    #   - click [on] [the] [button] <target>
    #   - tap [on] <target>
    #   - press [on] [the] [button] <target>
    #   - submit [the] [form] <target>
    #   - select [the] [button|link|option|tab] <target>
    #   - hit [the] [button] <target>
    #   - choose [the] [option|button|link|tab] <target>
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
                raw_instruction=raw,
            )
        return InstructionParseResult(
            is_valid=True,
            action_data=ParsedInstruction(
                action="click",
                target=_clean_target_descriptor(target_part),
                raw_instruction=raw,
            ),
            raw_instruction=raw,
        )

    # -------------------------------------------------------------------------
    # 7. Fallback: Unrecognized instruction
    # -------------------------------------------------------------------------
    return InstructionParseResult(
        is_valid=False,
        error=f"Unsupported instruction: could not determine action from '{raw}'. Supported actions: open/navigate, type/enter/fill, click/tap/press, verify text, verify url, discover page.",
        raw_instruction=raw,
    )


def parse_step_data(
    action: str,
    target: Optional[str] = None,
    value: Optional[str] = None,
    expected_result: Optional[str] = None,
) -> InstructionParseResult:
    """
    Interpret either a structured step row or a single natural language instruction row.

    Maintains 100% backward compatibility:
        - If action is already canonical ('fill', 'click', etc.), preserves structured inputs.
        - If action is an action verb synonym ('type', 'visit', etc.), normalizes action and preserves inputs.
        - If action contains a natural-language sentence and target/value are empty, passes it to parse_instruction.

    Returns:
        InstructionParseResult with normalized action and attributes.
    """
    raw_action = (action or "").strip()
    if not raw_action:
        return InstructionParseResult(
            is_valid=False,
            error="Action cannot be empty.",
            raw_instruction="",
        )

    # Case 1: action is a canonical keyword (navigate, fill, click, verify_url, verify_text, discover_page)
    canonical = normalize_action_verb(raw_action)
    if canonical and (target or value or expected_result or canonical == "discover_page"):
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
    # (e.g. action="Type 'admin' into '#user'", target=None, value=None)
    parsed = parse_instruction(raw_action)
    if parsed.is_valid and parsed.action_data:
        # If the caller also provided explicit secondary columns, let secondary columns supplement
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

    # Return the parse error from parse_instruction
    return parsed
