# Evidence: Plan 00594, branch lifecycle and branch-tip channel

Supporting document for [PLAN.md](PLAN.md) Task 1.1, read with [DESIGN.md](DESIGN.md). It gathers the counts, orderings and git shapes behind each failure class, in generic form. This repository is public, so there are no client, repository, host, branch, person or seat names here. The two sources are called "the first client seat" and "the second client seat".

## How to read the provenance

Every figure carries one of two tags.

- **Repo source**: the claim is recorded in a file in this repository (PLAN.md, DESIGN.md, a JOURNAL entry, a fact-check, a task report, or the niggles ledger entry named). A code citation that a fact-check verified counts as a repo source.
- **Second-hand**: the claim is a seat's own report, as relayed into this plan. This repository holds only the retelling, and nothing here can check the number against the seat's repository.

No figure below was invented or re-derived. Where the repo has no count for a class, the section says so. Sources are named by file, not by line, except where a fact-check verified the line.

Class numbers and names are those of the "Observed failure classes" list in PLAN.md, which DESIGN.md's sections map onto.

## Summary

| Class | Name                                         | Closing task(s)          | Status on main today                             |
| ----- | -------------------------------------------- | ------------------------ | ------------------------------------------------ |
| 1     | The daemon makes dangling branches itself    | 2.1, 2.2                 | Closed (both done)                               |
| 2     | The cap bites at creation                    | 4.2 (and 4.8 advisories) | Open (4.2 not done)                              |
| 3     | Some resolutions are impossible for an agent | 3.1, 3.2, 4.7            | Closed (all done)                                |
| 4     | Blockers appear one at a time                | 4.1                      | Closed (4.1 done)                                |
| 5     | Parking is fragile                           | 4.3, 4.5                 | Partly closed (4.5 done, 4.3 partly done)        |
| 6     | Regenerable directories block cleanup        | 3.3, 3.5                 | Closed (both done)                               |
| 7     | Pools are not counted per owner              | 4.4 (and 4.6 for stacks) | Open (4.4 and 4.6 not done)                      |
| 8     | Scale                                        | 3.4 (with 3.1, 3.2)      | Closed (3.4 done, on the proof from 3.1 and 3.2) |
| 9     | Journal heading churn (smaller, separate)    | 6.1, 6.2, 6.3            | Closed (all done)                                |

Phase 5 (branch-tip channel) is not a failure class and is covered in its own section at the end. Task statuses were checked against the PLAN.md checkboxes: done are 1.1, 2.1, 2.2, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 4.1, 4.5, 4.7, 4.8, 5.0, 5.2, 5.3, 6.1, 6.2, 6.3; partly done are 4.3 and 5.1; open are 4.2, 4.4, 4.6, 4.9 (a client report, ledger N611: the park commit is unsigned).

## Class 1: The daemon makes dangling branches itself

**Observed (second-hand, first client seat)**

- In one client repository, 5 of 14 open branches held only the daemon's own housekeeping commit.
- One such commit sat unpushed on a default branch.
- Sequence: the managed CLAUDE.md block is regenerated, which leaves a tracked file dirty. The auto-commit lands on whatever HEAD is. A dirty file also made `git worktree remove` refuse, so agents committed it on a throwaway branch to get the worktree removed.

**Git shapes (repo source, DESIGN.md section 2.5, fact-checked)**

- The injector skips only linked worktrees. In the main checkout it writes the block and commits onto the current HEAD: a feature branch, a detached HEAD (a dangling commit), or the default branch without a push.
- `regenerate-docs` forces the write in linked worktrees.

**Later seat feedback (repo source, DESIGN.md section 6 and JOURNAL)**

- Main checkouts sit on an environment, release or production branch for weeks, by policy. That turned "default branch only" into a "home branch" rule.
- The release candidate that carried the fix was live on two client seats. Its review found five important and seven minor findings in round one, four important in round two and one in round three.

**Closed by**: Tasks 2.1 (`branches.home`) and 2.2 (`branches.home_commit`), both done. Status on main: closed.

## Class 2: The cap bites at creation

**Observed**

- Sequence (second-hand, first client seat): the open-work cap denied at the moment an agent held an urgent fix. The agent's first workaround was to rename a merged branch to get under the cap.
- Counts (second-hand, second client seat): the open pool stood at 28 against a cap of 10 in the morning. After that seat's own cleanup it was 14 against 10. The merged pool was at its cap of 10 in the morning (four stale, six merged locally and awaiting a push), then 5 later.
- Effect (second-hand, second client seat): every agent type that needs worktree isolation could not start at all.
- Own-repo recurrence (repo source, JOURNAL): a sub-agent dispatch that needed a worktree branch was denied by the merged-pool rule. Two day-old merged leftovers from an earlier session caused it. They were cleared with the reap and sweep commands behind a recovery bundle. The deny came at creation, not at the earlier session's stop.
- Own-repo recurrence (repo source, JOURNAL): at release time the creation guard blocked the release branch itself until six stale merged agent branches were deleted behind recovery bundles and two release-candidate branches were kept with reasons.

**Closed by**: Task 4.2 (move pressure to stop, session start and merge; creation becomes a backstop with a grace margin, DESIGN.md section 2.3), not done. Task 4.8 added two creation-time advisories (below) but does not move the pressure. Status on main: open. The owner's stated position (repo source, JOURNAL) is that the cap must not be worked around, so the causes are fixed instead.

## Class 3: Some resolutions are impossible for an agent

**Observed (second-hand, first client seat)**

- A pull request merged under another branch name, a squash merge, or a patch-equivalent branch still counted as unmerged. The guard refused its remote delete, so a human was needed. The sweep proved patch-equivalence and then could not act on it.

**Observed (second-hand, second client seat)**

- The sweep printed a `git push --delete` line for a patch-equivalent remote branch, and the remote-delete guard then refused that line. Repo source (task-4-7-report.md): the diverging shape is a remote-tracking ref showing a merged tip while the live remote tip has moved.

**Measured in this plan (repo source, JOURNAL)**

- The widened proof rule (a first-parent commit of the default branch holds the net change) proved 31 of the last 40 merges treated as squashes, against 4 of 40 for a tip-only check. The coordinator re-ran the probes after the round-2 fixes and every false-positive shape the reviewers built was unproven. The journal does not say which repository these 40 merges came from.

**Git shapes (repo source, DESIGN.md sections 2.1 and 6)**

- Four kinds of evidence: ancestry, patch-id, tree containment, forge record. Tree containment proves no loss, not that the work is finished, so "deletable" and "finished" are separate predicates.
- The forge CLI is usable in every seat (second-hand), so the forge record is available on explicit commands.

**Closed by**: Tasks 3.1 (release note 040), 3.2 (release note 040) and 4.7 (release note 042), all done. Note from the 4.7 report: its test was written after the fix, so it was never seen failing. Status on main: closed.

## Class 4: Blockers appear one at a time

**Observed (second-hand, first client seat)**

- Three failed starts in a row: first the open cap, then a park that had silently not registered, then the merged pool.
- Second client seat (second-hand): the morning state had both the open pool and the merged pool over or at cap at once, so the one-at-a-time reporting applies there too. The plan records no start-by-start sequence for that seat.

**Own-repo recurrence (repo source, JOURNAL)**: the release-branch block above needed several stale branches cleared before the creation succeeded.

**Closed by**: Task 4.1 (`branch-preflight`, the creation deny renders the same report), done (release note 046, `task-4-1-report.md`). DESIGN.md section 2.3 specifies that it evaluates every pool rather than the first rule that trips. Status on main: closed.

## Class 5: Parking is fragile

**Observed (second-hand, first client seat)**

- A park is a commit that must stay the tip and be pushed. If the push is rejected, the branch is parked locally only and still counted. A later merge unparks it silently.
- Sequence (repo source, niggles ledger N607, second-hand origin): a project's pre-push gate requires a fresh full-QA verdict. A park from a worktree without one was refused at the push. The client saw this as a half-done park.

**What the repo's own check found (repo source, N607, task-4-3-report.md, JOURNAL)**

- The local park was already whole before the push. What was missing was a durable git-config record, a distinct exit status for "parked locally, not pushed", and a visible message when a merge clears the record.
- Same-tip twin (second-hand, repo-recorded under Task 4.5): a same-tip `-parked` twin stayed stale to the creation guard after its sibling was kept, and a same-reason re-keep was refused before the stale mark was cleared.

**Done on main**: Task 4.5 (release note 037, a keep covers every name at the kept tip). Task 4.3 (release note 043): the park writes a git-config record before the push; a refused push exits 3 with a retry command; a merge, `delete_if_merged`, the sweep and `branch-park --clear` print "Park cleared".

**Still open under 4.3**: a branch only the remote holds still parks nothing on a refused push; the group-pool PARKED resolution (DESIGN.md 2.4); the session-start "park cleared" print.

Status on main: partly closed.

## Class 6: Regenerable directories block cleanup

**Observed (second-hand, first client seat)**

- A merged branch's worktree held dependency-manager vendor directories. They can be regenerated but were not on the default regenerable list, so cleanup was refused.

**Git shapes (repo source, DESIGN.md section 6, second-hand origin)**

- The blocking directories were vendor and bin directories several levels down, next to their manifest and lock file. A root-level name list would miss them, hence the rule "an ignored directory beside a manifest and lock pair".
- Fact-check-02 verified that the default list at the time held none of the five vendor names DESIGN.md proposed. It did not compare the client's actual directory names; DESIGN.md section 4 question 6 (which names actually blocked cleanup) has no recorded answer beyond "nested, beside a manifest and lock pair".

**Own-repo recurrence (repo source, niggles ledger N600)**: every agent worktree that ran targeted tests or QA held two report directories under `untracked/` (a version-pair fixture range). The removal guard counts them as ignored and unregenerable, so every removal was denied until they were deleted by hand. This is a test-writes-to-the-real-checkout defect, still open in the ledger, and not a vendor-directory case.

**Closed by**: Task 3.3 (release note 034, lock-pair rule, configurable), plus Task 3.5 (release note 038, the deny says to look first, keep what matters and delete the disposable part in a separate command). Status on main: closed.

## Class 7: Pools are not counted per owner

**Observed**

- Second-hand, first client seat: remote-only branches created by other actors count against every checkout, so one seat is blocked by another's leftovers.
- Repo source (fact-check-01 item 10): the creator record (`hooksDaemonCreator`) exists, but only for branches the daemon saw being created. Pool counting does not consult it.
- Second-hand, review round 1 (DESIGN.md section 6): most seats commit under one shared identity, so an author-email rule cannot tell seats apart. A branch from an earlier container or a re-cloned checkout is foreign to every clone, so a "foreign, not counted" rule would hide most of the largest pile. This changed the design to an explicit "unowned" pool with its own cap and a configured owner.
- Second-hand, second client seat (Task 4.6): a five-deep stack of dependent pull-request branches counts once per link against the open cap, so it alone uses half of a cap of 10. Of the 14 open branches after that seat's cleanup: the five-deep stack, seven recovery copies (see class 8 and Task 4.8), three dormant agent, review or feature branches, and one unlinked release feature branch.

**Closed by**: Task 4.4 (count per owner) and Task 4.6 (stack counting, a design decision), neither done. Status on main: open.

## Class 8: Scale

**Observed**

- Second-hand, first client seat: one client repository has 275 remote branches, 135 of them zero commits ahead of the default branch. A first cleanup at that size needs a safe bulk path. DESIGN.md section 4 question 2 (how many of the 135 are foreign or bot-made) has no recorded answer.
- Second-hand, second client seat: seven recovery copies made during an earlier recovery. Four are patch-equivalent to the integration line. Three have one commit that adds a file byte-identical to the line's. These are not about scale alone; they show the proof must cover single-commit-adds-identical-file shapes (tree containment, DESIGN.md section 2.1).
- Advice given to that seat (repo source, JOURNAL): archive recovery copies under `refs/archive` and leave the deletes to the owner until the proof shipped.
- Second client seat, a nested agent worktree: one agent worktree was created inside another worktree.

**Closed by**: Task 3.4 (batched, resumable bulk cleanup tested against a fixture with hundreds of branches), done (release note 047, `task-3-4-report.md`: `--clean` previews, `--apply` deletes in batches of 50 with a bundle each, and a run resumes by running the same command again). The proof it depends on (3.1, 3.2) is done, and Task 4.8 (release note 044, "Branch Practice" in the core worktree doc) now says recovery copies go to a bundle or `refs/archive/<name>`, never to a branch, and worktrees are never nested. `branch_creation_guard` advises on a recovery-shaped branch name and on a nested worktree. Status on main: closed (the bulk path, the recovery-copy cause and the nested-worktree cause).

## Class 9: Journal heading churn

**Observed (second-hand, client QA pipelines)**

- `mkplan.bash --journal --title` with no `--ref` produced a heading with a dash placeholder, three spaces, then a second dash. A client formatter collapsed it, and the entry-immutability commit gate then refused the collapsed version, so the format check stayed red.
- Second route (repo source, JOURNAL): a client QA pipeline ran the `format-markdown` verb over a directory. Unlike the edit-time handler, the verb did not skip journal files and rewrote two entry headings on every run. The agent could neither commit them nor restore them, because restore is human-only.
- Repo source (fact-check-01, fact-check-03): the heading code, the optional-slot grammar and the daemon formatter's journal exemption were checked and hold.

**Closed by**: Tasks 6.1 (single-spaced separator, release note 031), 6.2 (the verb skips journal files, release note 033) and 6.3 (the immutability check accepts a whitespace-only change, release note 033), all done. Status on main: closed.

## Phase 5: Branch-tip channel (not a failure class)

- Repo source (JOURNAL): a release-candidate branch was installed through the guarded unreleased install and was live on two client seats. It unblocked a client seat and confirmed the class 6 fix the same day (PLAN.md, Task 5.0).
- Release-candidate feedback produced two defects, both fixed: the guarded install exited 141 when the pyproject was larger than one pipe write (Task 5.2), and `status` showed an earlier stamp because a reused venv was never re-stamped (Task 5.3).
- Two suites that Task 5.1's own branch had not run failed on the merged tree (repo source, JOURNAL). One concerned the guarded install's variable names appearing in handler text.
- Task 5.1 is partly done: the metadata, the moved-ref advisory and `upgrade.sh --release` are on main (release note 041). Still open: proof on the client test seat, and the stop, build, start handover owned by Plan 00535.

## What is not yet in the repo

- No per-start command sequence exists for the second client seat's blocked starts; only the pool counts and the end state are recorded.
- No client-side counts exist for class 7 beyond the qualitative report, nor for the share of the 135 zero-ahead branches that were foreign.
- DESIGN.md section 4 questions 1, 2, 4, 5 and 6 are unanswered in the repo. Questions 1 and 3 are partly answered by the review-round notes: seats share one identity, and the forge CLI is usable.
- Every client-side figure above is second-hand. The figures with a repo source are the ones tagged as measured in this plan, the own-repo recurrences, and the code citations verified by the fact-check files.
