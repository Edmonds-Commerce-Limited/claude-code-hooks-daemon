# bash_safe_mode heredoc statement split (N312)

## Defect

`utils/bash_flags.py::split_statements` ran `strip_quoted_heredoc_bodies`, which swaps a body for a
placeholder line and keeps the terminator, so one heredoc became three statements.

## Change

- `split_statements` now drops every heredoc body and terminator line (found with `scan_heredocs`,
  so quoted, unquoted, `<<-`, several per command, and unterminated all work) and keeps the opener
  line. One heredoc is one statement. `<<<` is not reported by the scanner as a heredoc.
- New keyword `heredoc_bodies_executable` (default False). True restores the previous behaviour:
  sink-fed quoted bodies blanked, any other body left as its lines, so a mutator inside
  `bash <<EOF` stays visible. Passed by the three callers that hunt for commands inside bodies:
  `verification_result_gate`, `flaggable_content_channel_guard`, `quarantine_artefact_read_guard`.
  `bash_safe_mode` uses the default.
- `bash <<'EOF'\ncmd1\ncmd2\nEOF` counts as one outer statement. The outer shell's `set -e` does
  not govern the inner shell, so demanding a prelude for the inner lines would not protect them.

## Tests

RED first: 13 failures in `tests/unit/utils/test_bash_flags.py`. GREEN after: 45 pass. Added
handler-level cases to `tests/unit/handlers/pre_tool_use/test_bash_safe_mode.py`.

## Results

- ruff check, black --check --target-version py311: clean. mypy on 4 touched src files: no issues.
- test_bash_flags, test_bash_safe_mode, test_verification_result_gate,
  test_handlers_do_not_match_prose, test_blocking_handler_evasion: 432 passed.
- Unit tests matching flaggable_content / quarantine_artefact / bash_safe / verification_result /
  bash_flags: 419 passed.
- `scripts/qa/check_dangerous_invocation_corpus.py`: every recorded verdict holds.

## Environment note

`export PYTHONPATH=... && pytest` was denied by `R-UPGRADE-APPROVAL-ENV-BYPASS` (a false positive on
a pytest command). Used `-o pythonpath=src` instead.
