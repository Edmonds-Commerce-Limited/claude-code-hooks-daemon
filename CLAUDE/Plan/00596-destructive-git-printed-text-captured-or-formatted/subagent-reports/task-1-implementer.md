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
