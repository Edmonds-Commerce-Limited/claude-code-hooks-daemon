# N47 gate fix: error_hiding on model_fallback_records.py

## Scope

Fixed the `error_hiding` gate failure reported against
`src/claude_code_hooks_daemon/utils/model_fallback_records.py`:

- `event_epoch` (return-none-on-error): the `except ValueError: return None`
  inside the try/except is now `except ValueError as exc: logger.debug(...); parsed = None`, with the actual `return None` moved outside the try/except
  to a plain `if parsed is None: return None` check. Behaviour for callers is
  unchanged (unparseable and empty timestamps both still yield `None`), but a
  genuinely malformed timestamp is now logged at debug instead of being
  indistinguishable from a documented empty-timestamp case.
- `_parse_payload_line` (return-none-on-error): same restructuring — the
  `except ValueError` now logs at debug and sets `payload = None`; the final
  `return payload if isinstance(payload, dict) else None` (already outside
  the try/except) is unchanged.
- Removed the stale exclusion entry in `scripts/qa/error_hiding_exclusions.json`
  for `utils/model_fallback_records.py` / `parse_fallback_line` /
  `return-none-on-error`: that function no longer contains a try/except itself
  (the parsing moved to `_parse_payload_line` in an earlier round), so the
  entry matched nothing. The still-valid `scan_transcript_tail` exclusion in
  the same file was left untouched — it matches a real, still-present finding
  (`OSError` handling around the tail read).
- No new exclusion added, per instruction.

## Tests

Added RED tests (proven against a `git archive HEAD` scratch copy — old code,
new tests — before applying the src fix; both failed there, then passed
against the fixed src) to `tests/unit/utils/test_model_fallback_records.py`:

- `TestEventEpoch::test_an_unparseable_timestamp_is_logged_not_silently_dropped`
- `TestEventEpoch::test_an_empty_timestamp_logs_nothing`
- `TestParseFallbackLine::test_unparseable_json_is_logged_not_silently_dropped`
- `TestParseFallbackLine::test_blank_lines_log_nothing`

## Verification run

- `scripts/qa/llm_qa.py error_hiding` — 0 violations (was 3: two findings +
  one stale exclusion).
- `tests/unit/utils/test_model_fallback_records.py` — 47 passed.
- `tests/unit/qa/test_audit_error_hiding.py` — 43 passed (the two tests
  reported as failing by team-lead now pass).
- `tests/unit/supervise/` — 853 passed.
- `ruff check`, `black --check`, `mypy`, `pyright` on both touched files —
  clean.
- Worktree daemon restarted, `bin/hooks-daemon status` reports RUNNING.

## Commit

Committed to the worktree branch (SHA reported to team-lead separately).
