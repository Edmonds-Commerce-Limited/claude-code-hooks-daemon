# Task: review any new denials after `daemon.strict_mode` starts working

**Type**: workflow-change
**Severity**: notification
**Applies to**: any project with `daemon.strict_mode: true`, or any handler
tagged both `SAFETY` and `BLOCKING` (Plan 00466 N24)
**Idempotent**: yes

## Why

`daemon.strict_mode: true` used to have no effect: a handler that raised was
always treated as "no match" and the call allowed, whatever
`hooks-daemon.yaml` declared. It now actually reaches the daemon. Separately,
a handler tagged both `SAFETY` and `BLOCKING` that raises now always denies,
whatever `strict_mode` says.

If any handler in your project (built-in or project-level) had a latent bug
that only ever manifested as a silent fail-open, this upgrade turns that into
a visible deny. That is the intended fix — a crashed safety guard should not
silently let a call through — but it can surface as an unexpected new denial
on a call that used to succeed.

## How to detect if this applies to you

After upgrading, watch for a deny reason containing either:

- `SYSTEM ERROR: Handler <name> crashed - blocking for safety` (strict_mode
  path), or
- `<name>: evaluation error, denied for safety` (SAFETY+BLOCKING path)

on a call that previously succeeded. Both name the crashed handler.

## How to handle

1. Reproduce the crash: the deny reason names the handler and the exception
   type/message.
2. If it is a built-in handler, file it with the daemon's bug-reporting
   procedure (`BUG_REPORTING.md`) — a handler should not crash on any input.
3. If it is a project-level handler (`.claude/project-handlers/`), fix the
   underlying bug in your own handler code.
4. If you need the call to succeed again before a fix lands, set
   `handlers.<event>.<handler>.enabled: false` for that one handler — do not
   disable `strict_mode` project-wide as a workaround, which would re-open
   the fail-open gap for every other guard.

## How to confirm

The handler no longer raises on the input that triggered the deny, and the
call it should allow succeeds again.

## Rollback / if this goes wrong

Setting `daemon.strict_mode: false` restores the pre-upgrade behaviour for
non-`SAFETY`+`BLOCKING` handlers (fail-open on a raise). It does NOT affect a
`SAFETY`+`BLOCKING` handler, which denies on its own raise either way — that
half of the fix is not gated by `strict_mode`, by design.
