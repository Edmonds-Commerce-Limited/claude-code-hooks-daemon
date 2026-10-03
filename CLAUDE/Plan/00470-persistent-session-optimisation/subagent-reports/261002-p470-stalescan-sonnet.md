# Plan 00470 Task 4.5: stale-scan follow-ups

1. `daemon/paths.pid_path_for` is the one pid-path computation (relocation included, no mkdir, no env override); `get_pid_path` uses it. `find_stale_daemons` takes `pid_path_fn` and scans that file.
2. `utils/git_repo.parse_worktree_porcelain` is the one parser; `worktree_reaping` and `stale_checkouts` both use it.
3. `stale_worktree_days` is validated in a property setter (int, not bool, >= 1), the `bash_safe_mode` pattern.
4. `ScanDeadline` with `SCAN_BUDGET_SECONDS`; a spent budget renders a `SCAN INCOMPLETE` line, even when nothing was found.
5. The report has no CLI-path literal, so nothing to pass in. Unset `base_branch` now resolves through `git_sync.default_branch`, falling back to `main`.

Checks: ruff, black, mypy, pyright, error-hiding audit and generated-doc drift are clean; 240 targeted tests pass.
