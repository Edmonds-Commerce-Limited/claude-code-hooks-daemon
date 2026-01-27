# QA Patterns & Solutions

**Purpose:** Living document of QA issue patterns and their proper fixes. Maintained by the qa-fixer agent.

**Philosophy:** Best practice fixes ONLY. No suppressions, no shortcuts.

---

## Format Issues (Black)

### Long Lines in String Literals

**Symptom:**
```
error: Line exceeds 100 characters
```

**Root Cause:**
Long strings (URLs, messages, paths) exceed line limit.

**Fix:**
```python
# ❌ WRONG - Line too long
message = "This is a very long error message that explains what went wrong and how to fix it"

# ✅ RIGHT - Use parentheses for implicit concatenation
message = (
    "This is a very long error message that explains what went wrong "
    "and how to fix it"
)

# ✅ ALSO RIGHT - Use textwrap.dedent for multiline
message = textwrap.dedent("""
    This is a very long error message that explains
    what went wrong and how to fix it
""").strip()
```

**Notes:**
- Parentheses allow string continuation without backslashes
- String literals next to each other are concatenated automatically

---

## Lint Issues (Ruff)

### F401: Unused Import

**Symptom:**
```
F401 `module.thing` imported but unused
```

**Root Cause:**
Import was added but never used, or usage was removed.

**Fix:**
```python
# ❌ WRONG - Unused import
from typing import Dict, List, Optional  # Only using Dict

# ✅ RIGHT - Only import what's used
from typing import Dict
```

**Notes:**
- If import is for re-export, use `__all__` to make it explicit
- If import is for type checking only, use `TYPE_CHECKING` block

### F841: Unused Variable

**Symptom:**
```
F841 Local variable `x` is assigned but never used
```

**Root Cause:**
Variable assigned but not used. Often from copy-paste or incomplete refactoring.

**Fix:**
```python
# ❌ WRONG - Unused variable
result = expensive_operation()
return True

# ✅ RIGHT - Use the variable or remove assignment
result = expensive_operation()
return result.success

# ✅ OR - Use underscore for intentionally ignored
_, important_value = get_pair()
```

**Notes:**
- Single underscore `_` is convention for intentionally ignored values
- If you need the side effect but not the value, consider if function should be void

### E711/E712: Comparison to None/True/False

**Symptom:**
```
E711 Comparison to `None` should be `is None`
E712 Comparison to `True` should be `if x:`
```

**Root Cause:**
Using `==` instead of `is` for singleton comparisons.

**Fix:**
```python
# ❌ WRONG
if result == None:
if flag == True:
if enabled == False:

# ✅ RIGHT
if result is None:
if flag:  # or `if flag is True:` for explicit boolean check
if not enabled:  # or `if enabled is False:` for explicit
```

**Notes:**
- Use `is` for None, True, False (they're singletons)
- Use `==` for value comparison

---

## Type Errors (MyPy)

### Missing Return Type

**Symptom:**
```
error: Function is missing a return type annotation
```

**Root Cause:**
Function defined without return type.

**Fix:**
```python
# ❌ WRONG
def process(data):
    return data.upper()

# ✅ RIGHT
def process(data: str) -> str:
    return data.upper()
```

### Incompatible Types in Assignment

**Symptom:**
```
error: Incompatible types in assignment (expression has type "X", variable has type "Y")
```

**Root Cause:**
Type mismatch between declared type and assigned value.

**Fix:**
```python
# ❌ WRONG - Type mismatch
def get_count() -> int:
    return "5"  # Returns str, not int

# ✅ RIGHT - Fix return value
def get_count() -> int:
    return 5

# ✅ OR - Fix return type
def get_count() -> str:
    return "5"
```

### Optional Type Not Handled

**Symptom:**
```
error: Item "None" of "Optional[X]" has no attribute "y"
```

**Root Cause:**
Accessing attribute on value that might be None.

**Fix:**
```python
# ❌ WRONG - Doesn't handle None
def get_name(user: User | None) -> str:
    return user.name  # user might be None!

# ✅ RIGHT - Handle None explicitly
def get_name(user: User | None) -> str:
    if user is None:
        return "Anonymous"
    return user.name

# ✅ OR - Raise exception
def get_name(user: User | None) -> str:
    if user is None:
        raise ValueError("User required")
    return user.name
```

### Dict Key Access Type Error

**Symptom:**
```
error: TypedDict "X" has no key "y"
```

**Root Cause:**
Accessing key that's not in TypedDict definition.

**Fix:**
```python
# ❌ WRONG - Key not in TypedDict
class Config(TypedDict):
    name: str

def process(config: Config) -> None:
    print(config["value"])  # "value" not in Config

# ✅ RIGHT - Add key to TypedDict
class Config(TypedDict):
    name: str
    value: str  # Add the key

# ✅ OR - Use dict[str, Any] if truly dynamic
def process(config: dict[str, Any]) -> None:
    print(config.get("value", "default"))
```

---

## Test Failures (Pytest)

### Fixture Not Found

**Symptom:**
```
fixture 'my_fixture' not found
```

**Root Cause:**
Fixture not defined in scope or conftest.py.

**Fix:**
```python
# ❌ WRONG - Fixture in wrong scope
# tests/unit/test_foo.py
def my_fixture():  # Not decorated
    return 42

# ✅ RIGHT - Proper fixture
@pytest.fixture
def my_fixture():
    return 42

# ✅ OR - Put in conftest.py for shared fixtures
# tests/conftest.py
@pytest.fixture
def my_fixture():
    return 42
```

### Mock Not Applied Correctly

**Symptom:**
Test passes but doesn't actually test anything, or mock isn't called.

**Root Cause:**
Patching wrong path or mock not configured correctly.

**Fix:**
```python
# ❌ WRONG - Patching where defined, not where used
# Module: myapp.service (imports from myapp.utils)
@patch("myapp.utils.helper")  # Patches definition
def test_service():
    ...

# ✅ RIGHT - Patch where it's used
@patch("myapp.service.helper")  # Patches usage
def test_service():
    ...
```

**Notes:**
- Patch the name as it's used in the module under test
- Not where it's defined

### Assertion Never Reached

**Symptom:**
Test passes but assertion is never executed.

**Root Cause:**
Return/exception before assertion, or wrong test structure.

**Fix:**
```python
# ❌ WRONG - Assertion after return
def test_something():
    result = do_thing()
    if result:
        return  # Exits before assertion!
    assert result is False

# ✅ RIGHT - Proper assertion structure
def test_something():
    result = do_thing()
    assert result is True  # Or False, depending on expected
```

---

## Coverage Issues

### Uncovered Branch

**Symptom:**
```
Missing branch coverage for line X
```

**Root Cause:**
If/else or try/except not fully tested.

**Fix:**
```python
# Code under test
def process(value: int) -> str:
    if value > 0:
        return "positive"
    else:
        return "non-positive"  # Need test for this branch

# ✅ Add test for missing branch
def test_process_non_positive():
    assert process(0) == "non-positive"
    assert process(-1) == "non-positive"
```

### Uncovered Exception Handler

**Symptom:**
Except block shows as uncovered.

**Root Cause:**
Tests don't trigger the exception path.

**Fix:**
```python
# Code under test
def load_file(path: Path) -> str:
    try:
        return path.read_text()
    except FileNotFoundError:
        return ""  # Uncovered

# ✅ Add test that triggers exception
def test_load_file_not_found(tmp_path):
    missing = tmp_path / "does_not_exist.txt"
    assert load_file(missing) == ""
```

---

## Security Issues (Bandit)

### B101: Assert Used

**Symptom:**
```
B101: Use of assert detected
```

**Root Cause:**
Assert statements are removed in optimized mode (-O flag).

**Fix:**
```python
# ❌ WRONG - Assert in production code
def process(data: dict) -> None:
    assert "key" in data
    ...

# ✅ RIGHT - Explicit validation
def process(data: dict) -> None:
    if "key" not in data:
        raise ValueError("Missing required key")
    ...
```

**Notes:**
- Asserts are for debugging and tests only
- Use explicit validation in production code

### B602: subprocess with shell=True

**Symptom:**
```
B602: subprocess call with shell=True is identified
```

**Root Cause:**
Shell injection vulnerability when using shell=True with user input.

**Fix:**
```python
# ❌ WRONG - Shell injection risk
subprocess.run(f"ls {user_input}", shell=True)

# ✅ RIGHT - Use list of args without shell
subprocess.run(["ls", user_input], shell=False)

# ✅ OR - Use shlex for complex cases
import shlex
subprocess.run(shlex.split(command), shell=False)
```

---

## Project-Specific Patterns

### Handler Priority Conflicts

**Symptom:**
Two handlers with same priority cause non-deterministic ordering.

**Root Cause:**
Handlers should have unique priorities within their category.

**Fix:**
```python
# ❌ WRONG - Duplicate priorities
class HandlerA(Handler):
    def __init__(self):
        super().__init__(priority=50)

class HandlerB(Handler):
    def __init__(self):
        super().__init__(priority=50)  # Conflict!

# ✅ RIGHT - Unique priorities
class HandlerA(Handler):
    def __init__(self):
        super().__init__(priority=50)

class HandlerB(Handler):
    def __init__(self):
        super().__init__(priority=51)
```

**Priority Ranges:**
- 5: Test handlers
- 10-20: Safety handlers
- 25-35: Code quality
- 36-55: Workflow
- 56-60: Advisory

### HookResult Schema Validation

**Symptom:**
```
ValidationError: Invalid HookResult
```

**Root Cause:**
HookResult fields don't match expected schema.

**Fix:**
```python
# ❌ WRONG - Invalid decision value
return HookResult(decision="block")  # "block" not valid

# ✅ RIGHT - Valid decision values
return HookResult(decision="deny")   # or "allow"
```

**Valid HookResult fields:**
- `decision`: "allow" | "deny"
- `reason`: str (optional but recommended for deny)

---

## Maintenance Notes

**Last Updated:** 2026-01-27

**Adding New Patterns:**
1. Encounter a QA issue during development
2. Research the proper fix (not suppression)
3. Document symptom, root cause, and fix
4. Include code examples
5. Add to appropriate category

**Review Schedule:**
- Update when encountering new patterns
- Review and prune quarterly
- Remove patterns no longer relevant
