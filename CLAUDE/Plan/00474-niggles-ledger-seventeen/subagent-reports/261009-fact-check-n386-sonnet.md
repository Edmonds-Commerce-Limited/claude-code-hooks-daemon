# Fact check: N386 and N384 status (commit 04295d4ee)

Tree: current working tree. Paths below are under `src/claude_code_hooks_daemon/` unless stated.

## REFUTED (completeness claim)

R1. The claim "four other places re-derive the same decision" is REFUTED. The Python count is right: no further `.py` copy exists in `src/` or `scripts/`. Three shell scripts in `scripts/` make the same decision from the same marker, using `-d`:

- `scripts/setup_worktree.sh:184`: `if [[ -d "${PROJECT_ROOT}/src/claude_code_hooks_daemon" ]]; then self_install="true"`. This is the same decision, feeding `preflight_socket_path`.
- `scripts/install/mode_guard.sh:66`: `detect_self_install_mode` tests `-d $project_root/src/claude_code_hooks_daemon`, and also requires `pyproject.toml` and "not a real daemon clone". It is a stricter variant of the rule and drifts from the canonical one.
- `scripts/health_check.sh:169`: after a config-driven `SELF_INSTALL` flag, it re-tests `-d $PROJECT_ROOT/src/claude_code_hooks_daemon`. This is a validation of the flag, so it is borderline.

Change to the plan: either list these (the first two at least) in N386, or state that N386 covers Python only. The QA-detector remedy must also say whether it scans shell.

Borderline, probably not a copy: `daemon/validation.py:105-125` decides "is this the daemon repository" from `pyproject.toml` declaring the package, a different marker, not the `src/...` directory.

## Claims table

| #   | Claim                                                                                                 | Verdict        | Evidence                                                                                                                                                                                                                            |
| --- | ----------------------------------------------------------------------------------------------------- | -------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | `daemon/install_layout.is_self_install_mode(project_path)` is the canonical rule                      | VERIFIED       | `daemon/install_layout.py:25-31` returns `project_path.joinpath("src", "claude_code_hooks_daemon").is_dir()`. Its docstring says "ONE definition (Plan 00457)".                                                                     |
| 2   | It is standard-library only                                                                           | VERIFIED       | The only import is `from pathlib import Path`, plus `__future__` (`install_layout.py:14-16`).                                                                                                                                       |
| 3   | `ProjectContext` delegates to it                                                                      | VERIFIED       | `core/project_context.py:236-244` imports it and calls `is_self_install_mode(project_root)`.                                                                                                                                        |
| 4   | `daemon/paths.py` delegates to it                                                                     | VERIFIED       | `daemon/paths.py:1587-1597`: the wrapper calls `_install_layout().is_self_install_mode`, loaded by file path. `get_untracked_dir` is delegated the same way (line 1615).                                                            |
| 5   | N384: `daemon_stats` now calls it                                                                     | VERIFIED       | `handlers/status_line/daemon_stats.py:21` imports it and `:58` calls `is_self_install_mode(context.project_root)` inside `Relevance.when`.                                                                                          |
| 6   | `daemon/cli.py:2645` tests `.exists()` and re-implements `get_untracked_dir()` whole                  | VERIFIED       | `daemon/cli.py:2645` is `if (project_root / "src" / "claude_code_hooks_daemon").exists(): return project_root / "untracked"`. Line 2647 returns the `.claude/hooks-daemon/untracked` path.                                          |
| 7   | `install/client_validator.py:240` tests `.exists()` and refuses a client install into the daemon repo | VERIFIED       | `client_validator.py:240-247` builds `daemon_src`, tests `.exists()`, and appends the error "Installation target appears to be the daemon repository itself".                                                                       |
| 8   | `utils/ccy_supervisor.py:45,136` uses `_SELF_INSTALL_MARKER_PARTS` with `.exists()`                   | VERIFIED       | `ccy_supervisor.py:45` defines the tuple. `:136` is `if project_root.joinpath(*_SELF_INSTALL_MARKER_PARTS).exists():` inside `daemon_untracked_dir`.                                                                                |
| 9   | `scripts/debug_info.py:275` tests `.is_dir()` and re-implements `get_untracked_dir()`                 | VERIFIED       | `debug_info.py:275` is `if (self.project_root / "src" / "claude_code_hooks_daemon").is_dir():` in `_untracked_dir`, returning the same two paths.                                                                                   |
| 10  | "two test `.exists()` and two `.is_dir()`"                                                            | REFUTED, minor | The four listed sites split three `.exists()` (cli, client_validator, ccy) and one `.is_dir()` (debug_info). The canonical rule is itself `.is_dir()`. Fix the counts: three `.exists()` and one `.is_dir()` among the four copies. |
| 11  | No other site makes the same decision (completeness)                                                  | REFUTED        | See R1. No further Python copy was found: `daemon/paths.py:1473`, `cli.py:10008` and `process_verification.py` take the mode as an argument or call the canonical function. `cli.py:5113-5136` imports the canonical function.      |
| 12  | N384 status: the first fix "hand-rolled its own marker" and now uses the one rule                     | VERIFIED       | `daemon_stats.py` has no `src/claude_code_hooks_daemon` literal now, and it imports `install_layout`. The "first fix hand-rolled" part is history and was not checked.                                                              |
| 13  | `daemon/signal_standalone.py` loads `install_layout.py` by path                                       | VERIFIED       | `signal_standalone.py:154-155`: `_load_by_file_path("claude_code_hooks_daemon.daemon.install_layout", _DAEMON_DIR / "install_layout.py")`.                                                                                          |

## Other candidates examined and excluded

These are path construction for scanning or reading, not an install-mode decision:

- `issue_report/citation.py:104`
- `qa/strategy_pattern_checker.py:422`
- `install/skills.py:39`
- `scripts/qa/*` scan roots
- `scripts/handler_status.py:114`
- `scripts/qa/check_skill_references.py:352`
- `scripts/venv_bootstrap.sh` and `scripts/lib/resolve_venv.sh`: they only locate `paths.py`.

Counts: 13 claims, 11 verified, 2 refuted (the completeness claim and the exists/is_dir tally), 0 unverifiable.
