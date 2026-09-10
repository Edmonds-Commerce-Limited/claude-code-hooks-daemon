# Plan 00372: worktree reap two defects

**Status**: Complete
**Created**: 2026-09-10
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

`bin/hooks-daemon worktree-reap` was run live in this repository and two
defects surfaced immediately, one of them a real data-loss hazard.

**Defect 1** — a worktree created seconds earlier for an actively-working
sub-agent was listed as safe to reap. It had made no commits yet, so every
existing safety predicate (`uncommitted_paths`, `commits_ahead_of_base`,
`unlanded_patches`) passed vacuously: a worktree with no history of its own
is exactly as consistent with "just started" as with "finished and gone
stale," and nothing in `core/worktree_reaping.py` could tell the two apart.
Reaping it would have silently destroyed the agent's in-flight work. The fix
adds two independent, additive signals to `WorktreeState` — a live process
whose cwd resolves inside the worktree (read from `/proc/*/cwd`, never
`pgrep -f`, which this repo already forbids for self-match reasons), and a
minimum-age gate below which a history-free worktree is refused regardless
of what else is true about it.

**Defect 2** — reaping three genuinely finished worktrees reported, for
each, that git "kept" the branch while the same message quoted git saying
the branch was "not found." The branch delete never once succeeded, for any
worktree, ever: `reap_worktree` and `prune_branch` both call
`git branch -d refs/heads/<name>`, and `git branch -d` — unlike the general
ref-resolving commands (`rev-parse`, `cherry`, `merge-base`) that motivated
`branch_ref()` in Plan 00254 — does not accept a fully-qualified ref at all;
it resolves its argument directly inside `refs/heads/` and rejects anything
already qualified. Verified live in a throwaway repository before writing
the fix. The two-line diff is passing the bare branch name instead, which
also matches this project's own `destructive_git` guidance ("`git branch -d <name>` — ALWAYS TRY THIS FIRST").

## Goals

- A worktree with no commits of its own is refused when it is recently
  created OR has a live process running inside it, with a KEEP message that
  states which (or both) applied.
- `reap_worktree` and `prune_branch` actually delete a fully-merged branch's
  ref on the success path, and every failure message states one true thing
  (never "kept" alongside a "not found" from the same git call).
- A regression test reproduces each defect against real git/real `/proc`
  before the fix, not just against a fake that assumed the buggy argv was
  correct.

## Non-Goals

- Not building a general "who is using this directory" utility for reuse
  elsewhere in the daemon — the `/proc/*/cwd` scan is scoped to
  `worktree_reaping.py`, matching its existing self-contained style.
- Not making the age window configurable via a CLI flag or YAML key; it is a
  single module constant (`MINIMUM_AGE_SECONDS`), consistent with the
  other sentinels already local to this module (`UNKNOWN_COUNT`).
- Not touching `collect_orphaned_branches`'s classification — the branch-scan
  half of Defect 2's fix is confined to the two `git branch -d` call sites.
- Not revisiting Plan 00254's `branch_ref()` guidance for the commands it
  actually applies to (`rev-parse`, `cherry`, `merge-base`, diff ranges) —
  those remain correct; only the two misapplied `git branch -d` call sites
  are in scope here.

## Tasks

### Phase 1: Defect 2 — the branch delete that never worked

- [x] ✅ **Task 1.1**: RED — a test that mimics real git's actual constraint
  (`git branch -d` rejects a `refs/heads/`-qualified argument) reproduces the
  exact observed message text for both `reap_worktree` and `prune_branch`.
- [x] ✅ **Task 1.2**: GREEN — both call sites pass the bare branch name.
  Correct the two docstring/comment spans that state the now-disproven
  "bare name risks resolving a same-named tag" rationale for `-d`
  specifically (that rationale is real for `rev-parse`/`cherry`/etc., not for
  `branch -d`, which resolves only inside `refs/heads/`).
- [x] ✅ **Task 1.3**: Update the three existing test files
  (`test_worktree_reap_action.py`, `test_orphaned_branches.py`,
  `test_cli_worktree_reap_branches.py`, `test_cli_worktree_reap.py`) that
  hard-coded the buggy full-ref argv as the expected call, including the
  docstring narrative in `test_orphaned_branches.py` that repeats the
  disproven tag-ambiguity claim for `-d`.

### Phase 2: Defect 1 — a history-free worktree is not evidence it is finished

- [x] ✅ **Task 2.1**: RED — a real-git regression test in
  `test_worktree_collection.py` builds a freshly-created worktree (the exact
  shape `test_a_worktree_at_the_base_is_reapable` asserted reapable) and
  shows it is refused; a second test proves discrimination by backdating the
  worktree's `.git` pointer-file mtime and showing an old, otherwise-clean
  worktree stays reapable.
- [x] ✅ **Task 2.2**: RED — a real subprocess with its cwd set inside a
  backdated (old) worktree still gets refused, proving the live-process
  signal is independent of the age signal rather than redundant with it.
- [x] ✅ **Task 2.3**: GREEN — `WorktreeState` gains `live_process_pids` and
  `age_seconds`; `reap_refusal_reason` refuses on either, each with a KEEP
  message that plainly states which pid(s) or which age tripped it, in the
  voice of the existing messages; `collect_worktree_states` gains injectable
  `process_cwds_fn` / `age_fn` parameters (defaulted to real `/proc` and
  real `stat`), mirroring the existing `run_fn` DI pattern.
- [x] ✅ **Task 2.4**: Update `test_a_worktree_at_the_base_is_reapable` (now
  incorrect under the new rule) and any other pre-existing real-git test that
  asserted a just-created worktree reapable.

### Phase 3: Verify

- [x] ✅ **Task 3.1**: Restart the worktree's own daemon, then full QA
  (`./scripts/qa/llm_qa.py all`) — 25/27 green; the 10 `pyright` errors are
  pre-existing and outside four files this plan never touched, and every
  file this plan touched is individually pyright-clean.
- [x] ✅ **Task 3.2**: Release-notes callout added under
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/`.

## Success Criteria

- [x] Both defects have a test that fails against pre-fix code and passes
  post-fix, and at least one of each is a real git / real `/proc` test, not
  only a fake.
- [x] `reap_refusal_reason` refuses a history-free worktree that is either
  under `MINIMUM_AGE_SECONDS` old or has a live process inside it, and stays
  silent on that axis for one that is neither.
- [x] `reap_worktree` and `prune_branch` delete a fully-merged branch's ref
  on the success path (verified against real git, not just a fake that
  always returns success).
- [x] QA green on every check this plan's changes could affect (magic
  values, error hiding, format, lint, the full test suite); no
  suppressions. `pyright` carries 10 pre-existing errors, all in four files
  this plan never touched (`core/result_types.py` and three tests under
  `handlers/`); every file this plan touched is individually pyright-clean.
- [x] Every release-bound consequence is in the pending-release holding
  area: `CLAUDE/UPGRADES/UNRELEASED/release-notes/24-worktree-reap-fresh-worktree-and-branch-delete.md`.
- [x] This plan folder is committed alongside the work; PLAN.md tasks are
  ticked and Status is `Complete` before hand-off to the coordinator for
  archiving on `main`.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00372-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Filed on `main`; implementation proceeds in
  `untracked/worktrees/worktree-plan-00372`.
- Defect 2 (branch delete) fixed, `edfacfdc`.
- Defect 1 (fresh-worktree guard) fixed, `259227ef`.
- Release-notes callout, `8f6207eb`.
- QA fixes (magic value, error-hiding exclusions, format), branch pushed;
  ready for the coordinator to merge and archive.
