# Plan 00540 / issue #126: review fixes (Opus)

Responds to `261020-issue126-review-opus.md`. Fix commit: `8b7faec53` on `worktree-plan-00540`.

## Red before green

The new tests were run against the pre-fix source (head `1b0018cb6`): **37 failed, 141 passed**.
Every new test failed. The log is `untracked/scratch/rf126-red-full.txt`. After the fix, the three
test files gave **178 passed** (`untracked/scratch/rf126-green.txt`). ruff, mypy and black are
clean on the touched files.

## Findings

**M1: no boundary after the supervisor name.**

- Red tests:

  - `test_a_file_that_only_starts_with_the_supervisor_name_is_untouched`, with
    `_helper.py`, `-wrapper`, `.sh` and `.py.bak` (install)
  - `test_a_line_that_is_not_python_before_the_launcher_does_not_warn`, with `-wrapper`,
    `_x` and `.sh` (integrity)
  - `test_a_name_that_only_starts_with_the_supervisor_name_is_neither` (utils:
    `wrapper_names_launcher` and `wrapper_execs_bare_script`)

- Fix: `SUPERVISOR_NAME_END` (`(?=[\s"'};]|$)`) and `file_name_token()` in `utils/ccy_supervisor.py`
  are now used by:

  - the prefix regex
  - `names_deployed_file`, the line gate (moved to utils together with `DEPLOYED_LOCATIONS`)
  - the script-to-launcher substitution
  - the integrity checks

  `is_armed` is unchanged: it still matches the substring.

**M2: the interpreter word had no left boundary.**

- Red tests: `foo-python3` and `/usr/bin/foo-python3` in both install and integrity.
- Fix: `_WORD_START` matches at the start of the line, after whitespace, after a quote or `=`,
  or after `:-`.

**S1: flags and quoted paths.**

- Quoted paths are rewritten and keep their quote
  (`test_a_quoted_path_keeps_its_quote_and_loses_the_interpreter`, and the integrity quoted test).
- Lines with Python options are **left unchanged and reported**:
  - Install: `test_a_prefix_the_upgrade_cannot_rewrite_is_left_alone_and_reported`, with
    `-u`, `-X dev`, `-I` and `-m trace`, each on `.py` and on the launcher.
  - Integrity: warns and says to change the line by hand.
- Why I chose this over rewriting: the launcher execs `$interpreter claude-supervise.py "$@"`,
  so it cannot carry Python options. Dropping them silently changes behaviour. Some options are
  not passive: `-m mod` means the path is an argument to mod, and `-E`/`-I` change how the
  environment is read. A left-alone `.py` line keeps working wherever it already worked. A
  left-alone launcher line is reported both at upgrade and at every session start, so no
  combination of Python and launcher goes unreported.

**A1.** The comment on `PLAIN_INTERPRETER_WORDS` now says correctly that the search ends at
`python3` and never tries `python`. The behaviour is unchanged.

**A2.** Every distinct pin is listed, each with its own `export CCY_PYTHON=...`
(`test_every_pinned_interpreter_is_listed_in_the_ccy_python_hint`). Release note 005 now says
that the note appears only once and tells readers to read the upgrade output.

**A3.** `wrapper_prefix_before_launcher` returns a `LauncherPrefix(word, is_python, upgrade_repairs)`. The integrity message promises a repair only for a word with no options in
front of the launcher in the deployed directory. In every other case it says the upgrade leaves
the line alone (`test_a_python_launcher_line_the_upgrade_leaves_alone_is_not_promised_a_repair`).

**A4.** This was cheap and does not add noise, so it is implemented. It fires only when `$VAR`
or `${VAR}` is the command word directly before the supervisor path.

- Integrity warns that the variable "cannot be checked"
  (`test_a_variable_before_the_launcher_is_reported_as_unverifiable`).
- The migration leaves the line unchanged and reports it.

**A5.** `SHELL_INTERPRETER` is now shared from utils, by both install and integrity.

## Residual (not fixed)

The integrity warning for the bare script ("execs claude-supervise.py directly ... a daemon
upgrade repoints it") still promises a repoint in two cases where the upgrade now leaves the line
alone:

- a `.py` line with Python options or a variable
- a script outside the deployed directory (this was already true before this change)

The upgrade output does report both lines.

## QA

`./scripts/qa/llm_qa.py changed` on head `8b7faec53`: QA_EXIT=0, **40/40 PASSED**.
changed_tests: 2728 passed, 0 failed, 5 skipped (45 test files from 8 changed files, 0 unmapped).
The run was recorded green for the merge-time advisory. The full output is in
`untracked/scratch/rf126-qa.txt`.
