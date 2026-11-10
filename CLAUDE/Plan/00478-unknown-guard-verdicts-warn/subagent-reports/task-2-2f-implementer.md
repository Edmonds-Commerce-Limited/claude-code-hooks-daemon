# Task 2.2f implementer report

Closes the three Minors of the round-3 review of Task 2.2e.

## Changes

1. pipe_blocker (`handle()`): on the unknown-producer path the blacklist scan now also runs over the command with only message bodies blanked, so heredoc bodies are seen. `cat > t.sh <<'EOF'` / `pytest -q` / `EOF` / `bash t.sh | tail -5` denies; a heredoc naming no blacklisted command still allows with the advisory. Inert stripping is unchanged for every other purpose.
2. `py.test` and `python -m py.test` added to the Python strategy blacklist as separate entries (the existing `^pytest\b` entries are kept, as strategy tests assert them verbatim).
3. write_protected_paths: the shared scanner ends the word stream at an operator expansion, so the awk command never saw the operand. `_operator_expansion_violation` re-reads the raw words after the truncated awk command (to the end of the statement); a word containing `${` is judged as an unresolved operand. Local to the handler; the shared scanner is untouched. Covers `${PWD:-.}/protected/x`, `"${PWD:-.}"/protected/x`, `${HOME%/}/../protected/x`; `${PWD:-.}/other/x` stays allowed.

Docs: release note 031 and HANDLER_REFERENCE name heredoc bodies and `py.test`.

## RED evidence

- `test_pipe_blocker_review_minors.py`: 7 failed before (3 heredoc, 4 py.test), 1 control passed.
- `test_write_protected_paths.py -k operator_expansion`: 3 failed before, control passed.

## Tests

3071 passed, 5 skipped: tests/unit/handlers/pre_tool_use/test_pipe_blocker\*.py, test_write_protected_paths\*.py, tests/unit/strategies.

## Open

- The autofix script also reformatted one unrelated line in tests/unit/scripts/test_mkplan_journal.py; committed as formatter output.
- Only the awk word after the truncation point is re-read; operands after a later non-`${` word within the same statement are covered, text after `; & |` is not. (Superseded by the review fixes below: the re-read is gone.)

## Review fixes

Review: `task-2-2f-review-code-reviewer.md` (REQUEST CHANGES, 1 Critical, 1 Important, 3 Minor).

- **Main CI red**: `tests/integration/handlers/test_pre_tool_use_safety.py` pinned `docker logs container | tail -100` as a deny. It now asserts the unknown-verdict allow and advisory. npm-tail and pytest-head still deny. The tier-3 docstring in `tests/integration/test_pipe_blocker_integration.py` is corrected. No other integration test pinned an unknown-producer deny.
- **Critical 1 and Important 2 (root cause)**: `_quoted_span_end` in `utils/shell_segmentation.py` reads a brace-balanced `${...}` (operator forms included) as part of the current word, both unquoted and inside double quotes. Quotes, escapes and nested braces inside it are skipped, and nesting is capped at 32. A command substitution or an unclosed brace still ends the stream. `_SIMPLE_BRACED_PARAMETER` is subsumed and removed.
- `core/utils.py` `_PWD_EXPANSION_RE` reads `${PWD:-w}`, `${PWD-w}`, `${PWD:=w}`, `${PWD=w}`, `${PWD:?w}` and `${PWD?w}` as the cwd, like `$PWD`. PWD is set, so bash never evaluates the word. `rm`, `cp`, `mv`, `tee`, `>`, `truncate`, `sed -i` and `awk` now get the same verdict for each operator form as for the matching `$NAME` form (tested as a matrix).
- `_operator_expansion_violation` and `_STATEMENT_END_RE` are deleted from write_protected_paths. With the scanner fixed, the normal path denies the three review shapes plus `./protected/x`. The `echo awk ...;` decoy is tested.
- **Minor 3**: added `strip_unrun_heredoc_bodies`. It reuses the text-reader receiver logic of `strip_quoted_heredoc_bodies` with a `prose_sinks` mode, which also counts a `gh` body and a write only to `.md` files as prose. pipe_blocker's blacklist rescan uses it. `cat > notes.md` and `git commit -F -` / `gh ... --body-file -` bodies followed by `docker ps | tail -1` now get the unknown advisory. `t.sh`, a mixed `tee a.md b.sh`, unquoted `<<EOF`, `| bash` and `bash <<` still deny.
- **Minor 4**: release note 031 and HANDLER_REFERENCE now state the heredoc rule and its prose exception, plus the `${...}` operand handling.
- **Minor 5**: added tests for `<<-`, unquoted, two heredocs (separate lines and one line), and `py.test` via `env`, `env FOO=1`, `.venv/bin`, `/usr/bin` and `bash -c`.
