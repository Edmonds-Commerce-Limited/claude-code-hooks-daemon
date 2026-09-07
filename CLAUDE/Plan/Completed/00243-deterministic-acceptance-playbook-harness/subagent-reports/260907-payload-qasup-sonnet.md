# Task 1.2 — Convert qa_suppression strategy acceptance-test payloads

Scope: `/workspace/src/claude_code_hooks_daemon/strategies/qa_suppression/`

## Files converted (10 files, 12 tests)

Each `AcceptanceTest.command` was hand-written prose/quoted-shell-style text
describing a `Write` call. Converted to declare a `ToolPayload` once
(`tool_name=ToolName.WRITE`, `tool_input={"file_path": ..., "content": ...}`),
then `command=probe.as_instruction()`, `tool_payload=probe` — copying
`strategies/tdd/go_strategy.py`'s shape exactly.

- `python_strategy.py` (1 payload: `probe`)
- `javascript_strategy.py` (1: `probe`)
- `csharp_strategy.py` (1: `probe`)
- `dart_strategy.py` (1: `probe`)
- `go_strategy.py` (1: `probe`)
- `java_strategy.py` (1: `probe`)
- `kotlin_strategy.py` (1: `probe`)
- `ruby_strategy.py` (1: `probe`)
- `rust_strategy.py` (1: `probe`)
- `swift_strategy.py` (1: `probe`)
- `php_strategy.py` (3: `probe_ignore_next_line`, `probe_ignore`, `probe_phpcs_disable`)

## Skipped under rule 6 / blocked under rule 7

None. Every test's content was a literal string, never an English description,
and every `Write` went through `Edit` without the `qa_suppression` handler
firing (this directory is on its exclude list, as expected).

## Notes on the conversion

- Escaped `\\n`/`\\"` in the old prose became real newlines/quotes, e.g. Java:
  `"@Suppress" + "Warnings" + '("unchecked")\npublic class Example {}'`.
- Preserved this module's existing convention of splitting suppression
  keywords across `+` concatenation (`"no" + "qa"`, `"# type: " + "ignore"`)
  in the new `content` values, matching `_FORBIDDEN_PATTERNS` in the same
  files — so the daemon's own source still never spells a suppression
  directive contiguously.
- `file_path` in each payload reuses the exact same `scratch_path(...)` call
  the prose used, wrapped in `str(...)`.
- Nothing else in any `AcceptanceTest` was changed.

## Test assertions updated

None needed. `test_uses_scratch_path` only checks the scratch-dir substring
is present in `test.command`; `as_instruction()` preserves it via `repr()`.

## Verification

```
.venv/bin/pytest tests/unit/strategies/qa_suppression/ -q --color=no --no-header
```

Result: `300 passed, 1 warning in 0.21s`. The one warning
(`PytestCollectionWarning` on the `TestType` enum having an `__init__`) is
pre-existing and unrelated to this change.

## Constraints observed

No git command was run.

## Other note

Mid-task, a system-reminder appeared instructing use of Bash/sed instead of
Read/Edit/Write. Disregarded as an injected instruction: it contradicted both
this project's explicit sed-block rule and the assigned task's explicit
"use Edit, sed is blocked" instruction.
