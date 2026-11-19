# Plan 00628 sub-agent report: over-limit socket path forced by init.sh

**Branch**: `agent-a846cb391ebdc85b8-4a1c1f76` (pushed; not merged)

## Root cause

1. `init.sh` `start_daemon` always passed its own computed default through `CLAUDE_HOOKS_SOCKET_PATH` / `CLAUDE_HOOKS_PID_PATH`, and `paths.get_socket_path` / `get_pid_path` returned an override verbatim. The length fallback never ran for a daemon a hook started, so the bind failed (`OSError: AF_UNIX path too long`). The CLI, which passes no override, computed the fallback and reported a different socket.
2. `cmd_start`'s daemon child wrote the SHARED discovery file before binding, and its generic `except` set `i_owned_the_daemon = True`. A failed start therefore overwrote a live incumbent's discovery file with its own unbindable path, then deleted it. The reporter's reading (cli.py around 1004 and 1028-1040) was correct.

Reproduced in this worktree: see the journal finding entry; scripts `untracked/scratch/00628/repro.bash` and `repro2.bash`, with before and after output beside them.

## Fix

- `paths.fit_socket_path(project, requested=None)` and `fit_pid_path` are the one decision. A requested path that fits 104 bytes is honoured verbatim; an over-limit one becomes the project's fallback, the same path a caller naming none computes. They are used by env overrides (`get_socket_path`/`get_pid_path`), CLI flags (`_resolve_socket_path`/`_resolve_pid_path`), config (`DaemonConfig.get_socket_path`/`get_pid_file_path`) and `transport_verify.resolve_events_dir`.
- `init.sh`:
  - Passes only caller-set socket/PID paths to the launcher.
  - `_hooks_daemon_follow_discovery` (the extracted discovery block) runs at source time and in every readiness-poll tick, so the starting hook reaches the daemon.
  - The PID-follows-socket rule is unchanged: follow only when the PID path itself is over 104.
- The discovery file is written from the `serving` callback (after bind) and cleaned only when this process wrote it.

## Security

- Each short-path rung must pass `_is_private_dir`: lstat (a link is never followed), a directory, owned by the euid, no group/other bits.
- When none passes, the last resort is `/tmp/hooks-daemon-<euid>`, created 0700 and re-verified. Bare `/tmp` is never used.
- An existing non-private one raises `UnsafeRuntimeDirError`, which `cmd_start` prints to stderr before the fork and returns 1 (fail closed, clear message).
- Socket mode stays 0660, set by the server after bind.
- This TIGHTENS the guard; nothing is loosened. Hosts with a non-private `$XDG_RUNTIME_DIR` (this container: uid 0 with `/run/user/1000`, root-owned 0755) move to `/tmp/hooks-daemon-<uid>`.
- Nothing in bash or the relay recomputes the fallback: `git grep` shows no `run/user`/`XDG_RUNTIME_DIR` logic outside paths.py.

## Tests

- New:
  - `tests/unit/daemon/test_socket_path_fit.py`
  - `tests/unit/daemon/test_cli_start_discovery_after_bind.py`
  - `tests/integration/test_init_sh_long_project_path_reaches_its_daemon.py`
- Each new test failed before the fix for the reported reason. The integration test hit "Daemon startup timeout".
- Updated existing tests (expectations that encoded the defect or the bare `/tmp`):
  - `tests/daemon/test_paths.py`: env override is now fitted; run_user and tmp rungs go through `_is_private_dir`; `TestPathGeneration` pins a private XDG dir.
  - `tests/unit/daemon/test_cli_start_reuse.py`: the owner test calls `serving`.
- Targeted runs:
  - 1172 unit tests (paths, cli start/reuse/discovery, event sockets, forwarder generator, transport probe, config) pass.
  - 64 integration tests (init.sh discovery, boot race, live socket reuse, symlinked project, bash 3.2, hot path, relay guard, fallback events dir) pass, with 56 skipped by their own guards.
- ruff, black, mypy and shellcheck are clean on the touched files.

## Not fixed (niggle)

The launcher prints "Daemon started successfully" for a daemon child that died while binding: `_await_started_daemon` accepted the PID before the bind. Worth a separate plan.

## Release note

`CLAUDE/UPGRADES/UNRELEASED/release-notes/006-long-project-path-socket.md` (the coordinator renumbers it if needed).
