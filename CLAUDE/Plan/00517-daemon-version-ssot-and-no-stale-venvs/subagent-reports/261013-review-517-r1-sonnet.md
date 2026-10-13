# Code Review: Plan 00517 staleness cleanup (`worktree-plan-517-staleness`)

I read the diff in full and did not run any tests. My first test run was blocked by a hook and I did not retry it.

## Findings

**1. SHOULD-FIX (high): `sweep_dead_runtime_sets` can call a live peer's set "dead" across container namespaces.**
- Location: `paths.py` `_socket_is_dead` (~2441), `_set_sockets` (~2478), `sweep_dead_runtime_sets` (~2536).
- Failure scenario:
  - A peer container shares the checkout on a bind mount. Its socket path is too long, so it falls back to `/run/user/N` or `/tmp`. Its `daemon-<id>.pid` and `.socket-path` stay in the shared dir.
  - From our container, the fallback path does not exist, so the connect raises `FileNotFoundError`, which `_socket_is_dead` treats as dead.
  - `read_pid_file(verify_daemon=True)` checks the peer's pid in our pid namespace, so it finds nothing or an unrelated process. The check returns `None`.
  - The set is older than 60s, so the pid, discovery file and `events-<id>/` of a live daemon are deleted.
- The docstring says "refuses a connection", but the code accepts "file is gone" as proof. That is only proof when the path is inside the shared untracked dir.
- Fix direction:
  - Treat `FileNotFoundError` as dead only for a socket under `untracked_dir`.
  - If the discovery file names a path outside `untracked_dir`, or a pid that cannot be verified in this namespace, keep the set (fail closed).
  - Add a test for the discovery file naming an out-of-tree missing socket.

**2. SHOULD-FIX (high): the start-time venv cleanup cannot see peer containers using a same-slug venv.**
- Location: `cli.py` `_cleanup_proven_stale_venvs` (~3078); `paths.py` `processes_using_venvs`.
- Failure scenario:
  - The host and container mount the same checkout at the same path, so they have the same slug and share one `untracked/`.
  - The first one to start after a source or lock change sees the other's running venv as `lock_hash` differs and therefore STALE.
  - `/proc` only shows this pid namespace, so the in-use check passes. The venv under the peer's running daemon is `rmtree`d.
  - The peer's lazy imports and its next restart then fail.
- The old design (Plan 00181 Decision 1) refused auto-delete for exactly this reason. This diff reverses it with no peer-liveness check.
- `ProcessScan.unreadable` is ignored on the auto path.
- Fix direction:
  - Skip automatic removal while any other host's runtime set is alive. Reuse the socket-connect and pid checks from item 1.
  - Or require the venv to have been unmodified for a grace period.
  - Record the decision in the Plan 00517 journal.

**3. SHOULD-FIX: `prune-venvs --stale` and `--legacy` skip the process check that `--unproven` and the auto path do.**
- Location: `cli.py` `cmd_prune_venvs` (~3506-3535).
- The advisory tells users to run `--stale --force`.
- A stale venv with a live user (the bare-`python` case in item 6, or a peer) is removed. `_remove_venv_dirs` has no `processes_using_venvs` guard.
- Fix direction: apply the same in-use filter inside the shared removal path.

**4. NIT: release-note coverage is mostly there, with one stale caller.**
- The flag removal is in note 055, and the flag still parses and prints an explanation.
- `CLAUDE/UPGRADES/v3/v3.6-to-v3.7/post-upgrade-tasks/01-prune-legacy-venv.md:63-64` still instructs `prune-venvs --all-except-current --force`. A v3.6 upgrader now gets an error. Update it to `--stale`.
- Nothing in `scripts/`, `install/` or the skills calls the flag. `housekeeping.py:139` runs `prune-venvs` bare, and its label "Delete stale fingerprint-keyed venvs" is now inaccurate.
- The removal is not recorded in `config-changes`. That is arguably correct because it is a CLI flag, not config.

**5. NIT: duplicated catch in `_reap_stale_runtime_files` (`cli.py` ~637-653).**
- The `except (OSError, ValueError, VenvLockTimeout)` and the `except Exception` blocks do the same thing at different log levels.
- Fail-open holds, so a cleanup error cannot stop a start. Collapse the two blocks into one.
- `_stale_venv_advisory` runs after the try block and is unguarded. It could raise and abort the start. Wrap it too.
- `_newest_mtime` does `lstat` on files that can vanish mid-sweep. The resulting `FileNotFoundError` aborts the whole sweep, which is harmless but wasteful.

**6. NIT: `processes_using_venvs` argv0 matching is only partial.**
- A process started as bare `python` after venv activation, with its cwd outside the venv, has `exe` pointing at `/usr`. It is invisible to the scan.
- This weakens "no process uses it" for items 2 and 3.

**7. NIT: the SessionStart advisor runs a full `/proc` scan on every session start while any UNPROVEN venv exists.**
- Location: `unproven_venv_advisor.py` `handle`.
- It reads 3 files for every pid, and unproven venvs persist until someone removes them.
- Consider caching, or limiting the scan to when the unproven set has changed.
- Registration is otherwise correct: HandlerID, priority 72 (shared with `routine_qa_sweep`, with a comment), config example, acceptance test, config-changes entry, and `get_claude_md` returning `None` with a reason.

## Checks that passed

- **`classify_venv`** compares `venv_dir.resolve()` against `live_venv_realpaths`. That function takes the directory from the unresolved `bin/python` (`parent.parent`) and unions in `sys.prefix`, which avoids the `/usr` trap. Symlinked venv names are KEEP, and the current-fingerprint venv is always KEEP.
- **Sibling worktree and main venvs:** `classify_untracked_venvs` only scans this daemon dir's `untracked/`. Slugs differ across views, so those venvs come out UNPROVEN, never STALE.
- **Removal locking:** the cleanup holds `venv_lock` (5s cap, fail-open) and re-enumerates inside the lock.
- **Mid-build venvs:** missing metadata gives UNPROVEN, not STALE.
- **Own runtime set:** the sweep skips this host's own id, and a listening socket spares the whole set.
- **Constants:** the 60s grace and the 1s probe are named constants.
- **Tests:** coverage looks substantive, including a test that a failed removal does not stop the rest of the set. The gaps are the scenarios in items 1 and 2.

**Verdict: MERGE-AFTER-FIXES.** Fix items 1 and 2 first, because they auto-delete a live peer's state or venv in the shared-mount model. Item 3 is the next priority. Items 4-7 can be filed as non-blocking plan tasks.