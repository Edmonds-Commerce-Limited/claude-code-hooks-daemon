# Plan 00628: adversarial security and correctness review

**Reviewer**: independent sub-agent. I formed my view from `git diff main...HEAD` (tip 4005eee3a) before reading the builder's report.
**Verdict**: PASS once the two fixes in this commit are included. Without them it is a conditional pass: neither defect is a security hole, but one breaks the plan's own claim.

## Defects found and fixed (RED, then GREEN)

1. **The limit was counted in characters, not bytes.** `fit_socket_path` and `fit_pid_path` used `len(str(path))`. The kernel's AF_UNIX limit counts bytes. Probe: a requested path of 78 characters (148 bytes) was kept as it was, and `bind` then failed with `AF_UNIX path too long`. A project path with non-ASCII characters near the limit would hit the original failure again: the daemon cannot bind and every hook reports `daemon_startup_failed`. The same was true of the natural path, because it goes through the same function.
   - Fix: `paths._over_socket_limit()` measures `os.fsencode(...)`, and both fit functions use it.
   - In `init.sh`, `_hooks_daemon_follow_discovery` now runs under `local LC_ALL=C`, so `${#…}` counts bytes there too. Under a UTF-8 locale it counted characters, which would split the bash and Python decisions at the boundary. Checked by hand: under C.UTF-8, `éé` measures 4 inside the function and 2 outside.
   - Test: `test_the_limit_is_measured_in_bytes_not_characters`.
   - Not fixed: the other `len(str(path))` limit checks in paths.py are pre-existing (`socket_path_diagnosis`, the events-dir fit check, `get_event_socket_dir`, `get_log_path`). They have the same flaw. Ledger it.
2. **A relative `$XDG_RUNTIME_DIR` was accepted.** `_is_private_dir` ran an lstat relative to the current directory, so the fitted socket became a relative path such as `xdg/hooks-daemon-<hash>-<host>.sock`. That path differs for each caller's working directory (the daemon child, the hook and the CLI), and the daemon publishes it to the discovery file as it is.
   - Fix: only an absolute value is used. The XDG spec says to ignore a relative one.
   - Test: `test_a_relative_runtime_dir_is_not_used`.

Targeted runs, all GREEN after the fix:

- `tests/unit/daemon/test_socket_path_fit.py`
- `test_cli_start_discovery_after_bind.py`
- `tests/daemon/test_paths.py` (113 passed)
- the init.sh long-path integration test, plus the cmd_start, reuse and bash32 files (results are in the commit message)

Shellcheck on init.sh shows only the pre-existing SC1091 info.

## Attack results

### (1) The `/tmp/hooks-daemon-<uid>` last resort

I probed it against a fixture tree standing in for `/tmp`; the real `/tmp/hooks-daemon-0` was not touched.

| Case                           | Result       |
| ------------------------------ | ------------ |
| fresh                          | created 0700 |
| symlink to a private directory | refused      |
| 0755                           | refused      |
| owned by another uid, 0700     | refused      |
| regular file                   | refused      |

- **TOCTOU.** `mkdir` happens before `lstat`. If our `mkdir` succeeded, we own the entry, and a sticky `/tmp` stops another user renaming or unlinking it, so nothing can be swapped in after the check. A pre-planted entry is refused, which is a denial of service and fails closed.
- **Residual risk.** A `/tmp` that is world-writable but NOT sticky, a misconfigured host, would let another user rename our directory after the check. The parent's sticky bit is not verified. It is still strictly better than main, which used bare `/tmp`. Ledger it.
- **Hostile `XDG_RUNTIME_DIR`.** It must be absolute (fixed above), owned by the euid and closed to others. Whoever sets it already runs as this user; a project could equally set `CLAUDE_HOOKS_SOCKET_PATH` through settings `env`. No new trust boundary is crossed.
- **Parent directories.** Only the final component of XDG is lstat'ed. A private directory inside an attacker-writable parent is not detected. The user's own environment chooses it, so this is low risk.
- **uid 0 and sudo.** `geteuid` is used throughout. Under sudo, an inherited `/run/user/1000` is rejected because the owner does not match. Root and the user therefore compute different fallbacks, so `sudo hooks-daemon status` will not see the user's daemon. That is acceptable and arguably correct.
- **Hash collision.** The name is the first 8 hex digits of md5 plus a host tag, about 2^-32 per pair. It sits inside the user's own private directory, so only the user's own projects can collide. On a collision, project B would reuse project A's daemon. This is pre-existing and was not changed by the plan.
- **Stale socket of another user.** It cannot exist inside a private directory.

### (2) The discovery file

- It is written from the `serving` callback, which `server.start` calls only after `_acquire_socket_and_bind` and the event binds.
- A reuse-race loser raises `DaemonAlreadyRunningError` before `serving`, so it never publishes and never removes the file.
- A crash before the bind does not publish. A crash after the bind removes only its own file. Correct.
- **Residual race, not fixed.** The cleanup in `finally` runs after `asyncio.run` returns, which is after the socket and PID are released. A restart's new daemon could bind and publish in that window, and the old process would then unlink the NEW file. The content would have been the same path, so the only effect is a missing file. A hook in a long-path project would then fail to find the live daemon (start, then reuse, then no file is ever rewritten, then `daemon_startup_failed`) until the next restart. The window is microseconds against a Python start-up, so it is unlikely. A content or inode check before the unlink would close it. Ledger it.
- **Write and read behaviour.** `write_text` is not atomic and follows a symlink. A torn read by init.sh fails `-S` and the next tick re-reads it. Anything able to plant a symlink in the untracked directory can already write the project.
- **Stale file after SIGKILL.** It names a dead socket. init.sh's `-S` passes, the PID check fails, and a start rebinds the same deterministic path. This is self-healing.

### (3) Can a project file redirect hook payloads?

The only file-borne input is the discovery file in the untracked directory. A repository can force-commit a file into that gitignored path, but two things stand in the way:

- The name carries the victim's hostname.
- Following it to a foreign socket is not enough. `is_daemon_running` also needs a PID file whose process belongs to this user AND whose argv proves this project (or the helper's socket proof).

A planted file therefore yields "not running", then a start. The start is passed the planted path through `CLAUDE_HOOKS_SOCKET_PATH`, and binding a live foreign socket is refused. The result is a denial of service, not interception.

- **Behaviour change.** On main, the start overwrote a planted file before binding. Now it persists until a successful bind. Payloads still are not sent, because readiness needs a proven PID.
- **Also new.** The discovery file is now followed when a pinned `CLAUDE_HOOKS_SOCKET_PATH` is over the limit. A pin is the user's own input, so this is low risk.

### (4) Agreement between management commands, and the fail mode

- `status`, `stop`, `restart`, `start`, init.sh (through the forced env, fitted) and the config getters all reach `fit_socket_path` and `fit_pid_path`. A short path produces the same output as on main: the natural path, or the override verbatim.
- **Unsafe last resort, reproduced end to end** with a real init.sh and a stand-in fixture for `/tmp`:
  - `cli start` prints a clean `ERROR:` and exits 1 without forking.
  - `status`, `stop` and `restart` print an **uncaught `UnsafeRuntimeDirError` traceback**. The message inside it is good, but it is a rough edge.
- **The hook (PreToolUse) is FAIL-CLOSED.**
  - The launcher fails at once. init.sh nevertheless keeps polling until `Daemon startup timeout (... 15 seconds after its launcher finished)`, so **each tool call costs about 15 s**.
  - It then calls `emit_hook_error PreToolUse daemon_startup_failed`, which takes the standard branch and runs `_hooks_daemon_stdin_judge permitted`.
  - The result is a deny for every call except the daemon-down allowance (`_is_daemon_down_permitted`): the recovery command, a `Read` of a regular project file, and the exact read-only Bash shapes.
  - Stop and SubagentStop get the bounded block. Other events get the existing fail-open error context, which is the unchanged policy.
  - My first e2e attempt landed on the NOT_INSTALLED branch only because the scratch project had no daemon checkout. That was a fixture artefact; it is not how a real install behaves.

### (5) Regressions

- **Short-path case.** The paths are the same as on main: `fit_socket_path(project)` builds the same untracked path and suffix, and a short override is still verbatim. This is pinned by `test_a_short_forced_path_is_honoured_verbatim` and by the existing `test_paths`.
- **Upgrade with a running daemon (rough edge, ledger).** A long-path install on a host whose `$XDG_RUNTIME_DIR` is not private moves its fallback to `/tmp/hooks-daemon-<uid>/`. The old fallback was used as long as it existed; on main a missing XDG fell back to bare `/tmp`. This container is one such host: `/run/user/1000` is root-owned and 0755.
  - Upgrade Layer 2 runs the NEW CLI's `stop`, which computes the new PID path, finds nothing and reports "not running". The old daemon is orphaned.
  - Hooks keep reaching it through its discovery file until it idles out. A new daemon then starts beside it at the new path.
  - Short-path installs are unaffected.
- **bash 3.2.** The new init.sh code uses `local`, `(( ))` and `[[ ]]`. `local LC_ALL=C` re-reads the locale in 3.2 as well. No bash-4 constructs are added.

## Rough edges worth ledgering

1. The `status`, `stop` and `restart` traceback on `UnsafeRuntimeDirError`. Catch it the way `cmd_start` does.
2. init.sh waits the full startup timeout (about 15 s for each tool call) after the launcher has already exited 1. Stop polling once the launcher reports failure.
3. Cleanup of the discovery file can unlink a successor's file in the restart window. Check content or inode before the unlink.
4. Upgrade orphan: the new `stop` cannot find a daemon that ran under the old, non-private fallback directory.
5. The parent `/tmp` sticky bit is not verified for the last resort.
6. The remaining pre-existing `len(str(path))` limit checks in paths.py (events dir, log, diagnosis) should use `_over_socket_limit`.
7. Builder's niggle, confirmed plausible: "Daemon started successfully" is printed for a child that died while binding.
