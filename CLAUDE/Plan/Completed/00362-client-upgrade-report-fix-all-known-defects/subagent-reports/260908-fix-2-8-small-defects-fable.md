# Task 2.8 — D14, D19, R2, D21 (fable)

Branch: `agent-a52ac373230130055-b55b4903` (worktree
`/workspace/.claude/worktrees/agent-a52ac373230130055-b55b4903`).
Code commit `144d8dbb`; docs/plan-tick commit follows it on the same branch.

## Outcome per item

| Item | State on arrival                                                     | What landed                                                                                                                                                                                                                                                         |
| ---- | -------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| D14  | suggestion said 10; fallback heredoc had no `refreshInterval`        | `RECOMMENDED_REFRESH_INTERVAL_S = 1` (public) in `suggest_statusline.py`; fallback heredoc gains `"refreshInterval": 1`; two tests pin the suggestion JSON, the repo's `.claude/settings.json` and the heredoc to the constant                                      |
| D19  | already fixed on main (`resolved_stdin_fd: int`, every site)         | `pyright .claude/ccy/claude-supervise.py` → 0 errors, 0 warnings. No supervisor edit. Ticked as already fixed.                                                                                                                                                      |
| R2   | nine hand-rolled `.{stem}.{os.getpid()}.tmp` names                   | `utils/temp_names.unique_temp_path(final_path)` (pid + thread ident + 8-hex random token, dotfile beside the target); all nine sites use it; `test_temp_names.py` greps `src/` for the old form and checks each writer imports the helper; 7 files drop `import os` |
| D21  | already closed by Plan 00353 (`883990ea8`), blank-`PYTHON_CMD` guard | New test: an init.sh resolving a real interpreter yields "Daemon Status" and "Installed Handlers" sections with no `Errno` / `Permission denied` line and a `Discovered N handler classes` line. No source change needed.                                           |

## Files

- `src/claude_code_hooks_daemon/utils/temp_names.py` (new)
- `src/claude_code_hooks_daemon/handlers/session_start/suggest_statusline.py`
- `scripts/install_version.sh`
- nine writer modules listed in `tests/unit/utils/test_temp_names.py`
- `tests/unit/utils/test_temp_names.py` (new),
  `tests/unit/handlers/session_start/test_suggest_statusline.py`,
  `tests/integration/test_install_version_fallback_settings.py`,
  `tests/unit/test_debug_info.py`,
  `tests/unit/handlers/pre_compact/test_compaction_signal.py`
- `CLAUDE/UPGRADES/UNRELEASED/release-notes/13-statusline-interval-temp-names-and-bug-report-tool.md`
- Plan ticks: 00175 Tasks 1.1–1.3; 00159 Tasks 1.1–1.3, 2.1; 00362 Task 2.8

## Verification

- Touched suites (status_line, pre_compact, goal_injection, user_prompt_submit,
  model_fallback_detector, model_downgrade_signal, supervise, debug_info,
  suggest_statusline, fallback settings, temp_names): 1,614 passed.
- `ruff check` + `ruff format --check` clean on every touched file;
  `mypy --strict` clean on the ten touched sources.
- `shellcheck scripts/install_version.sh`: only the pre-existing SC1091 info.
- Daemon NOT restarted (as instructed); no `sed`, no stash, no destructive git.

## Notes for the coordinator

- `scripts/setup_worktree.sh` creates a new worktree and refuses to run
  without a `worktree-` branch name, so inside this existing worktree the venv
  was built with the same `uv sync --frozen --extra dev` the helper uses, at
  `untracked/venv-worktree-py311`.
- The install fallback is bash and cannot import the constant; "one constant"
  is delivered as the Python SSoT plus tests that fail if the heredoc or
  `settings.json` drift from it.
- One pre-existing test (`test_os_error_survived`) patched
  `compaction_signal.os.replace`; it now patches `os.replace` directly.
- Plan 00159 Task 1.4 (QA + daemon restart) is left for the merge.
- `ruff format --check src tests` reports pre-existing unformatted files
  outside this change (e.g. `config/loader.py`, `core/rule.py`); untouched.
