# Plan 00373: drift reached main unseen — merge bypass and QA blind spot

**Status**: In Progress
**Created**: 2026-09-10
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Main Thread

## Overview

Plan 00372 was archived to `Completed/` in `69803a2c`. Its worktree branch had
been cut before that archive, so when the branch wrote its subagent build
report it wrote to the plan's old ACTIVE path. Merge `a85e00e8` landed that
file on main, resurrecting `CLAUDE/Plan/00372-worktree-reap-two-defects/` as a
second folder claiming plan number 00372 — a folder with no `PLAN.md` in it.
Plan QA had four findings to make about this (`no-new-collisions`,
`row-folder-bijection`, `location-status-coherence`, `stats-recount`).

Nothing said a word. The drift sat on main through a full `27/27 PASSED` QA
run, a green CI run, and a `release-slate-check` whose only complaint was live
worktrees. Two independent gates were missing, and either alone would have
caught it.

The first is a bypass. `plan_qa_commit_gate.matches()`, and its siblings
`docs_qa_commit_gate` and `staged_lint_gate`, all key on a `git commit` Bash
command. A `git merge` (or `git pull`) creates a commit WITHOUT invoking
`git commit`, so no commit-stage gate ever saw the commit that introduced this.
Plan 00252 already named the principle for write-time guards — a guard that
only fires on one route does not cover what arrives by another — and this is
the same defect one stage later.

The second is a blind spot. `scripts/qa/llm_qa.py`'s `TOOL_REGISTRY` carries 27
tools and neither `plan-qa --sweep` nor `docs-qa --sweep` is among them, though
both are shipped CLI verbs that exit non-zero on findings and both support
`--json`. So the plan tree and the doc corpus can drift arbitrarily far without
QA, CI or the release slate registering anything.

## Goals

- Repair the plan-tree and doc-corpus drift currently on main.
- Make `plan-qa --sweep` and `docs-qa --sweep` first-class QA tools, so drift
  in either corpus fails QA and therefore CI and the release gate.
- Give the commit-stage gates coverage of commits that arrive by merge, so a
  merge can no longer land plan or doc drift unremarked.

## Non-Goals

- Changing what any individual plan-QA or docs-QA check decides. The checks
  were right; nothing consulted them.
- Promoting existing advisory findings to block level. The advise/block
  ratchet and `commit_scoped_level`'s inherited-state narrowing stay as they
  are.
- Blocking a `git merge` before it runs. The merge result does not exist until
  the merge does; this plan reports what a merge introduced, it does not
  predict it.

## Tasks

### Phase 1: Repair the drift now on main

- [x] ✅ **Task 1.1**: Re-home the orphaned 00372 build report into
  `Completed/00372-worktree-reap-two-defects/subagent-reports/`, clearing all
  four plan-QA findings. Delivered in `7a722965`.
- [ ] ⬜ **Task 1.2**: Clear the four `docs-qa --sweep` findings — two
  `module-doc-budget` over-runs (`src/CLAUDE.md`,
  `src/claude_code_hooks_daemon/strategies/lsp_noise/CLAUDE.md`) and two
  `duplicate-block` findings (`CLAUDE/Architecture/StatusLine.md` against
  `README.md`, `CLAUDE/PROJECT_HANDLERS.md` against
  `CLAUDE/core/Worktree.core.md`).

### Phase 2: The sweeps become QA tools

- [ ] ⬜ **Task 2.1**: Add `plan_qa` and `docs_qa` `ToolConfig` entries to
  `scripts/qa/llm_qa.py`'s `TOOL_REGISTRY`, each invoking its CLI verb with
  `--json`, plus a summarizer apiece reporting finding counts split by level.
- [ ] ⬜ **Task 2.2**: Cover both tools with tests asserting that a tree with
  a seeded finding fails the tool, so a sweep that silently stops running
  cannot read as a pass.

### Phase 3: Commit-stage gates cover the merge route

- [ ] ⬜ **Task 3.1**: Write the failing test first — `git merge --no-ff x` is
  matched by none of `plan_qa_commit_gate`, `docs_qa_commit_gate` or
  `staged_lint_gate`, and that is the hole.
- [ ] ⬜ **Task 3.2**: Teach `GitFacts` to source its change set from a commit
  RANGE (`ORIG_HEAD..HEAD`) as well as from the index, leaving every consumer
  of `staged_changes()` — `commit_touches_plan` and its siblings — unchanged.
- [ ] ⬜ **Task 3.3**: Add a PostToolUse handler that, after a `git merge` or
  `git pull` that created a commit, runs the plan-QA and docs-QA checks
  attributed to `ORIG_HEAD..HEAD`, and reports what the merge introduced. The
  merge has already landed, so this is a failure report to repair, in the same
  idiom as `lint_on_edit`.

## Success Criteria

- [ ] `bin/hooks-daemon plan-qa --sweep` and `bin/hooks-daemon docs-qa --sweep`
  both exit 0 on main.
- [ ] `scripts/qa/llm_qa.py all` runs both sweeps and fails when either finds
  drift.
- [ ] Replaying the 00372 scenario — merging a branch that writes into an
  archived plan's old active path — produces a report naming the finding.
- [ ] Full QA passes and CI is green.

## Delivery & Milestones

- `7a722965` — Task 1.1: the orphaned build report re-homed, plan tree clean.
