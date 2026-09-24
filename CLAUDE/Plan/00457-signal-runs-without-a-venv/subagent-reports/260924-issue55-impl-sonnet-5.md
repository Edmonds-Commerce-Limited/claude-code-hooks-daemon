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
`daemon/paths.py` directly by file path
(`importlib.util.spec_from_file_location`), registering each under its real
dotted name in `sys.modules` before executing it, so `operator_signal.py`'s
own `from claude_code_hooks_daemon.utils.temp_names import ...` resolves
from that cache instead of a real package import.

**Reuse, not re-implementation**: extracted `validate_signal_request()` and
`run_signal_cli()` into `operator_signal.py` from `cmd_signal`'s body;
`cmd_signal` (`daemon/cli.py`) now delegates to both, and
`signal_standalone.py:main()` calls the same `run_signal_cli`. Also
extracted `is_self_install_mode()`/`get_untracked_dir()` sharing into
`daemon/paths.py` (a pre-existing near-duplicate of `ProjectContext`'s own
inline check), which `ProjectContext.initialize()` now calls too.

**Minimum Python version: 3.10** — not the project's stated 3.11 floor. The
binding constraint is `daemon/paths.py`'s bare `X | Y` annotations with no
`from __future__ import annotations`, evaluated at function-definition time.
Pinned by `tests/unit/daemon/test_signal_standalone.py::TestSyntaxFloor`.
**Task 1.3 should check the invoking `python3` is >= 3.10** before calling
this module, per the module's own docstring.

`--project-root` is REQUIRED (unlike `cmd_signal`'s optional CWD walk-up,
which needs the full config-loading path this module exists to avoid) —
documented in the module docstring.

## Commits (worktree `worktree-issue-55-signal`, not merged/pushed)

- `9b954cd5` — Tasks 1.1-1.2 implementation
- `945aead4` — QA fix-up (mypy `TYPE_CHECKING` typing, pyright AST narrowing,
  black formatting)
- `292ed387` — journal only

## Tests

- `tests/unit/daemon/test_paths_untracked_dir_resolution.py` (new)
- `tests/unit/utils/test_operator_signal.py` (extended)
- `tests/unit/daemon/test_signal_standalone.py` (new — no-third-party-import
  check, syntax-floor AST check, end-to-end subprocess runs under
  `/usr/bin/python3`, kind-choices parity with `cli.py`)
- `tests/unit/core/test_project_context.py`, `tests/unit/daemon/test_cli_signal.py`
  unchanged and still green against the refactor

## QA

`QA: 35/35 PASSED` (second run, after fixing the first run's 4/35 findings:
format auto-fix already self-resolved, one mypy `no-any-return`, one
pyright `reportAssignmentType`; 10 acceptance-test errors were a stale
THIS-WORKTREE daemon, cleared by `bin/hooks-daemon restart`).

## What Task 1.3 needs

Wire `signal` into `bin/hooks-daemon`'s pre-venv-resolution dispatch
(Plan 00456's mechanism, once it merges) as a direct-file-path `python3`
invocation of `daemon/signal_standalone.py`, after checking the invoking
interpreter is Python >= 3.10 with a clear message otherwise. Do not add
`-m` or `PYTHONPATH` — the module needs neither.
