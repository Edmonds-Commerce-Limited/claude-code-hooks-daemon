# Plan 00557 Tasks 2.1-2.3: build report

## Built

- `_check_idle_compaction(project_root)` in `optimal_config_checker.py`, wired into `_run_checks` as the seventh check, "Idle Compaction".
  - Pass: no disabler found; an absent `idleCompaction` counts as on.
  - Fail, naming the cause: `idleCompaction: false`, `autoCompactEnabled: false`, or `DISABLE_AUTO_COMPACT`, `DISABLE_COMPACT`, `FORCE_PROMPT_CACHING_5M` truthy. "Truthy" means anything other than empty, `0`, `false`, `no`, `off`.
  - Sources read: the shell env, the user settings file and its `env` section, and the project's `.claude/settings.json` and `.claude/settings.local.json` with their `env` sections.
  - An unreadable project settings file is skipped with a debug log, so the check never fails on a guess. `_check_effort_source` reports such a file instead; I chose not to, because a confusing "fix" for an unreadable file helps nobody. Disagree if you want parity.
- `_enforce_settings_sync` writes `idleCompaction: true` only when the key is absent. An explicit false is never overwritten, and a read error writes nothing. Both docstrings are updated.
- Four existing sync tests assumed `written == ["alwaysThinkingEnabled=true"]` or an unchanged file; they now account for the second key.
- Docs: `src/claude_code_hooks_daemon/skills/hooks-daemon/check.md` is the only place that lists the checks. The `optimise.md` skill does not list individual checks, so it is unchanged. The sample output in `check.md` still reads "4/6", which is illustrative.
- `regenerate-docs` was not needed: the handler's `get_claude_md()` returns None, so its guidance text is unchanged.
- Release note: `CLAUDE/UPGRADES/UNRELEASED/release-notes/011-idle-compaction-config-check.md`.

## Red output (before implementation)

`pytest tests/unit/handlers/session_start/test_optimal_config_checker.py`: 17 failed, 89 passed. 16 failures were `StopIteration` (no "Idle Compaction" check exists) and 1 was `assert [] == ['idleCompaction=true']`.

## Green

The same file plus `tests/unit/daemon/test_cli_check.py`: 121 passed.

## QA

`llm_qa.py changed` could not run. It waited the full 600 s twice for the host-wide QA lock, held first by the worktree-issue-146-secret-guard run and then by worktree-p555-task43. In place of it I ran, on the two touched Python files, `black --check` (clean), `ruff check` (clean) and `mypy` on the source file (clean). The coordinator should run the targeted QA gate on this commit.

## Disagreements with the brief

None. The research and the shape in Task 1.2 held up. The "need 2.1.290 or later" version claim is the research's inference, not confirmed, and the `why` text states it as the docs do.
