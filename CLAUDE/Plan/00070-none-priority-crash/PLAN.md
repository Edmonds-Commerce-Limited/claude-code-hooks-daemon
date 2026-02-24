# Plan 00070: Fix NoneType Priority Comparison Crash

**Status**: Not Started
**Created**: 2026-02-24
**Owner**: Claude
**Priority**: High
**Type**: Bug Fix
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

The daemon crashes with `TypeError: '<' not supported between instances of 'NoneType' and 'int'` when a handler ends up with `priority=None`. This happens when a YAML config has `priority:` with no value (parsed as `None` by PyYAML), which bypasses the type validator and gets assigned to `instance.priority` in the registry. The chain sort then crashes comparing `None < int`.

The fix is multi-layered defence:
1. **Validator** — reject `priority: null` at config validation time (fail fast)
2. **Registry** — skip priority override when config value is `None` (defensive)
3. **Chain** — use a sane default if priority is somehow `None` at sort time (last resort)

The user also wants a **sane default for project-level handlers** that don't specify a priority.

## Bug Report

See [BUG_REPORT.md](BUG_REPORT.md) in this directory for the original external report.

## Root Cause Analysis

Three code paths can lead to `None` priority:

### Path 1: YAML `priority:` with no value (PRIMARY)
```yaml
my_handler:
  enabled: true
  priority:        # PyYAML parses this as None
```
- `handler_config` = `{"enabled": True, "priority": None}`
- Registry line 307: `ConfigKey.PRIORITY in handler_config` → `True`
- Registry line 308: `instance.priority = None`
- Chain sort crashes: `(None, "name") < (10, "other")` → TypeError

### Path 2: Validator gap
- Validator line 417: `not isinstance(priority, int)` catches `None`... but only if validation runs
- Config validation is fail-open (degraded mode) — daemon can start with invalid config
- Even when validation runs, errors are collected but daemon may still load handlers

### Path 3: Project handlers with explicit None
```python
class MyHandler(Handler):
    def __init__(self):
        super().__init__(handler_id="my-handler", priority=None)  # type: ignore
```
- Project handler loader calls `handler_class()` and trusts the result
- No post-instantiation priority validation

## Goals

- Fix the crash so the daemon never fails on `None` priority
- Provide a sane default (50) when priority is not explicitly set
- Catch `priority: null` at config validation time with a clear error
- Add defensive checks at all layers (defence in depth)
- Maintain 95%+ test coverage

## Non-Goals

- Changing the priority system design
- Making priority a required config field (would break existing configs that omit it)
- Changing project handler loading to support config-based priority override

## Tasks

### Phase 1: TDD — Failing Tests

- [ ] **Task 1.1**: Write failing test for validator — `priority: None` in config should produce validation error
- [ ] **Task 1.2**: Write failing test for registry — `priority: None` in config should NOT override handler default
- [ ] **Task 1.3**: Write failing test for chain sort — handler with `None` priority should use default (50) and log warning
- [ ] **Task 1.4**: Write failing test for project handler loader — handler with `None` priority gets default applied
- [ ] **Task 1.5**: Run tests, verify all 4 FAIL (proves bug exists)

### Phase 2: Fix Implementation

- [ ] **Task 2.1**: Fix validator — add explicit `None` check for priority field
  - In `_validate_handlers()`, when `priority` key exists but value is `None`, emit error:
    `"Field '{handler_path}.priority' must be integer, got NoneType (hint: remove the line or set a value)"`
  - The existing `not isinstance(priority, int)` already catches this since `None` is not `int`, but the error message should be more helpful
- [ ] **Task 2.2**: Fix registry — skip priority override when value is `None`
  - Change line 307-308 to: `if ConfigKey.PRIORITY in handler_config and handler_config[ConfigKey.PRIORITY] is not None:`
- [ ] **Task 2.3**: Fix chain sort — defensive fallback for `None` priority
  - In `HandlerChain.handlers` property, add pre-sort validation
  - If any handler has `priority is None`, set to default (50) and log warning
  - Use named constant for the default (e.g., `Priority.DEFAULT` or the existing `Handler.__init__` default)
- [ ] **Task 2.4**: Fix project handler loader — validate priority post-instantiation
  - After `handler = handler_class()`, check `handler.priority is not None`
  - If `None`, set to default and log warning
- [ ] **Task 2.5**: Run failing tests from Phase 1, verify all PASS

### Phase 3: Verification

- [ ] **Task 3.1**: Run full QA: `./scripts/qa/run_all.sh`
- [ ] **Task 3.2**: Restart daemon: `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart`
- [ ] **Task 3.3**: Verify daemon status: `$PYTHON -m claude_code_hooks_daemon.daemon.cli status` (RUNNING)
- [ ] **Task 3.4**: Commit with plan reference

## Technical Decisions

### Decision 1: Default priority value
**Context**: What default should be used when priority is None?
**Options**:
1. 50 (middle of range, matches Handler.__init__ default)
2. 100 (end of range, least disruptive)

**Decision**: 50 — matches the existing Handler base class default. A handler that doesn't specify priority should behave as if it used the base class default.

### Decision 2: Strict vs lenient on None priority
**Context**: Should `priority: null` in config be a hard error or a warning?
**Options**:
1. Hard validation error (fail fast, daemon enters degraded mode)
2. Warning with default applied (daemon starts normally)

**Decision**: Both — validator reports it as an error (fail fast at validation), but registry and chain also handle it defensively (belt and suspenders). This way, if validation is skipped or fails open, the daemon still works.

## Success Criteria

- [ ] `priority: null` in YAML config produces validation error
- [ ] Registry skips override when config priority is None
- [ ] Chain sort handles None priority gracefully (default 50, warning logged)
- [ ] Project handler with None priority gets default applied
- [ ] All existing tests pass (no regressions)
- [ ] 95%+ coverage maintained
- [ ] Daemon restarts successfully
- [ ] All QA checks pass

## Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Existing configs rely on None priority | Low | Very Low | None priority was always a crash, so no one depends on it |
| Default 50 conflicts with existing handler | Low | Low | Chain sorts ties alphabetically, deterministic |
