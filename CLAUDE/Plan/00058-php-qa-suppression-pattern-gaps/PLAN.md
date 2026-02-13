# Plan 00058: Fix PHP QA Suppression Pattern Gaps

**Status**: In Progress
**Type**: Bug Fix
**Severity**: Critical
**Created**: 2026-02-13
**Owner**: Claude Sonnet 4.5
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded (focused bug fix)

## Overview

The PHP QA suppression handler has critical pattern matching gaps that allow developers to bypass quality checks using modern PHPStan and PHPCS suppression patterns. This undermines the entire quality enforcement system.

**Root Cause**: The forbidden patterns list only covers older/partial suppression syntax, missing modern patterns that are now the recommended approaches.

## Bug Description

**Discovered**: 2026-02-13 during acceptance testing

**What's Broken**: Developers can bypass QA suppression blocking by using:
1. `@phpstan-ignore <identifier>` (e.g., `@phpstan-ignore argument.type`)
2. `phpcs:disable` / `phpcs:enable` (block-level suppression)
3. `phpcs:ignoreFile` (entire file suppression)
4. Deprecated `@codingStandardsIgnoreStart` / `@codingStandardsIgnoreEnd` / `@codingStandardsIgnoreFile`

**How to Reproduce**:
```php
// This is NOT blocked (BUG):
/** @phpstan-ignore test.suppression */
$x = 1;
```

**Expected**: Write should be blocked with QA suppression error
**Actual**: Write succeeds (file created)

**User Impact**: Project experiencing "serious issues due to suppressions not being blocked" - quality controls are ineffective.

## Research Sources

- PHPStan: [Ignoring Errors Documentation](https://phpstan.org/user-guide/ignoring-errors)
- Psalm: [Supported Annotations](https://psalm.dev/docs/annotating_code/supported_annotations/)
- PHPCS: [Advanced Usage Wiki](https://github.com/squizlabs/PHP_CodeSniffer/wiki/Advanced-Usage)

## Goals

- Block ALL PHPStan suppression patterns (line-based and identifier-based)
- Block ALL PHPCS suppression patterns (line, block, and file-level)
- Maintain existing Psalm and deprecated pattern blocking
- Achieve 100% suppression pattern coverage

## Non-Goals

- Not changing handler architecture or strategy pattern
- Not modifying other language strategies
- Not changing skip directory logic

## Tasks

### Phase 1: Write Failing Tests (TDD Red Phase)

- [x] ✅ **Test 1.1**: Document bug with reproduction test
  - [x] Create `/tmp/test-phpstan-ignore/test.php` with `@phpstan-ignore`
  - [x] Verify Write succeeds (proves bug exists)

- [ ] ⬜ **Test 1.2**: Write comprehensive failing tests
  - [ ] Add test for `@phpstan-ignore` (base pattern)
  - [ ] Add test for `@phpstan-ignore <identifier>`
  - [ ] Add test for `phpcs:disable`
  - [ ] Add test for `phpcs:enable`
  - [ ] Add test for `phpcs:ignoreFile`
  - [ ] Add test for deprecated `@codingStandardsIgnoreStart`
  - [ ] Add test for deprecated `@codingStandardsIgnoreEnd`
  - [ ] Add test for deprecated `@codingStandardsIgnoreFile`
  - [ ] Run tests - verify they FAIL: `pytest tests/unit/strategies/qa_suppression/test_php_strategy.py -v`

### Phase 2: Implement Fix (TDD Green Phase)

- [ ] ⬜ **Task 2.1**: Update forbidden patterns in PHP strategy
  - [ ] Add `@phpstan-ignore` base pattern (covers all variants)
  - [ ] Add `phpcs:disable` pattern
  - [ ] Add `phpcs:enable` pattern
  - [ ] Add `phpcs:ignoreFile` pattern
  - [ ] Add deprecated `@codingStandardsIgnoreStart`
  - [ ] Add deprecated `@codingStandardsIgnoreEnd`
  - [ ] Add deprecated `@codingStandardsIgnoreFile`
  - [ ] Verify patterns use string concatenation to avoid false positives in this file

- [ ] ⬜ **Task 2.2**: Verify tests now pass
  - [ ] Run: `pytest tests/unit/strategies/qa_suppression/test_php_strategy.py -v`
  - [ ] Expected: ALL tests PASS

### Phase 3: Integration Testing

- [ ] ⬜ **Task 3.1**: Update acceptance tests
  - [ ] Add acceptance test for `@phpstan-ignore <identifier>`
  - [ ] Add acceptance test for `phpcs:disable` / `phpcs:enable`
  - [ ] Add acceptance test for `phpcs:ignoreFile`
  - [ ] Verify acceptance tests are returned by `get_acceptance_tests()`

- [ ] ⬜ **Task 3.2**: Run integration tests
  - [ ] Run: `pytest tests/integration/handlers/test_pre_tool_use_qa.py -v`
  - [ ] Expected: ALL PASS

### Phase 4: Daemon Verification (MANDATORY)

- [ ] ⬜ **Task 4.1**: Restart daemon
  - [ ] Run: `/workspace/untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli restart`
  - [ ] Verify: Status shows RUNNING

- [ ] ⬜ **Task 4.2**: Check daemon logs
  - [ ] Run: `/workspace/untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli logs | grep -i error`
  - [ ] Expected: No import errors

### Phase 5: Live Acceptance Testing

- [ ] ⬜ **Test 5.1**: Test @phpstan-ignore blocking
  - [ ] Create temp file with `@phpstan-ignore argument.type`
  - [ ] Verify Write is BLOCKED
  - [ ] Verify error message mentions PHPStan suppression

- [ ] ⬜ **Test 5.2**: Test phpcs:disable blocking
  - [ ] Create temp file with `// phpcs:disable`
  - [ ] Verify Write is BLOCKED
  - [ ] Verify error message mentions PHPCS suppression

- [ ] ⬜ **Test 5.3**: Test phpcs:ignoreFile blocking
  - [ ] Create temp file with `// phpcs:ignoreFile`
  - [ ] Verify Write is BLOCKED
  - [ ] Verify error message mentions PHPCS suppression

- [ ] ⬜ **Test 5.4**: Verify safe code still works
  - [ ] Create temp file with normal PHP code (no suppressions)
  - [ ] Verify Write SUCCEEDS
  - [ ] Cleanup test files

### Phase 6: Full QA Suite

- [ ] ⬜ **Task 6.1**: Run complete QA suite
  - [ ] Run: `./scripts/qa/run_all.sh`
  - [ ] Expected: ALL CHECKS PASSED

- [ ] ⬜ **Task 6.2**: Fix any QA issues
  - [ ] If failures found, fix and re-run
  - [ ] Repeat until all checks pass

### Phase 7: Documentation & Commit

- [ ] ⬜ **Task 7.1**: Update documentation
  - [ ] Verify all patterns documented in strategy file comments
  - [ ] Update CHANGELOG.md with bug fix entry

- [ ] ⬜ **Task 7.2**: Commit with proper message
  - [ ] Stage specific files only
  - [ ] Commit with "Plan 00058:" prefix
  - [ ] Reference bug in commit message

## Complete Pattern Coverage

### PHPStan Patterns (All Blocked)
- `@phpstan-ignore-line` ✅ (existing)
- `@phpstan-ignore-next-line` ✅ (existing)
- `@phpstan-ignore` ❌ → ✅ (FIX)

### Psalm Patterns (All Blocked)
- `@psalm-suppress` ✅ (existing)

### PHPCS Patterns (Partial → Complete)
- `phpcs:ignore` ✅ (existing)
- `@codingStandardsIgnoreLine` ✅ (existing, deprecated)
- `phpcs:disable` ❌ → ✅ (FIX)
- `phpcs:enable` ❌ → ✅ (FIX)
- `phpcs:ignoreFile` ❌ → ✅ (FIX)
- `@codingStandardsIgnoreStart` ❌ → ✅ (FIX - deprecated)
- `@codingStandardsIgnoreEnd` ❌ → ✅ (FIX - deprecated)
- `@codingStandardsIgnoreFile` ❌ → ✅ (FIX - deprecated)

## Technical Decisions

### Decision 1: Pattern Matching Approach
**Context**: Need to block both base patterns and their variants

**Options Considered**:
1. Use base pattern only (`@phpstan-ignore`) - blocks all variants
2. List all variants explicitly - more maintainable but verbose

**Decision**: Use base patterns where possible (Option 1)
- `@phpstan-ignore` catches `@phpstan-ignore argument.type`, `@phpstan-ignore return.type`, etc.
- `phpcs:disable` catches `phpcs:disable PEAR.Functions`, etc.

**Rationale**: Simpler, more maintainable, harder to bypass

**Date**: 2026-02-13

### Decision 2: Handle Deprecated Patterns
**Context**: PHPCS deprecated `@codingStandards*` patterns (removed in v4.0)

**Decision**: Block deprecated patterns anyway
- Legacy codebases may still use them
- No harm in blocking (they shouldn't be used)
- Prevents bypass attempts using old syntax

**Date**: 2026-02-13

## Success Criteria

- [ ] All PHPStan suppression patterns blocked (3 patterns)
- [ ] All PHPCS suppression patterns blocked (7 patterns)
- [ ] All Psalm patterns still blocked (1 pattern)
- [ ] All unit tests pass with 95%+ coverage
- [ ] All integration tests pass
- [ ] Live acceptance tests verify blocking works
- [ ] Daemon starts successfully
- [ ] All QA checks pass
- [ ] User's project issue resolved

## Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Pattern too broad (false positives) | High | Low | Use string concatenation to avoid matching patterns in this file |
| Pattern too narrow (bypass still possible) | Critical | Medium | Test with actual suppression examples from docs |
| Breaks existing tests | Medium | Low | Run full test suite before committing |

## Timeline

- Phase 1-2 (TDD): 30 minutes
- Phase 3-4 (Integration): 15 minutes
- Phase 5 (Live Testing): 15 minutes
- Phase 6 (QA): 10 minutes
- Phase 7 (Documentation): 10 minutes
- **Total**: ~1.5 hours

## Notes & Updates

### 2026-02-13 - Bug Discovery
Discovered during user-requested acceptance test for PHPStan suppression blocking. User reported "serious issues" in their project due to suppressions not being blocked. Reproduction confirmed:
```php
/** @phpstan-ignore test.suppression */
$x = 1;
```
This Write succeeded when it should have been blocked.

### 2026-02-13 - Research Completed
Comprehensive research via official documentation sources confirmed 8 missing patterns:
- 1 PHPStan pattern (`@phpstan-ignore`)
- 6 PHPCS patterns (`phpcs:disable`, `phpcs:enable`, `phpcs:ignoreFile`, 3 deprecated)
- Verified existing Psalm pattern is complete

## Related Documentation

- Bug Fix Lifecycle: @CLAUDE/CodeLifecycle/Bugs.md
- QA Suppression Handler: `src/claude_code_hooks_daemon/handlers/pre_tool_use/qa_suppression.py`
- PHP Strategy: `src/claude_code_hooks_daemon/strategies/qa_suppression/php_strategy.py`
- Unit Tests: `tests/unit/strategies/qa_suppression/test_php_strategy.py`
