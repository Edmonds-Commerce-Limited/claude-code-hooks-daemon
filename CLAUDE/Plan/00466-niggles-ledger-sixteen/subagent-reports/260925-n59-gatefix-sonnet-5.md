# N59 gate-fix report

Worktree: `worktree-n466-n59`. Gate fix: `742f15154` (merge commit; the fix
itself is `12d246312`, N63 picked up via merge of main `8236d5d8a`). pidfd
extension (below): `dcaf9fb81`.

## Root causes (two, both in code N59 touched)

1. **`cli.py` `cmd_start`/`verified_daemon_process` project-root proof was
   unreliable for the common daemon-launch shape.** `cmd_start` never
   re-execs, so a daemon started without an explicit `--project-root` (the
   normal case — `scripts/upgrade.sh`/`scripts/install_version.sh` document
   this and rely on cwd instead) had its cmdline frozen at whatever argv
   `main()` was invoked with. `verified_daemon_process`'s only fallback for a
   missing flag was `_root_from_interpreter` (the interpreter's own venv
   path), which is wrong whenever a shared venv starts a daemon serving a
   *different* project root — exactly what `tests/integration/test_daemon_smoke.py`
   does, and what happens across sibling worktree daemons sharing pyenvs.
   `cmd_stop` therefore refused to signal the daemon it had just started.

   Fix: `main()` now re-execs `start`/`restart` exactly once with an explicit
   `--project-root <resolved>` before any forking happens (and records the
   same value in `CLAUDE_HOOKS_DAEMON_PROJECT_ROOT` for defence-in-depth), so
   the daemon's cmdline and environ both carry proof through the paths
   `verified_daemon_process` already trusts and every existing test already
   covers. Scoped to `main()`'s dispatch only — no test that calls
   `cmd_start()`/`cmd_restart()` directly is affected, and every test that
   calls `main()` with `start`/`restart` already passes `--project-root`
   explicitly, so the re-exec never fires under test.

   (I initially tried recording project root purely via
   `os.environ[...] = ...` inside `cmd_start`. That does **not** work:
   `/proc/<pid>/environ` reflects the environment at the process's last
   `execve()`, not later in-process mutation, and `cmd_start` only
   `os.fork()`s — proven by manual reproduction before committing to the
   re-exec design.)

2. **`scripts/qa/check_signal_targets.py`'s `scanned_shell_files()` read
   protected-path content.** It enumerated every tracked path via
   `git ls-files -z` and read each one's bytes with no protected-path check
   (Plan 00412 class 9), unlike its Python-side sibling
   `check_sensitive_content._without_protected_paths`. Fixed by adding the
   same filter, mirroring `staged_lint_gate.py:249`.

## Files changed

- `src/claude_code_hooks_daemon/daemon/cli.py` — `main()` re-exec.
- `src/claude_code_hooks_daemon/daemon/process_verification.py` —
  `_extract_project_root` gains an env-var resolution step
  (`PROJECT_ROOT_ENV_VAR`) between the flag and the interpreter-path
  fallback; `DAEMON_CLI_MODULE`/`PROJECT_ROOT_ENV_VAR` made public for reuse.
- `src/claude_code_hooks_daemon/utils/safe_signal.py` — updated call site.
- `scripts/qa/check_signal_targets.py` — `_without_protected_paths` filter.
- New/updated tests: `tests/unit/daemon/test_process_verification.py`,
  `tests/unit/utils/test_safe_signal.py`,
  `tests/unit/scripts/test_signal_target_checker.py`.

## Verification

- All originally-failing tests green: `test_playbook_harness.py`,
  `test_stop_hook_hard_block.py`, `test_daemon_smoke.py::test_daemon_starts_and_stops`,
  `test_forwarder_socket_stdin.py` (both), `test_git_enumerated_content_consults_protected_set.py`,
  `test_plugin_daemon_integration.py::test_daemon_restart_preserves_plugin_registration`.
- N63 (`test_effort_restore.py::test_opus_below_default_minimum_injects_high`)
  confirmed still red pre-merge, green after merging main.
- Full combined re-run of all the above plus every directly-related unit
  test: **258 passed**.
- ruff / black / mypy / pyright: clean on all touched files.
- Daemon restarted and verified RUNNING before each src/ commit.

## Note on this worktree's environment (not a code defect)

Two pre-existing worktree-provisioning gaps blocked verification and were
fixed locally (not committed — they're gitignored, worktree-local):
`.claude/hooks-daemon.env` was missing (`HOOKS_DAEMON_ROOT_DIR` unset), and a
leaked daemon from `/tmp/test-daemon-on_starts_and_stops0.*` (from an earlier
debugging run of mine) was masking the real fix behind a stale REUSE-gate
hit. Both cleaned up.

## Trailer note

The first commit (`12d246312`) is missing the `Co-Authored-By` trailer — I
made the commit before realizing the omission, then found
`git commit --amend` is hard-blocked (`R-GIT-COMMIT-AMEND`) by this
project's own hooks daemon, so it could not be corrected in place. The merge
commit (`742f15154`) does carry the trailer.

## pidfd extension (`dcaf9fb81`)

N24's branch signals a daemon through `os.pidfd_open` plus
`signal.pidfd_send_signal`, and its tests patched only `os.kill`, so a real
SIGKILL reached pid 12345 — the N59 crash class through a route N59 did not
cover. Extended N59 (RED test first for each change, confirmed failing
before implementing):

- `scripts/qa/check_signal_targets.py`: `signal.pidfd_send_signal` joins the
  `raw-signal` rule (same treatment as `os.kill`/`os.killpg`/
  `signal.pthread_kill`). `os.pidfd_open` itself is not flagged — it opens
  nothing dangerous; the SEND is `pidfd_send_signal`, so that call is what's
  reported, the same way `killpg(getpgid(pid), sig)` reports the `killpg`,
  not the `getpgid`.
- `tests/signal_safety_net.py`: the session-wide net now also wraps
  `os.pidfd_open` (records fd→pid, never refused — opening sends nothing)
  and `signal.pidfd_send_signal` (refused against the same protected set as
  `os.kill`, once the fd's pid is known; an fd the net never saw opened
  passes through, mirroring how an unrelated pid passes through `kill`).
- `utils/safe_signal.py`: new `signal_verified_daemon_via_pidfd` offers the
  identical proof as `signal_verified_daemon`, delivered via pidfd — immune
  to pid reuse between the proof and the send, since the fd stays bound to
  the exact process once opened.
- `CLAUDE/Security/UnprovenSignalTarget.md` updated to document the new
  coverage.

Verification: `tests/unit/scripts/test_signal_target_checker.py` (76),
`tests/unit/test_signal_safety_net.py` (43), `tests/unit/utils/test_safe_signal.py`
(33), `tests/unit/daemon/test_process_verification.py` — combined run: 181
passed. `check_signal_targets.py` run against the whole repo: 0 violations
(1979 files). ruff/black/mypy/pyright clean on all touched files. Daemon
restarted and verified RUNNING before the commit.
