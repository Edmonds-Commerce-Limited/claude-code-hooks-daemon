# Plan 00457 Tasks 1.1-1.2 report (GitHub issue #55)

## Task 1.1 — untracked-dir resolution has no path-keyed component

`ProjectContext.daemon_untracked_dir()` (`core/project_context.py`, now
delegating to `daemon/paths.py::is_self_install_mode`/`get_untracked_dir`)
resolves self-install mode by checking whether
`{project_root}/src/claude_code_hooks_daemon` exists, then joins either
`{project_root}/untracked` (self-install) or
`{project_root}/.claude/hooks-daemon/untracked` (normal mode) — a pure path
join off `project_root`, no slug, no hash, no env override for the
directory itself.

The ccy supervisor's independent stdlib-only mirror
(`.claude/ccy/claude-supervise.py:1882-1918`, `_default_sidecar_dir`/
`_daemon_untracked_dir`) performs the identical two-branch check, resolving
`project_dir` from `$CLAUDE_PROJECT_DIR` (exported by ccy in-container) or
CWD. The signal filename itself (`utils/operator_signal.py:74-88`,
`signal_path`) is keyed only by a sanitised `session_id`, no path component.

**Conclusion**: host and container resolve the SAME physical directory —
different STRINGS (host `--project-root` vs container `$CLAUDE_PROJECT_DIR`)
but the same bind-mounted `untracked/`, exactly the assumption
`daemon/cli.py`'s "multi-container shared-`untracked/` model" comment
(~line 2302) already relies on elsewhere. No rethinking needed.

## Task 1.2 — venv-free entry point

**Module and invocation**:
`python3 <daemon_root>/src/claude_code_hooks_daemon/daemon/signal_standalone.py <kind> [--minutes N] --all-sessions --project-root <root>`
— run DIRECTLY by file path (never `-m`, never `PYTHONPATH`); it locates its
siblings via `__file__`.

**Key finding**: `operator_signal.py` is stdlib-only, but a normal
`from claude_code_hooks_daemon.utils.operator_signal import ...` still
executes `claude_code_hooks_daemon/__init__.py` first (Python always
initialises a dotted import's parent packages) — confirmed empirically
under `/usr/bin/python3`: `ModuleNotFoundError: No module named 'pydantic'`
via `core/front_controller` -> `core/acceptance_test` -> `core/hook_result`.
Fix: `signal_standalone.py` loads `temp_names.py`, `operator_signal.py` and
`install_layout.py` directly by file path
(`importlib.util.spec_from_file_location`), registering each under its real
dotted name in `sys.modules` before executing it, so `operator_signal.py`'s
own `from claude_code_hooks_daemon.utils.temp_names import ...` resolves
from that cache instead of a real package import.

**Reuse, not re-implementation**: extracted `validate_signal_request()` and
`run_signal_cli()` into `operator_signal.py` from `cmd_signal`'s body;
`cmd_signal` (`daemon/cli.py`) now delegates to both, and
`signal_standalone.py:main()` calls the same `run_signal_cli`. Also
extracted `is_self_install_mode()`/`get_untracked_dir()` into a NEW tiny
module, `daemon/install_layout.py` (stdlib-only, zero
`claude_code_hooks_daemon` imports of its own) — not `daemon/paths.py`
(a pre-existing near-duplicate of `ProjectContext`'s own inline check):
team-lead review flagged that loading all of `paths.py` (1,800+ lines) to
reach two small functions set the Python floor at 3.10 purely as a side
effect of unrelated code, above what common host distros ship (Debian 11:
3.9, Ubuntu 20.04: 3.8). `daemon/paths.py` now loads `install_layout.py`
by FILE PATH too (not a dotted import — `paths.py` is itself run
standalone by `resolve_venv.sh` during fresh-clone bootstrap, so a dotted
import there would break exactly what this plan fixes for `signal`) and
delegates, keeping its own public names working. `ProjectContext` and
`signal_standalone.py` both load `install_layout.py` directly.

**Minimum Python version: 3.8** (re-derived after the `install_layout.py`
extraction; was 3.10 in the first draft, which loaded `daemon/paths.py`).
The binding constraint is `operator_signal.py`'s `from typing import Final`
(added 3.8) — used only inside deferred annotations, but the import
statement itself executes eagerly. Pinned across all four files
`signal_standalone.py` loads via
`tests/unit/daemon/test_signal_standalone.py::TestSyntaxFloor`.
`signal_standalone.py` now also checks this itself, first, via
`_check_python_version()` (parameterised on `version_info` so it is
unit-testable — `sys.version_info` is read-only and cannot be
monkeypatched) — a python3 below 3.8 gets a clear message and exit 1
instead of an `ImportError` from inside `operator_signal.py`.
**Task 1.3 should check the invoking `python3` is >= 3.8** before calling
this module (the module's own check is a backstop, not a substitute, for
a caller that wants to fail before spawning it at all).

`--project-root` is REQUIRED (unlike `cmd_signal`'s optional CWD walk-up,
which needs the full config-loading path this module exists to avoid) —
documented in the module docstring.

## Commits (worktree `worktree-issue-55-signal`, not merged/pushed)

- `9b954cd5` — Tasks 1.1-1.2 implementation
- `945aead4` — QA fix-up (mypy `TYPE_CHECKING` typing, pyright AST narrowing,
  black formatting)
- `292ed387` — journal only
- `8d5c7392` — subagent report
- `953731d5` — team-lead review fix: `install_layout.py` extraction,
  floor lowered to 3.8

## Tests

- `tests/unit/daemon/test_install_layout.py` (new)
- `tests/unit/daemon/test_paths_untracked_dir_resolution.py` (unchanged,
  still green — `paths.py`'s public names behave identically)
- `tests/unit/utils/test_operator_signal.py` (extended)
- `tests/unit/daemon/test_signal_standalone.py` (extended — no-third-party-import
  check, syntax-floor AST check, version-floor-enforcement unit tests,
  end-to-end subprocess runs under `/usr/bin/python3`, kind-choices parity
  with `cli.py`)
- `tests/unit/core/test_project_context.py`, `tests/unit/daemon/test_cli_signal.py`
  unchanged and still green against the refactor

## QA

`QA: 35/35 PASSED`, run in the foreground on the final commit
(`953731d5`) after a worktree daemon restart. (An earlier round on
`945aead4` fixed the first pass's 4/35 findings: format auto-fix already
self-resolved, one mypy `no-any-return`, one pyright
`reportAssignmentType`; 10 acceptance-test errors were a stale
THIS-WORKTREE daemon, cleared by `bin/hooks-daemon restart`.)

## Task 1.3 — wiring into `bin/hooks-daemon`

Merged `main` (Plan 00456, `9e2f74cd`) into this worktree as `74153796`
(clean, no conflicts) to pick up `_run_venv_free_verb` and its `repair` arm.

Added a `signal)` arm to `_run_venv_free_verb` in `bin/hooks-daemon` and its
install template (kept byte-identical), same shape as `repair`'s: a
`python3 >= 3.8` gate ahead of everything else, then `exec`s
`daemon/signal_standalone.py` by file path under the system `python3` — it
never touches `venv_bootstrap.sh` or builds a venv. A reconstruction loop
inside the arm replays `_subcommand_of`'s own option-recognition rule
(`--project-root`/`--pid-file`/`--socket` consume a value; the first bare
word is the verb and is dropped) to strip the literal `signal` word before
forwarding the rest to `signal_standalone.py`'s argparse — the first cut
forwarded `"$@"` unchanged and argparse rejected "signal" as an invalid
`<kind>`; this fixed it. `${rest[@]+"${rest[@]}"}` is used for that array's
expansion for bash 3.2 (`set -u`, empty-array) safety, proactively (not
forced by an existing test — extensionless `bin/hooks-daemon` isn't scanned
by `test_bash32_portability.py`).

`tests/venv_bootstrap_sandbox.py`'s `CLONE_FILES` now also stages
`signal_standalone.py`, `install_layout.py`, `operator_signal.py` and
`temp_names.py`. Replaced `TestVenvFreeVerbsAreOneDispatch` with
`TestDispatchHasOneArmPerVerb` (repair test file) to assert the dispatch
SHAPE covers both verbs; added
`tests/integration/test_bin_hooks_daemon_signal_without_venv.py` (6 tests,
mirroring `repair`'s own suite): writes a signal and builds no venv, a
malformed request is still refused, `--help` needs no venv, a missing entry
point is named at exit 5, an old `python3` is refused at exit 5 naming
"3.8", and the verb is found after a leading global option.

**Caveat carried from Plan 00456, not introduced here** (recorded in the
journal and in PLAN.md's Success Criteria): `resolve_venv_python`'s
glob-fallback scan checks only the executable bit on a candidate
`venv-*/bin/python`, not whether it can actually run on this host. A venv
built inside a container (present, wrong architecture) could in principle
be reported "resolved" rather than falling through to
`_run_venv_free_verb`. Out of Task 1.3's scope (reuse the mechanism, don't
redesign it) — flagged as a candidate niggle for its own follow-up plan.

### Commits (this session)

- `74153796` — merge `main` (Plan 00456)
- Task 1.3 implementation + tests + PLAN.md/journal updates (see the commit
  this report accompanies)

### QA

`QA: 36/36 PASSED`, run in the foreground on the final commit after a
worktree daemon restart. Two earlier foreground runs in this session hit
transient issues unrelated to Task 1.3's code: black auto-fixed one new
test file's formatting on the first run (re-verified clean afterwards), and
two subsequent runs failed only `smoke_test` because the daemon's own
`idle_timeout_seconds: 600` elapsed mid-run under heavy concurrent
host load (several other worktrees' QA suites running at once, each run
taking >15 minutes) — a keepalive loop pinging the daemon every 2 minutes
for the duration of the run (stopped and cleaned up afterwards) fixed this;
also ran `./scripts/qa/run_shell_check.sh` separately (67 files, 0 issues)
since `llm_qa.py` does not run shellcheck (ledger 00422 N22).
