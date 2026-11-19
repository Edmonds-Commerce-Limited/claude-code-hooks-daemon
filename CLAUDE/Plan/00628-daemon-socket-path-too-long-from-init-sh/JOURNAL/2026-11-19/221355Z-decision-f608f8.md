## 22:13 · decision · —

GREEN. Root cause: `paths.get_socket_path` / `get_pid_path` returned a `CLAUDE_HOOKS_SOCKET_PATH` / `CLAUDE_HOOKS_PID_PATH` override verbatim, and `init.sh`'s `start_daemon` always passed its own computed default through those variables, so the length fallback never ran for a hook-started daemon. Second defect: `cmd_start`'s daemon child wrote the shared discovery file before binding and its generic `except` claimed ownership, so a failed start overwrote then deleted a live incumbent's file.

Fix (one decision point):

- `paths.fit_socket_path(project, requested=None)` / `fit_pid_path`: the requested path if it fits the 104-byte limit, else the project's short fallback. Used by `get_socket_path`/`get_pid_path` (env), `cli._resolve_socket_path`/`_resolve_pid_path` (flags), `DaemonConfig.get_socket_path`/`get_pid_file_path` (config) and `transport_verify.resolve_events_dir`.
- `_pick_short_path_root_dir`: each rung must be a real dir owned by the euid with no group/other bits (`_is_private_dir`, lstat, no symlink follow). Last rung is `/tmp/hooks-daemon-<euid>` created 0700 and re-verified; a squatted/linked/open one raises `UnsafeRuntimeDirError`, which `cmd_start` reports before the fork (exit 1).
- Discovery file written from the `serving` callback (after bind), cleaned only when this process published it.
- `init.sh`: discovery-following extracted to `_hooks_daemon_follow_discovery`, called at source time and in `start_daemon`'s readiness poll; only caller-set socket/PID paths are passed to the launcher; `$PYTHON_CMD` now quoted.

Reproduction after the fix: `ensure_daemon: OK` on the first hook; status and hook name the same socket; a forced long-path start reuses the incumbent and the discovery file survives.

Container note: as uid 0 with `XDG_RUNTIME_DIR=/run/user/1000` (root-owned, 0755), the runtime dir is now rejected and the fallback is `/tmp/hooks-daemon-0` (0700). Not fixed here (niggle): the launcher prints "Daemon started successfully" for a daemon child that died while binding.
