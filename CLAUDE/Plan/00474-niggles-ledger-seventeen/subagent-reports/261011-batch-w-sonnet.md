# Plan 00474 batch W: N407 last two residuals

## Changes

- `src/claude_code_hooks_daemon/utils/command_position.py`
  - `_narrow_shell_body`: when the words before the shell include `sudo`/`doas`, the `-c` body view is passed
    through `_elevate_later_segments`, which heads every segment after the first with `sudo ` (the first already
    follows `sudo bash -c`). The guards then see `sudo pip install x` for `sudo bash -c 'cd /srv; pip install x'`.
  - `_narrow`: for a `git`/`awk` head whose pipeline does not hand output to a non-inert stage,
    `blank_quoted_text_arguments` is applied in the shared view. Cause of the false deny: that blanking existed only in
    `command_position_argument_segments`, which the pip guards do not call. It now applies to every view consumer and
    inside `bash -c` bodies. `rg` was already data (`DATA_HEADS`).
- `sudo_pip.py`: stale comment (claimed the single-quoted form was not caught) corrected.
- Tests: `tests/unit/handlers/pre_tool_use/test_pip_guards_elevated_body_and_search.py` (written first, RED, then green).
- Corpus: five `n407-*` rows in `tests/fixtures/ordinary_command_corpus.yaml`.
- Ledger: both N407 residual lines marked cleared by batch W.

## Checks

`tests/unit/utils` + all of `tests/unit/handlers/pre_tool_use` + corpus gate: 18534 passed, 1 skipped, 1 failed.
The one failure, `test_subagent_full_qa_blocker::test_every_option_of_the_running_pytest_is_in_a_table`
(`--anyio-mode`), comes from the `anyio` pytest plugin in the throwaway venv built for this worktree
(`untracked/venv-w`); it is unrelated to this change. black, ruff, mypy and pyright clean on the touched files.

## Notes

- Shared-code change affects `git_stash`, `destructive_git` and other view users: their suites pass.
- Still denied: real installs in `if`, `bash -c "..."`, `$(...)`, `git grep ... && pip install --break-system-packages x`,
  and `git log --format=... | sh`.
