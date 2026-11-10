# DESIGN: Plan 00594, branch lifecycle and branch-tip channel (Phase 1)

Paths are relative to `src/claude_code_hooks_daemon/` unless they start at the repo root. This design builds on 00558, 00570, 00571 (DESIGN.md §2-§7) and 00254. It contradicts none of them. Where 00571 deferred a decision, this design settles it.

## 1. Lifecycle state machine

| #   | Transition                                | Driven by                                                                         | Evidence required                                           | Records                                                                      |
| --- | ----------------------------------------- | --------------------------------------------------------------------------------- | ----------------------------------------------------------- | ---------------------------------------------------------------------------- |
| T1  | ∅ → **born**                              | creation guard (`handlers/pre_tool_use/branch_creation_guard.py`), WorktreeCreate | `branch-preflight` verdict (§2.3)                           | creator in git config (`core/branch_records.py:86`)                          |
| T2  | born → **open**                           | first commit (touch recorder)                                                     | tip ≠ base                                                  | `hooksDaemonTouchedBy`                                                       |
| T3  | open ⇄ **parked**                         | `branch-park` / `--clear`                                                         | stated reason, new on re-park                               | park commit + local park record (§2.4)                                       |
| T4  | open/parked → **finished (proven)**       | session start, stop, `branch-sweep`                                               | ancestry, patch-id, tree containment or forge record (§2.1) | proof cache keyed by tip sha; park record cleared, and the clear is reported |
| T5  | finished → **kept**                       | `branch-keep`                                                                     | finished state                                              | note `refs/notes/hooks-daemon/keep` (00571 §2)                               |
| T6  | finished → **deleted local**              | `delete-branch`, `branch-sweep --clean`                                           | T4 proof + tip re-check (00254)                             | recovery bundle (00571 §6)                                                   |
| T7  | finished → **deleted remote**             | `branch-sweep --clean --remote`                                                   | T4 proof + live `ls-remote` + lease                         | remote tip in the bundle                                                     |
| T8  | any → **foreign** (reported, not counted) | inventory                                                                         | no owner match (§2.2)                                       | none                                                                         |

Any new commit on a finished or kept branch sends it back to open, because proofs and keeps are keyed by tip. Nothing reaches T6 or T7 without a proof and a bundle. The no-loss guarantee is unchanged.

## 2. Decisions

### 2.1 Proof of merge (class 3, also class 8)

There are four kinds of evidence, tried in order and cheapest first:

1. **Ancestry.** Offline.
2. **Patch-id** (`git cherry`). Offline.
3. **Tree containment** (`TIER_CONTENT_PRESERVED`, `daemon/branch_safety.py:73,274`). Offline. This is what proves squash merges with many commits and renamed-PR merges.
4. **Forge record.** A merged PR whose head sha equals the tip. Needs the network, so it runs on explicit CLI commands only, never on a hook path (00570 non-goal).

Results go into the inventory cache keyed by tip sha (`core/branch_inventory.py:634,663`), so hooks read them offline.

Changes:

- `core/remote_branch_proof.py:103` (`_merged_into`, ancestry only) accepts evidence 1-3, reusing `branch_safety` helpers rather than adding new ones.
- `core/branch_cleanup.py:486-487` stops skipping patch-equivalent remotes.
- The `destructive_git` guard uses that same proof, which closes the "widening both together" item 00571 §6 left open.
- `core/branch_creation.py:266` `_merged_refnames` (ancestry only) also reads the cached proofs. Without that, a squash-merged branch keeps counting as open.

### 2.2 Owner (class 7)

The rule runs offline, in this order:

1. A `hooksDaemonCreator` record in this clone (`core/branch_records.py:33`) means **mine**.
2. Otherwise, a branch with a local ref, or a remote tip whose author email equals `git config user.email`, is **mine**.
3. Anything else is **foreign**. It is listed in a "Foreign" sweep group with its age and author, is counted in no pool, and is never cleaned automatically. `--clean --remote` still deletes a *proven-merged* foreign branch, because proof matters more than ownership.

Git notes and trailers were rejected: they need a push to exist, and branches created outside the daemon never get one. `bot_owned` (00571 §7) stays as it is. Foreign is the general case of it.

### 2.3 Where pressure lands (classes 2, 4)

| Point                                        | block mode                                                                                                    | warn mode |
| -------------------------------------------- | ------------------------------------------------------------------------------------------------------------- | --------- |
| session start                                | lists every blocker plus the preflight report                                                                 | same      |
| stop (`core/branch_stop_gate.py:148`)        | denies only for this session's own touched open branches over cap or dormant                                  | context   |
| after a merge (`merge_qa_advisor` / sweep)   | advises the T6/T7 command                                                                                     | same      |
| creation (`core/branch_creation.py:653-661`) | **backstop**: denies only at cap + `wip.creation_grace` (default 2), so an urgent fix can always get a branch | context   |

`branch-preflight [name]` reuses `creation_verdict` but evaluates every pool, not only the first rule that trips. Each blocker comes with its exact command. The creation deny renders the same report. No deny ever offers rename, or deleting a foreign branch, as a fix.

### 2.4 Park record (class 5)

The park commit stays the shared record, keeping the 00558 §5 mechanics and the 00571 §4 re-park count. Three additions:

- `branch.<name>.hooksDaemonParked=<park sha>` in git config (the `branch_records` precedent). It is written even when the push is rejected.
- `_group_pool` (`core/branch_creation.py:333-335`) currently returns OPEN if *any* copy is open. That is why a branch whose park push was rejected still counts. The change: when the local park record holds and the remote tip is an ancestor of the park commit, the group resolves to PARKED.
- `_park_shas` (`core/branch_inventory.py:476`) follows the first-parent line past a merge *from* the default branch. When a park ends, either through new work or through T4, the next session start and sweep print "park cleared: <reason>" once, and the config record is then removed. The park never ends silently.

### 2.5 Daemon housekeeping commits (class 1)

**Cause.** `ClaudeMdInjector._run_inject` (`core/claude_md_injector.py:393`) skips only *linked* worktrees (`:409`). In the main checkout it writes the block and `_auto_commit_if_dirty` (`:665`, commit at `:747-755`) commits onto whatever HEAD is: a feature branch, a detached HEAD (which leaves a dangling commit), or the default branch without pushing it. `regenerate-docs` forces the write in linked worktrees (`daemon/cli.py:4485`). A dirty `CLAUDE.md` there makes `git worktree remove` refuse, so agents committed it on a throwaway branch.

**Answer.** Write and auto-commit only when HEAD is the default branch, attached, in the main worktree. Anywhere else, do not write at all, which extends the `:409` rule. `regenerate-docs` off the default branch writes the file but never commits it, and says so.

**Reason.** The block describes the default branch's handlers. A feature branch picks up the regenerated block after its merge, at the next restart on the default branch. "Untracked" would lose the block in clones, and "no-branch commit" still leaves a dirty tree.

### 2.6 Regenerable dirs and bulk cleanup (classes 6, 8)

- `DEFAULT_REGENERABLE_STORES` (`utils/regenerable_paths.py:25`) gains the ignored vendor stores `node_modules/`, `vendor/`, `.venv/`, `target/` and `.gradle/`. The default is still checked against `NEVER_REGENERABLE`. The list is already configurable (`config/models.py:2390`), so only the default changes.
- Bulk cleanup: `branch-sweep --clean [--remote] --dry-run` writes `untracked/branch-cleanup/plan-<stamp>.json`. Then `--apply <plan> [--batch N]` deletes in batches of 50 per push, with a lease per ref and one bundle per batch, and records progress in the plan file so an interrupted run resumes. Branches zero commits ahead are proven by one `for-each-ref --merged`.

### 2.7 Journal heading (class 9)

`CLAUDE/Plan/mkplan.bash:517` defaults the ref to `—`, and `:625-627` adds `   — title` (three spaces). The fix emits `## HH:MM · category — title` when there is no ref, with single spaces. That heading is formatter-stable. The `**/JOURNAL/**` formatter exclusion also goes into `CLAUDE/LLM-INSTALL.md`.

## 3. Branch-tip channel

This builds on the guarded branch install from Plan 00291:

- `scripts/upgrade.sh:731-775` handles `HOOKS_DAEMON_UNSAFE_TRACK_REF` plus `_BECAUSE`.
- The stamp is `vX.Y.Z+<ref>.<sha>` (`install/install_stamp.py:25`).
- `handlers/session_start/version_check.py:227` flags it.

What is new:

- **Pin.** `upgrade --track <branch|sha> --because "<why>"` is a skill-level spelling of the two environment variables. The stamp loses the ref's `/` (it becomes `-`), so the exact ref, the full sha and the last release tag go into `.daemon-metadata.json` (`daemon/metadata.py:27`): `{tracked_ref, tracked_sha, last_release_tag}`. `last_release_tag` comes from `ROLLBACK_REF` (`scripts/upgrade_version.sh:898`) when the previous install was a release.
- **Detect a move.** `version_check._branch_install_context` (`:447`) reuses the handler's existing TTL cache and network budget. It makes one `remote_refs.list_remote_refs(patterns=[refs/heads/<ref>])` call (`utils/remote_refs.py:48`). If the tip differs from `tracked_sha`, it reports "tracked ref moved <old>..<new> (N commits); re-run `upgrade --track <ref>`". A sha pin never moves. A failed listing says "not checked" and never "current".
- **Rebuild.** Re-running the upgrade re-enters the existing path. `ensure_venv` (`scripts/upgrade_version.sh:936`) installs from the target's `uv.lock`, keyed by `INSTALL_STAMP`, so a new sha produces a new stamp and a rebuild. The order follows Plan 00535: stop the daemon, check out, build, then start. That part must land before the channel ships. Plan 00535 Task 2.1 stays the owner of the handover, and this plan depends on it.
- **Return.** `upgrade --release` checks out `last_release_tag`, or the latest tag if none was recorded, with no tracking environment variables. It also clears the tracking metadata. It is one command.

## 4. Open questions for the client test seat

1. Do seats share one `user.email`? If they do, the §2.2 rule 2 owner check cannot tell seats apart, and the fallback needs a per-seat identity.
2. Among the 135 branches zero commits ahead, how many are foreign or bot-made? This sizes the first `--apply` run.
3. Is the client's forge CLI usable for proof 4? Or are tree containment and patch-id enough for the PR-renamed shapes?
4. Does any seat keep the main checkout on a non-default branch for long periods? If so, the §2.5 rule leaves the block stale there.
5. Is a creation grace of 2 enough for the urgent-fix sequence that was observed?
6. Which vendor directory names actually blocked cleanup in client worktrees?

## 5. Critical files for implementation

- `core/claude_md_injector.py`
- `core/branch_creation.py`
- `core/remote_branch_proof.py`
- `core/branch_inventory.py`
- `scripts/upgrade.sh`, with `scripts/upgrade_version.sh` and
  `handlers/session_start/version_check.py`

Status: a draft for review with the client test seat (Task 1.3). It has not
been checked against client evidence yet.
