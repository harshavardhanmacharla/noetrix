"""
Unit tests for Noetrix Natural-Language Instruction Parser.
Verifies parsing of common plain-English test instructions, synonym normalization,
missing-parameter error handling, ambiguity detection, and backward compatibility.
"""
import pytest
from app.services.instruction_parser import (
    InstructionParseResult,
    ParsedInstruction,
    normalize_action_verb,
    parse_instruction,
    parse_step_data,
)


# =============================================================================
# 1. Navigation Instructions
# =============================================================================

@pytest.mark.parametrize(
    "instruction, expected_url",
    [
        ("open https://example.com", "https://example.com"),
        ("open 'https://example.com'", "https://example.com"),
        ('open "https://example.com"', "https://example.com"),
        ("open /dashboard", "/dashboard"),
        ("visit https://example.com/login", "https://example.com/login"),
        ('visit "https://example.com/login"', "https://example.com/login"),
        ("go to https://example.com", "https://example.com"),
        ("goto http://localhost:3000", "http://localhost:3000"),
        ("navigate to https://noetrix.internal", "https://noetrix.internal"),
        ('navigate "https://example.com"', "https://example.com"),
        ("load https://example.com/app", "https://example.com/app"),
        ("  VISIT   https://example.com/test  ", "https://example.com/test"),
    ],
)
def test_navigation_instructions_success(instruction: str, expected_url: str):
    res = parse_instruction(instruction)
    assert res.is_valid is True
    assert res.action_data is not None
    assert res.action_data.action == "navigate"
    assert res.action_data.value == expected_url
    assert res.error is None


def test_navigation_missing_destination_fails():
    for text in ["open", "visit", "go to", "navigate to", "navigate", "load"]:
        res = parse_instruction(text)
        assert res.is_valid is False
        assert "Missing destination URL" in (res.error or "")


# =============================================================================
# 2. Text Entry Instructions
# =============================================================================

@pytest.mark.parametrize(
    "instruction, expected_target, expected_value",
    [
        ('type "admin" into "#username"', "#username", "admin"),
        ("type 'admin' into '#username'", "#username", "admin"),
        ("type admin into #username", "#username", "admin"),
        ('enter "secret123" into "#password"', "#password", "secret123"),
        ('enter "${secret:APEX_PASSWORD}" into "#password"', "#password", "${secret:APEX_PASSWORD}"),
        ('input "search query" into "#search-box"', "#search-box", "search query"),
        ('write "hello" in "#notes"', "#notes", "hello"),
        ('type "test" into the "Username" field', "Username", "test"),
        ('fill "#username" with "admin"', "#username", "admin"),
        ('fill in "#email" with "user@example.com"', "#email", "user@example.com"),
        ('fill the "Email" field with "user@test.com"', "Email", "user@test.com"),
        ('fill #email with test@noetrix.internal', "#email", "test@noetrix.internal"),
    ],
)
def test_text_entry_instructions_success(instruction: str, expected_target: str, expected_value: str):
    res = parse_instruction(instruction)
    assert res.is_valid is True
    assert res.action_data is not None
    assert res.action_data.action == "fill"
    assert res.action_data.target == expected_target
    assert res.action_data.value == expected_value
    assert res.error is None


def test_text_entry_missing_parameters_fail():
    # Missing value
    res1 = parse_instruction('type into "#username"')
    assert res1.is_valid is False
    assert "Missing value" in (res1.error or "")

    # Missing target
    res2 = parse_instruction('type "admin"')
    assert res2.is_valid is False
    assert "Missing target" in (res2.error or "")

    # Fill without with
    res3 = parse_instruction('fill "#username"')
    assert res3.is_valid is False
    assert "Missing value" in (res3.error or "")

    # Bare keyword
    res4 = parse_instruction("type")
    assert res4.is_valid is False
    assert "Missing target and value" in (res4.error or "")


# =============================================================================
# 3. Clicking Instructions
# =============================================================================

@pytest.mark.parametrize(
    "instruction, expected_target",
    [
        ('click "#submit-btn"', "#submit-btn"),
        ('click button[type="submit"]', 'button[type="submit"]'),
        ("click button[type='submit']", "button[type='submit']"),
        ('click the "Sign In" button', "Sign In"),
        ('click the button "#login"', "#login"),
        ('click on "#submit"', "#submit"),
        ('click on the "Next" button', "Next"),
        ('tap "#menu-icon"', "#menu-icon"),
        ('tap on "#avatar"', "#avatar"),
        ('press the button "#confirm"', "#confirm"),
        ('press the "Save" button', "Save"),
        ('press "#submit"', "#submit"),
        ('submit "#login-form"', "#login-form"),
        ('submit the form "#checkout"', "#checkout"),
    ],
)
def test_clicking_instructions_success(instruction: str, expected_target: str):
    res = parse_instruction(instruction)
    assert res.is_valid is True
    assert res.action_data is not None
    assert res.action_data.action == "click"
    assert res.action_data.target == expected_target
    assert res.error is None


def test_clicking_missing_target_fails():
    for text in ["click", "click on", "tap", "tap on", "press the button", "press", "submit"]:
        res = parse_instruction(text)
        assert res.is_valid is False
        assert "Missing target" in (res.error or "")


# =============================================================================
# 4. Text Verification Instructions
# =============================================================================

@pytest.mark.parametrize(
    "instruction, expected_text, expected_target",
    [
        ('verify that text "Welcome back" is visible', "Welcome back", None),
        ("verify that text 'Welcome back' is visible", "Welcome back", None),
        ('check that text "Success" is visible', "Success", None),
        ('assert that text "Dashboard" is visible', "Dashboard", None),
        ('verify text "Order Confirmed"', "Order Confirmed", None),
        ('assert that "Welcome" is visible', "Welcome", None),
        ('check that "Payment received" appears', "Payment received", None),
        ('verify that text "Welcome" is visible in "#header"', "Welcome", "#header"),
        ('assert that text "Error" is visible in ".alert-danger"', "Error", ".alert-danger"),
        ('check that text "Status: Active" is visible on "#status-card"', "Status: Active", "#status-card"),
    ],
)
def test_text_verification_instructions_success(
    instruction: str, expected_text: str, expected_target: str
):
    res = parse_instruction(instruction)
    assert res.is_valid is True
    assert res.action_data is not None
    assert res.action_data.action == "verify_text"
    assert res.action_data.expected_result == expected_text
    assert res.action_data.target == expected_target
    assert res.error is None


def test_text_verification_missing_text_fails():
    for text in [
        "verify that text is visible",
        "verify text",
        "check that text is visible",
        "assert that text is visible",
        "verify",
    ]:
        res = parse_instruction(text)
        assert res.is_valid is False
        assert "Missing expected text" in (res.error or "")


# =============================================================================
# 5. URL Verification Instructions
# =============================================================================

@pytest.mark.parametrize(
    "instruction, expected_url",
    [
        ('verify url "https://example.com/dashboard"', "https://example.com/dashboard"),
        ('verify url https://example.com/dashboard', "https://example.com/dashboard"),
        ('verify that the url contains "/dashboard"', "/dashboard"),
        ('verify that the current url is "https://example.com"', "https://example.com"),
        ('check current url is "https://example.com"', "https://example.com"),
        ('check that the url contains "/reports"', "/reports"),
        ('assert url "/login"', "/login"),
        ('assert that the url equals "https://example.com/home"', "https://example.com/home"),
    ],
)
def test_url_verification_instructions_success(instruction: str, expected_url: str):
    res = parse_instruction(instruction)
    assert res.is_valid is True
    assert res.action_data is not None
    assert res.action_data.action == "verify_url"
    assert res.action_data.expected_result == expected_url
    assert res.error is None


def test_url_verification_missing_url_fails():
    for text in ["verify url", "check url", "assert url", "verify that the current url is"]:
        res = parse_instruction(text)
        assert res.is_valid is False
        assert "Missing expected URL" in (res.error or "")


# =============================================================================
# 6. Page Discovery Instructions
# =============================================================================

@pytest.mark.parametrize(
    "instruction",
    ["discover page", "discover elements", "scan page", "inspect page"],
)
def test_page_discovery_instructions_success(instruction: str):
    res = parse_instruction(instruction)
    assert res.is_valid is True
    assert res.action_data is not None
    assert res.action_data.action == "discover_page"


# =============================================================================
# 7. Ambiguity, Unsupported Actions, and Edge Cases
# =============================================================================

def test_empty_or_whitespace_instruction_fails():
    assert parse_instruction("").is_valid is False
    assert parse_instruction("   ").is_valid is False


def test_ambiguous_compound_instruction_fails():
    res = parse_instruction("click the submit button and type admin")
    assert res.is_valid is False
    assert "Ambiguous compound instruction" in (res.error or "")

    res2 = parse_instruction("navigate to https://example.com and then check text 'Welcome'")
    assert res2.is_valid is False
    assert "Ambiguous compound instruction" in (res2.error or "")


def test_unsupported_instruction_fails():
    res = parse_instruction("drink a cup of hot coffee")
    assert res.is_valid is False
    assert "Unsupported instruction" in (res.error or "")


# =============================================================================
# 8. Backward Compatibility & Structured Step Parsing (`parse_step_data`)
# =============================================================================

def test_canonical_step_preserved_without_alteration():
    """Exact canonical step rows from existing CSV uploads must remain 100% intact."""
    res = parse_step_data(action="fill", target="#username", value="admin")
    assert res.is_valid is True
    assert res.action_data.action == "fill"
    assert res.action_data.target == "#username"
    assert res.action_data.value == "admin"


def test_synonym_verb_normalized_in_structured_row():
    """If user supplies action='type' with structured target and value, normalizes to 'fill'."""
    res = parse_step_data(action="type", target="#username", value="admin")
    assert res.is_valid is True
    assert res.action_data.action == "fill"
    assert res.action_data.target == "#username"
    assert res.action_data.value == "admin"


def test_navigation_synonym_normalized_in_structured_row():
    """If user supplies action='visit' with target or value, normalizes to 'navigate'."""
    res = parse_step_data(action="visit", value="https://example.com")
    assert res.is_valid is True
    assert res.action_data.action == "navigate"
    assert res.action_data.value == "https://example.com"


def test_natural_language_sentence_in_action_column():
    """If user puts a full natural language instruction in action column with empty target/value."""
    res = parse_step_data(
        action='type "admin" into "#username"',
        target=None,
        value=None,
        expected_result=None,
    )
    assert res.is_valid is True
    assert res.action_data.action == "fill"
    assert res.action_data.target == "#username"
    assert res.action_data.value == "admin"


def test_action_verb_normalization_mapping():
    assert normalize_action_verb("navigate") == "navigate"
    assert normalize_action_verb("visit") == "navigate"
    assert normalize_action_verb("go to") == "navigate"
    assert normalize_action_verb("type") == "fill"
    assert normalize_action_verb("enter") == "fill"
    assert normalize_action_verb("click on") == "click"
    assert normalize_action_verb("tap") == "click"
    assert normalize_action_verb("verify url") == "verify_url"
    assert normalize_action_verb("check text") == "verify_text"
    assert normalize_action_verb("unknown_action") is None


# =============================================================================
# 9. Phase 6: Intelligent Instruction Understanding Tests
# =============================================================================

@pytest.mark.parametrize(
    "instruction, expected_url",
    [
        ("browse to https://example.com/search?q=test&lang=en#results", "https://example.com/search?q=test&lang=en#results"),
        ("browse 'https://subdomain.example.org:8443/app?session=123'", "https://subdomain.example.org:8443/app?session=123"),
        ("launch http://localhost:8080/dashboard", "http://localhost:8080/dashboard"),
        ("launch 'http://127.0.0.1:3000/auth?redirect=/home'", "http://127.0.0.1:3000/auth?redirect=/home"),
        ("access /settings", "/settings"),
        ("access '/api/v1/health?verbose=true'", "/api/v1/health?verbose=true"),
    ],
)
def test_phase6_navigation_paraphrases_and_complex_urls(instruction: str, expected_url: str):
    res = parse_instruction(instruction)
    assert res.is_valid is True
    assert res.action_data is not None
    assert res.action_data.action == "navigate"
    assert res.action_data.value == expected_url


def test_phase6_navigation_missing_destination():
    for text in ["browse", "browse to", "launch", "access"]:
        res = parse_instruction(text)
        assert res.is_valid is False
        assert "Missing destination URL" in (res.error or "")


@pytest.mark.parametrize(
    "instruction, expected_target, expected_value",
    [
        ('populate "#email" with "alice@example.com"', "#email", "alice@example.com"),
        ('populate the "Notes" field with "Urgent review"', "Notes", "Urgent review"),
        ('populate in "#bio" with "Test biography"', "#bio", "Test biography"),
        ('set "#username" to "admin"', "#username", "admin"),
        ('set the "Password" field to "${secret:DB_PASS}"', "Password", "${secret:DB_PASS}"),
        ('set #count to 42', "#count", "42"),
        ('put "secret123" into "#token"', "#token", "secret123"),
        ('put "John" in the username field', "username", "John"),
        ('insert "hello world" into "#editor"', "#editor", "hello world"),
        ('insert "memo" in "#notes"', "#notes", "memo"),
        ('set the option "Language" to "English"', "Language", "English"),
    ],
)
def test_phase6_text_entry_paraphrases(instruction: str, expected_target: str, expected_value: str):
    res = parse_instruction(instruction)
    assert res.is_valid is True
    assert res.action_data is not None
    assert res.action_data.action == "fill"
    assert res.action_data.target == expected_target
    assert res.action_data.value == expected_value


def test_phase6_text_entry_missing_parameters():
    # populate without value
    r1 = parse_instruction('populate "#email"')
    assert r1.is_valid is False
    assert "Missing value" in (r1.error or "")

    # set without value
    r2 = parse_instruction('set "#username"')
    assert r2.is_valid is False
    assert "Missing value" in (r2.error or "")

    # put without target
    r3 = parse_instruction('put "data"')
    assert r3.is_valid is False
    assert "Missing target" in (r3.error or "")

    # insert without value
    r4 = parse_instruction('insert into "#editor"')
    assert r4.is_valid is False
    assert "Missing value" in (r4.error or "")

    # bare verbs
    for verb in ["populate", "set", "put", "insert"]:
        r = parse_instruction(verb)
        assert r.is_valid is False


@pytest.mark.parametrize(
    "instruction, expected_target",
    [
        ('select the "Save Changes" button', "Save Changes"),
        ('select option "Express Shipping"', "Express Shipping"),
        ('select the tab "Security"', "Security"),
        ('select the menuitem "Log Out"', "Log Out"),
        ('select "#country-select"', "#country-select"),
        ('hit the "Submit" button', "Submit"),
        ('hit "#checkout-btn"', "#checkout-btn"),
        ('choose "Premium Plan"', "Premium Plan"),
        ('choose the option "Yearly"', "Yearly"),
        ('choose the tab "Billing"', "Billing"),
        ('press on "#confirm"', "#confirm"),
        ('press on the button "#agree"', "#agree"),
    ],
)
def test_phase6_clicking_paraphrases(instruction: str, expected_target: str):
    res = parse_instruction(instruction)
    assert res.is_valid is True
    assert res.action_data is not None
    assert res.action_data.action == "click"
    assert res.action_data.target == expected_target


def test_phase6_clicking_missing_targets():
    for text in ["select", "hit", "choose", "press on"]:
        res = parse_instruction(text)
        assert res.is_valid is False
        assert "Missing target" in (res.error or "")


@pytest.mark.parametrize(
    "instruction, expected_text, expected_target",
    [
        ('ensure that text "Welcome back" is visible', "Welcome back", None),
        ('ensure "Account Active" is visible', "Account Active", None),
        ('ensure that "Payment Received" appears', "Payment Received", None),
        ('confirm that text "Order #12345: Confirmed!" is visible', "Order #12345: Confirmed!", None),
        ('confirm "Bienvenue" is displayed', "Bienvenue", None),
        ('confirm that "Status: OK" is shown in "#status-card"', "Status: OK", "#status-card"),
        ('check that page displays "Willkommen, Jürgen!"', "Willkommen, Jürgen!", None),
        ('verify that page contains "Vérification réussie"', "Vérification réussie", None),
        ('ensure that the page displays "注文が完了しました"', "注文が完了しました", None),
        ('verify that the page contains "Don\'t lose your API key!"', "Don't lose your API key!", None),
        ('confirm text "Success: Saved" on "#toast"', "Success: Saved", "#toast"),
    ],
)
def test_phase6_text_verification_paraphrases_and_unicode(
    instruction: str, expected_text: str, expected_target: str
):
    res = parse_instruction(instruction)
    assert res.is_valid is True
    assert res.action_data is not None
    assert res.action_data.action == "verify_text"
    assert res.action_data.expected_result == expected_text
    assert res.action_data.target == expected_target


def test_phase6_text_verification_missing_text():
    for text in [
        "ensure that text is visible",
        "confirm text",
        "ensure that page displays",
        "verify that page contains",
        "ensure",
        "confirm",
    ]:
        res = parse_instruction(text)
        assert res.is_valid is False
        assert "Missing expected text" in (res.error or "") or "Unsupported instruction" in (res.error or "")


@pytest.mark.parametrize(
    "instruction, expected_url",
    [
        ('ensure that the url contains "/search?q=test&lang=en#results"', "/search?q=test&lang=en#results"),
        ('confirm that the current url is "https://example.com:8443/home"', "https://example.com:8443/home"),
        ('ensure url "https://example.com/checkout?step=2"', "https://example.com/checkout?step=2"),
        ('confirm url "/dashboard"', "/dashboard"),
        ('ensure that current url matches "https://example.com/portal/.*"', "https://example.com/portal/.*"),
    ],
)
def test_phase6_url_verification_paraphrases(instruction: str, expected_url: str):
    res = parse_instruction(instruction)
    assert res.is_valid is True
    assert res.action_data is not None
    assert res.action_data.action == "verify_url"
    assert res.action_data.expected_result == expected_url


def test_phase6_url_verification_missing_url():
    for text in ["ensure url", "confirm url", "ensure that current url is"]:
        res = parse_instruction(text)
        assert res.is_valid is False
        assert "Missing expected URL" in (res.error or "")


@pytest.mark.parametrize(
    "instruction",
    ["analyze page", "catalog page"],
)
def test_phase6_discovery_paraphrases(instruction: str):
    res = parse_instruction(instruction)
    assert res.is_valid is True
    assert res.action_data is not None
    assert res.action_data.action == "discover_page"


def test_phase6_compound_ambiguity_with_new_verbs():
    compound_samples = [
        "select option and type admin",
        "browse to https://example.com and confirm url is /home",
        "populate name with Alice and then hit submit",
        "set #user to test and ensure that text 'Success' is visible",
    ]
    for instruction in compound_samples:
        res = parse_instruction(instruction)
        assert res.is_valid is False
        assert "Ambiguous compound instruction" in (res.error or "")


def test_phase6_unsupported_actions_safe_rejection():
    unsupported_samples = [
        "scroll down to the footer",
        "hover over the navigation menu",
        "drag the file to the dropzone",
        "refresh the browser window",
        "zoom into the image preview",
    ]
    for instruction in unsupported_samples:
        res = parse_instruction(instruction)
        assert res.is_valid is False
        assert "Unsupported instruction" in (res.error or "")


def test_phase6_target_descriptor_cleaning():
    # Option
    r1 = parse_instruction('choose the option "Standard Delivery"')
    assert r1.action_data.target == "Standard Delivery"

    # Tab
    r2 = parse_instruction('select the tab "Notifications"')
    assert r2.action_data.target == "Notifications"

    # Menuitem
    r3 = parse_instruction('click the menuitem "Profile Settings"')
    assert r3.action_data.target == "Profile Settings"

    # Dropdown
    r4 = parse_instruction('click the dropdown "Country Selection"')
    assert r4.action_data.target == "Country Selection"

    # Selector preservation
    r5 = parse_instruction('click button[data-testid="submit"]')
    assert r5.action_data.target == 'button[data-testid="submit"]'

    r6 = parse_instruction('type "alice" into input[name="username"]')
    assert r6.action_data.target == 'input[name="username"]'


def test_phase6_structured_step_synonym_normalization():
    # 'populate' normalizes to 'fill'
    r1 = parse_step_data(action="populate", target="#notes", value="test notes")
    assert r1.is_valid is True
    assert r1.action_data.action == "fill"
    assert r1.action_data.target == "#notes"
    assert r1.action_data.value == "test notes"

    # 'browse' normalizes to 'navigate'
    r2 = parse_step_data(action="browse", value="https://example.com")
    assert r2.is_valid is True
    assert r2.action_data.action == "navigate"
    assert r2.action_data.value == "https://example.com"

    # 'select' normalizes to 'click'
    r3 = parse_step_data(action="select", target="Accept Terms")
    assert r3.is_valid is True
    assert r3.action_data.action == "click"
    assert r3.action_data.target == "Accept Terms"

