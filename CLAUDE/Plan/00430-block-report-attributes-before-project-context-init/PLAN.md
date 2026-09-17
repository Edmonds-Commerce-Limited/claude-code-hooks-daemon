# Plan 00430: block report attributes before project context init

**Status**: In Progress
**Created**: 2026-09-17
**GitHub Issue**: #48
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

`hooks-daemon block-report` attributes deny events to handlers by building a
rule-ID index from handler discovery. Discovery constructs every handler class,
and five handlers read `ProjectContext.project_root()` in their `__init__`.
`cmd_block_report` never initialises `ProjectContext`, so those five raise
during construction, are logged-and-skipped, and their rule IDs are absent from
the index — their denies land in the report's unattributed count.

**Reproduced at triage on current `main`, not inferred.** A run here produced
2130 `Failed to inspect handler` tracebacks inside a 29007-line report, and
`44 unattributed deny(s) skipped`. The five handlers are exactly the ones the
reporter named: `ValidateEslintOnWrite`, `MarkdownOrganization`, `NpmCommand`,
`PlanNumberHelper`, `RemoteDocsProvenance`.

Two harms, and the quiet one is worse. The noise is obvious. The silent harm is
that a frequency table and a promotion recommendation are built from an index
missing whole handlers, so the report understates exactly the guards whose
rules it cannot see — and reads as a complete answer.

## What is already true

- `cmd_block_report` (`daemon/cli.py:6938`) loads the project config and calls
  `analyse_transcripts` without initialising `ProjectContext`. The config path
  it would need is already in the function.
- **The fix already exists in this file.** `_init_project_context_for_explain`
  (`daemon/cli.py:7053`) is idempotent, tolerant of a missing config, and its
  docstring names these same handler constructors as its reason for existing.
  Five commands call it; `block-report` does not.
- `_rule_id_to_config_key` (`block_report/fingerprints.py:203`) deliberately
  refuses to memoise a partial index and emits one warning instead, so an
  uninitialised run is slow as well as incomplete: it rebuilds the whole index
  per deny event. That is why the traceback count scales with deny events
  rather than with transcript count.
- Plan 00364 Task 3.6 added that warning **on purpose**, to stop the
  unattributed count reading as a finding about the data. The diagnosis
  shipped; the precondition was never fixed. Never built, never reverted.
- The `housekeeping` step the reporter also named is **not a second surface**:
  step 9 of `.claude/skills/hooks-daemon/housekeeping.md` invokes this same
  `block-report` command. One fix covers both.

## Goals

- `block-report` attributes denies from all five ProjectContext-reading
  handlers instead of counting them unattributed.
- No `Failed to inspect handler` traceback in a normal run.
- A regression test that fails before the fix.

## Non-Goals

- Changing what `collect_handler_rules` does when a handler genuinely cannot be
  constructed. Logging-and-skipping one broken handler rather than losing every
  other rule is correct, and is what kept this degradation survivable.
- Removing the Plan 00364 warning. It should stay and simply stop firing here;
  a warning that can never fire is a guard that passes vacuously.
- Reworking the promotion recommendation itself.

## Tasks

### Phase 1: reproduce and fix

- [x] ✅ **Task 1.1**: RED test first — assert that a `block-report` run
  attributes a deny whose rule belongs to a ProjectContext-reading handler. It
  must fail before the fix, with the failure quoted.
- [x] ✅ **Task 1.2**: Initialise `ProjectContext` in `cmd_block_report` before
  analysis, reusing `_init_project_context_for_explain` rather than writing a
  second initialisation path. If its name no longer fits its callers, rename it
  in the same change.
- [x] ✅ **Task 1.3**: Decide and pin what happens when no config file can be
  found. The helper returns quietly; `block-report` must still produce a
  report, degraded exactly as it does today rather than erroring. A test names
  this.
- [x] ✅ **Task 1.4**: Confirm the index is not memoised in a partial state
  earlier in the same process. `_rule_id_to_config_key` guards this by
  construction, but it is one `lru_cache` away from a wrong answer no test
  would notice, so assert it rather than reading it.

### Phase 2: prove and ship

- [x] ✅ **Task 2.1**: Full QA in the worktree; read `QA_EXIT` on its own line.
- [x] ✅ **Task 2.2**: Release note — a report that silently understated some
  handlers is user-visible.

## Success Criteria

- [x] A `block-report` run on this repository emits zero
  `Failed to inspect handler` lines and attributes strictly more denies than
  before, with both numbers recorded.
- [x] Every release-bound consequence is in the pending-release holding area.
- [ ] #48 carries a closing comment saying what was wrong, what changed, how it
  was verified, and anything found that the reporter did not report.

## Delivery & Milestones

- Filed by the issue-sdlc loop from issue #48; triaged actionable and
  reproduced before any code was written.
