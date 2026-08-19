# Plan 00260: The Bash write side-door, and `sed_blocker`'s inaccurate guidance

**Status**: Not Started
**Created**: 2026-08-19
**Owner**: Unassigned
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

A field report (`REPORT-2026-08-18-original.md`, filed alongside this plan) raised
two independent findings against v3.53.1. Both were verified against the source
and against the live daemon socket before this plan was written; the per-claim
verdicts are recorded at the top of that report. One finding was confirmed and
found to be *worse* than reported; the other was confirmed exactly, including its
handler count.

**Finding 1 — guidance, not behaviour.** `sed_blocker` blocks strictly more than
its `get_claude_md()` admits. The resident guidance lists `sed -i` / `sed -e` as
blocked and offers an "Allowed (read-only, no file modification)" section. In
fact `sed -n` is blocked, a bare flagless `sed` at a command head is blocked, and
a pure stdout pipe stage is blocked too unless a `grep` or `echo` also appears
somewhere in the same command. So `cat f | sed 's/x/y/' | grep z` is allowed
while `cat f | sed 's/x/y/' | wc -l` is denied — a distinction the guidance never
hints at, and whose only surviving example happens to fall on the allowed side.

**Finding 2 — an architectural blind spot.** 21 handlers key on the `Write`/`Edit`
tool names. A file that reaches disk through a Bash heredoc, redirect or `tee` is
seen by none of them. This has always been true, but it used to be a theoretical
gap because agents reached for `Write`/`Edit` by default. It is now routinely
reachable: Claude Code injects a `system-reminder` in `bypassPermissions` mode
that explicitly directs agents to make file changes "with `sed`, heredocs, or
short scripts, rather than using the dedicated Read, Edit, or Write tools". The
daemon cannot suppress that instruction, and for projects where
`bypassPermissions` is permanent it is a standing condition of every session.

The two findings share one root: **the handler's model of "a write" is a tool
name, and the guidance it publishes describes a rule narrower than the one it
enforces.** Core Standard 15 (DBF) names this shape directly — a guard that only
fires at write time does not cover what arrives by another route.

## Goals

- Make `sed_blocker`'s `get_claude_md()` describe the rule the code actually
  enforces, including the pipe-stage-plus-`grep`/`echo` condition.
- Establish and document, per handler, whether it can see a Bash-mediated write.
- Decide (with a recorded rationale) which of the three candidate remedies for
  the side-door to adopt, and implement what is chosen.
- Leave the daemon's *behaviour* on `sed` unchanged unless a deliberate decision
  says otherwise — Finding 1 is a documentation defect, and the surprising
  pipe-stage behaviour is locked in by passing tests.

## Non-Goals

- **Not** a blanket shell parser in every handler. Shell is hard to parse safely;
  `pipe_blocker`'s own guidance shows how much nuance one command string already
  demands (`$( )` nesting, quoted vs unquoted heredocs, git `-m` exemptions).
- **Not** loosening `sed_blocker`. The false-positive string matching is
  deliberate and load-bearing for acceptance testing (see `CLAUDE.md`).
- **Not** re-litigating `bypassPermissions`. The harness instruction is a given.
- **Not** the commit-gate/`mv` half of this problem — Plan 00252 owns that.

## Context & Background

Verification evidence (full detail in the moved report's verdict table):

- `_SED_WITH_EXECUTION_FLAG` is `\bsed\s+-[a-z]*[ien]` (`sed_blocker.py:53-56`) —
  `n` is in the character class, so `-n` is blocked by design.
- `_SED_AS_COMMAND_HEAD` is `(?:^|;|&&|\|\|)\s*sed\b` (`:45-48`) — a flagless
  `sed` at a command head is blocked regardless of arguments.
- `_is_safe_readonly_command` (`:244-285`) returns `False` on its final line when
  neither `grep` nor `echo` appears, so a bare pipe stage is denied. This is
  intentional and tested: `test_matches_bash_sed_in_pipeline_without_grep` and
  `test_is_safe_readonly_command_rejects_cat_pipe_sed`.
- Live-socket probes reproduced all three denials, and confirmed that heredoc,
  redirect and `tee` writes carrying a `shell=True` call, a hardcoded AWS key, a
  `noqa` suppression, an error-suppression idiom, a new source file with no test,
  a relative path, a lock-file overwrite and a misplaced markdown file **all pass
  with no decision**.
- `markdown_organization` is the only handler that inspects Bash for write
  targets (`_bash_memory_write_target`, `:653-663`), and only for Claude
  auto-memory paths (Plan 00131).

**Relationship to Plan 00252**: 00252 addresses the sibling case — content
arriving by `mv` and reaching a commit unexamined by `sensitive_content` — and
fixes it at the *commit gate*. This plan addresses the PreToolUse surface and the
other 20 handlers. The two should be read together and must not duplicate work;
if 00252 lands a staged-content check first, Task 3.1 should reuse it rather than
build a parallel mechanism.

## Tasks

### Phase 1: Correct the `sed_blocker` guidance

- [ ] ⬜ **Task 1.1**: Rewrite `get_claude_md()` in `sed_blocker.py` so the
  blocked list includes `sed -n`, and a bare `sed` as a command head with or
  without flags.
- [ ] ⬜ **Task 1.2**: Retitle the "Allowed (read-only, no file modification)"
  section to describe the real rule — a pipe stage, and only when a `grep` or
  `echo` also appears in the command. State the `wc -l` counter-example
  explicitly so the boundary is not inferred from one lucky example.
- [ ] ⬜ **Task 1.3**: Add a test asserting the guidance text names `-n` and the
  command-head case, so the description cannot silently drift from the code
  again (DBF: the missing guard here is "nothing checks that guidance matches
  behaviour").
- [ ] ⬜ **Task 1.4**: Decide and record whether the pipe-stage-needs-`grep`
  behaviour is *wanted* or merely *tested*. If wanted, leave it and document
  it. If not, that is a behaviour change and needs its own tasks plus updated
  tests — do not fold it silently into a guidance fix.

### Phase 2: Map the blind spot

- [ ] ⬜ **Task 2.1**: Enumerate every handler keying on `ToolName.WRITE` /
  `ToolName.EDIT` (21 at v3.53.1) and record, per handler, whether a
  Bash-mediated write can reach the same premise it guards.
  - Input map (all 21 read and verified): [BASH-BLINDSPOT-MAP.md](BASH-BLINDSPOT-MAP.md).
    It corrects the provisional split used in Task 3.1 below — `lint_on_edit`
    and `validate_eslint_on_write` are PATH-keyed (they read from disk, so a
    path-only utility restores them outright), `plan_time_estimates` is NOT
    path-keyed, and `absolute_path` should be dropped from Task 3.1's list
    because extending it to Bash would block ordinary relative-path shell use.
- [ ] ⬜ **Task 2.2**: For each handler that is blind, add one sentence to its
  `get_claude_md()` naming the boundary — e.g. "this handler sees
  `Write`/`Edit` only; a file written via a Bash heredoc is not checked".
  This is remedy option 3 from the report and the cheapest real win: an agent
  that knows a guard is blind can compensate; one that assumes coverage
  cannot.
- [ ] ⬜ **Task 2.3**: Add a coverage test in the spirit of
  `test_claude_md_guidance_coverage.py` that fails when a Write/Edit-keyed
  handler carries no recorded verdict about its Bash blindness.

### Phase 3: Choose and build a remedy

- [ ] ⬜ **Task 3.1**: Evaluate a shared "is this Bash call a file write?"
  utility generalising `markdown_organization._bash_memory_write_target`
  (redirect, `tee`, and heredoc targets), returning target paths only — not
  content. Path-keyed handlers (`markdown_organization`,
  `lock_file_edit_blocker`, `absolute_path`, `tdd_enforcement`,
  `plan_time_estimates`) get most of the value at that cost.
- [ ] ⬜ **Task 3.2**: Evaluate a `bypassPermissions`-aware SessionStart advisory
  stating that the harness will push toward Bash-first editing and that
  write-time guards do not cover it. Cheap, honest, no parsing — it converts
  a silent gap into a known one.
- [ ] ⬜ **Task 3.3**: Record the decision in Technical Decisions with the
  rationale, then implement whichever options are adopted under TDD.
- [ ] ⬜ **Task 3.4**: If the shared utility is adopted, migrate
  `markdown_organization` onto it so there is one implementation, not two
  (DRY / single source of truth).

### Phase 4: Verify and close

- [ ] ⬜ **Task 4.1**: Full QA — `./scripts/qa/llm_qa.py all`.
- [ ] ⬜ **Task 4.2**: Restart the daemon and confirm RUNNING; re-probe the
  socket cases from the report's verdict table and confirm the new expected
  outcomes.
- [ ] ⬜ **Task 4.3**: Add a `truth-changes` entry if any documented statement
  about `sed` usage or handler coverage becomes false for client projects.

## Dependencies

- Related: Plan 00252 (same DBF shape, commit-gate surface, `mv` route). Sequence
  Task 3.1 after 00252's staged-content work if that lands first, and reuse it.
- Related: Plan 00131 (introduced the memory-path bash side-door closure that
  Task 3.1 generalises).
- Corroborated by: Plan 00257's `JOURNAL/00257-Journal-26-08-19.md`, where
  Finding 1 was hit independently and live during the v3.54.0 release (a
  `sed -n` range-read was denied) before this report was verified. That entry
  reaches the same conclusion by a different route and reasons the same way
  about the remedy — fix the guidance, do not loosen the guard — which is worth
  noting because two independent arrivals at one conclusion is the strongest
  evidence here that the defect is real and the fix is the documented one.
  It also records the aggravating factor: the harness instruction pushing
  agents toward Bash-first editing was observed in that same session, so
  Finding 2's premise is not hypothetical.

## Technical Decisions

### Decision 1: Guidance fix and behaviour change are separate

**Context**: Finding 1 reads as a bug, but the surprising behaviour is asserted
by passing tests, so changing it is a deliberate behaviour change, not a fix.

**Options Considered**:

1. Fix guidance only — honest immediately, leaves a rule that is arguably
   over-broad.
2. Loosen the handler so any pipe stage is allowed — changes safety behaviour on
   the strength of a documentation complaint.

**Decision**: Option 1 for Phase 1; Task 1.4 raises the behaviour question
explicitly rather than resolving it by accident. A guidance defect must never be
the justification for a silent safety change.

**Date**: 2026-08-19

## Success Criteria

- [ ] `sed_blocker`'s guidance names `-n`, the command-head case, and the
  `grep`/`echo` condition, and a test pins that.
- [ ] Every Write/Edit-keyed handler has a recorded verdict on Bash blindness,
  enforced by a test.
- [ ] The chosen side-door remedy is implemented, or explicitly declined with a
  recorded rationale.
- [ ] No duplicate implementation of bash-write-target detection remains.
- [ ] Full QA passes and the daemon restarts RUNNING.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes. Blow-by-blow goes in JOURNAL/. -->

- Filed from a verified field report; verification evidence in
  `REPORT-2026-08-18-original.md`.
