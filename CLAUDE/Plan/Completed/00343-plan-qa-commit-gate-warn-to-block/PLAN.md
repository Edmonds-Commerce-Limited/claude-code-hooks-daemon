# Plan 00343: flip the plan QA commit gate from warn to block

**Status**: Complete
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

- [x] ✅ **Task 1.3**: **7 of the 18 are false positives — 39% — and all 7 are
  the same shape.** A whole-tree check denies a commit for state the commit did
  not create and cannot see.

  Five commits (`3d71ff84`, `018b5238`, `b3063f4c`, `4dffe1c9`, `5242b58f`)
  were denied by `row-folder-bijection` over a stale README row for
  `00311-v3590-release-review-followups`. Not one of them touches a file
  mentioning 00311 — they are supervisor and venv-resolver work. Two more
  (`94459b2f`, `080da087`) were denied by `location-status-coherence` over
  plans 00304/00302 sitting in the active root with a terminal header; neither
  commit touches those folders either.

  **Corrected during Phase 3, and the correction is the interesting part.**
  This task first counted `42eb19da` as a sixth `row-folder-bijection` false
  positive, on the reasoning that it too was denied over the 00311 row. It is
  not: `git show 42eb19da^:CLAUDE/Plan/README.md` has no 00311 row and
  `git show 42eb19da:...` has one, so that commit CREATED the broken row and
  is the one commit that should be denied over it. The mistake surfaced only
  because Phase 3's narrowing kept blocking it — the fix disagreed with the
  measurement, and the fix was right. Grouping by symptom rather than by cause
  is what produced the wrong classification.

  The eleven true positives are all self-inflicted: 8 `same-commit-plan-doc`
  fires where the commit's own subject claims a plan whose header still read
  `Not Started`, plus `42eb19da` (added a README row for a folder that does not
  exist), `20714cd7` (scaffolded a plan folder with no README row) and
  `a502f02e` (flipped a status to Complete without moving the folder).

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

- [x] ✅ **Task 3.1**: **The rule is "BLOCK what this commit introduced,
  ADVISE what it inherited"**, lifted from `index-row-length._worsens` rather
  than invented. Three helpers in `checks/common.py` express it:
  `commit_touches_plan` (does the commit stage anything inside this plan's
  folder), `commit_changes_the_folder_set` (does it add/remove/move a plan
  folder — the narrower question a COUNT needs), and `commit_scoped_level`,
  which applies the downgrade and leaves the legacy allowlist and the
  gitfacts-less surfaces alone.

  Without gitfacts the level is unchanged, deliberately. The sweep's job is to
  report the tree as it stands; this narrowing is about who gets BLAMED, not
  about what is true.

- [x] ✅ **Task 3.2**: **`row-folder-bijection` narrowed.** A folder finding
  is the commit's only if it staged something in that folder; a row finding is
  the commit's if it wrote the row (compared against HEAD's parsed README) or
  moved the folder out from under one that was already there. Five tests,
  RED-first — the two false-positive shapes failed, the three true-positive
  and sweep cases passed unchanged, which is what made the RED meaningful.

- [x] ✅ **Task 3.3**: **`location-status-coherence` narrowed.** Every finding
  here is about one folder, so the predicate is `commit_touches_plan` alone.

- [x] ✅ **Task 3.4**: **All four needed it, and all four got it** — the
  survey found no check whose findings cannot be pre-existing, which is the
  opposite of what this task allowed for.

  - `no-new-collisions`: its NAME already promised this ("no NEW collisions",
    "catch it before it lands") while `_run` reported every collision in the
    tree. Narrowed by folder.
  - `index-row-length._run_tree`: now uses its own module's `_worsens` against
    HEAD's README, which is where the principle was written down in the first
    place. A commit that SHORTENS the worst row no longer blocks.
  - `stats-recount`: narrowed by `commit_changes_the_folder_set`, not by
    folder — the finding is about a count, and editing a `PLAN.md` in place
    cannot change what the recount produces.
  - `structure-archive-dirs`: only its misplaced-FOLDER finding is narrowed.
    **"No README index" and "no completed archive" keep blocking
    unconditionally, on purpose**: they are not about a plan, they are about
    the plan directory being usable at all. With no README, `context.readme`
    is None and half the check suite silently no-ops — "carry on and fix it
    later" is not a coherent state to allow.

### Phase 4: Re-measure, then flip

- [x] ✅ **Task 4.1**: **Bar met: 18 → 11 denials, ZERO false positives.**
  Re-run over the IDENTICAL corpus, which took a second attempt to get right —
  the first re-run used "last 250 commits" and this session's own three commits
  had slid the window, silently dropping `20714cd7` (a true positive) from the
  comparison. Re-run at 253 to restore the original set.

  The seven commits that stopped being denied are exactly the seven
  false positives, by hash: `3d71ff84`, `018b5238`, `b3063f4c`, `4dffe1c9`,
  `5242b58f`, `94459b2f`, `080da087`. The eleven that remain are the eleven
  true positives. Nothing was traded away.

- [x] ✅ **Task 4.2**: **Flipped.** `commit_gate_mode: block`, daemon restarted
  (1220370 → 1461157) and `plan-qa --check-staged` clean afterwards.

  Pre-check first: `plan-qa --sweep` reported 0 block / 3 advise on the current
  tree, so the flip could not wedge this repository on day one. The escape
  hatch is one key — set it back to `warn` and restart — and it is named in
  the config comment rather than only in the commit message, because that is
  where somebody hitting an unexpected denial will look.

## Success Criteria

- [x] The set of commit-stage BLOCK-capable checks is written down, not
  inferred — 11 of 16, split into staged-scoped and whole-tree.
- [x] The flip decision cites a replay count and a false-positive
  classification, not a judgement call — 250 commits, 18 denials, 8 false
  positives, one shared shape.
- [x] No commit-stage check can BLOCK a commit over plan-tree state that
  commit did not touch. Six checks narrowed; the 253-commit replay confirms it
  end to end — seven inherited-state denials gone, eleven caused-here denials
  kept.
- [x] `commit_gate_mode` and its config comment agree with each other and with
  reality. The comment now records the measurement and the escape hatch
  instead of an open-ended promise.
- [x] Full QA green (25/25) and the daemon restarted and verified before the
  terminal status flip. 18,349 tests, 95.2% coverage; daemon 1220370 →
  1461157 with `block` mode live and `plan-qa --check-staged` clean after.

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
