# Builder report: N716, secret-guard globs read at least as widely as bash

Branch `fix-n710-secret-guard-glob-later-parts`, reused because the branch pool is at its cap. It was fast-forwarded to `origin/main` 6ac79ca2b first.

Scope: ledger N716, plus findings 1 and 2 of `261123-opus-delta-review-pr230.md`. N718 is deliberately not fixed (see the end of this report).

## What changed

### One bracket-aware reader (delta findings 1 and 2)

The new reader is `_component_regex`, with `_shell_glob_regex` and `_bracket_regex`, in `src/claude_code_hooks_daemon/utils/secret_file_matching.py`. It replaces the global `[^` -> `[!` rewrite (`_bash_bracket_negation`) and `fnmatch.translate`. Both fnmatch sites now use it: the stem heuristic in `_token_mention_judged` and the walker, `LinkNames` and `CwdSet`, through `_component_spells`. `fnmatch` is no longer imported.

- **Negation.** `!` or `^` negates only right after the opening `[`. So `[a[^z]` matches `a [ ^ z`, as bash does.
- **First member.** A `]` right after the opener, or after the negator, is a member: `[]b]`, `[!]a]`, `[^]]`.
- **Ranges.** A range is `x-y`. A `-` at the start or the end is a literal.
- **Classes.** A POSIX class, an equivalence class or a collating symbol anywhere in a bracket makes the whole component match anything. That is fail closed, because a negated set must never be guessed.
- **Backslash outside a bracket.** It becomes an optional literal backslash, and the next character keeps its glob meaning. This covers both the escape reading and the literal-backslash reading of a dequoted word.
- **Backslash with a bracket.** A backslash anywhere in a component that also holds `[` makes the component match anything.
- **Unclosed bracket.** A bracket that does not close is a literal `[`.
- **Regex errors.** A regex the engine refuses, such as a reversed range, is read as anything, and the event is logged with `log_and_continue`.
- **Extglob.** `_extglob_regex` now returns anything when a bracket, an escape or a quote sits beside a group. Before, it translated `[` and `]` one character at a time, which read `@(b)[i]n` too narrowly. That was found and fixed while touching the code.

### nocaseglob

`_component_regex(component, ignore_case)` matches case-blind unless the caller knows bash's defaults are certain.

- The walker passes `not default_semantics`.
- `LinkNames` and `CwdSet` cannot know the options, so they use the wide reading, which is the default.
- In the stem heuristic, both the residue check and the pattern match ignore case unless the defaults are certain.
- A literal component stays case-exact. Bash 5.2 does the same: with nocaseglob, `kit/BIN/l*` does not match, but `kit/bin/L*` does (probed).
- `shell_snapshot.default_glob_semantics` now also requires every snapshot to record `nocaseglob` as off. Real snapshots do record it: `shopt -u nocaseglob` is present.

### dotglob and other option switches

The pattern `_SWITCHES_OPTIONS` (in `shell_snapshot.py`) now also treats these as a command that changes options: `GLOBIGNORE`, `BASHOPTS`, `BASH_ENV`, `source`, `eval`, and `.` in command position. A command that names one of them gets the conservative reading: dot names, recursive `**`, and case-blind matching.

Probed in bash: `GLOBIGNORE=zz; echo kit/*/late2` matches the dot directory. The same assignment passed only in the environment, or set to an empty value, does not. The guard denies on the name alone and does not model that difference.

### Extglob words

`_extglob_words` is now a character scanner (`_scan_extglob_words`) instead of the `_EXTGLOB_WORD` regex over masked text.

- **Word boundaries.** A word ends only at an unquoted break that is outside any group. A quote or escape earlier in the word, a quoted alternative and a nested group all stay inside the word.
- **Quoting.** The word is returned dequoted.
- **Inner bodies.** Every single-quoted, double-quoted, `$'...'`, `$(...)` or backtick body that holds `(` is scanned again as a command of its own. That covers a `bash -c` or `eval` body.
- **Unclosed group.** A group that never closes is skipped, because bash refuses that line. Skipping it also keeps a stray `@(` in a comment or a commit message from becoming a deny.

## Tests

The tests were written first and were red before the fix: 62 failed. They are in the new file `tests/unit/handlers/pre_tool_use/test_secret_file_guard_glob_bash_options.py`.

- **Modes.** Every case runs in two modes. In defaults-certain mode an all-off snapshot sits in a tmp `CLAUDE_CONFIG_DIR`. In conservative mode there is no snapshot. The host's real snapshots are never read.
- **Routes.** Each reproducer runs on three routes: the Bash route, the Write-script route, and the Bash route with `_index` patched to None.
- **Bracket reproducers.** These include the delta review's reproducers, read from the project root and from `kit`. A component table pins bash 5.2's own verdicts, each probed with `shopt -s nullglob; echo <pattern>`. `LinkNames(["kit/x^/late"]).reaches("x[a[^z]/late")` is tested directly.
- **nocaseglob.** All four reviewer reproducers, plus `env BASHOPTS=nocaseglob bash -c ...`. Also a case-blind glob that names a protected file directly (the advisor's question): `shopt -s nocaseglob; cat kit/lib/ID_RS*` is denied. That test was added after the fix and was not run against main.
- **Extglob.** All six reviewer reproducers, plus `@(b)[i]n`, `@(bin)/[l]ate`, a double-quoted `bash -O extglob -c` body, and a unit test on the whole captured words.
- **Dot names.** `GLOBIGNORE=zz; cat kit/*/late2`, `env BASHOPTS=dotglob bash -c ...` and `env BASHOPTS=globstar bash -c 'cat kit/**/late3'`.
- **Allowed controls.** `[!b]in`, `[^b]in` and `[ac]in` do not reach the link. With certain defaults, `kit/B?N/late` and `kit/*/late2` are allowed. An extglob that reaches no link is allowed.

Changes to existing tests:

- `tests/unit/utils/test_shell_snapshot.py`: the all-off snapshot now includes nocaseglob. New cases cover a snapshot without nocaseglob, one that turns nocaseglob on, and the new switches.
- `tests/unit/utils/test_secret_file_matching_default_globs.py`: the all-off snapshot now includes nocaseglob.

Targeted QA was run with `nice -n 19`, using this worktree's source (`PYTHONPATH=src`):

- tests: `tests/unit/handlers/pre_tool_use/test_secret_file_guard*.py`, `tests/unit/utils/test_secret_file_matching*.py`, `tests/unit/utils/test_shell_snapshot.py` and `tests/unit/utils/test_recursive_search*.py`. `recursive_search` also consumes `default_glob_semantics`. The results are listed in the QA section below.
- `ruff check` and `black --check` on the touched files: clean.
- `mypy` on the two source files: clean.

## Not done or left open

- **N718 is left unfixed.** A non-root `cat $V/*/name` is denied on EACCES at `/root`. The only fix is to treat an EACCES probe as no match, which loosens a fail-closed branch. The ledger asks for that to get its own security delta review, so it is not an obvious fail-closed fix and it is not done here.
- **New N719, recorded in the ledger.** `protected_file_index.glob_matches` and `directories_matching` are a second shell-pattern reader outside this module. That reader is still case-exact and not bracket-aware. No reproducer leaks through it, because every N716 reproducer is denied with the index off. `globasciiranges` and `${x:-word}` are not modelled.
- **Cost of the wider reading.** A command that names `source`, `eval`, `.`, `GLOBIGNORE`, `BASHOPTS` or `BASH_ENV` is now read conservatively. A glob in it that reaches a link in a dot directory, or a link of a different case, is denied. That cost is accepted as fail closed.

## QA

The targeted run listed above passed: 4370 passed, 13 skipped. The skips are host-dependent tests plus this file's two defaults-only cases, which are skipped in conservative mode. The direct nocaseglob test, which was added after that run started, passes on its own. The full gate was not run, as the brief asked.
