# Plan 049: NPM Handler - LLM Command Detection & Advisory Mode

**Status**: Complete (2026-02-12)
**Created**: 2026-02-12
**Owner**: Claude Sonnet 4.5
**Priority**: Medium
**Estimated Effort**: 3-4 hours

## Overview

The current NPM command handlers (NpmCommandHandler and ValidateEslintOnWriteHandler) BLOCK usage of raw npm commands (like `npm run lint`) and FORCE users to use llm: prefixed commands (like `npm run llm:lint`). This is problematic because:

1. **Not all projects have llm: commands** - The handlers assume every project has implemented llm: wrappers
2. **Blocking prevents legitimate work** - Users cannot run standard npm scripts in projects without llm: setup
3. **Missing opportunity for education** - Instead of blocking, we should ADVISE users about best practices

This enhancement converts the handlers from **hard enforcement** to **smart advisory**:
- Detect if project has llm: commands in package.json
- If llm: commands exist → DENY with suggestion (current behavior)
- If NO llm: commands → ALLOW with advisory about creating them

## Goals

- Detect presence of llm: commands in package.json before blocking
- Convert to advisory mode when llm: commands don't exist
- Provide helpful guidance on creating llm: command wrappers
- Maintain blocking behavior for projects that DO have llm: commands (enforce consistency)
- Update both NpmCommandHandler and ValidateEslintOnWriteHandler

## Non-Goals

- Automatically creating llm: commands for projects
- Validating the implementation of existing llm: commands
- Handling non-Node.js projects differently
- Creating a configuration option to disable this feature

## Context & Background

### Current Behavior

**NpmCommandHandler** (src/claude_code_hooks_daemon/handlers/pre_tool_use/npm_command.py:127-143):
```python
return HookResult(
    decision=Decision.DENY,
    reason=(
        f"🚫 BLOCKED: Must use llm: prefixed command instead of '{blocked_cmd}'\n\n"
        f"PHILOSOPHY: Claude should use llm: prefixed commands which provide:\n"
        f"  • Minimal stdout (summary only)\n"
        f"  • Verbose JSON logging to ./var/qa/ files\n"
        ...
    ),
)
```

**Problem**: Assumes llm: commands always exist. Blocks all projects unconditionally.

### LLM Command Philosophy

LLM-prefixed commands provide:
- **Minimal stdout** - Summary only (exit code, counts, timing)
- **Verbose JSON output** - Full machine-readable data in ./var/qa/*.json
- **JQ-optimized structure** - Easy filtering, querying, data extraction
- **Cache system** - Performance optimization for repeated runs

### Example Advisory Message

When llm: commands don't exist:
```
⚠️  ADVISORY: Consider creating llm: prefixed npm commands

You're using: npm run lint

RECOMMENDATION: Create llm: wrappers for better LLM integration
  • Minimal stdout (summary only: "✅ 45 files checked, 0 errors")
  • Verbose JSON files in ./var/qa/ (optimized for jq queries)
  • Machine-readable output (parse with jq, not grep/sed)

Example package.json script:
  "llm:lint": "eslint . --format json --output-file ./var/qa/eslint-cache.json && eslint . --format compact"

Then query results with jq:
  jq '.[] | select(.errorCount > 0)' ./var/qa/eslint-cache.json

This command will run for now, but consider adding llm: wrappers.
```

## Tasks

### Phase 1: Design & Research

- [ ] ⬜ **Research package.json detection**
  - [ ] ⬜ Identify best way to locate package.json (ProjectContext.project_root())
  - [ ] ⬜ Determine how to parse scripts section (json.loads)
  - [ ] ⬜ Design startup caching in ProjectContext (parse once, cache for daemon lifetime)

- [ ] ⬜ **Design detection logic**
  - [ ] ⬜ Define what counts as "has llm: commands" (threshold: 1+ scripts starting with "llm:")
  - [ ] ⬜ Design fallback behaviour if package.json is malformed/missing
  - [ ] ⬜ Add to ProjectContext singleton (computed once at daemon startup)

- [ ] ⬜ **Design advisory messages**
  - [ ] ⬜ Draft advisory text for NpmCommandHandler
  - [ ] ⬜ Draft advisory text for ValidateEslintOnWriteHandler
  - [ ] ⬜ Include specific examples based on command being run

### Phase 2: TDD Implementation

- [ ] ⬜ **Create shared detection utility**
  - [ ] ⬜ Write failing tests for `_detect_llm_commands_in_package_json()`
    - [ ] ⬜ Test: Returns True when package.json has llm: scripts
    - [ ] ⬜ Test: Returns False when package.json has no llm: scripts
    - [ ] ⬜ Test: Returns False when package.json missing
    - [ ] ⬜ Test: Returns False when package.json malformed
    - [ ] ⬜ Test: Returns False when scripts section missing
  - [ ] ⬜ Implement utility function to pass tests
  - [ ] ⬜ Location: `src/claude_code_hooks_daemon/utils/npm.py`
  - [ ] ⬜ Function reads package.json at project root, checks for llm: prefixed scripts

- [ ] ⬜ **Update NpmCommandHandler**
  - [ ] ⬜ Write failing tests for new advisory behaviour
    - [ ] ⬜ Test: DENY when llm: commands exist (current behaviour)
    - [ ] ⬜ Test: ALLOW with advisory when llm: commands don't exist
    - [ ] ⬜ Test: Advisory message includes helpful guidance
    - [ ] ⬜ Test: `self.has_llm_commands` cached in memory (no repeated file reads)
  - [ ] ⬜ Modify `__init__()` to call detection utility and cache boolean in `self.has_llm_commands`
  - [ ] ⬜ Modify `handle()` to check `self.has_llm_commands` (zero I/O overhead)
  - [ ] ⬜ Add advisory path with Decision.ALLOW when `self.has_llm_commands == False`
  - [ ] ⬜ Update acceptance tests
  - [ ] ⬜ Refactor for clarity

- [ ] ⬜ **Update ValidateEslintOnWriteHandler**
  - [ ] ⬜ Write failing tests for conditional validation
    - [ ] ⬜ Test: DENY on ESLint errors when llm: commands exist
    - [ ] ⬜ Test: ALLOW with advisory when llm: commands don't exist
    - [ ] ⬜ Test: Advisory suggests creating llm:lint script
    - [ ] ⬜ Test: `self.has_llm_commands` cached in memory (no repeated file reads)
  - [ ] ⬜ Modify `__init__()` to call detection utility and cache boolean in `self.has_llm_commands`
  - [ ] ⬜ Modify `handle()` to check `self.has_llm_commands` (zero I/O overhead)
  - [ ] ⬜ Skip ESLint validation entirely if `self.has_llm_commands == False` (just advise)
  - [ ] ⬜ Add advisory branch
  - [ ] ⬜ Update acceptance tests
  - [ ] ⬜ Refactor for clarity

### Phase 3: Integration & Testing

- [ ] ⬜ **Integration tests**
  - [ ] ⬜ Test with project that HAS llm: commands (enforce mode)
  - [ ] ⬜ Test with project that LACKS llm: commands (advisory mode)
  - [ ] ⬜ Test with no package.json (advisory mode)
  - [ ] ⬜ Verify handlers parse package.json ONCE at `__init__()` time
  - [ ] ⬜ Verify `handle()` method has zero file I/O (just checks `self.has_llm_commands`)

- [ ] ⬜ **Verify coverage**
  - [ ] ⬜ Run coverage report for modified handlers
  - [ ] ⬜ Ensure 95%+ coverage maintained
  - [ ] ⬜ Add missing tests if needed

### Phase 4: Documentation & QA

- [ ] ⬜ **Update documentation**
  - [ ] ⬜ Update handler comments/docstrings
  - [ ] ⬜ Update CLAUDE.md if needed
  - [ ] ⬜ Document detection logic in code

- [ ] ⬜ **Run full QA suite**
  - [ ] ⬜ Run: `./scripts/qa/run_all.sh`
  - [ ] ⬜ Fix any QA issues
  - [ ] ⬜ Verify all checks pass

- [ ] ⬜ **Daemon verification**
  - [ ] ⬜ Restart daemon: `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart`
  - [ ] ⬜ Verify status: `$PYTHON -m claude_code_hooks_daemon.daemon.cli status`
  - [ ] ⬜ Check logs for errors

- [ ] ⬜ **Live testing**
  - [ ] ⬜ Test in Node.js project WITH llm: commands (should block)
  - [ ] ⬜ Test in Node.js project WITHOUT llm: commands (should advise)
  - [ ] ⬜ Test in Python project (should advise - no package.json)
  - [ ] ⬜ Verify advisory messages are helpful

## Dependencies

- None (standalone enhancement)

## Technical Decisions

### Decision 1: Detection Strategy - Walk Up Directory Tree

**Context**: Need to find package.json from any working directory within project

**Options Considered**:
1. **Use ProjectContext.project_root()** - Assumes package.json is at repo root
2. **Walk up from cwd** - Find nearest package.json (supports monorepos)
3. **Check both locations** - Try cwd first, fall back to project root

**Decision**: Use Option 1 (ProjectContext.project_root()) with fallback to cwd walk

**Rationale**:
- Most projects have package.json at repo root
- ProjectContext already handles git root detection
- Simpler implementation, handles 95% of cases
- Can enhance later if monorepo support needed

**Date**: 2026-02-12

### Decision 2: Detection Threshold - 1+ LLM Scripts

**Context**: How many llm: scripts must exist to trigger enforcement mode?

**Options Considered**:
1. **Any llm: script exists** - Even 1 script triggers enforcement
2. **Specific script must exist** - Check for exact command being run
3. **Majority of scripts** - 50%+ must be llm: prefixed

**Decision**: Option 1 - Any llm: script exists

**Rationale**:
- If project has started using llm: pattern, enforce consistency
- Prevents mixing patterns within same project
- Simpler logic, clearer behavior
- Encourages complete adoption

**Date**: 2026-02-12

### Decision 3: Caching Strategy - Daemon Startup Only

**Context**: Should we cache package.json detection results?

**Options Considered**:
1. **No caching** - Read package.json every time (inefficient)
2. **Per-request caching** - Cache during single hook event
3. **Daemon startup caching** - Parse once at startup, cache for daemon lifetime

**Decision**: Option 3 - Parse at daemon startup and cache

**Rationale**:
- **Efficiency**: Handlers fire frequently, file I/O on hot path is wasteful
- **Startup is ideal time**: package.json rarely changes during daemon session
- **ProjectContext pattern**: Already established for project metadata
- **Zero runtime overhead**: Handlers just read boolean from memory
- **Simple invalidation**: Daemon restart picks up package.json changes
- **Consistent with existing patterns**: Similar to how ProjectContext caches project root, git URL, etc.

**Implementation**:
- Add `has_llm_commands: bool` instance variable to NpmCommandHandler and ValidateEslintOnWriteHandler
- Parse package.json in handler `__init__()` (runs once at daemon startup)
- Cache boolean result in `self.has_llm_commands` (in-memory, zero overhead)
- Handler `handle()` method checks `self.has_llm_commands` to decide DENY vs ALLOW
- Daemon restart required if package.json changes (acceptable tradeoff)
- Helper utility `_detect_llm_commands_in_package_json()` in utils/npm.py for reuse

**Date**: 2026-02-12

### Decision 4: Advisory vs Blocking - File Not Found

**Context**: What to do if package.json is missing or malformed?

**Options Considered**:
1. **Default to advisory** - Assume no llm: commands
2. **Default to blocking** - Assume best practices should be followed
3. **Skip handler** - Return ALLOW without any message

**Decision**: Option 1 - Default to advisory mode

**Rationale**:
- Non-Node.js projects won't have package.json (Python, Go, etc.)
- Better UX to advise than block in ambiguous cases
- Aligns with "smart advisory" philosophy
- Users can still work, just get helpful suggestions

**Date**: 2026-02-12

## Success Criteria

- [ ] NpmCommandHandler detects llm: command presence
- [ ] ValidateEslintOnWriteHandler detects llm: command presence
- [ ] Handlers DENY when llm: commands exist (maintain enforcement)
- [ ] Handlers ALLOW with advisory when llm: commands absent
- [ ] Advisory messages are clear and actionable
- [ ] All unit tests pass with 95%+ coverage
- [ ] Integration tests pass for both modes
- [ ] Full QA suite passes
- [ ] Daemon loads successfully
- [ ] Live testing in both scenarios works

## Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Detection logic has false positives | Medium | Low | Comprehensive test suite with real package.json examples |
| Advisory messages too verbose | Low | Medium | Keep messages concise, include examples |
| Performance impact from file reads | Low | Low | File reads are fast; can add caching later if needed |
| Confusion about when blocking vs advising | Medium | Medium | Clear messages explaining detection logic |
| Breaking change for existing users | Low | Low | Only changes behavior when llm: commands DON'T exist |

## Timeline

- Phase 1: 1 hour (Design & Research)
- Phase 2: 1.5 hours (TDD Implementation)
- Phase 3: 30 minutes (Integration Testing)
- Phase 4: 1 hour (Documentation & QA)
- Target Completion: 2026-02-12

## Notes & Updates

### 2026-02-12
- Plan created based on user speech-to-text input
- Identified key enhancement: convert from hard blocking to smart advisory
- Philosophy: Don't block legitimate work, educate users instead
- Focus on detecting llm: command presence in package.json
