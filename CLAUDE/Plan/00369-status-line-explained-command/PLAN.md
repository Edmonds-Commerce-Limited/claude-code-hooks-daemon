# Plan 00369: status line explained command

**Status**: Not Started
**Created**: 2026-09-10
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Field report, verbatim: "🧹 1 stale — i have forgotten what this means. can
we build a /hooks-daemon status-line-explained tool which generates all the
status line icons and under each one provides a human friendly terse clear
explanation of what it is in general and what the current value means?" The
"🧹 1 stale" glyph is `StartupCleanupHandler` — one of 14 status-line handlers
in `src/claude_code_hooks_daemon/handlers/status_line/`, none of which
currently have any self-describing capability. `explain-rule`/`explain-handler`
(Plan 00116) solve this for blocking rules, but a status-line segment is
advisory-only and carries no `Rule` — there is nothing today to ask "what does
this icon mean?" of.

This plan gives every status-line handler a first-class `explain_segment()`
contract (glyph(s), name, what it is, how to read it, current value) enforced
by a completeness sweep, and a new CLI verb —
`hooks-daemon status-line-explained` (alias `explain-status-line`), routed
through the `hooks-daemon` skill as `/hooks-daemon status-line-explained` —
that renders every segment's explanation for the CURRENT project, in
status-line order, text or JSON.

## Goals

- Every status-line handler (14 concrete classes under
  `handlers/status_line/`) implements `explain_segment() -> SegmentExplanation`
  on a shared base contract, read-only (no handler gains a new write path).
- A completeness test iterates the status-line handler registry and fails if
  any handler lacks a non-empty explanation, or if a declared glyph cannot be
  found in that handler's own source (the ground truth of what it can render).
- `hooks-daemon status-line-explained` (+ `explain-status-line` alias) prints,
  for the current project, every segment in status-line priority order: a
  reference icon line, then per segment a terse what-it-is/how-to-read/
  current-value block. `--format json` for machine consumption. Handlers
  disabled by config are listed separately under "not enabled".
- Routed via the `hooks-daemon` skill (`/hooks-daemon status-line-explained`),
  matching the `restart`/`bug-report` case-routing pattern, plus a skill doc
  page and updated `CLAUDE/Architecture/StatusLine.md` cross-reference.
- A release-notes callout announces the command.

## Non-Goals

- Not a byte-for-byte replay of the live rendered status line: several
  segments (model/context/effort, working-directory diff, multithread count,
  downgrade state) only have real values inside a live Claude Code session
  render and are reported as "not shown now" with the reason, not faked.
- Not a change to any handler's `handle()` behaviour, output format, priority,
  or default-enabled state — this plan only adds a parallel, read-only
  self-description method.
- Not a rewrite of `explain-rule`/`explain-handler` — those remain the rule-ID
  surface; this is the advisory-segment surface `explain-rule --list` cannot
  reach because status-line handlers declare no `Rule` objects.

## Tasks

### Phase 1: Contract + dataclass

- [x] ✅ **Task 1.1**: `SegmentExplanation` dataclass (glyphs, name, what_it_is,
  how_to_read, current_value) with fail-fast validation on empty required
  fields.
- [x] ✅ **Task 1.2**: `StatusLineSegmentHandler` base (subclasses
  `AdvisoryHandler`, adds abstract `explain_segment()`); `StatusLineHandlerBase`
  repointed to it. Verify the existing `test_handler_bases.py` sweep still
  passes unchanged (base substitution must not alter the Status tier).

### Phase 2: Per-handler explanations

- [x] ✅ **Task 2.1**: Implement `explain_segment()` on all 14 concrete
  status-line handlers, each read-only (no new writes).
- [x] ✅ **Task 2.2**: Completeness sweep test: every discovered status-line
  handler has a non-empty explanation; every declared glyph appears in
  that handler's own source (`inspect.getsource`); every status-line
  `*.py` file's `Handler` subclasses are concrete (guards against a
  forgotten `explain_segment()` silently vanishing the handler from
  discovery via `inspect.isabstract`).

### Phase 3: CLI command + skill routing

- [x] ✅ **Task 3.1**: `cmd_status_line_explained` in `daemon/cli.py`:
  resolves project config, discovers status-line handlers, sorts by
  resolved priority, renders enabled segments (reference icon line +
  explanation blocks) and disabled segments (under "not enabled"); `--json`.
  Argparse subcommand `status-line-explained` with alias
  `explain-status-line`.
- [x] ✅ **Task 3.2**: Skill routing: `.claude/skills/hooks-daemon/SKILL.md`
  command list, help text, case-statement routing to `daemon-cli.sh`; new
  `status-line-explained.md` skill doc page. Mirrored into the packaged
  source (`src/claude_code_hooks_daemon/skills/hooks-daemon/`), which this
  repo tracks alongside the deployed copy and keeps byte-identical.
- [x] ✅ **Task 3.3**: `CLAUDE/Architecture/StatusLine.md` cross-reference
  (new "Self-Description" section + Step 6) plus
  `docs/guides/HANDLER_REFERENCE.md`'s StatusLine Handlers intro (the
  human-docs precedent `explain-rule` itself sets no `docs/` entry for, so
  no separate CLI-reference page was invented).

### Phase 4: QA + release

- [ ] ⬜ **Task 4.1**: `./scripts/qa/llm_qa.py all` clean on every touched
  file (whole-repo pyright may carry pre-existing errors from other
  in-flight branches; touched files must be pyright-clean regardless).
- [ ] ⬜ **Task 4.2**: Release-notes callout under
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/`.
- [ ] ⬜ **Task 4.3**: Worktree daemon restarted, confirmed RUNNING, real
  `status-line-explained` output captured for the report.

## Success Criteria

- [ ] All 14 status-line handlers implement `explain_segment()`; the
  completeness sweep passes.
- [ ] `hooks-daemon status-line-explained` and `explain-status-line` both run
  against this project and print every enabled segment's explanation plus
  a "not enabled" section for disabled ones; `--format json` validates as
  JSON.
- [ ] `/hooks-daemon status-line-explained` is routed in the skill, with a
  doc page, and the skill-surface coherence gate (Plan 00330) passes.
- [ ] Release-notes callout exists.
- [ ] Full QA green on touched files; worktree daemon restarted and verified
  RUNNING.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00369-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- <!-- milestone or delivery commit hash -->
