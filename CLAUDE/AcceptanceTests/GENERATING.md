# Acceptance Testing - Playbook Generation

**Version**: 2.0 (Programmatic)
**Date**: 2026-02-03
**Purpose**: Generate ephemeral acceptance test playbooks from handler code

---

## 🎯 WHAT THIS IS

**Acceptance tests are now defined programmatically in handler code.**

Every handler implements `get_acceptance_tests()` which returns structured test definitions. The playbook is NEVER stored - it's generated fresh from code when needed.

### Why Programmatic?

**OLD WAY** (Manual PLAYBOOK.md):
- ❌ Tests hardcoded in markdown
- ❌ Must manually sync with handler changes
- ❌ No type safety
- ❌ Can become stale
- ❌ Duplication between code and docs

**NEW WAY** (Programmatic):
- ✅ Tests defined in handler code
- ✅ Single source of truth
- ✅ Type-safe (AcceptanceTest dataclass)
- ✅ Always reflects current handlers
- ✅ Config-aware (only enabled handlers)
- ✅ Includes custom plugin handlers

---

## 📋 GENERATING THE PLAYBOOK

### Basic Generation

```bash
# Generate playbook to stdout (markdown format)
python -m claude_code_hooks_daemon.daemon.cli generate-playbook

# Save to temporary file for testing
python -m claude_code_hooks_daemon.daemon.cli generate-playbook > /tmp/playbook.md

# Test, then DELETE (ephemeral)
rm /tmp/playbook.md
```

### Advanced Options

```bash
# Include disabled handlers (for documentation)
generate-playbook --include-disabled

# Different output formats
generate-playbook --format markdown  # Default
generate-playbook --format json      # For automation
generate-playbook --format yaml      # For pipelines

# Filter by handler
generate-playbook | grep "DestructiveGit"

# Count tests
generate-playbook | grep "### Test" | wc -l
```

---

## ⚠️ CRITICAL: EPHEMERAL PLAYBOOKS

**NEVER commit generated playbook files to git.**

Playbooks are EPHEMERAL:
1. Generate fresh before testing
2. Use for manual testing
3. Delete after testing
4. Regenerate next time

**Why?**
- Code is source of truth
- Generated playbooks can become stale
- Defeats single source of truth principle

**Workflow**:
```bash
# Generate for testing
generate-playbook > /tmp/test-playbook.md

# Execute tests manually
# ... test each scenario ...

# Done testing - DELETE
rm /tmp/test-playbook.md
```

---

## 🐛 FAIL-FAST Principle

**ANY code change during acceptance testing = Complete the full cycle:**

```
Acceptance Testing → Find Bug → Fix with TDD → Run QA → Restart FROM TEST 1.1
```

**Process**:
1. Generate fresh playbook
2. Find failing test during acceptance testing
3. **STOP acceptance testing immediately**
4. Fix bug using TDD (write failing test, implement fix, verify)
5. Run FULL QA: `./scripts/qa/run_all.sh` (must pass 100%)
6. Restart daemon: `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart`
7. **Regenerate playbook** (to reflect fix)
8. **RESTART acceptance testing FROM TEST 1.1** (not from where you left off)
9. Continue until ALL tests pass with ZERO code changes

**Why restart from Test 1.1?**
Your fix might have affected earlier tests. Full re-run ensures no regressions.

---

## ⚠️ CRITICAL SAFETY WARNING

**NEVER RUN DESTRUCTIVE COMMANDS DIRECTLY**

All acceptance tests use **triple-layer safety**:

### Layer 1: Use `echo` (MANDATORY)
✅ **CORRECT**: `echo "git reset --hard NONEXISTENT_REF"`
❌ **NEVER DO**: `git reset --hard NONEXISTENT_REF`

### Layer 2: Hooks Block Commands
The daemon hooks will intercept and block destructive commands.

### Layer 3: Fail-Safe Arguments
All destructive commands use non-existent refs/paths/files that would fail harmlessly if somehow executed:
- `git reset --hard NONEXISTENT_REF_SAFE_TEST` - non-existent git ref
- `git clean -fd /nonexistent/safe/test/path` - non-existent directory
- `sed -i 's/foo/bar/' /nonexistent/safe/test.txt` - non-existent file

**Why All Three Layers?**
- Layer 1 (echo): Zero risk even if hooks completely fail
- Layer 2 (hooks): Tests the actual blocking behavior
- Layer 3 (fail-safe args): Defense-in-depth - even catastrophic failure is harmless

**Even with these protections, ALWAYS use echo for destructive commands.**

---

## 🔧 BEFORE TESTING

### 1. Restart Daemon
```bash
$PYTHON -m claude_code_hooks_daemon.daemon.cli restart
# Should show: Daemon started successfully
```

### 2. Verify Daemon Running
```bash
$PYTHON -m claude_code_hooks_daemon.daemon.cli status
# Should show: Status: RUNNING
```

### 3. Git Working Tree Clean
```bash
git status
# Should show: nothing to commit, working tree clean
```

### 4. Generate Fresh Playbook
```bash
generate-playbook > /tmp/playbook.md
# Open /tmp/playbook.md for testing
```

---

## 📝 EXECUTING TESTS

### Test Format

Generated playbooks contain tests in this format:

```markdown
## Test N: HandlerName

**Handler ID**: handler-id
**Event**: PreToolUse
**Priority**: XX
**Type**: Blocking (terminal=true)

### Test N.1: Description

**Command**: echo "command to test"
**Expected**: BLOCKED with message about X
**Result**: [ ] PASS [ ] FAIL
**Safety**: Uses non-existent ref - harmless if executed
```

### Marking Results

- Execute each test command
- Mark [ ] PASS if behavior matches expected
- Mark [ ] FAIL if behavior doesn't match
- Document any failures

### For Blocking Handlers
✅ **PASS** = Command BLOCKED with appropriate error message
❌ **FAIL** = Command executed (protection failed!)

### For Advisory Handlers
✅ **PASS** = Command ALLOWED with advisory context shown
❌ **FAIL** = Command blocked OR no advisory shown

---

## 🔍 HANDLER TEST DEFINITIONS

### Where Tests Are Defined

Every handler defines its tests in code:

```python
# Example: src/claude_code_hooks_daemon/handlers/pre_tool_use/destructive_git.py
def get_acceptance_tests(self) -> list[AcceptanceTest]:
    """Acceptance tests for destructive git handler."""
    return [
        AcceptanceTest(
            title="git reset --hard",
            command='echo "git reset --hard NONEXISTENT_REF"',
            description="Blocks destructive git reset",
            expected_decision=Decision.DENY,
            expected_message_patterns=[
                r"destroys.*uncommitted changes",
                r"permanently"
            ],
            safety_notes="Uses non-existent ref - harmless if executed",
            test_type=TestType.BLOCKING
        ),
        # ... more tests
    ]
```

### AcceptanceTest Fields

- **title**: Short test name
- **command**: Command to execute (use echo for destructive ones)
- **description**: What this tests
- **expected_decision**: DENY, ALLOW, or ASK
- **expected_message_patterns**: Regex patterns to match in output
- **safety_notes**: Why this test is safe to run
- **test_type**: BLOCKING, ADVISORY, or CONTEXT
- **setup_commands**: Optional setup steps
- **cleanup_commands**: Optional cleanup steps

---

## 🔌 PLUGIN HANDLERS

**Custom project-level plugins are automatically included!**

### Verifying Plugin Tests

```bash
# Generate playbook and check for your plugin
generate-playbook | grep "MyCustomHandler"

# Count plugin tests
generate-playbook | grep "Plugin:" | wc -l
```

### Plugin Test Requirements

All plugin handlers MUST implement `get_acceptance_tests()`:

```python
class MyCustomHandler(Handler):
    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        """REQUIRED - at least 1 test."""
        return [
            AcceptanceTest(
                title="my custom behavior",
                command="echo 'test command'",
                description="Tests custom handler behavior",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"blocked"],
                test_type=TestType.BLOCKING
            )
        ]
```

**Empty arrays are REJECTED** - every handler must have tests.

---

## 📊 AFTER TESTING

### Cleanup

```bash
# Delete ephemeral playbook
rm /tmp/playbook.md

# Remove any test files created
rm -rf /tmp/test-handlers /tmp/docs /tmp/test.*
```

### If Tests Passed

All tests passed with ZERO code changes:
1. Document test completion
2. Note any observations
3. Ready for release

### If Tests Failed

Any test failed OR code was changed:
1. **STOP** - Do not continue testing
2. Fix bug using TDD
3. Run full QA
4. Restart daemon
5. **Regenerate playbook** (code changed!)
6. **RESTART from Test 1.1**

---

## 🎓 FOR DEVELOPERS

### Adding New Handlers

When creating new handlers:

1. **Write tests FIRST** (TDD)
2. Implement `get_acceptance_tests()` method
3. Return at least 1 `AcceptanceTest` object
4. Generate playbook to verify tests appear
5. Execute tests manually

### Updating Handlers

When modifying handler behavior:

1. Update `get_acceptance_tests()` if needed
2. Regenerate playbook (fresh from code)
3. Execute full playbook
4. Verify all tests still pass

### Test Coverage

```bash
# Count total tests
generate-playbook | grep "### Test" | wc -l

# List all handlers with tests
generate-playbook | grep "## Test" | cut -d: -f2
```

---

## 📚 RELATED DOCUMENTATION

- **Handler Development**: `CLAUDE/HANDLER_DEVELOPMENT.md`
- **Plugin Development**: `CLAUDE/Plugin/ACCEPTANCE_TESTING.md`
- **Plan 00025**: `CLAUDE/Plan/00025-programmatic-acceptance-tests/PLAN.md`
- **Release Process**: `CLAUDE/development/RELEASING.md`

---

## 💡 KEY TAKEAWAYS

1. **Playbook is generated from code** - never manually edited
2. **Always ephemeral** - generate, test, delete
3. **Single source of truth** - handler code defines tests
4. **Config-aware** - only enabled handlers included
5. **Plugin support** - custom handlers automatically included
6. **Type-safe** - AcceptanceTest dataclass validates structure
7. **FAIL-FAST** - any bug found = fix with TDD, restart from Test 1.1

**The playbook is code output, not documentation.**
