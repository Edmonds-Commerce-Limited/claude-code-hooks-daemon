# Plan 050: Display Config Key in Handler Block/Deny Output

**Status**: Complete (2026-02-12)
**Created**: 2026-02-12
**Owner**: Claude Sonnet 4.5
**Priority**: Medium

## Overview

When a handler blocks a command, the user currently has no easy way to identify which configuration key controls that handler. This means disabling a handler requires searching documentation or source code.

Inspired by PHPStan's approach (which provides a two-level namespaced rule identifier with every error so you can easily add it to your ignore list), every handler's DENY/ASK output should include its full configuration path so users can immediately know how to disable it.

**Example - Current output:**
```
BLOCKED: git reset --hard destroys all uncommitted changes permanently
```

**Example - Proposed output:**
```
BLOCKED: git reset --hard destroys all uncommitted changes permanently

To disable: handlers.pre_tool_use.destructive_git  (set enabled: false)
```

This is the same UX pattern as:
- PHPStan: `phpstan-ignore phpstan.rules.missingReturnType`
- ESLint: `// eslint-disable-next-line no-unused-vars`
- Ruff: `# noqa: E501`

## Goals

- Every handler DENY/ASK response includes its fully-qualified config key
- Config key format: `handlers.{event_type}.{config_key}` (two-level namespaced)
- Implementation at the FrontController level (not repeated in every handler)
- Zero changes required to individual handler `handle()` methods
- Users can copy the key directly into their YAML config to disable

## Non-Goals

- Adding inline suppression comments (like `// eslint-disable-next-line`)
- Auto-disabling handlers based on user response
- Changing the config format itself
- Modifying ALLOW responses (only DENY/ASK need the config key)

## Context & Background

### What Already Exists

Every handler already has:
- `self.config_key` - The snake_case config key (e.g., `destructive_git`)
- `self.handler_id` - HandlerIDMeta with `config_key` attribute

The config YAML is structured as:
```yaml
handlers:
  pre_tool_use:
    destructive_git:    # <-- this is config_key
      enabled: true
      priority: 10
```

So the fully-qualified path is: `handlers.{event_type}.{config_key}`

### What's Missing

1. Handlers don't know their event type at runtime (it's determined by which directory they're in and which config section they're registered under)
2. The config key is not appended to DENY/ASK reason messages
3. There's no standard format for displaying the config key

### The PHPStan Model

PHPStan displays rule identifiers alongside every error:
```
Line   file.php
 12    Parameter $foo has no type declaration.
       phpstan: missingType.parameter
```

Users can then add to their config:
```neon
parameters:
    ignoreErrors:
        - identifier: missingType.parameter
```

We want the same instant-copy UX.

## Technical Design

### Approach: Inject Config Path in FrontController Dispatch

The cleanest approach is to append the config key at the **FrontController level** after the handler returns its result, not inside each handler. This is because:

1. **The FrontController knows the event type** (it dispatches by event type)
2. **Handlers don't need to change** (zero modifications to 26+ handler files)
3. **Single point of implementation** (DRY - one place to maintain)
4. **Consistent formatting** (all handlers get the same format)

### Where to Inject

In the FrontController's dispatch loop, after a handler returns a DENY/ASK result, append the config path to the reason string:

```python
# In FrontController dispatch (pseudocode)
result = handler.handle(hook_input)
if result.decision in (Decision.DENY, Decision.ASK):
    config_path = f"handlers.{event_type}.{handler.config_key}"
    result.reason += f"\n\nTo disable: {config_path}  (set enabled: false)"
```

### Config Path Format

```
handlers.{event_type}.{config_key}
```

Examples:
- `handlers.pre_tool_use.destructive_git`
- `handlers.pre_tool_use.sed_blocker`
- `handlers.pre_tool_use.npm_command`
- `handlers.post_tool_use.validate_eslint_on_write`
- `handlers.session_start.yolo_container_detection`

### Output Format

Append a footer line to the reason string:

```
[existing handler reason message]

To disable: handlers.pre_tool_use.destructive_git  (set enabled: false)
```

This is:
- Visually separated from the main message (blank line)
- Copy-pasteable (the dotted path maps directly to YAML nesting)
- Self-explanatory (tells user what to do)
- Consistent across all handlers

## Tasks

### Phase 1: Research & Design

- [ ] ⬜ **Identify injection point**
  - [ ] ⬜ Read FrontController dispatch logic
  - [ ] ⬜ Identify where handler results are processed
  - [ ] ⬜ Confirm event_type is available at that point
  - [ ] ⬜ Verify config_key is accessible from handler instance

- [ ] ⬜ **Verify event type mapping**
  - [ ] ⬜ Confirm event type names match YAML section names (pre_tool_use, post_tool_use, etc.)
  - [ ] ⬜ Handle any naming mismatches (e.g., camelCase vs snake_case)

### Phase 2: TDD Implementation

- [ ] ⬜ **Write failing tests for config key injection**
  - [ ] ⬜ Test: DENY result includes config path in reason
  - [ ] ⬜ Test: ASK result includes config path in reason
  - [ ] ⬜ Test: ALLOW result does NOT include config path
  - [ ] ⬜ Test: Config path format is `handlers.{event_type}.{config_key}`
  - [ ] ⬜ Test: Works for pre_tool_use handlers
  - [ ] ⬜ Test: Works for post_tool_use handlers
  - [ ] ⬜ Test: Works for other event types (session_start, stop, etc.)
  - [ ] ⬜ Test: Reason is None edge case (DENY without reason)

- [ ] ⬜ **Implement injection in FrontController**
  - [ ] ⬜ Add config path append after handler returns DENY/ASK
  - [ ] ⬜ Use consistent format string
  - [ ] ⬜ Handle edge case where reason is None
  - [ ] ⬜ Ensure formatting doesn't break JSON serialisation

- [ ] ⬜ **Verify all existing tests still pass**
  - [ ] ⬜ Update any tests that assert exact reason strings
  - [ ] ⬜ Ensure acceptance test patterns still match (they use regex)

### Phase 3: Integration & Testing

- [ ] ⬜ **Integration tests**
  - [ ] ⬜ Test full dispatch flow with real handler returning DENY
  - [ ] ⬜ Verify config path appears in final JSON output
  - [ ] ⬜ Test with progressive verbosity handlers (terse/standard/verbose all get footer)

- [ ] ⬜ **Verify no regressions**
  - [ ] ⬜ Run full test suite
  - [ ] ⬜ Ensure 95%+ coverage maintained

### Phase 4: QA & Verification

- [ ] ⬜ **Run full QA suite**
  - [ ] ⬜ Run: `./scripts/qa/run_all.sh`
  - [ ] ⬜ Fix any QA issues
  - [ ] ⬜ Verify all checks pass

- [ ] ⬜ **Daemon verification**
  - [ ] ⬜ Restart daemon: `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart`
  - [ ] ⬜ Verify status: `$PYTHON -m claude_code_hooks_daemon.daemon.cli status`
  - [ ] ⬜ Check logs for errors

- [ ] ⬜ **Live testing**
  - [ ] ⬜ Trigger a blocking handler (e.g., destructive git)
  - [ ] ⬜ Verify config path appears in error output
  - [ ] ⬜ Verify path is correct and maps to actual YAML config
  - [ ] ⬜ Verify ALLOW responses are unchanged

## Dependencies

- None (standalone enhancement)

## Technical Decisions

### Decision 1: Injection Point - FrontController (Not Handler)

**Context**: Where should the config key be appended to the reason?

**Options Considered**:
1. **Each handler appends it** - Modify all 26+ handlers to include config key
2. **Base Handler class appends it** - Override `handle()` in base class
3. **FrontController appends it** - Post-process result after handler returns

**Decision**: Option 3 - FrontController injection

**Rationale**:
- Zero changes to individual handlers (DRY)
- FrontController already knows the event type
- Single maintenance point
- Handlers don't need to know about their config location
- New handlers automatically get the feature

**Date**: 2026-02-12

### Decision 2: Config Path Format - Dotted Notation

**Context**: How to represent the config key to users?

**Options Considered**:
1. **Just config_key**: `destructive_git`
2. **Dotted path**: `handlers.pre_tool_use.destructive_git`
3. **YAML snippet**: `handlers:\n  pre_tool_use:\n    destructive_git:\n      enabled: false`

**Decision**: Option 2 - Dotted path notation

**Rationale**:
- Familiar from PHPStan, ESLint, Ruff
- Unambiguous (includes full path to the config item)
- Concise (single line)
- Maps directly to YAML nesting (mental model is clear)
- Easy to grep/search for

**Date**: 2026-02-12

### Decision 3: Only DENY/ASK - Not ALLOW

**Context**: Which decision types should show the config key?

**Decision**: Only append to DENY and ASK results

**Rationale**:
- ALLOW responses are often silent (empty result)
- Users only need to disable handlers that are blocking them
- Adding config keys to ALLOW would be noise
- Advisory context messages don't need disable instructions

**Date**: 2026-02-12

## Success Criteria

- [ ] Every DENY/ASK handler response includes fully-qualified config path
- [ ] Config path format: `handlers.{event_type}.{config_key}`
- [ ] Zero changes to individual handler `handle()` methods
- [ ] Implementation in FrontController (single injection point)
- [ ] ALLOW responses unchanged
- [ ] All existing tests pass (updated for new footer)
- [ ] Full QA suite passes
- [ ] Daemon loads successfully
- [ ] Live testing confirms config path appears in real block messages

## Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Existing tests break (assert exact reason strings) | Medium | High | Update affected test assertions to account for footer |
| Acceptance test patterns break | Medium | Medium | Regex patterns should still match (footer is appended after) |
| Progressive verbosity messages look cluttered | Low | Low | Footer is visually separated with blank line |
| Event type naming mismatch (camelCase vs snake_case) | Medium | Low | Verify mapping in Phase 1 research |

## Notes & Updates

### 2026-02-12
- Plan created based on user feedback
- Inspired by PHPStan's rule identifier pattern
- Key insight: FrontController already knows event type + handler, making it the ideal injection point
- Zero handler modifications needed - purely a dispatch-layer enhancement
