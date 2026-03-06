# Plan: Integrate SecurityAntipatternHandler

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

### Phase 1: RED — Write Failing Tests
- Create `tests/unit/handlers/pre_tool_use/test_security_antipattern.py`
- Run tests — must FAIL (handler not in source tree yet)

### Phase 2: GREEN — Add Constants + Move Handler
- Add `HandlerID.SECURITY_ANTIPATTERN` constant
- Add `Priority.SECURITY_ANTIPATTERN` constant
- Add to `HandlerKey` Literal
- Copy handler file to source tree
- Register in `__init__.py`
- Run tests — must PASS

### Phase 3: Config + Verification
- Register in `.claude/hooks-daemon.yaml`
- Run `./scripts/qa/run_all.sh` — all checks must pass
- Restart daemon and verify RUNNING
- Checkpoint commit

## Verification

```bash
# Unit tests
pytest tests/unit/handlers/pre_tool_use/test_security_antipattern.py -v

# Full QA
./scripts/qa/run_all.sh

# Daemon load
$PYTHON -m claude_code_hooks_daemon.daemon.cli restart
$PYTHON -m claude_code_hooks_daemon.daemon.cli status
```
