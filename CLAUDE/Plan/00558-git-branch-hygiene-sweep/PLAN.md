# Plan 00558: branch WIP limit and hygiene (v2)

**Status**: Not Started
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

- `branch_count_advisor` is advisory, runs only at SessionStart on new sessions, and counts only local `worktree-*` and `agent-*` branches. The daemon's own `worktree_create` names its branches `<slug>-<8hex>`, so the advisor does not count them.
- `worktree_create`'s branches are never deleted: WorktreeRemove leaves them behind.
- No Stop or SubagentStop handler looks at git state.
- No hook acts on branch creation.
- The remote-delete guard (R-GIT-PUSH-DELETE-REMOTE) treats a branch as deletable only when it is an ancestor of the default branch, with no notion of an integration line. It also times out on a large delete (#153).
- The default branch is resolved in three separate places (`git_sync.default_branch`, `delete-branch --protected-ref`, `worktree-reap --base-branch`), and no project setting names it or any integration line.

## Goals

1. **One branch model.** A single inventory module and a single config surface used by every branch feature:
   - the default branch, and a list of integration-line patterns (for example `release/*`, `epic/*`) that count as merge targets;
   - an exempt list (never counted, never deleted by an agent);
   - each branch's state: merged into the default branch, merged into an integration line, patch-equivalent, same tip as another branch, live work, parked, dormant.
2. **Report.** `hooks-daemon branch-sweep` (text and `--json`) and a terse SessionStart line: every local branch, remote branch and worktree with work, with its ahead count, lines, age, drift, remote presence and linked plan or issue. This is v1's scope.
3. **A WIP cap that holds.** Every non-default, non-exempt branch counts, local and remote, with identical tips counted once. At the cap, new work is denied: `git switch -c`, `git checkout -b`, `git branch <new>`, `git worktree add`, an Agent dispatch with `isolation: worktree`, and WorktreeCreate. The denial lists the open branches to finish.
4. **Same-task duplicates.** Creating a branch whose stem or issue number matches an open branch (`-2`, `-r3`, `-orig` and similar) is warned about, naming the existing branch to continue.
5. **Dormancy.** Days since a branch's last commit, advisory at one age and blocking new work at a second. A branch can be marked parked on a human decision (reason and date); it is then shown as waiting, not forgotten, and does not trip the dormancy block.
6. **Stop and SubagentStop guard.** A session or sub-agent may not stop while a branch it created has unpushed commits, a dirty worktree, or is merged but not deleted (locally, on the remote, or as a worktree). It says which, and how to finish.
7. **Lossless cleanup after a merge.** Optional, on by default in this repository: after a merge into the default branch or an integration line, `git branch -d`, a remote delete of the merged branch, and `git worktree remove` without `--force`. Never a force, never an integration line itself, never an unproven branch.
8. **Integration lines in the delete guards.** R-GIT-PUSH-DELETE-REMOTE and the cleanup accept "an ancestor of an integration line's remote-tracking ref, and the live tip matches" as proof, and never let an agent delete the integration branch itself. The guard's remote check is one `ls-remote` for all named branches (#153).
9. **The daemon cleans up after itself.** WorktreeRemove deletes the branch WorktreeCreate made once it is proven merged; `worktree_create` branch names are counted.

## Non-Goals

- Deleting or rewriting anything that cannot be proven recoverable. Unproven deletion stays with a human (`delete-branch --allow-unproven`).
- Judging whether unmerged work is any good.
- Deleting an integration line, the default branch or any exempt branch.
- Replacing `git_upstream_checker`.

## Open questions

- **Q1 (for the #152 commenter):** the "preserve" branches the daemon reportedly auto-commits to were not found in this repository's source (finding 4 of the code-facts report). What is their name pattern, and which tool created them? Until that is answered, they are covered generically by Goals 3 and 7, not by a dedicated rule.
- **Q2 (owner):** the WIP cap's default value, and whether it applies per session or to the whole repository. #152 implies the repository.
- **Q3 (owner):** the dormancy defaults (advisory and blocking ages).
- **Q4 (design):** where a "parked" marker lives so it survives a fresh clone. Candidates: a tracked file, the plan the branch belongs to, a git note on the tip. Decide in Phase 1.

## Tasks

### Phase 1: Design

- [ ] ⬜ **Task 1.1**: Decide the config surface (Goal 1), including how it migrates the three existing default-branch resolutions and the existing `branch_count_advisor` options. Record the decision in this folder.
- [ ] ⬜ **Task 1.2**: Decide the classification rules, the parked marker (Q4), how a branch's creator (session or sub-agent) is recorded for the Stop guard, and the guard modes (advisory, block). Record them.
- [ ] ⬜ **Task 1.3**: Fact-check this plan against the repository (`hooks-daemon-plan-fact-checker`) and fold in the findings.

### Phase 2: Inventory and report (TDD)

- [ ] ⬜ **Task 2.1**: Write the inventory module with fixture repositories: local and remote branches, worktrees, ahead and behind counts, lines, age, identical tips, integration-line merges, plan and issue links.
- [ ] ⬜ **Task 2.2**: Add the `branch-sweep` CLI verb (text and `--json`).
- [ ] ⬜ **Task 2.3**: Add the SessionStart summary. It must be time-bounded, cached and silent when clean, and it replaces `branch_count_advisor`'s line.

### Phase 3: Enforcement (TDD)

- [ ] ⬜ **Task 3.1**: Add the creation guard: the WIP cap (Goal 3) and same-task duplicate warning (Goal 4) on every creation route.
- [ ] ⬜ **Task 3.2**: Add the dormancy limit and the parked marker (Goal 5).
- [ ] ⬜ **Task 3.3**: Add the Stop and SubagentStop guard (Goal 6).
- [ ] ⬜ **Task 3.4**: Teach R-GIT-PUSH-DELETE-REMOTE about integration lines, and batch its remote check (#153) (Goal 8).

### Phase 4: Cleanup (TDD)

- [ ] ⬜ **Task 4.1**: Add the lossless cleanup after a merge (Goal 7).
- [ ] ⬜ **Task 4.2**: Make WorktreeRemove delete its proven-merged branch, and count `worktree_create` names (Goal 9).

### Phase 5: Ship

- [ ] ⬜ **Task 5.1**: Write the handler guidance, docs and the `/hooks-daemon housekeeping` step.
- [ ] ⬜ **Task 5.2**: Add release notes in the pending-release holding area.
- [ ] ⬜ **Task 5.3**: Dogfood on this repository: run the sweep, act on what it finds, and confirm the guards fire.

## Success Criteria

- [ ] On a fixture repository with branches merged into the default branch, merged into a `release/*` line, abandoned, duplicated and parked, the sweep classifies each correctly. A test proves it.
- [ ] At the configured cap, every creation route in Goal 3 is denied, and the denial lists the open branches. A test per route proves it.
- [ ] A Stop and a SubagentStop that leave a created branch unpushed, dirty, or merged but undeleted are refused. Tests prove it.
- [ ] A remote delete of a branch merged only into an integration line is allowed; a delete of the integration line is refused; a 40-branch delete is judged within the dispatch budget. Tests prove it.
- [ ] Nothing is deleted that is not proven recoverable. A test proves an unproven branch survives the cleanup.
- [ ] Release notes are recorded in `CLAUDE/UPGRADES/UNRELEASED/` (the pending-release holding area).
- [ ] GitHub #152 and #153 are commented on with what shipped and closed.
