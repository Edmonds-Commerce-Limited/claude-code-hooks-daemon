# Plan 00558: branch WIP limit and hygiene (v2)

**Status**: In Progress
**Created**: 2026-11-02
**Revised**: 2026-11-03 (v2; v1 was report-only, see [CRITIQUE-v1.md](CRITIQUE-v1.md))
**Owner**: dev
**Priority**: High
**GitHub Issue**: #152 (related: #153)
**Recommended Executor**: Opus for Phase 1 design, Sonnet for the build tasks
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Agent sessions create branches and worktrees far faster than anything removes them. Three installations show it:

- **This repository, 3 November 2026:** 52 linked worktrees, 56 local and 44 remote branches. 49 worktrees and 39 remote branches held nothing that was not on `main`. The manual triage is in this plan's journal.
- **#152:** one project reached about 1,100 local branches, 290 remote branches and 380 worktrees in a few weeks. Some branches were merged and never deleted; others were left mid-operation by sub-agents that stopped on a rate limit or context budget, or waited on a human decision and were forgotten.
- **#152 follow-up comment (a second installation):** about 250 unmerged remote branches across 40 repositories waiting for a human to delete them. The reporter classified roughly 40% as merged into a long-lived integration line (a release or epic branch), not the default branch; roughly 15% as the same task restarted on a new branch; and most of the abandoned share as sub-agents that stopped part-way.

Today nothing holds a limit (code facts with citations: [subagent-reports/261103-issue-152-code-facts.md](subagent-reports/261103-issue-152-code-facts.md)):

- `branch_count_advisor` is advisory, runs only at SessionStart on new sessions, and counts only local `worktree-*` and `agent-*` branches. The daemon's own `worktree_create` names its branches `<slug>-<8hex>`, so the advisor counts only those whose slug happens to start with `worktree` or `agent`, and misses the rest.
- `worktree_create`'s branches are never deleted: WorktreeRemove leaves them behind.
- No Stop or SubagentStop handler looks at git state.
- No hook acts on branch creation.
- The remote-delete guard (R-GIT-PUSH-DELETE-REMOTE) treats a branch as deletable only when it is an ancestor of the default branch, with no notion of an integration line. It also times out on a large delete (#153).
- The default branch is decided in three separate places: `git_sync.default_branch` resolves it (`origin/HEAD`, then `main`/`master`), while `delete-branch --protected-ref` and `worktree-reap --base-branch` default to `main` unless the caller overrides them. No project setting names it or any integration line.

## Goals

01. **One branch model.** A single inventory module and a single config surface used by every branch feature:
    - the default branch, and a list of integration-line patterns (for example `release/*`, `epic/*`) that count as merge targets;
    - an exempt list (never counted, never deleted by an agent);
    - each branch's state: merged into the default branch, merged into an integration line, patch-equivalent, same tip as another branch, live work, parked, dormant.
02. **Report.** `hooks-daemon branch-sweep` (text and `--json`) and a terse SessionStart line: every local branch, remote branch and worktree with work, with its ahead count, lines, age, drift, remote presence and linked plan or issue. This is v1's scope.
03. **A WIP cap that holds.** Repository-wide, default 10 (owner, Q2). Every non-default, non-exempt branch counts, local and remote, with identical tips counted once. At the cap, new work is denied: `git switch -c`, `git checkout -b`, `git branch <new>`, `git worktree add`, an Agent dispatch with `isolation: worktree`, and WorktreeCreate. The denial lists the open branches to finish.
04. **Same-task duplicates.** Creating a branch whose stem or issue number matches an open branch (`-2`, `-r3`, `-orig` and similar) is warned about, naming the existing branch to continue.
05. **Dormancy.** Days since a branch's last commit: an advisory at 7 days, a noisy advisory at 14 days, and a block on new work at 30 days (owner defaults, Q3). A named stricter preset, a warning at 3 days and a block at 7 (owner ruling), is suggested by the docs and the config optimiser, never applied silently. Each idle branch is reported with its containment: contained in the default branch or another remote branch (a cleanup candidate), or contained nowhere (lost work, reported loudly). A branch can be marked parked on a human decision (reason and date); it is then shown as waiting, not forgotten, and does not trip the dormancy block.
06. **Stop and SubagentStop guard.** A session or sub-agent may not stop while ANY branch it touched (created, committed on, merged, switched to or edited in, not only the current one) has a dirty worktree, holds commits no remote contains, or is merged but not deleted (locally, on the remote, or as a worktree). It says which, and how to finish.
07. **Lossless cleanup after a merge.** Optional, on by default in this repository: after a merge into the default branch or an integration line, `git branch -d`, a remote delete of the merged branch, and `git worktree remove` without `--force`. Never a force, never an integration line itself, never an unproven branch.
08. **Integration lines in the delete guards.** R-GIT-PUSH-DELETE-REMOTE and the cleanup accept "an ancestor of an integration line's remote-tracking ref, and the live tip matches" as proof, and never let an agent delete the integration branch itself. The guard's remote check is one `ls-remote` for all named branches (#153).
09. **The daemon cleans up after itself.** WorktreeRemove deletes the branch WorktreeCreate made once it is proven merged; `worktree_create` branch names are counted.
10. **Lossless force removal.** `git worktree remove --force` is denied when the worktree has uncommitted changes or commits no other ref contains; `git branch -D` uses the same "contained elsewhere" proof.
11. **Every deny states the purpose.** The limit exists so work finishes, never so it disappears; work serving another lane goes on that lane's branch; a patch or copy under an ignored directory is lost work, not compliance; when the limit seems to force losing work or exceeding it, stop and ask a human.
12. **No evacuate-then-destroy.** Writing `git diff`/`format-patch`/`stash show -p` output to an ignored or untracked path and removing that worktree or deleting that branch, in the same command or the same turn, is denied, naming the right move.

## Non-Goals

- Deleting or rewriting anything that cannot be proven recoverable. Unproven deletion stays with a human (`delete-branch --allow-unproven`).
- Judging whether unmerged work is any good.
- Deleting an integration line, the default branch or any exempt branch.
- Replacing `git_upstream_checker`.
- Plan-number collisions across clones (raised on #152; filed separately).

## Open questions

- **Q1 (for the #152 commenter):** the "preserve" branches the daemon reportedly auto-commits to were not found in this repository's source (finding 4 of the code-facts report). What is their name pattern, and which tool created them? Until that is answered, they are covered generically by Goals 3 and 7, not by a dedicated rule.
- **Q2 (owner), answered 3 November 2026:** the WIP cap is repository-wide, default 10.
- **Q3 (owner), answered 3 November 2026:** dormancy has three stages: an advisory at 7 days since the last commit, a noisy advisory at 14 days, and a block on new work at 30 days.
- **Q4 (design), decided in Phase 1:** a `Parked-Reason:` trailer on an empty commit at the branch tip, set by `hooks-daemon branch-park` ([DESIGN.md](DESIGN.md) section 5).
- **Q5 (owner):** `CLAUDE/Worktree.md` says at most 3 open work branches; the cap is 10. Keep 3 as a local working rule, or change it? And the Goal 6 default refuses a sub-agent stop with commits no remote holds, while this repository tells sub-agents not to push: should they push their work branch, or does this repository keep the advisory setting ([DESIGN.md](DESIGN.md) section 6)?

## Tasks

### Phase 1: Design

- [x] ✅ **Task 1.1**: Decide the config surface (Goal 1), including how it migrates the three existing default-branch resolutions and the existing `branch_count_advisor` options. Recorded in [DESIGN.md](DESIGN.md) section 1: a top-level `branches:` block.
- [x] ✅ **Task 1.2**: Decide the classification rules, the parked marker (Q4), how a branch's creator (session or sub-agent) is recorded for the Stop guard, and the guard modes (advisory, block). Recorded in [DESIGN.md](DESIGN.md) sections 2-13, including the strict preset and the #152 follow-up requirements (Goals 10-12).
- [x] ✅ **Task 1.3**: Fact-check this plan against the repository (`hooks-daemon-plan-fact-checker`) and fold in the findings. The plan was checked in v2 and DESIGN.md in [subagent-reports/261103-design-fact-check.md](subagent-reports/261103-design-fact-check.md); all refuted claims are corrected.

### Phase 2: Inventory and report (TDD)

- [x] ✅ **Task 2.0**: Add the `branches:` config block, `resolve_default_branch`, and migrate the `delete-branch`/`worktree-reap` defaults, `branch_safety`'s protected names and `branch_count_advisor`'s options onto it, with the config-changes manifest entries ([DESIGN.md](DESIGN.md) section 1). Report: [subagent-reports/261103-phase2-inventory.md](subagent-reports/261103-phase2-inventory.md).
- [x] ✅ **Task 2.1**: Write the inventory module with fixture repositories: local and remote branches, worktrees, ahead and behind counts, lines, age, identical tips, integration-line merges, containment of idle branches, plan and issue links. `core/branch_inventory.py`; same report.
- [x] ✅ **Task 2.2**: Add the `branch-sweep` CLI verb (text and `--json`). `core/branch_sweep.py` and `daemon/cli.py`. Report: [subagent-reports/261103-phase2-sweep.md](subagent-reports/261103-phase2-sweep.md).
- [x] ✅ **Task 2.3**: Add the SessionStart summary. It must be time-bounded, cached and silent when clean, and it replaces `branch_count_advisor`'s line. `handlers/session_start/branch_sweep.py`, with the old key as an alias (`HANDLER_KEY_ALIASES`); same report.

### Phase 3: Cleanup (TDD)

Cleanup comes before enforcement: on the #152 commenter's 154 leftovers it alone would have removed about three quarters ([DESIGN.md](DESIGN.md) section 9).

- [x] ✅ **Task 3.1**: Add the lossless cleanup after a merge and `branch-sweep --clean` (Goal 7), with integration lines in R-GIT-PUSH-DELETE-REMOTE and its batched remote check (#153) (Goal 8). The batched check is already merged (e4841e27d). Before any cleanup deletes on `classify_branch`, close its two fail-open gaps: a failed `git cherry` reads as patch-equivalent (`_unique_commit_count` returns 0; switch to `cherry_unique_shas`, which fails closed), and a branch whose merge commits carry content not in the target passes as patch-equivalent (it decides from the `git cherry` count alone; the same gap that [subagent-reports/261103-phase2-review.md](subagent-reports/261103-phase2-review.md) finding 2 found and fixed in the inventory).
- [x] ✅ **Task 3.2**: Make WorktreeRemove delete its proven-merged branch, and count `worktree_create` names (Goal 9). Until Task 4.2's creator record exists, eligibility is the `<slug>-<8 hex>` name. Report: [subagent-reports/261103-task32-33.md](subagent-reports/261103-task32-33.md).
- [x] ✅ **Task 3.3**: Fix what dogfooding `branch-sweep --clean --dry-run` on this repository showed, and restore one line the summary dropped:
  - an empty `untracked/scratch/` counts as a blocker;
  - a regenerable glob with a trailing slash does not match a symlinked store (`untracked/lsp-venv`);
  - the defaults miss `untracked/repair.log`, `untracked/repair.txt`, `.coverage`, `untracked/.python-cmd-cache`, `untracked/context-sidecar/`, `untracked/logs/`, `untracked/acceptance/` and `.CLAUDE.md.pre-inject`;
  - the SessionStart summary dropped the far-behind-default line, so `branches.sweep.behind_threshold` is read only by a deprecation line ([subagent-reports/261103-phase2-sweep.md](subagent-reports/261103-phase2-sweep.md)).

### Phase 4: Enforcement (TDD)

- [x] ✅ **Task 4.1**: Deny a lossy `worktree remove --force` and widen `branch -D`'s proof to "contained elsewhere" (Goal 10). Report: [subagent-reports/261103-task41-45.md](subagent-reports/261103-task41-45.md).
- [x] ✅ **Task 4.2**: Add the creation guard: the WIP cap (Goal 3) and same-task duplicate warning (Goal 4) on every creation route, the creator and touch record, and the shared deny text (Goal 11). Handoff with parts A and B: [subagent-reports/261103-task42-handoff.md](subagent-reports/261103-task42-handoff.md). Known gap: the shared argv parser treats `echo git checkout -b x` as a creation.
- [x] ✅ **Task 4.3**: Add the dormancy limit, the `standard` and `strict` presets, and the parked marker (Goal 5). `R-BRANCH-DORMANT` in the creation verdict, `hooks-daemon branch-park [--clear]`, and the optimiser's non-scoring strict suggestion. The creation guard reads the stage from the SessionStart labels snapshot, so a branch's stage is as of the last session start; `branch-park` clears its label at once.
- [ ] ⬜ **Task 4.4**: Add the Stop and SubagentStop guard (Goal 6).
- [x] ✅ **Task 4.5**: Deny evacuate-then-destroy, same command then same turn (Goal 12). Same command: `R-GIT-EVACUATE-THEN-DESTROY` in `core/evacuation.py` ([subagent-reports/261103-task41-45.md](subagent-reports/261103-task41-45.md)). Same turn: the `evacuation_recorder` PostToolUse handler records evacuations in `core/evacuation_turns.py`, keyed by the `evacuation_turn_marker` UserPromptSubmit prompt count on the main thread or by `agent_id` in a sub-agent, and the destroy guard reads that record.

### Phase 5: Ship

- [ ] ⬜ **Task 5.1**: Write the handler guidance, docs and the `/hooks-daemon housekeeping` step.
- [ ] ⬜ **Task 5.2**: Add release notes in the pending-release holding area.
- [ ] ⬜ **Task 5.3**: Dogfood on this repository: run the sweep, act on what it finds, and confirm the guards fire.

## Success Criteria

- [ ] On a fixture repository with branches merged into the default branch, merged into a `release/*` line, abandoned, duplicated and parked, the sweep classifies each correctly. A test proves it.
- [ ] At the configured cap, every creation route in Goal 3 is denied, and the denial lists the open branches. A test per route proves it.
- [ ] A Stop and a SubagentStop that leave any touched branch dirty, holding commits no remote contains, or merged but undeleted are refused. Tests prove it, including a branch touched and then switched away from.
- [ ] A forced worktree removal or `branch -D` that would lose work is refused, and an evacuate-then-destroy command is refused; every deny carries the Goal 11 text. Tests prove it.
- [ ] Idle branches are reported with their containment, and the `strict` preset applies 3 and 7 days. Tests prove it.
- [ ] A remote delete of a branch merged only into an integration line is allowed; a delete of the integration line is refused; a 40-branch delete is judged within the dispatch budget. Tests prove it.
- [ ] Nothing is deleted that is not proven recoverable. A test proves an unproven branch survives the cleanup.
- [ ] Release notes are recorded in `CLAUDE/UPGRADES/UNRELEASED/` (the pending-release holding area).
- [ ] GitHub #152 and #153 are commented on with what shipped and closed.
