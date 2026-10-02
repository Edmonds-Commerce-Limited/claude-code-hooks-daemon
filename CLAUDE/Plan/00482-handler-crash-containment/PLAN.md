# Plan 00482: handler crash containment

**Status**: Not Started
**Created**: 2026-10-02
**Owner**: dev
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Owner ruling: handlers must never crash. When one does, the daemon handles it gracefully. For
example, it turns the handler off and asks the agent to submit a bug report with the details.

What happens today when a handler raises (`src/claude_code_hooks_daemon/core/chain.py`, the
`except BaseException` block at about lines 1111-1176):

- **A SAFETY+BLOCKING handler** denies the call with the reason `<handler>: evaluation error, denied for safety (<exception>)`. This applies whatever `strict_mode` says (Plan 00466 N24).
  Some guards add their own catch, for example `quarantine_artefact_read_guard` catching
  `TooManyToEnumerateError`.
- **Any other handler**, in non-strict mode, is logged, and a `Handler exception: …` line is
  added to the accumulated context. The chain then continues.
- **What is missing**: nothing tells the agent the crash is a bug to report, nothing captures
  the details a report needs, and nothing stops a handler that crashes on every event from
  crashing again.

GitHub #68 is the case that matters. Two safety guards raised on ordinary commands and failed
closed, as designed, on every such call. The design held, because nothing was ever read. The
experience was still a session repeatedly blocked with an error-shaped reason, and the only
route to a fix was a user filing an issue by hand.

**The tension the owner's ruling has to resolve.** "Turn the handler off" is right for an
advisory or context handler. For a SAFETY guard it is a bypass: anyone who can craft an input
that makes the guard raise could then switch the protection off for the rest of the session.
This plan therefore treats the two classes differently, and asks the owner to confirm (open
question 1).

## Goals

- **Report request**: every handler crash produces a structured, redacted crash record and a
  clear request to the agent to file a bug report through the existing generator
  (`hooks-daemon issue-report`), naming the record.
- **Non-safety handlers**: a crash is contained. The handler is disabled for the rest of the
  daemon's life (or a TTL) after N crashes, the agent is told once, and it is re-enabled on restart.
- **Safety guards**: a crash still fails closed for that call. The deny reason says it is a daemon
  bug, not a policy decision, and gives the report route. Repeated crashes are surfaced, for
  example on the status line and at SessionStart, without disabling the guard.
- A crash never ends the chain for the other handlers beyond what the rules above say.

## Non-Goals

- Changing the fail-closed rule for SAFETY guards without the owner's decision.
- Fixing individual crashing handlers. Each crash found is its own niggle, as #68 was.
- Plan 00478 (when a guard cannot place a token, warn rather than block). That covers a guard
  deciding it cannot decide. This plan covers a guard raising. The two must agree on wording and
  telemetry, so they are cross-linked.

## Tasks

### Phase 1: Inventory (read-only)

- [ ] ⬜ **Task 1.1**: Map every place a handler exception is caught today:

  - the chain;
  - `core/bounded_dispatch.py`;
  - per-guard wrappers;
  - the status-line and lifecycle event paths;
  - any `except Exception` in a handler that hides a crash.

  For each, record what the agent sees, what is logged, and what the verdict log (Plan 00209)
  records.

- [ ] ⬜ **Task 1.2**: Measure how often handlers raise in this repository's logs and verdict log.
  Use the result to pick N (the crash count before a non-safety handler is disabled).

### Phase 2: Crash record and report request (TDD)

- [ ] ⬜ **Task 2.1**: A crash record, written under the daemon's untracked dir, with:
  - the handler, event and exception type;
  - a stack trace with file:line;
  - the daemon version;
  - a redacted input shape (never raw secrets, paths or content), reusing the issue-report
    redaction rules.
- [ ] ⬜ **Task 2.2**: `hooks-daemon issue-report` can take a crash record and build the report
  body from it.
- [ ] ⬜ **Task 2.3**: The agent-facing message on any crash names the handler, says it is a
  daemon bug, and gives the exact `issue-report` command. It is delivered once per handler per
  session, not on every call.

### Phase 3: Containment (TDD)

- [ ] ⬜ **Task 3.1**: Non-safety handlers are disabled after N crashes (a circuit breaker per
  handler, in memory). Disabling is logged, shown on the status line, and cleared by a daemon
  restart or after a TTL.
- [ ] ⬜ **Task 3.2**: Safety guards keep failing closed on each crash. A crash count above a
  threshold raises a visible alert (status line and SessionStart) and points to the report. The
  guard is not disabled unless the owner rules otherwise.
- [ ] ⬜ **Task 3.3**: Acceptance tests: a deliberately raising test handler of each class, run
  through the real chain, shows the message, the record, the breaker (for non-safety handlers) and
  the continued deny (for safety guards).

### Phase 4: Docs

- [ ] ⬜ **Task 4.1**: Document the crash contract in `CLAUDE/HANDLER_DEVELOPMENT.md`, the
  CLAUDE.md guidance block, and a release note.

## Open questions for the owner

1. **Safety guards**: should they fail closed and alert, but never be disabled (recommended)? Or
   be disabled after N crashes, accepting that a crafted input could switch protection off?
2. The value of N, and whether the disable lasts for the daemon's lifetime or for a TTL.
3. Should the agent file the bug report itself? It can, through `issue-report` against the public
   tracker. Or should it only prepare the body for a human to file?

## Success Criteria

- [ ] A raising non-safety handler is disabled after N crashes. The agent is asked once to
  report, with a ready-made crash record, and the rest of the chain is unaffected.
- [ ] A raising safety guard still denies the call. The deny names it as a daemon bug and gives
  the report route, and a repeat raises a visible alert.
- [ ] Replaying the #68 shapes against the pre-fix tree produces the report request and the alert,
  not just a bare error-shaped deny.

## Delivery & Milestones

- Plan filed at the owner's request after #68.
