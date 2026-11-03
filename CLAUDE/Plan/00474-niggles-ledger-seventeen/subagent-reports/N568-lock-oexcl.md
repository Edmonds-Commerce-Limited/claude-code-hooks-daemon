# N568: scaffold and venv locks no longer trust the external `mkdir`

Brief: `/workspace/untracked/scratch/brief-lock-oexcl.md`. Branch `worktree-lock-oexcl`. Not merged or pushed.

## Root cause

CI run 41530438536 (`ubuntu-26.04`) traced two `mkroutine.bash` runners that both took the
lock (`mkdir` exited 0 twice on one path, 11 µs apart) and both allocated `00001`. Ubuntu
25.10+ ships uutils coreutils as `mkdir`. The exact uutils mechanism was NOT confirmed from its
source; the fix does not depend on it.

## Class and sweep

Class: a lock whose exclusivity rests on an external `mkdir` failing with EEXIST.

Swept all tracked `*.sh`, `*.bash` and extensionless bash-shebang files (155), excluding
`tests/fixtures/cyber-flag/` and `CLAUDE/Plan/Completed/`. Instances:

1. `CLAUDE/Plan/mkplan.bash` `acquire_lock` (fixed)
2. `src/claude_code_hooks_daemon/install/templates/mkplan.bash` (fixed, byte-identical copy)
3. `CLAUDE/Routine/mkroutine.bash` `acquire_lock` (fixed; not deployed anywhere)
4. `scripts/install/venv.sh` "mkdir" backend (`_venv_lock_try_once`, adopt, release) (fixed)
5. NEW, not in the brief: `provision.sh` `_provision_background_lock` (`background-sync/lock.d`);
   `.claude/provision.sh` is a symlink to it (fixed)

Related but outside the class: `src/claude_code_hooks_daemon/daemon/venv_lock.py` used `os.mkdir`
(a real syscall). It was moved to the same lock-file shape so it still excludes bash.

Second-order uses noted, not changed: `if ! mkdir "$target"` collision guards in mkplan.bash
(plan folder, `JOURNAL/`) and mkroutine.bash (routine folder, `RUNS/`). They run under the lock
and back up the counter, so they do not grant exclusivity on their own. A permissive `mkdir`
weakens only that extra check.

## Fix

A lock is now a regular file at the SAME path, holding the holder's pid, created with
`(set -C && printf '%s\n' "$pid" > "$lock")`. Bash's noclobber opens a missing file with
`O_CREAT|O_EXCL`, and the subshell keeps `set -C` from leaking. This is POSIX, so macOS bash 3.2
works. Kept: the `BASHPID` owner check, EXIT/INT/TERM traps, the retry, timeout and error text
(now "remove it" rather than "remove the directory"), the `MKROUTINE_TRACE` events, venv.sh's
stale age and heartbeat (its error log moved to `<lock>.heartbeat.log`, removed on release), and
the handoff spec `mkdir:<path>` (the backend name stays for compatibility).

Older version's lock DIRECTORY at the same path: the exclusive open fails on it (EISDIR), so it
counts as held. The scaffolders wait and then time out naming it. venv.sh and `venv_lock.py`
reclaim it by age. provision.sh reads the `pid` inside it. Release reads either shape. Legacy-dir
behaviour is still covered by the existing tests that `mkdir` the lock path.

Because a held lock is now a file that `git status` can see, `.mkplan.lock` and `.mkroutine.lock`
are gitignored.

## Tests

New file: `tests/unit/scripts/test_lock_survives_a_permissive_mkdir.py`. A fake `mkdir` goes
first on PATH; it uses `-p` semantics after a 0.2s sleep.

- `test_a_held_lock_keeps_a_second_runner_out[mkplan|mkroutine]`: the holder is parked at the
  counter read by a `git` shim, and the test requires that a second runner never gets there.
- `test_parallel_runs_get_distinct_numbers[mkplan|mkroutine]`
- `test_venv_fallback_lock_refuses_a_second_taker`: a second `try_acquire_venv_lock` must return 75.

RED against the unfixed scripts: all 5 failed. The second runner entered the critical section
(`second=0`, `00001-second-run`). `numbers=['00001', '00001']` for mkroutine. For mkplan, the CI
`rmdir: failed to remove ... No such file or directory` reproduced. venv returned
`first=0 second=0`. All 5 are GREEN after the fix.

Updated for the new shape: `tests/unit/daemon/test_venv_lock.py` (file-shape tests added, and
legacy-dir tests kept), `tests/unit/scripts/test_scaffold_lock_signal.py` (`is_file`), and
`tests/integration/test_venv_bootstrap_driver.py` (the adopted lock is a file).

Run after the fix: `tests/unit/scripts/`, `tests/unit/daemon/test_venv_lock.py`,
`tests/unit/daemon/test_cli_repair.py`, `tests/integration/test_ensure_venv_lock.py`,
`tests/integration/test_venv_bootstrap_driver.py`, `tests/integration/test_provision_sh.py`,
`tests/unit/routines`. Result: 846 passed.

## Docs

- Release note `CLAUDE/UPGRADES/UNRELEASED/release-notes/021-mkroutine-mkplan-lock-race.md`
  (Callout retitled).
- N568 in `NIGGLES.md` and its `STATUS-INDEX.md` row.
