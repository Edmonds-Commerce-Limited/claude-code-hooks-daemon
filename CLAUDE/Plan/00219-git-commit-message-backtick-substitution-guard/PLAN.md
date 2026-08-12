# Plan 00219: git commit message backtick substitution guard

**Status**: Not Started
**Created**: 2026-08-12
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Backticks inside a **double-quoted** `git commit -m "..."` are not quoted —
bash performs command substitution. The backticked span is **executed**, and
its stdout replaces the text in the message.

This is not theoretical. It happened in this repo while writing a commit
message that described a handler interaction in backticks. Bash ran the
command, it printed a `fatal:` line to stderr and nothing to stdout, and the
commit landed with the phrase silently deleted from its body. The `fatal:`
read as git rejecting the commit; it was bash running a command nobody asked
it to run. The commit itself succeeded.

Two distinct failure modes, and they need separating because their severity
and their existing coverage differ:

1. **Message corruption** (what happened). Silent, and there is currently
   nothing that detects it — no handler, no QA check, no test.
2. **Unintended execution**. A message describing a destructive command in
   backticks would run it. This is **already covered** for the dangerous
   cases: the blocking handlers match the FULL Bash command string, so
   `destructive_git` / `sed_blocker` / the rest deny it before bash sees it.
   That is the same string-matching that produces the documented
   commit-message false positives, and it is real defence rather than luck.

So the gap worth closing is (1). Treating this plan as a security fix would
overstate it and would risk duplicating protection that already works.

## Context & Background

The corrupting commit is on `main`; its body reads "pipe_blocker now allows ,
so the force-delete form" where a backticked command used to be. It was not
amended, because `git commit --amend` is blocked in this repo — which is
itself part of the argument for a write-time guard: there is no cheap
after-the-fact repair, so the only effective place to catch this is before
the commit runs.

The lesson is recorded in `CLAUDE/development/LESSONS.md` ("Backticks in a
double-quoted `-m` message are executed, not quoted").

## Goals

- Detect an unescaped backtick inside a double-quoted `-m` message and warn
  before the commit runs, naming the substitution that is about to happen.
- Keep single-quoted `-m '...'` completely unaffected — no substitution
  happens there, and backticks are legitimate markdown in that form.

## Non-Goals

- **Re-solving the execution risk.** Already covered by full-command-string
  matching in the existing blocking handlers. Verify that claim rather than
  assume it, but do not build a second layer.
- Blocking. A false positive here denies a commit, which is expensive and
  will get the handler switched off. Advisory unless measurement justifies
  otherwise.
- Parsing shell exhaustively. `$(...)` substitution has the same effect and
  should be considered, but a full shell parser is not warranted.

## Tasks

### Phase 1: Establish the real shape before writing a rule

- [ ] ⬜ **Task 1.1**: Confirm the execution half is genuinely covered — probe
  the live daemon with a destructive command inside backticks in a commit
  message and verify it is denied. If it is NOT, that changes this plan's
  priority entirely and should be raised immediately
- [ ] ⬜ **Task 1.2**: Measure against this repo's own history: how many past
  commit messages contain backticks, and how many of those were
  single-quoted (safe) versus double-quoted (would have substituted)? A rule
  that would have fired constantly on legitimate history is the wrong rule
- [ ] ⬜ **Task 1.3**: Decide advisory vs blocking from that measurement, and
  record the decision with its numbers under Technical Decisions

### Phase 2: Implement

- [ ] ⬜ **Task 2.1**: TDD the detection — unescaped backtick or `$(` inside a
  double-quoted `-m` argument. Escaped and single-quoted forms must not fire
- [ ] ⬜ **Task 2.2**: Make the message name the concrete remedy: single-quote
  the `-m`, or use `git commit -F <file>`
- [ ] ⬜ **Task 2.3**: Add `get_claude_md()` guidance and a
  `get_acceptance_tests()` entry

### Phase 3: Verify

- [ ] ⬜ **Task 3.1**: Full QA, daemon restart RUNNING, and a live probe
  through the production forwarder — not a hand-rolled socket client
- [ ] ⬜ **Task 3.2**: Stage a `config-changes` entry if the handler ships
  enabled

## Dependencies

- Related: Plan 00209, whose merge is the commit that got corrupted.

## Success Criteria

- [ ] A double-quoted `-m` containing an unescaped backtick is flagged before
  the commit runs
- [ ] Single-quoted `-m` and escaped backticks never fire
- [ ] The false-positive rate is measured against this repo's real commit
  history, not asserted
- [ ] The execution half is confirmed already-covered, with evidence

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00219-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Defect hit live while committing Plan 00209 follow-up work; lesson recorded
