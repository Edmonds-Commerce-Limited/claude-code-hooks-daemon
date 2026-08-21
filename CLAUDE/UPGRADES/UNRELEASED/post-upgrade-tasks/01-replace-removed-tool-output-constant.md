# Task: Replace the removed `HookInputField.TOOL_OUTPUT` constant

**Type**: workflow-change
**Severity**: optional
**Applies to**: projects whose own handlers reference `HookInputField.TOOL_OUTPUT`
**Idempotent**: yes

## Why

`HookInputField.TOOL_OUTPUT` (value `"tool_output"`) has been removed, and
`HookInputField.TOOL_RESPONSE` (value `"tool_response"`) added in its place.

A real PostToolUse event carries `tool_response`. It has never carried
`tool_output` — `POST_TOOL_USE_INPUT_SCHEMA` requires the former and contains an
explicit `"not": {"required": ["tool_output"]}` clause, so the daemon rejects any
payload using the old name outright.

The constant was therefore a trap rather than an alternative spelling. This
project's NO MAGIC rule tells a handler author to use a named constant instead of
a string literal; an author who obeyed it landed on `TOOL_OUTPUT` and read a key
that is never present. The result is a handler that silently sees nothing, with
no error and no failing test, because the value is simply always absent. Nothing
in the daemon's own `src/` ever used it — the one handler that legitimately reads
the tool response had defined the correct name privately.

Severity is **optional** because any handler that used the old constant was
already reading nothing. The upgrade converts a silent misread into a loud
failure, which is an improvement, not a regression.

## How to detect if this applies to you

Search your own project handlers and plugins for the constant. Sample:

```bash
grep -rn "TOOL_OUTPUT" .claude/project-handlers/ 2>/dev/null
```

You do not need to search the daemon's own source — this task is only about code
your project owns.

If your daemon upgraded and a project handler now fails to load, the session-start
`project_handler_load_checker` alert names it, and `validate-project-handlers`
reports the `AttributeError` with the file and line. Sample:

```bash
bin/hooks-daemon validate-project-handlers
```

## How to handle

Replace each reference and, critically, **check what the surrounding code did with
the value** — it was reading a key that never existed, so the logic around it has
never actually run:

```python
# before — reads a field no event carries, so always None
output = hook_input.get(HookInputField.TOOL_OUTPUT)

# after — reads the field real events carry
output = hook_input.get(HookInputField.TOOL_RESPONSE)
```

Note that a Bash `tool_response` carries `stdout` and `stderr` but **no
`exit_code`**. If your handler branched on an exit code it never received, decide
what the correct behaviour is now that the value is genuinely present — do not
assume the old dead branch was right. Ask the user if the intended behaviour is
not obvious from the handler's tests.

## How to confirm

```bash
bin/hooks-daemon validate-project-handlers   # no AttributeError
bin/hooks-daemon restart && bin/hooks-daemon status   # RUNNING
```

Then exercise the handler and confirm it now sees the tool response — a handler
whose logic never ran before will change behaviour once the field is real.

## Rollback / if this goes wrong

Nothing is modified on disk by this task beyond your own handler source, so `git diff` and `git checkout` of your handler file recovers the previous state. If the
newly-live logic misbehaves, prefer disabling that handler in
`.claude/hooks-daemon.yaml` over reinstating a constant that reads nothing.
