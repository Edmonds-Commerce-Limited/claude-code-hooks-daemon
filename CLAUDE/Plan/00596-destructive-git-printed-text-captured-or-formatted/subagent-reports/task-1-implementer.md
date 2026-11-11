# Task 1 implementer report

The original implementer report was not present in the worktree; this file
records the review-fix round only. See task-1-review-code-reviewer.md.

## Review fixes

1. `_runs_written_script` (`utils/command_position.py`) now also counts a shell
   fed a script the same command wrote on stdin: `sh < s.sh`, `bash < s.sh`,
   `bash -s < s.sh`, `cat s.sh | sh`, `cat s.sh | bash`. This includes the
   pre-existing plain `echo 'git reset --hard' > s.sh; sh < s.sh`. A shell with
   `-c` is not treated as reading stdin.
2. `printf -v VAR ...` assigns rather than prints: `_assigns_variable` makes it
   never print-only in `_printing_body` / `_prints_only`, and `_narrow` no
   longer blanks its arguments, so the pre-existing plain
   `printf -v n '%s' 'git reset --hard'; $n` and `...; eval "$n"` deny too
   (same code path, cheap).

Tests (handle()-level, RED first, in `test_destructive_git_printed_text.py`):
`TestAWrittenScriptRunThroughStdinDenies` (8 cases) and
`TestPrintfDashVAssignsRatherThanPrints` (3 cases).

Probe on HEAD: 85 + 14 cases, 0 errors; only verdict changes versus the
previous HEAD are the two intended ALLOW to DENY flips. Autofix clean; pytest on
the destructive_git, command_position and shell_segmentation test files: 1755
passed.

### Round 2 (task-1-review-round2-code-reviewer.md)

1. Important 1, over-tightening: `fed` now carries along `|` stages only and
   resets at `;`, `&&`, `||`, so `cat notes.txt && bash scripts/qa.sh` and
   `cat s.sh; sh other.sh` allow again. `_reads_shell_input` takes the command
   words (redirects, leading assignments and `exec`/`env`/`command`/`builtin`
   stripped) and is False under `-c`, under `-n` (syntax check only), and when
   the first operand is a script other than `/dev/stdin` or `-`. Under `-s`
   every operand is positional, so it stays True. `-o`/`-O` values and `--`
   are skipped. An unreadable option word counts as a script operand.
2. Substitution-form regressions: `_segment_words` splits a plain unquoted
   word at its redirect operators (`sh<s.sh`, `0<s.sh`), and `_stdin_paths`
   accepts `0<`. `_command_words` drops a redirect placed before the command
   word (`< s.sh sh`) and the pass-through wrappers, including `env` options
   and assignments. A `cp`/`mv` whose source is a written path writes its
   destination (`_copied_paths`). The literal-echo forms of these now deny as
   well (main allowed them).
3. `printf -v` spellings: `_printf_options` skips a leading `builtin` or
   `command`, and `_assigns_variable` matches any word starting with `-v`.
   An unused assignment (`printf -v x '<reset>'` with no `$x`, `${x}`, `${!x}`
   or `${#x}` anywhere in the command) is data again: `_narrow` keeps the
   segment only when the assigned name is expanded, or cannot be read.

Tests, handle()-level and written RED first (27 failing before the fix):
`TestAWrittenScriptReachesTheShellHoweverStdinIsSpelled` (deny),
`TestAShellThatDoesNotReadTheWrittenFileIsNotFedIt` (allow, which also pins the
Suggestion 3 allows), plus deny and allow cases in
`TestPrintfDashVAssignsRatherThanPrints`.

Probe: rv596out v-set, 49 of 49 deny. Its pinned-allow tail is unchanged
except `bash -n < s.sh` and the unused `printf -v x`, which now allow as main
does. The w-set allows 5 of 5, including the substitution-form
`cat n.txt; bash build.sh`, which main denied. cases.json and c2.json: 0
errors. Every verdict change versus 2a4e8e8a1 is an intended ALLOW-to-DENY.
Autofix, ruff and mypy are clean. pytest over the 26 destructive_git,
command_position and shell_segmentation files: 1949 passed. The 13 other
handlers importing command_position: 1674 passed. command_position.py
coverage is 95.8% over its own tests, and the lines still uncovered existed
before this round.
