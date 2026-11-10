# Task 2.2d report: ESLint timeout and run failure become advisories

## Change
- `validate_eslint_on_write.py`: `TimeoutExpired` (row 17, R-ESLINT-TIMEOUT) and any launch exception (row 18, R-ESLINT-RUN-FAILURE) now return `unknown_verdict_allow(...)`. The advisory says the file was NOT linted. The cause carries the exception class name only, not its message. Both rule texts are advisory-only (matching `_TIMED_OUT_RULE` in `conflict_marker_commit_gate`); IDs kept. `get_claude_md()` updated. R-ESLINT-ERRORS still DENIES.
- `HANDLER_REFERENCE.md`: ESLint section only.
- Release note 029.
- Tests updated: `test_handle_timeout`, `test_handle_exception`, the two disclosure-ladder rule tests (renamed `..._is_an_advisory_not_a_deny`), plus new guidance, rule-text and still-denies tests. A stale docstring in `test_eslint_bash_writes.py` was corrected.

## RED (before the handler change)
`tests/unit/handlers/post_tool_use/test_validate_eslint_on_write.py`: 6 failed, 68 passed (the two handler tests, the two ladder tests, and the two new guidance/rule-text tests).

## GREEN
Same file plus `test_eslint_bash_writes.py` and the holding-area integration test: 101 passed.

## Disagreements
None.
