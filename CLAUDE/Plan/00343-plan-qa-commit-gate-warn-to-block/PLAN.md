# Plan 00343: flip the plan QA commit gate from warn to block

**Status**: In Progress
**Created**: 2026-09-07
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Opus
**Execution Strategy**: Single agent

## Overview

`plan_workflow.qa.commit_gate_mode` has been `warn` since the plan QA commit
gate shipped, and the config comment states the intent plainly: "warn-first
rollout; flip to block after clean dogfooding". Nothing has decided whether
that dogfooding is now clean, so the flip has simply never been revisited.

In `warn` mode `PlanQaCommitGateHandler` renders EVERY finding as advisory
regardless of level — only `_MODE_BLOCK` converts a `Level.BLOCK` finding into
a DENY. So the gate's entire BLOCK tier is currently decorative, and adding
more BLOCK-level checks does not change that.

That is not hypothetical. **Plan 00341 was filed because an advisory fired on
commit `923fd583` and the plan stayed `Not Started` for five days anyway** —
an advisory is a suggestion an agent mid-commit is free to scroll past, and one
did. 00341 shipped a correct BLOCK-level finding and then had to record that
BLOCK-level is not the same as blocking. This plan is the lever it deliberately
did not pull, because flipping the mode changes the behaviour of EVERY plan QA
commit check at once and that is a project-wide decision, not a side effect of
one check.

## Goals

- Decide, with measured evidence rather than argument, whether
  `commit_gate_mode: block` is safe for this repository today.
- If it is, flip it and record what the first blocked commit looked like.
- If it is not, name precisely which checks are not ready and why, so the
  question is answerable next time rather than re-opened from scratch.

## Non-Goals

- Changing any individual check's level. Which findings are BLOCK is each
  check's own decision; this plan only decides whether BLOCK means anything.
- Changing `documentation.qa.commit_gate_mode`. The docs QA gate has its own
  warn-first rollout, its own checks and its own false-positive profile — it
  deserves the same treatment but not the same commit.
- Changing `edit_mode` (already `block`) or `sweep_mode` (already `advise`).

## Tasks

### Phase 1: Measure before deciding

- [x] ✅ **Task 1.1**: **11 of the 16 commit-stage checks can emit a
  `Level.BLOCK` finding**, and they split cleanly on the axis that turned out
  to matter — whether the check judges what THIS commit did, or the state of
  the whole plan tree.

  Staged-scoped (consult `context.gitfacts`): `archived-status-coherence`,
  `counter-sanity`, `index-at-birth`, `same-commit-plan-doc`,
  `terminal-state-atomic`.

  Whole-tree (walk `context.tree` / `context.readme`, no reference to the
  staged changes at all): `location-status-coherence`, `no-new-collisions`,
  `row-folder-bijection`, `stats-recount`, `structure-archive-dirs`, and
  `index-row-length` — whose `_run_tree` blocks on any over-limit row, though
  its EDIT-stage sibling does not (see Task 1.3).

  The five that stay ADVISE at commit stage: `journal-entry-with-progress`,
  `journal-completion-entry`, `index-no-log`, `plan-ref-format`,
  `plan-shrink-without-journal`.

- [x] ✅ **Task 1.2**: **Replayed over 250 commits: 18 would have been
  DENIED (7.2%).** `untracked/scratch/replay_commit_gate.py` materialises each
  commit's own `CLAUDE/Plan` tree with `git archive` and answers `gitfacts`
  from that commit against its parent, so each check sees the tree as it was
  rather than as it is now. That distinction is not cosmetic: Plan 00341's
  measurement read TODAY's status and found 2 fires of `same-commit-plan-doc`;
  reading the status as of each commit finds 8. Same rule, same corpus — the
  earlier number was an artefact of measuring against a tree that had since
  been fixed.

  By check: `row-folder-bijection` 13, `same-commit-plan-doc` 8,
  `location-status-coherence` 3, `terminal-state-atomic` 1, `index-at-birth` 1
  (26 findings over 18 distinct commits).

- [x] ✅ **Task 1.3**: **8 of the 18 are false positives — 44% — and all 8 are
  the same shape.** A whole-tree check denies a commit for state the commit did
  not create and cannot see.

  Six commits (`3d71ff84`, `018b5238`, `b3063f4c`, `4dffe1c9`, `5242b58f`,
  `42eb19da`) were denied by `row-folder-bijection` over a stale README row for
  `00311-v3590-release-review-followups`. Not one of them touches a file
  mentioning 00311 — they are supervisor and venv-resolver work. Two more
  (`94459b2f`, `080da087`) were denied by `location-status-coherence` over
  plans 00304/00302 sitting in the active root with a terminal header; neither
  commit touches those folders either.

  The ten true positives are all self-inflicted: 8 `same-commit-plan-doc`
  fires where the commit's own subject claims a plan whose header still read
  `Not Started`, plus `20714cd7` (scaffolded a plan folder with no README row)
  and `a502f02e` (flipped a status to Complete without moving the folder).

  **The project already has the right answer written down.** `index-row-length`
  fixed this exact problem at EDIT stage with `_worsens(before, after)`, whose
  docstring states the principle outright: "an already-degraded index is never
  trapped". Its own `_run_tree` — the COMMIT path — never adopted it.

### Phase 2: The verdict — not yet, and here is exactly why

- [x] ✅ **Task 2.1**: **Not flipped.** Phase 1 is not clean, so this task's
  precondition failed. Recorded rather than quietly dropped, because "we did
  not flip" is the result, and the reason has to travel with it.

- [x] ✅ **Task 2.2**: **`row-folder-bijection` and
  `location-status-coherence` produced every false positive**, and the
  narrowing is Phase 3 below rather than a vague follow-up.

  The consequence of flipping today is worse than 44% suggests. These checks
  are not merely noisy — they are STICKY. One stale README row denies EVERY
  subsequent commit until somebody fixes that row, including commits that have
  nothing to do with plans. The 00311 row survived at least six commits, so
  the flip would have wedged ordinary work six times over one unrelated
  mistake.

- [x] ✅ **Task 2.3**: **Config comment updated** to state the measured
  position — 250-commit replay, 18 denials, 44% false positives from
  whole-tree checks — instead of an open-ended promise nobody was tracking.

### Phase 3: Narrow the whole-tree checks so a clean commit is never trapped

- [ ] ⬜ **Task 3.1**: Establish the rule from the precedent rather than
  inventing one. `index-row-length._worsens` already decides this exact
  question at EDIT stage: block when the change makes things worse, advise
  when it merely fails to fix what was already broken. The commit-stage
  equivalent is a comparison against HEAD, which `GitFacts.head_file_text`
  already supports.

- [ ] ⬜ **Task 3.2**: Apply it to `row-folder-bijection` — a finding about a
  folder or row the commit did not touch drops to ADVISE; one the commit
  created or broke stays BLOCK. TDD, with the six replayed false positives as
  the fixtures.

- [ ] ⬜ **Task 3.3**: Apply it to `location-status-coherence`, same rule,
  same fixture discipline. `94459b2f` and `080da087` are the cases to pin.

- [ ] ⬜ **Task 3.4**: Decide whether `stats-recount`,
  `structure-archive-dirs`, `no-new-collisions` and `index-row-length._run_tree`
  need the same treatment. None fired in the replay, so this is a question
  about SHAPE, not observed pain — and the answer may legitimately be "leave
  them" if their findings cannot be pre-existing. Record which, and why.

### Phase 4: Re-measure, then flip

- [ ] ⬜ **Task 4.1**: Re-run the 250-commit replay after Phase 3. The bar is
  zero false positives, not a smaller number: a sticky false positive blocks
  every commit after it, so a low rate is not a low cost.

- [ ] ⬜ **Task 4.2**: If the bar is met, flip `commit_gate_mode` to `block`
  and restart the daemon. Name the escape hatch in the commit message — the
  mode is one config key, so reverting is one edit.

## Success Criteria

- [x] The set of commit-stage BLOCK-capable checks is written down, not
  inferred — 11 of 16, split into staged-scoped and whole-tree.
- [x] The flip decision cites a replay count and a false-positive
  classification, not a judgement call — 250 commits, 18 denials, 8 false
  positives, one shared shape.
- [ ] No commit-stage check can BLOCK a commit over plan-tree state that
  commit did not touch.
- [ ] `commit_gate_mode` and its config comment agree with each other and with
  reality.
- [ ] Full QA green (25/25) and the daemon restarted and verified before the
  terminal status flip.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00343-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Source: Plan 00341 Task 3.2, which reached this lever and deliberately left
  it unpulled — see that plan's journal entry "BLOCK-level is not the same as
  blocking".
- Prior art: Plan 00144 introduced the plan QA subsystem and its warn-first
  rollout; Plan 00341 added the first commit-stage BLOCK finding that the flip
  would arm.
