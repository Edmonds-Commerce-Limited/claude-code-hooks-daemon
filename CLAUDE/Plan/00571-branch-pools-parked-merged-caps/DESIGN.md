# Plan 00571 design: three branch pools, safe merged-branch removal

Phase 1 (Task 1.1) of [PLAN.md](PLAN.md). Builds on Plan 00558's design
(`CLAUDE/Plan/Completed/00558-git-branch-hygiene-sweep/DESIGN.md`, cited as
"00558 §N"). Paths are relative to `src/claude_code_hooks_daemon/` unless they
start with a top-level directory.

## 1. Pools

| Pool      | Members                                                             | Cap key      | Age key               |
| --------- | ------------------------------------------------------------------- | ------------ | --------------------- |
| open work | unmerged, unparked work branches (inventory `LIVE`/`DORMANT`/...)   | `wip.cap`    | dormancy (00558 §4)   |
| parked    | tip carries `Parked-Reason` (inventory `PARKED`)                    | `parked.cap` | `parked.max_age_days` |
| merged    | `MERGED_DEFAULT`, `MERGED_LINE`, `PATCH_EQUIVALENT`, kept or unkept | `merged.cap` | `merged.max_age_days` |

A branch is in exactly one pool, decided by the inventory state that already
exists (`core/branch_inventory.py` `BranchState`). Identical tips count once
per pool, as `open_work_count` does today (`core/branch_sweep.py`). Each deny
lists only that pool's branches and only actions that lower that pool's count
(the #165 defect is that the wip deny offered "park", which did not).

## 2. Keep-reason store for merged branches: a git note on the tip

**Decision:** `branch-keep <name> --reason "<text>"` adds a note under
`refs/notes/hooks-daemon/keep` on the branch's tip commit. The note body is
`Kept-Reason: <text>`, `Kept-By: <git user>`, `Kept-At: <UTC ISO>`. It pushes
that notes ref to `branches.remote` explicitly.

Why a note, against 00558 §5, which rejected notes for the park marker:

- **A commit is out.** A park commit on a merged branch makes it unmerged
  (PLAN.md), which is the one thing a keep must not do.
- **00558's first objection inverts here.** "A note silently detaches when the
  tip moves" was a defect for parking (work resumed, park should clear by a
  commit, not by losing metadata). For a merged branch a moved tip means new
  work: the branch has left the merged pool and is open work again, so the
  keep SHOULD lapse. Keying the keep by tip sha gets that for free, and a
  local branch and its remote copy at one tip share one keep.
- **00558's second objection (not fetched by default) is answered where it
  matters.** The sweep and creation guard read the local notes ref only, no
  network (`git notes --ref=... list` is one process, joined on tips the
  inventory already holds). A clone without the ref sees the branch as
  unkept, so at worst it reports cleanup debt. The one place a missing ref
  could destroy shared state is `branch-sweep --clean --remote`, which is
  already a network command: it fetches `refs/notes/hooks-daemon/keep` before
  judging, and refuses the remote half if that fetch fails.
- **A tracked file is worse** for the reasons 00558 §5 gives: a commit to the
  default branch per keep, concurrent agents conflicting on one file, entries
  outliving deleted branches.
- **Local git config** (the `branch_records` precedent,
  `core/branch_records.py`) is per clone and never shared; a keep made in one
  clone would not stop `--clean --remote` in another.

Age: `Kept-At` in the note body (the note commit date would also do, but the
body survives `git notes copy`/rewrite tooling unchanged).

## 3. Defaults and mode keys

```yaml
branches:
  wip:
    cap: 10            # unchanged (owner, 00558 Q2); now open work only
  parked:
    cap: null          # null = wip.cap
    max_age_days: null # null = the dormancy preset's block_days (30 standard, 7 strict)
    mode: block        # block | warn | off
  merged:
    cap: null          # null = wip.cap
    max_age_days: null # null = the dormancy preset's block_days; applies to KEPT branches
    mode: block        # block | warn | off
```

No new number is introduced; every default derives from a value the owner
already ruled on:

- **Caps default to `wip.cap`.** One owner number (10) governs how many
  branches may sit in any pool. Splitting the old single pool into three can
  only lower each pool's count relative to the old total, so no project that
  passes today's cap is denied by the new caps on upgrade.
- **Max ages default to the effective dormancy `block_days`.** A park exempts
  dormancy (00558 §5), so it buys exactly one more dormancy lifetime before it
  must be dealt with; a keep likewise. `preset: strict` tightens all three ages
  together, which is what "strict" means; it still leaves the caps alone
  (00558 §4 "strict changes nothing else").
- **An unkept merged branch has no age allowance**: it is cleanup debt from
  the moment it is merged, counted in `merged.cap`, and the deny names the one
  command (`branch-sweep --clean`, plus `--remote` when a remote copy exists).
- **Modes mirror `wip.mode`**: `block` denies the creation routes (00558 §3)
  when the pool is at its cap or holds a stale member; `warn` turns both into
  context lines; `off` stops counting the pool. Staleness is staged like the
  dormancy block stage: a stale member is listed in every SessionStart and
  denies creation in `block` mode; nothing else (commits, merges, deletes) is
  ever denied, so the way out stays open.

## 4. Re-parking and re-keeping a stale entry

- `branch-park <name> --reason <text>` on an already-parked branch writes a new
  park commit (00558 §5 mechanics). The age resets to that commit's date.
- **A re-park whose reason equals the current `Parked-Reason` is refused**
  (exit 2, "a re-park needs a new reason"). That is the only gate: resetting
  the clock costs a stated, different reason, as the owner ruled.
- **The count stays visible**: every park commit stays in history, and the
  inventory already walks the tip's run of empty park commits (`_park_shas`,
  `core/branch_inventory.py`). The sweep prints `re-parked N times` from that
  run's length. No separate counter.
- `branch-keep` on an already-kept tip replaces the note; the notes ref's own
  history (`git log refs/notes/hooks-daemon/keep`) keeps every earlier reason
  and gives the re-keep count. The same new-reason rule applies.

## 5. Config and truth migration

- **Config:** additive keys only (section 3), every one with a model default,
  `extra="forbid"` like the existing `Branch*Config` models
  (`config/models.py`). Phase 3 records a `config-changes` entry under
  `CLAUDE/UPGRADES/UNRELEASED/config-changes/` listing the six keys as
  `added`, `breaking: false`, none `recommended`.
- **Truth changes** (Phase 3, `CLAUDE/UPGRADES/UNRELEASED/truth-changes/`):
  "a parked branch still counts against `branches.wip.cap`"
  (`docs/guides/CONFIGURATION.md`, 00558 §3, §5) and "merged-but-undeleted
  branches count against `branches.wip.cap`" (00558 §3) both become false;
  each pool now has its own cap.
- `daemon/init_config.py`'s template gains the two blocks.

## 6. Phase 2 decisions (safe removal tooling)

- **`delete-branch` bundles:** one file per call,
  `untracked/deleted-branches/delete-branch-<UTC %Y%m%dT%H%M%SZ>-<6 hex>.bundle`,
  named by `branch_safety.new_bundle_path`, which `branch-sweep --clean` now
  uses too (`branch-cleanup-<stamp>-<hex>.bundle`), closing the one-second
  collision ROOTCAUSE.md noted for both. One file per call rather than one
  accumulating file, because two deletions of one name would otherwise collide
  on `refs/heads/<name>` inside the bundle (ROOTCAUSE.md item 1).
- **Explicit `--bundle PATH` refuses an existing file** (exit 2, before
  anything is classified). Overwriting is the defect being fixed; refusing
  also makes the "git refused every delete" cleanup safe, because the file it
  removes is always this run's own. When nothing was deleted the CLI says so
  and says no bundle was kept because nothing needs recovering.
- **Remote cleanup is an explicit flag, `branch-sweep --clean --remote`**, not
  a config default: it changes shared state on the remote and needs the
  network, so each run states that intent. It also deletes the local branches
  (a superset of `--clean`), so it is the one command PLAN.md asks for.
- **Remote proof = the remote-delete guard's proof, exactly.** The guard's
  check (`handlers/pre_tool_use/destructive_git.py`: name policy, tag
  ambiguity, ancestry of the tracking ref against the default or an
  integration line, then one batched `ls-remote` per remote confirming the
  live tip) moves into `core/remote_branch_proof.py` and both callers use it,
  so the CLI and the guard cannot disagree. A consequence: a PATCH-EQUIVALENT
  remote branch is not deleted by `--remote`, because the guard does not
  accept that proof and an agent's `git push --delete` of it would be denied.
  It is listed as skipped. Widening both together is a separate decision.
- **The push carries a lease per ref**
  (`--force-with-lease=refs/heads/<n>:<proven tip>`), so a commit pushed
  between `ls-remote` and the delete makes git reject that ref rather than
  lose it. Results are read per ref from `--porcelain`.
- **Remote tips go into the same recovery bundle** as
  `refs/remotes/<remote>/<name>`, with a restore line that fetches the ref back
  and pushes it.

## Open questions (owner)

1. **Limit on re-parks/re-keeps?** Recommendation: none; the new-reason rule
   and the visible count are enough, and a hard limit would force a delete of
   work someone still wants.
2. **Should a stale kept merged branch be deleted automatically by
   `branch-sweep --clean`?** Recommendation: yes, once Phase 3 lands: a lapsed
   keep is just an unkept merged branch, and the clean path still proves it
   and bundles it.
3. **Notes ref push conflicts** between two clones keeping different branches:
   recommendation `git notes merge -s union` on a rejected push, retried once;
   otherwise report the retry command, as `branch-park` does for its push.
