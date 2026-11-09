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
per pool, as `open_work_count` does today (`core/branch_sweep.py:148`). This
replaces 00558 §3 (`00558 DESIGN.md:137`: "Merged-but-undeleted branches DO
count ... Parked branches count"). Each deny
lists only that pool's branches and only actions that lower that pool's count
(the #165 defect is that the wip deny offered "park", which did not).

## 2. Keep-reason store for merged branches: a git note on the tip

**Decision:** `branch-keep <name> --reason "<text>"` adds a note under
`refs/notes/hooks-daemon/keep` on the branch's tip commit. The note body is
`Kept-Reason: <text>`, `Kept-By: <git user>`, `Kept-At: <UTC ISO>`. It pushes
that notes ref to `branches.remote` explicitly.

Why a note, against 00558 §5 (`00558 DESIGN.md:218`), which rejected notes for
the park marker:

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
  bot_owned: ["dependabot/*"]  # section 7: in no pool, never cleaned
```

No new number is introduced; every default derives from a value the owner
already ruled on: `wip.cap` 10 (`config/models.py:2268`, 00558 Q2) and the
dormancy presets `standard (7, 14, 30)` / `strict (3, 3, 7)`
(`config/models.py:2254-2257`).

**This repository's real counts** (`bin/hooks-daemon branch-sweep --all`,
2026-11-07, on this branch):

| Pool                    | Members today                                                                           | Ages     |
| ----------------------- | --------------------------------------------------------------------------------------- | -------- |
| open work (8 of 10)     | 2 agent branches, `worktree-n578-chained-push-delete`, **4 `dependabot/*` remote-only** | 0d-1d    |
| parked (1)              | `worktree-476-ci-gate-trial` (Plan 00476 trial, not to be merged)                       | 2d (tip) |
| merged, not deleted (2) | two `agent-*` branches whose live isolation worktrees hold them (Task 2.8 spares them)  | 0d       |

and, from the #165 report that opened this plan (PLAN.md Overview), five
58-day-old merged branches made up most of a 9-of-10 count. Read against the
defaults:

- Parked: 1 of 10, so the default cap does not bind; the one park is a
  deliberate not-to-merge record and sits well inside 30 days.

- Merged: the five 58-day-old branches would have been 5 of 10, not denied by
  the cap, but each is UNKEPT, so it is cleanup debt the deny names from day 0
  (below) and `branch-sweep --clean` clears in one call. The cap is the
  backstop for kept branches, not the main pressure.

- Open work: half of today's 8 are bot branches no agent can finish, park or
  delete. That is section 7's exemption, not a reason to raise `wip.cap`.

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
  `core/branch_inventory.py:438`, called at `:482`). The sweep prints `re-parked N times` from that
  run's length. No separate counter.
- `branch-keep` on an already-kept tip replaces the note; the notes ref's own
  history (`git log refs/notes/hooks-daemon/keep`) keeps every earlier reason
  and gives the re-keep count. The same new-reason rule applies.

## 5. Config and truth migration

- **Config:** additive keys only (section 3), every one with a model default,
  `extra="forbid"` like the existing `Branch*Config` models
  (`config/models.py:2263-2272` is the `BranchWipConfig` shape to mirror).
  Phase 3 records a `config-changes` entry under
  `CLAUDE/UPGRADES/UNRELEASED/config-changes/` listing the six pool keys plus
  `branches.bot_owned` (section 7) as `added`, `breaking: false`, none
  `recommended`. A project that sets nothing gets three caps of `wip.cap`
  and ages of its dormancy preset, so its existing `wip.cap` keeps meaning
  "how many of anything".
- **Truth changes** (Phase 3, `CLAUDE/UPGRADES/UNRELEASED/truth-changes/`):
  "a parked branch still counts against `branches.wip.cap`"
  (`docs/guides/CONFIGURATION.md:346`, `00558 DESIGN.md:137`) and
  "merged-but-undeleted branches count against `branches.wip.cap`"
  (`00558 DESIGN.md:137`) both become false; each pool now has its own cap.
  A third: "remote-only branches count" (`count_remote`,
  `config/models.py:2270`) stops being true of `branches.bot_owned` branches.
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
- **One remote listing implementation (Task 2.7).** `--clean --remote`
  (`core/branch_cleanup.py:705` `_proven_remote`) never listed the remote
  twice in one run: the clean path builds its inventory offline and makes its
  only `ls-remote` inside the proof. But that proof
  (`core/remote_branch_proof.py:221` `live_remote_tips`) carried its own
  `ls-remote` call and parser beside Plan 00570's
  `utils/remote_refs.py`. It now lists through
  `remote_refs.list_remote_refs(..., patterns=..., timeout=...)`
  (`utils/remote_refs.py:48`), bounded to the judged `refs/heads/<name>`
  patterns and kept on the hook timeout (`Timeout.GIT_CONTEXT`), because the
  `destructive_git` guard runs the same proof on the hook path. A failed
  listing is still no proof.
- **One work-queue reader (Task 2.7).** The stop gate's
  `_running_queue_branches` (`core/branch_stop_gate.py:113`) delegates to
  `agent_ownership.running_holds` (`core/agent_ownership.py:51`), the reader
  `--clean` and `worktree-reap` use. It now honours worktree holds too: a
  branch checked out in a worktree a `running` record names, in any path
  spelling, is handed over, so the gate and the sweep agree on what a live
  agent owns.

## 7. Bot-owned branches (`dependabot/*`)

Dependabot was enabled for this repository by Plan 00572 Task 4.1
(`.github/dependabot.yml`, weekly, grouped). Within hours its four branches
were half of this repository's open-work count (section 3 table). They are
remote-only (`count_remote: true` counts them, `config/models.py:2270`),
unmerged, and owned by the bot: no agent can finish, park or delete one
without closing the bot's pull request.

**Decision:** a new key `branches.bot_owned: ["dependabot/*"]`. A branch
matching it is in NO pool and is never a `--clean`/`--clean --remote`
candidate, exactly as `exempt` behaves ("never counted, judged or deleted",
`config/models.py:2408`), and is listed in its own "Bot-owned" sweep group so
it is visible rather than silent.

- **Why not reuse `exempt`:** `exempt` is a user list defaulting to `[]`
  (`config/models.py:2417`); a model default of `["dependabot/*"]` there
  would vanish the moment a project sets its own `exempt`, re-counting the
  bot branches. A separate key keeps the bot default independent.
- **Why not delete merged bot branches:** GitHub and Dependabot remove
  their own head branches when the pull request closes. A
  `--clean --remote` race on one gains nothing and can close an open PR
  whose branch is at an old merged tip. The remote-delete guard is
  unchanged: an agent's explicit `git push --delete dependabot/...` is still
  judged by the proof, not blanket-allowed.
- **The default names only the bot this repository runs.** `renovate/*` and
  others are added by a project that uses them; the doc lists them as
  examples rather than shipping globs for bots nobody here runs.

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
