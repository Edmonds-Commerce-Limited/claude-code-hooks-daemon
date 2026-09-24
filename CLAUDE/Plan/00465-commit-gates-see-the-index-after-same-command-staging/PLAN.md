# Plan 00465: commit gates see the index after same command staging

**Status**: Not Started
**Created**: 2026-09-24
**Owner**: dev
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration (worktree, TDD)

## Overview

**From 00422 N26, found by Plan 00464's agent.** Every PreToolUse commit
gate reads the index BEFORE any part of the command has run. So
`git add <file> && git commit -m x` commits content that no staged-content
check ever examined. That includes the secret-term scan, plan QA, docs
QA, staged lint and remote-docs provenance. `git add -A && git commit` is
one of the most common commit shapes there is.

**Evidence, both directions.**

- **Fail open.** The agent's probe (in the 00464 worktree:
  `untracked/scratch/p464_probe_same_command_add.py`, recorded in 00464's
  JOURNAL, T1.3) uses a real repo with an unstaged file carrying a listed
  term. `git add leak.md && git commit -m ok` gives `matches=False`. After
  a separate `git add`, the same commit gives `matches=True`.
- **False deny.** The coordinator's own close-out of Plans 00458 and 00459
  was denied by `R-PLAN-QA-COMMIT` for README links to `Completed/…`. The
  `git mv` that created those folders sat earlier in the SAME command, so
  the gate judged a tree that did not exist yet.

**Starts after 00464 merges.** Plan 00464 moves every commit gate onto a
shared effective-repository resolver. This plan changes the same gates,
and doing both in parallel would conflict. 00464 also adds a `git merge`
scan, which limits the damage meanwhile: content committed this way in a
worktree reaches `main` only through a merge, and the merge scan reads it.

## Goals

- No commit gate passes a commit it did not see. A `git commit` whose
  command also stages or moves content earlier in the chain is judged on
  the index the commit will actually record, or is refused with a message
  saying to stage in one call and commit in the next.
- Decide between the two candidate remedies with evidence, and record the
  decision:
  1. **Deny the chained shape.** It is simple and fails closed, but it
     costs a round trip on the most common commit idiom.
  2. **Simulate.** Replay the staging commands against a temporary
     `GIT_INDEX_FILE` copy of the index and judge that. It is precise, but
     the staging commands include `git add -A`, `git rm`, `git mv`, and
     `git add -p` (interactive, cannot be simulated), and any unsupported
     shape must fall back to (1).
- `git commit -a`/`--all` and pathspec commits are covered consistently.
  The sensitive-content scan already reads the working tree for `-a`;
  make sure every gate does the same.

## Non-Goals

- Changing what any gate checks.

## Tasks

### Phase 1: TDD in a worktree

- [ ] ⬜ **Task 1.1**: Decide remedy 1, remedy 2, or a hybrid (simulate
  the supported shapes, deny the rest), with the trade-off measured, and
  journal it.
- [ ] ⬜ **Task 1.2**: RED tests per gate for `git add X && git commit`,
  `git add -A; git commit`, `git mv A B && git commit`,
  `git rm X && git commit` and `git commit -a`. Each carries a violation
  that exists only after the staging step. Include the false-deny case
  (a `git mv` that makes a README link valid).
- [ ] ⬜ **Task 1.3**: Implement it on 00464's shared resolver. Update the
  docs, the handler guidance (the `sensitive_content` guidance currently
  says "the commit is the gate" without this caveat), the Security class
  doc, and a release note.
- [ ] ⬜ **Task 1.4**: Targeted QA (Plan 00463 rule). The coordinator runs
  the full gate.

### Phase 2: Deliver

- [ ] ⬜ **Task 2.1**: The coordinator runs full QA, merges `--no-ff`,
  verifies ancestry and CI, and restarts the daemon.
- [ ] ⬜ **Task 2.2**: Live check both directions in the main checkout.
  Mark 00422 N26 remedied.

## Success Criteria

- [ ] `git add <file-with-term> && git commit` is denied, or judged on the
  staged result, by the sensitive-content scan and by every other commit
  gate.
- [ ] A same-command `git mv` no longer causes a false plan-QA deny.
- [ ] Full QA passes (run by the coordinator) and CI is green.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00465-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Not yet delivered.
