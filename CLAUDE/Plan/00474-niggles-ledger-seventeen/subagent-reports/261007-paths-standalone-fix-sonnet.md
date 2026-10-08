# paths.py standalone-by-file-path fix (B4, N296 regression)

Root cause: N296 added a module-level `from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue` to `daemon/paths.py`, which `resolve_venv.sh` / `venv_bootstrap.sh` run by file path with no package on `sys.path`.

## Fix

- `daemon/paths.py`: removed the dotted import. Added `_load_package_module_by_path(relative_path)` (reuses a module already in `sys.modules`, else loads by path and `setdefault`s it under its dotted name, so one shared object when the package is importable). `_install_layout()` now uses it (DRY, same behaviour).
- `daemon/paths.py`: added a local `log_and_continue(log, exc, *, reason, level)` that loads `utils/escape_hatch.py` first (stdlib-only; registering it makes deliberate_swallow's own dotted import resolve from `sys.modules`), then `utils/deliberate_swallow.py`, and delegates. `deliberate_swallow.py` needed no change.
- The N296 audit (`scripts/qa/audit_error_hiding.py`) recognises the sanctioned form by call NAME (`log_and_continue`) plus a specific `reason=` keyword, so the 16 existing call sites in paths.py stay compliant unchanged. No exclusion/allowlist entries added.

## Other standalone modules checked

- `install/upgrade_gate_standalone.py`: B4 already added escape_hatch and deliberate_swallow to its `_LOAD_ORDER` before `upgrade_tasks`; `upgrade_gate.py` and `upgrade_tasks.py` gained the import in N296 and are covered. Existing test_upgrade_gate_standalone passes. No change needed.
- `daemon/signal_standalone.py` loads temp_names, operator_signal, install_layout: none gained a package import (their dotted imports are TYPE_CHECKING-only or already in its load list).
- version_parse, install_stamp, path_containment, path_predicates, one_shot_approval, install_layout, escape_hatch: no package imports added.
- So paths.py is the only broken instance.

## Tests

- Existing red test `tests/unit/daemon/test_bootstrap_decision_cli.py::TestItNeedsNoVenv::test_runs_by_file_path_with_no_package_on_the_path` now passes.
- New `tests/unit/daemon/test_paths_standalone_swallow.py`: subprocess under `-S` with no PYTHONPATH loads paths.py by path, calls `log_and_continue` (logs; rejects an empty reason), and proves the package really is unimportable; plus in-process tests that it delegates to the already imported shared module and still rejects a bad reason.

## QA (interpreter: the py311 venv under /workspace/.claude/worktrees/agent-ac99a72836eafa143-24488d95/untracked/venv-\*, PYTHONPATH = this worktree's src)

- pytest tests/unit/daemon, tests/unit/utils/test_deliberate_swallow.py, tests/unit/qa/test_audit_error_hiding.py, tests/unit/install/test_upgrade_gate_standalone.py: 2798 passed.
- `scripts/qa/audit_error_hiding.py`: no violations.
- ruff check: clean. black --check: clean. mypy on paths.py and the new test: clean.
- Only Python 3.11 was run; 3.12/3.13 were not run here.
