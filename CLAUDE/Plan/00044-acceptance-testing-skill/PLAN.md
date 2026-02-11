# Plan 00044: Acceptance Testing Skill and Agent

**Status**: Not Started
**Created**: 2026-02-11
**Owner**: Claude
**Priority**: High

## Context

During the v2.8.0 release, acceptance testing was done manually by testing a handful of "critical" blocking handlers. The user rightly called this out - the release process requires ALL 90 tests to pass, not just a subset. Manual execution of 90 tests is slow, error-prone, and doesn't scale.

This plan creates an automated acceptance testing skill that generates the playbook from code, spawns parallel Haiku subagents to execute tests, and reports comprehensive pass/fail results.

## Deliverables

### 1. JSON Output for PlaybookGenerator (code change)

**Files:**
- `src/claude_code_hooks_daemon/daemon/playbook_generator.py` - Refactor + add `generate_json()`
- `src/claude_code_hooks_daemon/daemon/cli.py` - Add `--format json`, `--filter-type`, `--filter-handler` flags
- `tests/unit/daemon/test_playbook_generator.py` - Tests for JSON generation
- `tests/unit/daemon/test_cli.py` - Tests for new CLI flags (or extend existing)

**Changes:**
1. Extract shared logic from `generate_markdown()` into `_collect_tests()` private method
2. Add `generate_json()` that returns `list[dict[str, Any]]` with all test fields plus handler_name, event_type, priority, test_number, source
3. Add CLI flags: `--format json|markdown`, `--filter-type blocking|advisory|context`, `--filter-handler <name>`
4. Apply filters in `cmd_generate_playbook()` when format is JSON

### 2. `acceptance-test-runner` Agent

**File:** `.claude/agents/acceptance-test-runner.md`

- Model: haiku (fast, cheap, parallelizable)
- Tools: Bash, Read, Glob, Grep
- Instructions for executing each test type:
  - **BLOCKING**: Run command, expect hook BLOCKS it, verify error patterns match
  - **ADVISORY**: Run command, expect it succeeds, check system-reminder for advisory patterns
  - **CONTEXT**: Run benign command, check system-reminder for context patterns
- Outputs structured JSON: `{batch_results: [...], summary: {total, passed, failed, skipped}}`

### 3. `/acceptance-test` Skill

**Files:**
- `.claude/skills/acceptance-test/SKILL.md` - Frontmatter + documentation
- `.claude/skills/acceptance-test/invoke.sh` - Orchestration prompt generator

**Accepts args:** `all` (default), `blocking-only`, `advisory-only`, `context-only`, or handler name substring

**Orchestration flow:**
1. Restart daemon
2. Generate playbook as JSON (with filters)
3. Group tests into batches of 3-5
4. Spawn parallel Haiku agents per batch
5. Collect JSON results from all agents
6. Report comprehensive summary

**Lifecycle event handling:** Tests for SessionStart/SessionEnd/PreCompact that can't be triggered by subagents are marked SKIP (not FAIL).

### 4. Documentation Updates

- `.claude/skills/release/invoke.sh` - Update Stage 2 to use `/acceptance-test`
- `CLAUDE/development/RELEASING.md` - Add automated option reference

## Tasks

### Phase 1a: JSON Output for PlaybookGenerator (TDD)

- [ ] Write failing tests for `_collect_tests()` extraction
- [ ] Write failing tests for `generate_json()` method
- [ ] Write failing tests for `--format json` CLI flag
- [ ] Write failing tests for `--filter-type` and `--filter-handler` flags
- [ ] Refactor: Extract `_collect_tests()` from `generate_markdown()`
- [ ] Implement `generate_json()` method
- [ ] Add CLI flags to `generate-playbook` command
- [ ] Run QA + daemon restart verification

### Phase 1b: Agent Definition (parallel with 1a)

- [ ] Create `.claude/agents/acceptance-test-runner.md`

### Phase 2: Skill Definition (depends on Phase 1)

- [ ] Create `.claude/skills/acceptance-test/SKILL.md`
- [ ] Create `.claude/skills/acceptance-test/invoke.sh` (chmod +x)

### Phase 3: Documentation & Integration (depends on Phase 2)

- [ ] Update `.claude/skills/release/invoke.sh` Stage 2 to use `/acceptance-test`
- [ ] Update `CLAUDE/development/RELEASING.md` with automated option
- [ ] Strengthen release docs: make clear ALL tests must pass, no shortcuts
- [ ] Full QA pass + daemon restart verification

## Implementation Order

```
Phase 1 (parallel):
  1a. JSON output + CLI flags + tests (TDD: tests first)
  1b. Agent definition (no code dependency)

Phase 2 (depends on Phase 1):
  2a. Skill SKILL.md + invoke.sh

Phase 3 (depends on Phase 2):
  3a. Update release skill invoke.sh
  3b. Update RELEASING.md
  3c. Full QA + daemon restart verification
```

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Batch size 3-5 tests per agent | Balances parallelism overhead vs throughput. ~90 tests = 18-30 batches |
| SKIP lifecycle events | SessionStart/End/PreCompact can't be triggered by subagent. Honest > false confidence |
| JSON via CLI flag not separate command | Reuses existing infrastructure, follows Unix conventions |
| Filtering at CLI level | Reduces prompt size for orchestrating agent |
| Extract `_collect_tests()` | DRY - both markdown and JSON need same collection logic |
| Agent outputs JSON not free-text | Enables programmatic aggregation across batches |

## Verification

1. `./scripts/qa/run_all.sh` - All 7 checks pass
2. `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart && status` - Daemon loads
3. `$PYTHON -m claude_code_hooks_daemon.daemon.cli generate-playbook --format json` - Valid JSON output
4. `$PYTHON -m claude_code_hooks_daemon.daemon.cli generate-playbook --format json --filter-type blocking` - Filtered output
5. Invoke `/acceptance-test` and verify parallel agent execution works end-to-end
