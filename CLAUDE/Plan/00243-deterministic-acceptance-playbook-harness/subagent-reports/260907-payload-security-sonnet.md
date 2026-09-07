# Task 1.2 — Convert security strategy acceptance-test payloads

Scope: `/workspace/src/claude_code_hooks_daemon/strategies/security/`

## Files converted (12 files, 13 tests)

Each had `AcceptanceTest`(s) whose `command` was hand-written English prose
describing a `Write` call. Converted to declare a `ToolPayload` once
(`tool_name=ToolName.WRITE`, `tool_input={"file_path": ..., "content": ...}`),
then `command=probe.as_instruction()`, `tool_payload=probe` — copying
`tdd/go_strategy.py`'s shape exactly.

- `csharp_strategy.py` (1)
- `dart_strategy.py` (1)
- `go_strategy.py` (1)
- `java_strategy.py` (1)
- `javascript_strategy.py` (1)
- `kotlin_strategy.py` (1)
- `php_strategy.py` (1)
- `python_strategy.py` (1)
- `ruby_strategy.py` (1)
- `rust_strategy.py` (1)
- `secret_strategy.py` (2: AWS-key deny test + fixture-path allow test)
- `swift_strategy.py` (1)

## Skipped under rule 6 (English-described content, not stated literally)

None. Every command in this directory already stated its `content` string
literally, so all 13 converted cleanly.

## Blocked under rule 7 (security_antipattern handler)

None. `strategies/security/` is on that handler's own exclusion list
(`common.py` `SKIP_PATTERNS` includes `/strategies/security/`), so none of
the `Edit` calls carrying dangerous-looking test data were denied.

## Hardcoded absolute paths (rule 3)

None found needing `scratch_path(...)`. All 13 tests already used
`$CLAUDE_PROJECT_DIR/...` rather than a literal `/workspace/...` path — per
PLAN.md Task 0.3, that class of 17 hardcoded-`/workspace` occurrences
(13 of them in this directory) was already fixed to `$CLAUDE_PROJECT_DIR`
before this task started. No path substitution was needed.

## Notes on the conversion

- No `content` string in this directory contained an escaped `\\n` — all are
  single-line snippets, so no newline conversion was needed.
- Nothing else in any `AcceptanceTest` (title, description, expected_decision,
  expected_message_patterns, setup_commands, cleanup_commands, safety_notes,
  test_type, recommended_model, requires_main_thread) was changed.
- No real credential was substituted for any fake one; existing fake AWS key
  (`AKIAIOSFODNN7EXAMPLE1`) etc. carried over unchanged.

## Test assertions updated

None needed — no test asserted on the old literal command string.

## Verification

```
.venv/bin/pytest tests/unit/strategies/security/ -q --color=no --no-header
```

Result: `172 passed in 0.14s`.

## Constraints observed

No git command was run.

## Follow-up: repoint all 13 payloads into the scratch directory

The team lead identified a gap in the original spec (not in the conversion
above): all 13 payloads targeted the real source tree via
`$CLAUDE_PROJECT_DIR/src/...` or `$CLAUDE_PROJECT_DIR/tests/fixtures/...`.
Harmless as prose (a human balks or substitutes a scratch path), but a
declared `tool_payload` is dispatched verbatim by a harness — and these are
DENY tests, so exactly the case where the handler has regressed is the case
where the write would actually land in `src/`.

Fixed in the same 12 files: added a module-level `_FIXTURE_DIR` constant
(`"acceptance-test-security-{lang}"`) and `from claude_code_hooks_daemon.utils.scratch_dir import scratch_path`, then rebuilt
every `file_path` as `str(scratch_path(_FIXTURE_DIR, "<same filename>"))` —
filename/extension unchanged, `content` unchanged byte-for-byte, `command`
untouched (re-renders from the payload).

One special case: `secret_strategy.py`'s "Allow test fixture files" test
depends on the path containing the literal substring `tests/fixtures/` (the
handler's `should_skip()` is a substring match against `SKIP_PATTERNS`, not a
real-path check). Nesting it under the scratch root as
`scratch_path(_FIXTURE_DIR, "tests", "fixtures", "security_test.py")`
preserves that substring while still resolving under `untracked/scratch/`, so
both the skip-path behaviour under test and the new scratch-containment
guard are satisfied simultaneously.

No `setup_commands`/`cleanup_commands` were added — none of these 13 tests
had them before, and the team lead's instruction was not to invent them.

### Verification (follow-up)

```
.venv/bin/pytest tests/integration/test_acceptance_tool_payload_agrees_with_prose.py -q --color=no --no-header
.venv/bin/pytest tests/unit/strategies/security/ -q --color=no --no-header
.venv/bin/ruff check src/claude_code_hooks_daemon/strategies/security/
```

Results: `7 passed` (integration guard), `172 passed` (unit, unchanged from
before), `All checks passed!` (ruff). No git command was run.
