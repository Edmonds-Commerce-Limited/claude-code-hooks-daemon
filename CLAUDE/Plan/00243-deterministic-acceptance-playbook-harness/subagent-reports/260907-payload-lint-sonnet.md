# Task 1.2 — Convert lint strategy acceptance-test payloads

Scope: `/workspace/src/claude_code_hooks_daemon/strategies/lint/`

## Files converted (10, 20 AcceptanceTests)

Each `Write`-tool test's hand-written English prose was replaced with a
declared `ToolPayload` (`tool_name=ToolName.WRITE`,
`tool_input={"file_path": ..., "content": ...}`), then
`command=probe.as_instruction()`, `tool_payload=probe` — copying
`strategies/tdd/go_strategy.py`'s shape exactly.

- `ansible_strategy.py` (3 tests: `probe_valid`, `probe_broken`, `probe_workflow`)
- `dart_strategy.py`, `go_strategy.py`, `kotlin_strategy.py`, `php_strategy.py`,
  `python_strategy.py`, `ruby_strategy.py`, `rust_strategy.py`,
  `shell_strategy.py`, `swift_strategy.py` (2 tests each: `probe_valid`,
  `probe_invalid`)

## Skipped under rule 6 (English-described content, not stated literally)

None. All 20 tests stated literal content strings, not English descriptions.

## Notes on the conversion

- Escaped `\\n` in the old prose became real newlines in `content`, e.g.
  shell's invalid.sh: `"#!/bin/bash\nif [ -f file ]; then\necho missing fi"`.
- Escaped `\\"` in the old prose (representing an internal quote character
  inside the described content, not a delimiter) became a real `"` in
  `content`, e.g. Kotlin/Swift's `println("hello")` / `print("hello")` —
  not a literal backslash-quote.
- Two payloads preserve deliberately-broken, unclosed constructs verbatim:
  ansible's `probe_broken` content ends `...echo "it is broken\n` (one
  unbalanced quote, trailing newline, no closing quote) and Go/Swift's
  `probe_invalid` end in an unclosed string (`x := "unclosed`,
  `print("hello`) — these are the intentional syntax errors the blocking
  tests assert against, not truncation bugs.
- `file_path` in each payload reuses the exact same `scratch_path(...)` call
  the prose used, wrapped in `str(...)`.
- Nothing else in any `AcceptanceTest` was changed.

## Test assertions updated

None needed. `test_php_strategy.py`'s
`assert "?>" not in blocking_test.command` still holds — the derived content
(`"<?php\necho 'hello'\necho 'world';"`) contains no `?>` substring.

## Verification

```
cd /workspace && .venv/bin/pytest tests/unit/strategies/lint/ -q --color=no --no-header
```

Result: `189 passed in 0.29s`.

## Constraints observed

No git command was run.
