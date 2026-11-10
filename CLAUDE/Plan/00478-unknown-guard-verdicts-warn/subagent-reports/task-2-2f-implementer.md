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
- Only the awk word after the truncation point is re-read; operands after a later non-`${` word within the same statement are covered, text after `; & |` is not.
