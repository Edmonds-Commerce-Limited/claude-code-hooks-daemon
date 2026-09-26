# N24 gate fix (sonnet-5)

Worktree: `worktree-n466-n24`. Brief:
`/workspace/untracked/scratch/briefs/n24-gatefix.md`. HEAD before this work:
`07c3ce9ab`. HEAD after: `f6128bcbb`.

## 1. Merge main

Merged `main` (N63 ambient-`CCY_*` fix, B3 integration) into the branch,
commit `a46449d6e`. Conflicts resolved in:

- `CLAUDE.md`, `.claude/HOOKS-DAEMON.md` — auto-generated, took HEAD's copy
  (regenerated on the next daemon restart regardless).
- `CLAUDE/UPGRADES/UNRELEASED/post-upgrade-tasks/README.md` — merged both
  task-index rows; kept the `02`-number collision per agent-rules
  ("leave them; the coordinator renumbers at merge").
- `CLAUDE/Plan/00466.../JOURNAL/00466-Journal-26-09-24.md` — reordered the
  two conflicting entry blocks by timestamp (main's `20:21` entries before
  HEAD's `20:37`+ entries; append-only journal, entries must increase in
  time).
- `NIGGLES.md` / `PLAN.md` — kept every row, each row's most advanced
  status: N24/N25 marked Remedied (this branch's own work), N34 restored
  (only existed on HEAD, main's ledger table didn't have the row at all),
  kept main's fuller N26 remedy write-up (a later, more complete fix than
  HEAD's copy of the same entry).
- `src/.../config/models.py`, `daemon/cli.py` — merged import lists
  (`ConfigKey`+`Timeout`, `DaemonPath`+`HandlerID`+`handler_options`).
- `daemon/controller.py` — merged `initialise()`'s new kwargs
  (`chain_deadline_problems` + `config_fingerprint`) and `get_health()`'s
  dict (kept main's `HEALTH_KEY_CONFIG_FINGERPRINT` alongside HEAD's
  straggler-health block).
- `daemon/server.py` — combined main's `_answer_event` refactor with
  HEAD's `_drain_oversized_request` (N40 m5) and the N24 review-3 MA2
  non-verdict guard: `_answer_event` gained `arrival_time` forwarding and
  the MA2 check so main's extraction didn't drop either.
- `tests/unit/handlers/test_registry_option_injection.py` — merged the
  import list.

## 2. error_hiding: `daemon/cli.py:793` fixed

`_open_pidfd` had `except AttributeError/OSError: return None` — flagged
by `return-none-on-error`. Restructured to bind a local and return once
after the `try`, with a `logger.warning` in each except branch (fail
CLOSED is preserved — callers already fall back to signalling by pid
number; now that fallback is visible in logs instead of silent).

Merging main's strengthened checker (Plan 00466 N29,
`return-none-via-local`) also surfaced 3 more pre-existing violations in
`daemon/server.py`, in code this branch itself added (N40's
`_drain_oversized_request`, `_handle_event_client`, `_handle_client`):
bare `return` inside an except handler. Fixed by converting the drain
loop's early exit to `break` (function already falls through to an
implicit `None` return) and restructuring both socket handlers'
inner try/except into try/except/else so happy-path processing runs from
`else:` — behaviourally identical, no longer matches the AST shape the
checker flags. Commit `38752cd26`.

`error_hiding` audit: 0 violations (was 1 pre-merge, 4 after the main
merge). `tests/unit/qa/test_audit_error_hiding.py`: 78 passed (item 4 of
the brief, done).

## 3. Daemon start/stop test failures — root cause and fix

Both `test_daemon_smoke.py::test_daemon_starts_and_stops` and
`test_plugin_daemon_integration.py::test_daemon_restart_preserves_plugin_registration`
fail **even run alone** — not order/load-dependent. `stop` returns exit 1:
"PID N is attributed by its interpreter's venv path to `<this worktree>`,
not to `<tmp project root>`; refusing to signal it".

Root cause: N24 review 3's mi1 fix (this branch) added a project-root
attribution check to `cmd_stop` before signalling — closing a real
pid-reuse race. Attribution resolves from an explicit `--project-root`
flag or, failing that, the interpreter's venv path. These two test files
launch the daemon via `sys.executable` (this worktree's own shared venv,
since pytest runs under it) against a disposable tmp-dir project root
with no venv of its own, and never pass `--project-root` — so the
venv-path fallback resolves to the worktree, not the tmp project, and the
new safety check correctly (but disruptively) refuses to signal it.
Confirmed via `git show main:.../cli.py`: main's `cmd_stop` has no
attribution check at all, so this gap never surfaced there — it is
genuinely this branch's change, not pre-existing flakiness.

Fix: pass `--project-root <resolved root>` on every start/status/stop/
restart CLI invocation in both test files (25 call sites total;
`--project-root` is a GLOBAL flag and must precede the subcommand — first
pass put it after and got argparse exit 2, caught before commit). This is
exactly the mechanism `daemon_process_project_root`'s flag branch exists
for. Commit `f6128bcbb`.

Along the way found 8 already-running daemon processes this gap had
silently leaked in this container from prior runs (the `daemon_process`
fixture's teardown never asserted `stop`'s exit code, so a failed stop
was invisible). Each pid's own `/proc/<pid>/cmdline` was read and checked
against the exact `claude_code_hooks_daemon.daemon.cli start` shape
before sending SIGTERM (agent-rules signal-safety rule).

## QA run

- `tests/unit/daemon`: 2307 passed, 1 skipped (root chmod-guard skip,
  pre-existing, unrelated).
- `tests/unit/supervise`: 898 passed.
- `tests/unit/handlers/test_registry_option_injection.py`: passed (part
  of the 419-test batch with the error_hiding self-scan).
- `tests/unit/qa/test_audit_error_hiding.py`: 78 passed.
- `tests/integration/test_daemon_smoke.py` +
  `test_plugin_daemon_integration.py`: 15 passed, verified zero leaked
  daemon processes after the run (checked every `.pid` file under
  `/tmp/test-*daemon*` against `/proc`).
- `scripts/qa/audit_error_hiding.py`: 0 violations.
- ruff, mypy, pyright, black: clean on every touched file except one
  pre-existing mypy `no-any-return` finding in
  `test_daemon_smoke.py:235` (`send_hook_event`), confirmed present at
  HEAD before this branch touched the file.

Daemon restarted and confirmed RUNNING before each `src/`-touching
commit. Full gate queued in the background
(`bash /workspace/untracked/scratch/gate.sh worktree-n466-n24`); not
waited on.

## Files touched

- `src/claude_code_hooks_daemon/daemon/cli.py`
- `src/claude_code_hooks_daemon/daemon/server.py`
- `src/claude_code_hooks_daemon/daemon/controller.py` (merge only)
- `src/claude_code_hooks_daemon/config/models.py` (merge only)
- `tests/unit/handlers/test_registry_option_injection.py` (merge only)
- `tests/integration/test_daemon_smoke.py`
- `tests/integration/test_plugin_daemon_integration.py`
- `CLAUDE.md`, `.claude/HOOKS-DAEMON.md` (merge only, auto-generated)
- `CLAUDE/UPGRADES/UNRELEASED/post-upgrade-tasks/README.md` (merge only)
- `CLAUDE/Plan/00466-niggles-ledger-sixteen/{NIGGLES.md,PLAN.md,JOURNAL/00466-Journal-26-09-24.md}` (merge only)
