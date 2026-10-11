# Plan 00474 batch Y: N407 residuals (sudo_pip, pip_break_system)

## Changes

- `pip_break_system.py`: `_substitution_bodies` extracts `$( )` and backtick bodies (single-quoted text skipped).
  `_env_var_governs_pip_install` takes `exported` as a starting state and, when an export is live, re-judges each
  substitution body with the export inherited (recursive, so nesting works). `_XARGS_VALUE_OPTION` lets `-a FILE`,
  `-I X`, `-d D`, `-E S`, `-s N`, `-L N`, `-n N`, `-P N` precede `pip`; other options stay one word
  (`--arg-file=FILE`, `-r`, `-0`).
- `sudo_pip.py`: `_elevated_heredoc_bodies` / `_feeds_elevated_shell` find heredocs fed to `sudo`/`doas` with `-i`/`-s`
  and no command, or with a shell (`bash`, `sh -s`, a path) lacking `-c`; `_elevated_body_runs_pip` judges the body
  segments (command-position view, so echo/grep mentions allow) as `sudo`-headed. `<<-` tab stripping is honoured.
  `sudo -s ls <<EOF` is not a shell on stdin and allows.
- No change to `utils/command_position.py` (shared by about 11 guards).
- Tests: `tests/unit/handlers/pre_tool_use/test_pip_guards_substitution_xargs_heredoc.py` (47 cases).
- Corpus: 7 new `n407-*` allow rows in `tests/fixtures/ordinary_command_corpus.yaml`.
- Ledger: three N407 residual lines marked "cleared by batch Y".

## Verification

- `tests/unit/utils`, all of `tests/unit/handlers/pre_tool_use`, the corpus gate
  (`tests/integration/test_ordinary_command_regression_gate.py`) and
  `tests/unit/qa/test_ordinary_command_gate_is_wired.py`: 18615 passed, 1 skipped (a permissions test for this user), 0 failed.
- black, ruff, mypy, pyright on the touched files: clean.

## Known limits

- A `$( )` body is judged only when the export is live; a prefix assignment (`PIP_BREAK_SYSTEM_PACKAGES=1 echo $(pip install x)`)
  does not reach the substitution, which matches bash.
- Heredoc detection is line-based: a heredoc opened mid-line after other heredocs on the same line is not tracked.
- Long xargs options with a separate value (`--arg-file FILE`) are read as a flag plus a word and not matched.
