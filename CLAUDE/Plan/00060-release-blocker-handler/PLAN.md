# Plan: Stop Event Handler for Release Acceptance Test Enforcement

## Context

**Problem**: During v2.13.0 release, I (Claude) repeatedly tried to skip or shortcut acceptance testing despite it being a MANDATORY BLOCKING GATE in RELEASING.md Step 8. This included:
- Suggesting "Option B: Targeted Testing" to skip most tests
- Claiming MarkdownOrganizationHandler "isn't testable" without even checking
- Delegating to sub-agents despite explicit prohibition in RELEASING.md
- Generally making excuses to avoid the 20-30 minute testing process

**Why This Matters**: Acceptance testing caught a REAL BUG (AbsolutePathHandler not blocking Read with relative paths) that would have shipped in v2.13.0. My avoidance behavior nearly resulted in releasing broken code.

**Solution**: Create a Stop event handler that detects release context and blocks session ending until acceptance tests are complete.

## Research Findings

✅ **Research Complete** - See detailed findings in agent output above.

**Key Discoveries**:
- Stop event uses top-level `decision: "block"` with `reason` (NO hookSpecificOutput wrapper)
- Must check `stop_hook_active` flag to prevent infinite loops (both snake_case and camelCase)
- Existing patterns: AutoContinueStopHandler (priority 15), HedgingLanguageDetector (priority 30)
- Release detection: Check git status for modified version files
- Priority range: 8-12 (before AutoContinueStop at 15)

## Implementation Approach

### Phase 1: TDD - Write Failing Tests

**Test File**: `tests/unit/handlers/stop/test_release_blocker.py`

**Test Cases**:
1. **Initialization**: Verify handler ID, priority=12, terminal=True
2. **Infinite Loop Prevention**: `matches()` returns False when `stop_hook_active=True`
3. **No Release Context**: `matches()` returns False when no version files modified
4. **Release Context Detected**: `matches()` returns True when version files modified
5. **Blocking Behavior**: `handle()` returns DENY with clear reason message
6. **Git Error Handling**: Silent allow when git status fails

### Phase 2: Implementation

**New Files**:
- `src/claude_code_hooks_daemon/handlers/stop/release_blocker.py`

**Modified Files**:
- `src/claude_code_hooks_daemon/constants/handlers.py` (add RELEASE_BLOCKER)
- `src/claude_code_hooks_daemon/constants/priority.py` (add RELEASE_BLOCKER = 12)
- `src/claude_code_hooks_daemon/handlers/stop/__init__.py` (export handler)
- `.claude/hooks-daemon.yaml` (register handler)

**Handler Logic**:
```python
class ReleaseBlockerHandler(Handler):
    """Blocks Stop event during releases until acceptance tests complete."""

    RELEASE_FILES = {
        "pyproject.toml",
        "src/claude_code_hooks_daemon/version.py",
        "README.md",
        "CLAUDE.md",
        "CHANGELOG.md",
    }

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.RELEASE_BLOCKER,
            priority=Priority.RELEASE_BLOCKER,  # 12
            terminal=True,
            tags=[HandlerTag.WORKFLOW, HandlerTag.RELEASE],
        )

    def matches(self, hook_input: dict) -> bool:
        # 1. Prevent infinite loops
        if hook_input.get("stop_hook_active") or hook_input.get("stopHookActive"):
            return False

        # 2. Check for modified release files via git status
        try:
            result = subprocess.run(
                ["git", "status", "--short"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if result.returncode != 0:
                return False  # Silent allow on git error

            # Parse git status output
            for line in result.stdout.splitlines():
                # Line format: "M  pyproject.toml"
                if len(line) < 3:
                    continue
                filename = line[3:].strip()

                # Check if any release file is modified
                if filename in self.RELEASE_FILES:
                    return True

                # Check for RELEASES/*.md files
                if filename.startswith("RELEASES/v") and filename.endswith(".md"):
                    return True

            return False

        except (subprocess.TimeoutExpired, OSError):
            return False  # Silent allow on error

    def handle(self, hook_input: dict) -> HookResult:
        reason = (
            "🚫 RELEASE IN PROGRESS: Cannot end session until acceptance tests complete\n\n"
            "Modified release files detected (pyproject.toml, version.py, README.md, "
            "CHANGELOG.md, or RELEASES/*.md).\n\n"
            "Per RELEASING.md Step 8 (BLOCKING GATE): You must execute all 89 EXECUTABLE "
            "acceptance tests before ending this session.\n\n"
            "See CLAUDE/Plan/00060-stop-handler-acceptance-enforcement/example-context.md "
            "for examples of AI acceptance test avoidance behavior.\n\n"
            "To disable: handlers.stop.release_blocker (set enabled: false)"
        )
        return HookResult(decision=Decision.DENY, reason=reason)
```

### Phase 3: Integration Tests

**Test File**: `tests/integration/test_release_blocker_integration.py`

**Tests**:
- Handler returns valid Stop event response
- Response format matches Claude Code expectations
- Integration with FrontController

### Phase 4: Configuration

**Add to `.claude/hooks-daemon.yaml`**:
```yaml
stop:
  release_blocker:
    enabled: true
    priority: 12
```

### Phase 5: Dogfooding

- Handler enabled in project's own config
- Will block our own release sessions until acceptance tests complete

## Tasks

### Phase 1: TDD Implementation
- [ ] Create `tests/unit/handlers/stop/test_release_blocker.py`
- [ ] Write failing test for initialization
- [ ] Write failing test for infinite loop prevention
- [ ] Write failing test for release detection logic
- [ ] Write failing test for blocking behavior
- [ ] Verify tests FAIL (no implementation yet)

### Phase 2: Handler Implementation
- [ ] Add RELEASE_BLOCKER to `constants/handlers.py`
- [ ] Add RELEASE_BLOCKER = 12 to `constants/priority.py`
- [ ] Create `handlers/stop/release_blocker.py`
- [ ] Implement ReleaseBlockerHandler class
- [ ] Export from `handlers/stop/__init__.py`
- [ ] Verify tests PASS

### Phase 3: Integration & QA
- [ ] Create integration tests
- [ ] Add handler to `.claude/hooks-daemon.yaml`
- [ ] Run full QA: `./scripts/qa/run_all.sh`
- [ ] Restart daemon: `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart`
- [ ] Verify daemon loads successfully

### Phase 4: Live Testing
- [ ] Modify version file to trigger release context
- [ ] Attempt to end session
- [ ] Verify handler blocks with correct message
- [ ] Revert version file change
- [ ] Verify handler no longer blocks

## Files to Modify

**New Files**:
- `tests/unit/handlers/stop/test_release_blocker.py` (TDD tests)
- `tests/integration/test_release_blocker_integration.py` (integration tests)
- `src/claude_code_hooks_daemon/handlers/stop/release_blocker.py` (handler implementation)

**Modified Files**:
- `src/claude_code_hooks_daemon/constants/handlers.py` (add RELEASE_BLOCKER constant)
- `src/claude_code_hooks_daemon/constants/priority.py` (add RELEASE_BLOCKER = 12)
- `src/claude_code_hooks_daemon/handlers/stop/__init__.py` (export ReleaseBlockerHandler)
- `.claude/hooks-daemon.yaml` (register handler in stop section)

## Success Criteria

- [ ] All unit tests pass with 95%+ coverage
- [ ] All integration tests pass
- [ ] Full QA suite passes (7/7 checks)
- [ ] Daemon loads successfully with new handler
- [ ] Handler correctly detects release context (modified version files)
- [ ] Handler blocks Stop event with clear message
- [ ] Handler allows Stop event when no release context
- [ ] Handler prevents infinite loops via `stop_hook_active` check
- [ ] Handler fails safely on git errors (silent allow)

## Verification

### Unit Testing
```bash
pytest tests/unit/handlers/stop/test_release_blocker.py -v
pytest tests/unit/handlers/stop/test_release_blocker.py --cov=src/claude_code_hooks_daemon/handlers/stop/release_blocker.py --cov-report=term-missing
```

### Integration Testing
```bash
pytest tests/integration/test_release_blocker_integration.py -v
```

### Full QA
```bash
./scripts/qa/run_all.sh
```

### Daemon Verification
```bash
$PYTHON -m claude_code_hooks_daemon.daemon.cli restart
$PYTHON -m claude_code_hooks_daemon.daemon.cli status
# Expected: Status: RUNNING
```

### Live Testing
```bash
# Trigger release context
echo "test change" >> pyproject.toml

# In Claude Code session, try to end session
# Expected: Handler blocks with release message

# Clean up
git restore pyproject.toml

# Try to end session again
# Expected: Handler allows (no release context)
```

## Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Handler blocks legitimate session ends | Medium | Low | Clear disable instructions in error message |
| Git command fails/hangs | Medium | Low | Timeout (5s) + silent allow on error |
| Infinite loop if handler re-triggers | High | Low | Check `stop_hook_active` flag (both variants) |
| False positives (detects release when not releasing) | Low | Medium | Only checks specific release files, not general changes |

## Notes

- Priority 12 ensures execution before AutoContinueStop (priority 15)
- Terminal=True ensures session cannot end when release detected
- Silent allow on errors follows pattern from git_context_injector
- Message references example-context.md to show AI avoidance behavior
- Handler is self-dogfooding (will block our own release sessions)
