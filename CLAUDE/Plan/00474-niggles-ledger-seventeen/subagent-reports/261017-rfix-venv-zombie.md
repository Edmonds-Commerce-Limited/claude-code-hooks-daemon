# rfix-venv-zombie: zombies and kernel threads no longer count as unreadable processes

## Assumption

The brief said to count as unreadable only a pid where something was refused with EACCES/EPERM. I did not do that.
A kernel thread read by a non-root user is refused (EPERM from the ptrace check on `exe`), not ENOENT, so the errno cannot
tell it from another user's process. The test is the world-readable `/proc/<pid>/stat`: state `Z`, or `PF_KTHREAD`
(0x00200000) in the flags field. I chose the flag test because it is exact and works for another user's zombie too.

Any pid that shows nothing and is not positively identified that way (stat missing, unreadable or unparseable) is still
counted, so the cleanup stays fail-closed for genuine doubt.

## Fix

`src/claude_code_hooks_daemon/daemon/paths.py`: new `_holds_no_user_memory(stat_path)`; `processes_using_venvs` consults
it only when exe, cwd and argv0 are all empty. The comm field is split after the last `)` so a comm containing spaces or
parentheses cannot hide the state. `daemon/cli.py` `_cleanup_proven_stale_venvs` needed no change: it reads `scan.unreadable`.
`list-venvs`, `gather_venv_evidence` and the SessionStart advisory share the scan, so the false "could not be read" line is gone too.

## Tests (red then green)

Red, with the fix reverted: 5 failed, 40 passed (zombie, kernel thread and comm-with-parens in
`tests/unit/daemon/test_paths_venv_evidence.py`; zombie and kernel-thread reclaim in
`tests/unit/daemon/test_cli_stale_venv_cleanup_on_start.py`). Green with the fix: 45 passed.

Kept: the deliberately-unreadable other-user case (`stat` says an ordinary sleeping process, nothing else readable: counted),
the bare empty `/proc/21` case, the mid-scan exit case. Added: unparseable stat stays counted.
The existing start-time cleanup fixture patched the scan to `unreadable=0`, which hid this defect; the new reclaim test
runs the real scan against a fake proc root instead.

## Release note

None added. Note 055 does not describe the unreadable-count behaviour, so nothing became untrue.

## Siblings checked

`gather_venv_evidence`, `list-venvs` and the advisory consume the same `ProcessScan`; no other `/proc` scan counts unreadable pids.
