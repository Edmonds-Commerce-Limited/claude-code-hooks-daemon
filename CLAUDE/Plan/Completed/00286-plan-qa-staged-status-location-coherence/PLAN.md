# Plan 00286: plan qa staged status location coherence

**Status**: Complete
**Created**: 2026-08-28
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

`bin/hooks-daemon plan-qa --check-staged` reported "0 findings" for a commit
whose staged tree held `CLAUDE/Plan/Completed/00284-.../PLAN.md` with a
STAGED status of `In Progress` — a non-terminal status sitting inside the
archive directory. The field sequence was: the status flip to a terminal
value was made in the worktree, then `git mv` staged the folder's rename
using the index's existing (pre-flip) blob, and the flip itself was never
re-`git add`ed. The commit landed the inconsistency (fixed forward in
`bf159461`).

`location-status-coherence`'s COMMIT-stage registration exists to catch
exactly this shape, but its `_run` reads `context.tree`, which
`staged_context()` builds by scanning the **worktree filesystem**
(`PlanTree.scan`), not the staged git blobs. By the time anyone inspects the
session the worktree file usually already carries the correct (fixed)
content, so the check silently passes even though the STAGED blob that
`git commit` would actually write is still wrong. `terminal-state-atomic`
gets this right — it reads `gitfacts.staged_file_text()` — but only checks
the flip→must-also-move direction, not the mv→must-carry-terminal-status
direction.

This plan adds a new commit-gate-only check, `archived-status-coherence`,
that reads the STAGED content of any `PLAN.md` staged under an archive
directory and flags a non-terminal (or unparseable) status header in that
staged content specifically — independent of what the worktree file
currently says.

## Goals

- Add a `plan_qa` check that inspects the STAGED blob (not the worktree) of
  every staged `PLAN.md` change located under an archive directory, and
  flags a non-terminal or missing status header found there.
- Register it at `Stage.COMMIT` only (this is a staged-vs-worktree
  divergence check; the SWEEP stage already has `location-status-coherence`
  reading worktree state, which is the correct surface for on-disk drift).
- Respect `legacy_plan_allowlist` (ADVISE instead of BLOCK) and the existing
  `commit_gate_mode` (`warn` default) the same way every other commit-gate
  check does.
- Reproduce the exact field sequence in a TDD test (stage a rename without
  re-staging the content flip) and confirm the new check fires.
- Confirm the check stays silent on a correct atomic archive commit
  (terminal status staged + folder moved in the same commit).

## Non-Goals

- Not changing `location-status-coherence` or `terminal-state-atomic`
  themselves — this is an additive check filling the specific staged-blob
  gap, not a rewrite of the existing coherence checks.
- Not making the commit gate `block` by default — stays under the shared
  `commit_gate_mode` policy (`warn` rollout default).

## Tasks

### Phase 1: Reproduce and design

- [x] ✅ **Task 1.1**: Reproduce the field sequence in a scratch git repo:
  stage a status flip to terminal in the worktree, `git mv` the folder
  without re-adding, and confirm `location-status-coherence`'s COMMIT
  registration misses it (worktree already shows the flip).

### Phase 2: TDD implementation

- [x] ✅ **Task 2.1**: Write failing tests for a new
  `archived-status-coherence` check under
  `tests/unit/plan_qa/checks/test_archived_status_coherence.py`, covering:
  the field sequence (rename staged, flip not re-added → BLOCK), a correct
  atomic archive commit (silent), a non-terminal status genuinely staged
  fresh into the archive dir (BLOCK), an unparseable/missing status header
  staged into the archive dir (BLOCK), and legacy-allowlist downgrade to
  ADVISE.
- [x] ✅ **Task 2.2**: Implement
  `src/claude_code_hooks_daemon/plan_qa/checks/archived_status_coherence.py`
  reading staged blobs via `GitFacts.staged_file_text`, following the
  conventions in `terminal_state_atomic.py` and `common.py`.
- [x] ✅ **Task 2.3**: Register the check in
  `src/claude_code_hooks_daemon/plan_qa/checks/__init__.py`.

### Phase 3: Verification

- [x] ✅ **Task 3.1**: Run the full unit suite for `plan_qa` and QA
  (`./scripts/qa/llm_qa.py all`) fully green.
- [x] ✅ **Task 3.2**: `bin/hooks-daemon restart && bin/hooks-daemon status`
  → RUNNING.
- [x] ✅ **Task 3.3**: Live-verify `plan-qa --check-staged` against a
  synthesised staged state reproducing today's field case, and confirm a
  correct atomic archive commit stays clean.
- [x] ✅ **Task 3.4**: Update `docs/guides/HANDLER_REFERENCE.md`'s
  `plan_qa_commit_gate` invariants list to name the new check.

## Success Criteria

- [x] `archived-status-coherence` check exists, is registered at
  `Stage.COMMIT`, and is BLOCK level (ADVISE for legacy-allowlisted plans).
- [x] The exact field sequence (rename staged, content flip not re-added) is
  now flagged by `plan-qa --check-staged`.
- [x] A correct atomic archive commit (terminal status staged + move staged
  together) produces no finding from the new check.
- [x] Full QA suite green; daemon restarts and reports RUNNING.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00286-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Plan scaffolded and indexed at 07da31ea.
- Check implemented, registered, documented and verified at c7633e3f (QA 25/25; daemon RUNNING; live-verified: staged non-terminal status under Completed/ flagged as BLOCK, correct atomic archive silent).
