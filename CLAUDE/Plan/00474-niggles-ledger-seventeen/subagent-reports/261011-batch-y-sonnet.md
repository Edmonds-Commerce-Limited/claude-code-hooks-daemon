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

## Round 2 (review: fix first)

- B1: `_elevated_heredoc_bodies` now uses `scan_heredocs` (quote-aware) and judges only a heredoc whose receiving
  segment (`segment_spans` of the text before the operator) is an elevated shell. The four mention shapes (double- and
  single-quoted commit messages, `; sudo -s <<EOF` in a message, a `python3 -c` string) allow; tests and 6 corpus rows added.
- B2: `_shell_reads_stdin` returns False at the first script operand unless `-s` was given; `-c` is False; `-o X` skips
  its value. `sudo bash script.sh`, `./setup.sh` and `-e script.sh` allow.
- `--login` / `--shell` count like `-i` / `-s`; long value options (`--user root`) skip their value; redirect words
  (`2>/dev/null`) are ignored in the receiver.
- `$( )` bodies now use `heredoc_operators.substitution_end` (bash grammar), so `$(echo ")"; pip install x)` denies.
- Four deny tests that already passed on main (`--arg-file=`, `-s 100`, `-L 2`, the `cd /srv &&` substitution) are now a
  labelled regression-guard test or replaced by quoted-paren substitutions.
- Reviewer probes `probe.py` (66 checked, 0 bad: nothing batch S/U/W denied is now allowed) and `probe2.py` (all
  mention shapes False; `-x`, `--`, `--login`, `--shell`, `-S -s`, `-E bash` True; `bash -e script.sh` False).
- The new test file run against main's two handlers: 26 failed (all deny cases), 36 passed (allow cases).
- Re-run: `tests/unit/utils`, `tests/unit/handlers/pre_tool_use`, corpus gate and wiring test: 18636 passed, 1 skipped;
  black, ruff, mypy, pyright clean.

## Verification (round 1)

- `tests/unit/utils`, all of `tests/unit/handlers/pre_tool_use`, the corpus gate
  (`tests/integration/test_ordinary_command_regression_gate.py`) and
  `tests/unit/qa/test_ordinary_command_gate_is_wired.py`: 18615 passed, 1 skipped (a permissions test for this user), 0 failed.
- black, ruff, mypy, pyright on the touched files: clean.

## Known limits

- A `$( )` body is judged only when the export is live; a prefix assignment (`PIP_BREAK_SYSTEM_PACKAGES=1 echo $(pip install x)`)
  does not reach the substitution, which matches bash.
- Heredoc detection is line-based: a heredoc opened mid-line after other heredocs on the same line is not tracked.
- Long xargs options with a separate value (`--arg-file FILE`) are read as a flag plus a word and not matched.
