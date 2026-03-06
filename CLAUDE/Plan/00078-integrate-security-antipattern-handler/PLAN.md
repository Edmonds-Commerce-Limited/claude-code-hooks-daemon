# Plan 00078: Integrate SecurityAntipatternHandler

**Status**: In Progress
**Created**: 2026-03-06

## Context

A prototype `SecurityAntipatternHandler` exists in `untracked/security-antipattern-handler/security_antipattern.py`. It blocks Write/Edit operations containing hardcoded secrets (AWS keys, Stripe keys, GitHub tokens, private keys), PHP dangerous functions (eval, exec, shell_exec, etc.), and TypeScript/JS unsafe patterns (eval, new Function, dangerouslySetInnerHTML, innerHTML). OWASP A02/A03 coverage.

The prototype is well-written and follows project patterns. It needs to be properly integrated into the source tree with constants, unit tests, config registration, and daemon verification.

## Files to Create

1. **`src/claude_code_hooks_daemon/handlers/pre_tool_use/security_antipattern.py`**
   - Move from `untracked/security-antipattern-handler/security_antipattern.py`
   - No code changes needed — prototype already uses correct imports (`HandlerID`, `Priority`, `HookInputField`, `ToolName`, `get_file_path`, `get_file_content`)

2. **`tests/unit/handlers/pre_tool_use/test_security_antipattern.py`**
   - TDD-style comprehensive tests following `test_curl_pipe_shell.py` patterns
   - Init tests (name, priority, terminal, tags)
   - `matches()` positive: AWS key, Stripe key, GitHub token, private key, PHP eval/exec/shell_exec/system/passthru/proc_open/unserialize, TS eval/new Function/dangerouslySetInnerHTML/innerHTML/document.write
   - `matches()` negative: clean files, non-Write/Edit tools, skipped directories (vendor, node_modules, test fixtures, docs, CLAUDE, eslint-rules, PHPStan), empty content, no file path
   - `handle()` tests: deny decision, reason contains OWASP codes, correct issue labels
   - Edit tool support: `new_string` extraction

## Files to Modify

3. **`src/claude_code_hooks_daemon/constants/handlers.py`**
   - Add `SECURITY_ANTIPATTERN` to `HandlerID` class (in Safety handlers section, after `ERROR_HIDING_BLOCKER` ~line 213)
   - Add `"security_antipattern"` to `HandlerKey` Literal (in Safety handlers section, after `"error_hiding_blocker"`)

4. **`src/claude_code_hooks_daemon/constants/priority.py`**
   - Add `SECURITY_ANTIPATTERN = 14` to Safety handlers section (between ERROR_HIDING_BLOCKER=13 and TDD_ENFORCEMENT=15)

5. **`src/claude_code_hooks_daemon/handlers/pre_tool_use/__init__.py`**
   - Add import: `from .security_antipattern import SecurityAntipatternHandler`
   - Add to `__all__`: `"SecurityAntipatternHandler"`

6. **`.claude/hooks-daemon.yaml`**
   - Add `security_antipattern` entry under `pre_tool_use` handlers, priority 14, enabled true

## Constants Values

```python
# HandlerID
SECURITY_ANTIPATTERN = HandlerIDMeta(
    class_name="SecurityAntipatternHandler",
    config_key="security_antipattern",
    display_name="block-security-antipatterns",
)

# Priority
SECURITY_ANTIPATTERN = 14  # Safety range, after error_hiding_blocker (13)
```

## Execution Phases

### Phase 1: RED — Write Failing Tests ✅ COMPLETE
- [x] Create `tests/unit/handlers/pre_tool_use/test_security_antipattern.py` (60 tests)
- [x] Run tests — confirmed FAIL before handler in source tree

### Phase 2: GREEN — Add Constants + Move Handler ✅ COMPLETE
- [x] Add `HandlerID.SECURITY_ANTIPATTERN` constant
- [x] Add `Priority.SECURITY_ANTIPATTERN` constant
- [x] Add to `HandlerKey` Literal
- [x] Copy handler file to source tree
- [x] Register in `__init__.py`
- [x] Run tests — all 60 PASS

### Phase 3: Config + Verification ✅ COMPLETE
- [x] Register in `.claude/hooks-daemon.yaml` (priority 14)
- [x] Type check passes (mypy --strict)
- [x] Daemon restart verified — RUNNING
- [x] Checkpoint commit: `adeb96b`

### Phase 4: Source Guard CLAUDE.md Files ✅ COMPLETE
- [x] Create `src/CLAUDE.md` — warns project agents not to edit daemon source
- [x] Create `tests/CLAUDE.md` — warns project agents not to edit daemon tests
- [x] Both files link to project-level handlers guide and bug reporting guide

### Phase 5: Strategy Pattern Refactoring (FUTURE)

**Status**: Not Started — separate plan recommended

The current handler uses `if _is_php_file()` / `if _is_ts_or_js_file()` chains, which violates the project's Strategy Pattern principle (CLAUDE.md: "If you see an if/elif chain on type/language names, use Strategy Pattern instead").

**Proposed approach**:
- Define a `SecurityStrategy` Protocol with `file_extensions`, `patterns`, and `owasp_category`
- Create per-language strategy implementations:
  - `PhpSecurityStrategy` — eval, exec, shell_exec, system, passthru, proc_open, unserialize
  - `TypeScriptSecurityStrategy` — eval, new Function, dangerouslySetInnerHTML, innerHTML, document.write
  - `SecretDetectionStrategy` — AWS keys, Stripe keys, GitHub tokens, private keys (all file types)
- Registry maps file extensions to active strategies
- Config-driven: project's `hooks-daemon.yaml` can specify which languages are active
- Allows projects to enable only relevant language strategies (e.g. PHP-only project skips TS checks)

**Benefits**:
- New language support by adding new strategy, not modifying handler
- Project-specific language configuration
- Independent TDD per strategy
- Follows SOLID/Open-Closed principle

**This should be a separate plan** (00079 or similar) since it's a non-trivial refactoring effort.

## Verification

```bash
# Unit tests
pytest tests/unit/handlers/pre_tool_use/test_security_antipattern.py -v

# Full QA
./scripts/qa/llm_qa.py all

# Daemon load
$PYTHON -m claude_code_hooks_daemon.daemon.cli restart
$PYTHON -m claude_code_hooks_daemon.daemon.cli status
```
