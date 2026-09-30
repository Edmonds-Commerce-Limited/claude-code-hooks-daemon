# N59 Independent Search — Defence Before Fix

Class: code sends a nonzero signal to a PID whose identity has not been proven
(cmdline check / project-root check / pgid-vs-own-group check) immediately
before the signal.

Scope: `/workspace` (main checkout, commit `9f83b9ff9`), Python under `src/`,
`scripts/`, `bin/`, `.claude/ccy/`, and shell scripts repo-wide. Excluded:
`node_modules`, `.venv`, `untracked/`, `.claude/worktrees/` (other agents'
worktree copies — pure duplicates of the same source, not distinct code), and
the two paths named in the brief
(`untracked/worktrees/worktree-n466-n59/scripts/qa/` and everything under that
worktree).

Techniques used: (1) text search (`grep`) for `os.kill`, `os.killpg`,
`pthread_kill`, `send_signal`, `.terminate(`, `.kill(`, `psutil.*kill*`, and
shell `kill`/`pkill`/`killall`; (2) reading the code paths around every hit to
find where the PID/pgid came from and whether it was verified.

## Totals

- Total call sites inspected (nonzero-signal or process-ending calls,
  deduplicated across template copies): **11** distinct code locations (plus 2
  further byte-identical shipped-template copies of two of them).
- **CARRIES THE HAZARD: 4**
- **SAFE: 7**

## Findings

### 1. `src/claude_code_hooks_daemon/install/client_validator.py:320,329` — CARRIES THE HAZARD

- Signal: `SIGTERM` then (if still alive) `SIGKILL`.
- PID source: read directly from a glob of `untracked/daemon*.pid` files
  (`client_validator.py:300-308`), during pre-install validation
  (`_check_running_daemon`).
- Verification before signal: **none**. Only a `os.kill(pid, 0)` liveness
  check (line 312) precedes the `SIGTERM` — liveness, not identity. No cmdline
  check, no project-root check, nothing that proves the PID still names the
  daemon that wrote the file.
- Verdict: **CARRIES THE HAZARD.** A stale PID file (e.g. after a container
  restart reused the PID for an unrelated process) is signalled with SIGTERM
  and then SIGKILL with no re-verification. This is exactly the class this
  plan targets. Found by text search, confirmed by reading.

### 2. `scripts/upgrade.sh:_stop_running_daemons` (~line 493-494) — CARRIES THE HAZARD

- Signal: `SIGTERM`.
- PID source: read directly from `$DAEMON_DIR/untracked/daemon-*.pid` files.
- Verification before signal: only `kill -0 "$pid"` (liveness) immediately
  before `kill -TERM "$pid"`; no cmdline/project-root check. The code
  comment even documents the design as "PID-kill only" (Plan 00100 Task 2.5)
  — a deliberate simplification that dropped the `daemon.cli stop` path,
  which is the one place in this codebase (see finding 6 below) that *does*
  verify the PID before sending SIGTERM.
- Verdict: **CARRIES THE HAZARD.** Same stale-PID-file hazard as finding 1:
  runs before checkout during an upgrade, exactly the kind of restart-adjacent
  window where a PID file can outlive the process it named. Found by text
  search, confirmed by reading; comment context made the design intent
  explicit.

### 3. `scripts/venv_bootstrap.sh:_vb_watchdog` (~line 440-448) — CARRIES THE HAZARD

- Signal: `SIGTERM` (`kill -TERM "$owner"`), inside a bound-timeout watchdog
  that also does `kill -0` liveness checks in the loop condition.
- PID source: `$owner` is `"$$"` of the build-runner script, captured once at
  spawn time (`_vb_watchdog "$$" ...` at line 553) and handed to a
  background watchdog subshell.
- Verification before signal: only `kill -0 "$owner"` (liveness) in the same
  loop iteration, no cmdline check. The surrounding comment explicitly
  acknowledges the risk: "By the bound, the build's process group id may
  belong to someone else (final review N7)" — i.e. the authors already
  identified that PID/pgid reuse across the bound's duration is possible and
  left it as an accepted/undecided risk rather than a proven-safe design.
- Verdict: **CARRIES THE HAZARD**, though the race window per loop iteration
  is narrow (liveness check and signal happen back-to-back with no sleep
  between them within the same iteration) — the exposure is across the whole
  polled bound, not a single instant, and the file's own comment flags it as
  unresolved. Found by text search; the caller chain and the N7 comment were
  found by reading.

### 4. `scripts/dummy-client-repo.sh:verify_dummy_daemon_stopped` (~line 122-136) — CARRIES THE HAZARD (narrow)

- Signal: default (`SIGTERM`) sent to a process **group** via
  `kill -- -"$pgid"`.
- PID source: `pgrep -f "${DUMMY_DAEMON_DIR}/untracked/venv-"` (cmdline
  pattern match against a fixture-unique venv path) in
  `_surviving_dummy_daemons`, then `ps -o pgid= -p "$pid"` to resolve the
  group id, in a **separate, later** call (`verify_dummy_daemon_stopped`).
- Verification before signal: the cmdline match happens at `pgrep` time, not
  immediately before the `kill`; between the `pgrep` and the `kill -- -$pgid`
  there is a `ps -o pgid=` round trip with no re-check of cmdline identity.
  If the matched PID exited and its number was reused in that window, `ps`
  would report the *new* process's pgid and the kill would land on an
  unrelated group.
- Verdict: **CARRIES THE HAZARD**, but low practical severity: this is a test
  fixture's teardown path (`dummy-client-repo.sh`), the window is only the
  time for one `ps` invocation, and the PID pattern (venv path unique to the
  fixture) makes accidental collision on a project-critical process unlikely.
  Still matches the class definition (no re-verification of identity
  immediately before the signal). Found by text search, confirmed by reading.

## Verified SAFE (for completeness / to save the fix agent re-deriving them)

### 5. `src/claude_code_hooks_daemon/daemon/process_verification.py:184,192` (`kill_daemon_process`) — SAFE, with a caveat

- Called only from `enforcement.py:94`, whose PID list comes from
  `find_all_daemon_processes(project_root=...)`, which verifies `cmdline()`
  matches a daemon-server invocation AND (when a project root is given) that
  the process's own resolved project root matches, excluding anything it
  cannot positively attribute (`process_verification.py:75-98`).
- Caveat: `kill_daemon_process(pid)` itself does not re-verify cmdline
  immediately before `process.terminate()`/`.kill()` — it re-wraps the PID in
  `psutil.Process(pid)` and signals. There is a small TOCTOU gap between
  enumeration and the kill loop (`enforcement.py:88-97`), but it is a tight
  in-process loop with no sleep, so the gap is effectively the iteration cost,
  not a restart-shaped exposure. Judged SAFE overall given cmdline+root
  verification at enumeration, but flagged in case the fix wants a
  belt-and-braces re-check.

### 6. `src/claude_code_hooks_daemon/daemon/cli.py:788` (`cmd_stop`) — SAFE

- `pid = read_pid_file(str(pid_path), verify_daemon=True)` (line 781); the
  comment states plainly: "verify_daemon guards against a stale PID file
  (after reboot / PID reuse) pointing at an unrelated live process we would
  otherwise SIGTERM." This is the verified counterpart to findings 1 and 2's
  unverified `SIGTERM`.

### 7. `src/claude_code_hooks_daemon/install/transport_verify.py:151` (`proc.kill()`) — SAFE

- `proc` is a `subprocess.Popen` created a few lines above in the same
  function; a direct child handle is not subject to PID-reuse ambiguity while
  unreaped.

### 8. `.claude/ccy/claude-supervise.py:6823,6826` (`WorkerHandle.close`) — SAFE

- `proc = self._proc`, a `subprocess.Popen` the same class spawned as its
  worker subprocess; direct child handle, same reasoning as #7.

### 9. `.claude/skills/hooks-daemon/scripts/install.sh` / `src/claude_code_hooks_daemon/skills/hooks-daemon/scripts/install.sh` (byte-identical shipped-template copy) — SAFE

- `kill "$ASIDE_HEARTBEAT_PID"` and the trap's `kill "$_hb_sleep"`: both PIDs
  are captured via `$!` immediately after backgrounding, i.e. own direct
  child jobs, reaped via `wait`. `kill -0 "$owner"` uses is liveness only.

### 10. `scripts/install/venv.sh:venv_heartbeat_stop` (and the identical

`CLAUDE/Plan/_planlib.inc.bash` / `src/claude_code_hooks_daemon/install/templates/_planlib.inc.bash`
self-signal cases) — SAFE

- `venv_heartbeat_stop` signals a PID captured via `$!` right after
  backgrounding (own child). The `_planlib.inc.bash` `kill "-${sig}" "$$"` /
  `kill -TERM "$$"` cases signal the script's own PID (`$$`), which needs no
  identity proof — it is unconditionally itself.

### 11. `scripts/lib/resolve_venv.sh:_rv_candidate_runs` (`kill -KILL "$pid"` watchdog) — SAFE

- `pid=$!` captured immediately after backgrounding the probe candidate (own
  child); the watchdog subshell is killed by the parent right after `wait "$pid"` returns, bounding the race to the standard own-child job-control
  window used throughout this codebase's other heartbeat/watchdog helpers.

## Notes for the fix

Findings 1 and 2 are the clearest and highest-value fixes: both read a raw PID
straight out of a `*.pid` file and SIGTERM/SIGKILL it with only a liveness
check, no identity check — this is precisely the "stale PID file after a
container restart names a reused PID" hazard from the brief. `cli.py`'s
`read_pid_file(..., verify_daemon=True)` (finding 6) already exists in this
codebase as the verified pattern to converge on.

Findings 3 and 4 are lower-severity/narrower-window but still match the class
as defined (no proof of identity immediately before the signal); worth
flagging to the fix branch even if the remediation there is a comment or a
cheap re-check rather than a redesign.
