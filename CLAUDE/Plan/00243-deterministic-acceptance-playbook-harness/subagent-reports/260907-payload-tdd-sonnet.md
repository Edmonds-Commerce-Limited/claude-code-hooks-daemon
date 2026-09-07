# Task 1.2 — Convert TDD strategy acceptance-test payloads

Scope: `/workspace/src/claude_code_hooks_daemon/strategies/tdd/`

## Files converted (10)

Each had exactly one `AcceptanceTest` whose `command` was hand-written English
prose describing a `Write` call. Converted to declare a `ToolPayload` once
(`tool_name=ToolName.WRITE`, `tool_input={"file_path": ..., "content": ...}`),
then `command=probe.as_instruction()`, `tool_payload=probe` — copying
`go_strategy.py`'s shape exactly. `go_strategy.py` itself was not touched.

- `csharp_strategy.py`
- `dart_strategy.py`
- `java_strategy.py`
- `javascript_strategy.py`
- `kotlin_strategy.py`
- `php_strategy.py`
- `python_strategy.py`
- `ruby_strategy.py`
- `rust_strategy.py`
- `swift_strategy.py`

## Skipped under rule 6 (English-described content, not stated literally)

None. All 10 tests stated literal content strings, not English descriptions,
so all converted cleanly.

## Notes on the conversion

- Escaped `\\n` in the old prose became real newlines in `content`, e.g. Java:
  `"package com.example;\n\npublic class UserService {}"`.
- `file_path` in each payload reuses the exact same `scratch_path(...)` call
  the prose used, wrapped in `str(...)` — no path was retyped by hand.
- Nothing else in any `AcceptanceTest` (title, description, expected_decision,
  expected_message_patterns, setup_commands, cleanup_commands, safety_notes,
  test_type, recommended_model, requires_main_thread) was changed.

## Test assertions updated

None needed. `test_uses_scratch_path` checks the scratch-dir substring is
present in `test.command`; that still holds because `as_instruction()` renders
`file_path=...` via `repr()`, which preserves the path string unchanged.

## Verification

```
.venv/bin/pytest tests/unit/strategies/tdd/ -q --color=no --no-header
```

Result: `328 passed, 1 warning in 0.24s`. The one warning
(`PytestCollectionWarning` on the `TestType` enum having an `__init__`) is
pre-existing and unrelated to this change.

## Constraints observed

No git command was run. `go_strategy.py` was not modified.
