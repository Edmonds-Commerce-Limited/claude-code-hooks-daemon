# Plan 00594: branch lifecycle and branch tip channel

**Status**: In Progress
**Created**: 2026-11-10
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Plan 00571 split branches into three finite pools (open, parked, merged), and
earlier plans added no-loss guards. That model is right. But one day of real
multi-agent use, with several seats sharing repositories, showed that the
guards apply pressure at the wrong moments, ask for actions an agent cannot
perform, and are partly fed by the daemon itself. The result is the problem
the pools exist to prevent: WIP branches sprawl, work gets lost or duplicated,
and nobody can tell what is live.

This plan redesigns the WHOLE branch lifecycle as one model rather than
patching symptoms one by one: how a branch is born, finished, proven merged,
deleted locally and remotely, parked, and owned. It also adds a way for a
client checkout to run the tip of a daemon branch, not only a released tag,
so client seats can test changes as they are pushed and roll back in one
step.

All evidence comes from client use and is described here by class only. This
repository and its tracker are public, so no client names, hosts, branch
names, people or hashes appear here.

## Observed failure classes (evidence, generic)

1. **The daemon makes dangling branches itself.** Regenerating the managed
   CLAUDE.md block leaves a tracked file dirty. The auto-commit then lands on
   whatever branch is checked out, or on a throwaway branch made just so a
   worktree can be removed. In one client repository, 5 of 14 open branches
   held only that. One such commit sat unpushed on a default branch.
2. **The cap bites at creation.** The open-work cap denies at the moment an
   agent holds an urgent fix. Its first workaround was to rename a merged
   branch to get under the cap. Pressure belongs where work ENDS (stop,
   session start, merge); creation should only be the backstop.
3. **Some resolutions are impossible for an agent.** A PR merged under another
   branch name, a squash merge, or a patch-equivalent branch still counts as
   unmerged, and the guard refuses its remote delete, so a human is needed.
   The sweep proves patch-equivalence and then cannot act on it.
4. **Blockers appear one at a time.** First the open cap, then a park that had
   silently not registered, then the merged pool: three failed starts in a
   row. What is needed is one preflight that answers "can I branch?" and lists
   every blocker, each with its exact fix.
5. **Parking is fragile.** A park is a commit that must stay the tip and must
   be pushed. If the push is rejected, the branch is parked locally only and
   still counted. A later merge unparks it silently.
6. **Regenerable directories block cleanup.** A merged branch's worktree held
   dependency-manager vendor directories. These can be regenerated but are
   not on the default regenerable list, so cleanup was refused.
7. **Pools are not counted per owner.** Remote-only branches created by
   other actors count against every checkout, so one seat is blocked by
   another's leftovers. A creator record already exists
   (`hooksDaemonCreator` in `core/branch_records.py`), but only for branches
   the daemon saw being created, and pool counting does not consult it.
8. **Scale.** One client repository has 275 remote branches, 135 of them zero
   commits ahead of the default branch. A first cleanup at that size needs a
   safe bulk path.
9. **Journal heading churn (smaller, separate).** A journal entry made with
   `mkplan.bash --journal --title` and no `--ref` gets the heading
   `· —   — title`: a dash placeholder for the missing ref, three spaces,
   then a second dash. The daemon's own formatter already skips journal
   files, but a client repository's own format check collapses that
   heading. The commit gate treats journal entries as immutable, so the
   collapsed version can never be committed and the format check stays red.
   Interim advice to clients: exclude `**/JOURNAL/**` from their formatter.
   The fix: emit a heading that formatters leave alone, and document the
   exclusion in the install guide.

## Goals

- One written lifecycle model (`DESIGN.md`) covering birth, finish, proof of
  merge, local and remote delete, park, and owner. Each guard and command maps
  onto it, and each failure class above is explained by a gap in it.
- The daemon creates no branch and no commit as a side effect of its own
  housekeeping (class 1).
- "Merged" means the work is in the default branch, not that the branch name
  is an ancestor. Squash merges, renamed-PR merges and patch-equivalent
  branches are proven merged and are deletable by an agent, local and remote,
  behind the recovery bundle (class 3).
- Pressure moves to where work ends: stop, session start and merge. Creation
  remains a backstop and never forces a destructive workaround (class 2).
- One preflight command lists every blocker with its exact fix. The creation
  deny is that same report (class 4).
- Parking is recorded so that it survives a rejected push and a merge clears
  it explicitly, never silently (class 5).
- The default regenerable list covers common dependency-manager vendor
  directories, and the list can be configured (class 6).
- Pools are counted per owner. Another actor's branches are reported, not
  counted against this seat (class 7).
- A safe, resumable bulk cleanup works at hundreds of branches (class 8).
- A client checkout can follow a named daemon branch or commit, knows when it
  has moved, and returns to the last released tag in one step.

## Non-Goals

- Changing the no-loss guarantee. Nothing is deleted without proof plus a
  recovery bundle.
- Dropping the three-pool model or its caps.
- Shipping any change to guard behaviour before the design is reviewed with
  the client test seat.

## Design decisions to settle in Phase 1 (with evidence, before code)

- **Proof of merge.** Which evidence counts as merged: ancestry, patch-id
  equivalence, tree containment, or a forge record (merged PR head). Which of
  these works offline and which needs the network, and how each is cached.
  Plans 00254 and 00570 must be reused, not duplicated.
- **Owner.** Where a branch's owner is recorded and how a branch created
  outside the daemon (by a forge, a person or another seat) is classified.
  Candidates: creator trailer, git notes under a daemon ref, the
  branch-touch record, or the forge's author. The rule must work without a
  network.
- **Where pressure lands.** For each lifecycle point (stop, session start,
  merge, creation), what is denied, what is advised, and in which mode. The
  rule must never make renaming or deleting someone else's branch the
  cheapest exit.
- **Park record.** Keep the commit as the park, or move it to a note/ref so
  it survives a rejected push and does not have to stay the tip.
- **Daemon housekeeping commits (class 1).** Should the managed block be
  generated untracked, written only on the default branch by an explicit
  command, or committed through a no-branch path? One answer, with its
  reason.
- **Branch tip channel.** How a client pins `ref: <branch|sha>` instead of a
  tag; how the daemon detects that the pinned branch has moved (and says so
  at session start); how the venv/lock is rebuilt for the new source; and the
  single command that returns to the last tag. Plan 00535 (upgrade handover)
  must be reconciled.

## Tasks

### Phase 1: Design

- [ ] ⬜ **Task 1.1**: Collect the counts and sequences behind each class from
  the client test seat (generic: counts, orderings, git shapes; no names).
  Store them in `EVIDENCE.md` in generic form.
- [x] ✅ **Task 1.2**: (draft written in [DESIGN.md](DESIGN.md); open
  questions in its §4) Write `DESIGN.md`: the lifecycle state machine, and the
  answers to every decision above, each with its reason and the failure class
  it closes.
- [ ] ⬜ **Task 1.3**: Review the design with the client test seat before any
  code is written.

### Phase 2: Stop the daemon making branches (class 1)

- [x] ✅ **Task 2.1**: (on main, config key `branches.home`, release note
  032; proven live on two client seats through the release candidate; three
  review rounds) The daemon writes and commits the CLAUDE.md block only on a
  home branch. The default branch is resolved without a remote when needed
  (`init.defaultBranch` naming a real branch, an unborn HEAD, a sole local
  branch). An unresolved home is reported at SessionStart by the branch sweep.
- [x] ✅ **Task 2.2**: (on main, config key `branches.home_commit`) A home
  branch that only accepts changes by pull request: under `home_commit: false`
  the daemon never writes the block there, so a pull is never blocked by a
  dirty CLAUDE.md. It reports the stale block at SessionStart, and
  `regenerate-docs` writes it on a pull-request branch (it refuses on the home
  branch). A post-upgrade task tells clients when to set both keys.

### Phase 3: Proof of merge and agent-performable deletion (classes 3, 6, 8)

- [ ] ⬜ **Task 3.1**: Proof of merge covers squash merges, renamed-PR merges
  and patch-equivalent branches, with tests for each shape.
- [ ] ⬜ **Task 3.2**: Remote delete of a proven-merged branch is allowed for
  an agent, behind the recovery bundle.
- [x] ✅ **Task 3.3**: (on main, release note 034) An ignored directory that
  a committed manifest and lock file let a package manager rebuild counts as
  regenerable, unless it holds a nested git clone or contains the scratch
  area. The scan is bounded and runs once per guard call. The list stays
  configurable through `branches.cleanup_after_merge.regenerable`.
- [ ] ⬜ **Task 3.4**: Bulk cleanup is batched, resumable and dry-run first,
  and is tested against a fixture with hundreds of branches.
- [x] ✅ **Task 3.5**: (RC feedback; done, release note 038) When the
  worktree-removal guard names ignored blocking paths, its deny says to keep
  what matters and delete what is disposable in a separate command first. A
  chained delete is still denied, and the deny says it was not counted.
- [x] ✅ **Task 3.6**: (RC feedback; done, release note 039) The installer
  removes the settings backup it took when the merge left the file
  byte-identical to it.

### Phase 4: Pressure, preflight, park, owner (classes 2, 4, 5, 7)

- [ ] ⬜ **Task 4.1**: A preflight command (`branch-preflight` or similar)
  lists every blocker with its fix; the creation deny renders the same report.
- [ ] ⬜ **Task 4.2**: Move pressure to stop, session start and merge per
  `DESIGN.md`.
- [ ] ⬜ **Task 4.3**: The park record survives a rejected push, and a merge
  clears it visibly.
- [ ] ⬜ **Task 4.4**: Pools are counted per owner.
- [x] ✅ **Task 4.5**: (done: `clear_label_stale_at_tips`; release note 037)
  A keep covers every branch name at the kept tip, in the creation guard as
  in the sweep. Client report: a same-tip `-parked` twin stayed stale to the
  guard after its sibling was kept, and a same-reason re-keep was refused
  before the stale mark was cleared. In the lifecycle model, a keep, a park
  and a proof are all facts about a COMMIT. Every per-name cache of them
  must be keyed or invalidated by tip, never by the name typed.
- [ ] ⬜ **Task 4.6**: (second client seat) A stack of dependent pull-request
  branches counts once per link against the open cap, so a five-deep stack
  alone uses half of a cap of 10. Decide (design review): count a stack as
  one stream, cap stack depth, or keep counting each link and document the
  practice of landing the bottom first.
- [ ] ⬜ **Task 4.7**: (second client seat) `branch-sweep` prints a
  `git push --delete` for a patch-equivalent remote branch that the
  remote-delete guard then refuses. Every command the sweep prints must pass
  the guard that judges it; Task 3.2's shared proof closes most of this, and
  a test pins that the two agree.
- [ ] ⬜ **Task 4.8**: (second client seat) Write the branch practice down
  for clients: recovery copies go to a bundle or `refs/archive/<name>`
  (pools count only branches), never to a branch; worktrees are created
  from the main checkout, never nested; agents' worktrees are reaped after
  each agent. Prefer a daemon advisory where the practice can be detected
  (a new `rescue/*`-shaped branch, a nested worktree).

### Phase 5: Branch tip channel

- [x] ✅ **Task 5.0**: (done: RELEASING.md "Release candidate branches")
  At the owner's ruling, `rc/X.Y.Z` release-candidate branches become the
  supported beta channel. They are installed through the existing guarded
  unreleased install. Every push gets autofix and targeted QA first and is
  announced with its sha. Proven live: the first RC, `rc/3.73.3`, unblocked
  a client seat and confirmed the class 6 fix the same day.
- [ ] ⬜ **Task 5.1**: A client can follow a branch or commit, is told when it
  has moved, and can return to the last tag in one step. Proven on the client
  test seat.
- [x] ✅ **Task 5.2**: (RC feedback; done on the release branch, release note
  034\) A guarded unreleased install no longer exits 141 when the ref's
  `pyproject.toml` is larger than one pipe write. Layer 1 reads the blob
  whole before parsing it.
- [x] ✅ **Task 5.3**: (RC feedback; done, release note 036) `hooks-daemon status` on a branch-tip install shows the stamp of the clone HEAD. A venv
  reused because its lock is unchanged is now re-stamped, never rebuilt.

### Phase 6: Journal heading churn (class 9)

- [x] ✅ **Task 6.1**: (done: single-spaced title separator in both
  `mkplan.bash` copies and the journal template; test
  `test_titled_heading_is_single_spaced`; release note 031) Write a failing test in which a `--title` journal entry
  is rewritten by the formatter, then make the scaffolder emit the
  formatter-stable heading.
- [x] ✅ **Task 6.2**: (done: release note 033) `format-markdown` skips plan
  journal files, both in a directory walk and when one is named (the
  edit-time handler already did). Client report: a QA pipeline's call to the
  verb rewrote entries.
- [x] ✅ **Task 6.3**: (done: `only_whitespace_changed` in
  `plan_qa/model.py`; release note 033) The journal immutability check
  (`journal-dayfile-is-today`) accepts a whitespace-only change (same word
  sequence) at both edit and commit time, at the owner's request relayed by
  the client team. Any word change still blocks.

## Success Criteria

- [ ] `DESIGN.md` maps each of failure classes 1–9 to the lifecycle gap that
  caused it and to the change that closes it.
- [ ] Each class has a regression test that failed before its fix.
- [ ] The client test seat runs a branch tip, observes a move, and returns to
  the last tag in one step.
- [ ] Release-bound consequences (config keys, truth changes, release notes)
  are recorded in `CLAUDE/UPGRADES/UNRELEASED/`.

## Delivery & Milestones

- Plan opened.
