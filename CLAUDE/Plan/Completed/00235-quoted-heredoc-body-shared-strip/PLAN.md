# Plan 00235: share the quoted-heredoc strip so handlers stop re-deriving it

**Status**: Complete
**Created**: 2026-08-13
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

Writing the commit that recorded Plan 00234's audit findings was DENIED by
`enforce_llm_qa`, because the commit message mentioned the script that handler
guards. That should not happen: the handler carries a deliberate VCS allowlist
so git metadata is never read as an invocation, and its own docstring records
fixing that exact false positive once already.

The allowlist could not reach this spelling. `_SEGMENT_SEPARATORS` includes a
newline, so a `git commit -F - <<'EOF'` body is split into pseudo-commands and
judged line by line. The leading word of the offending "command" was the English
word `prose`.

A heredoc with a QUOTED delimiter disables every expansion — bash hands the body
over verbatim and never parses it as shell syntax — so nothing in it can invoke
anything. `pipe_blocker` already encoded that fact and kept a private copy of the
rule. `enforce_llm_qa` did not, and re-derived the false positive from scratch.

That makes this the third time two handlers have disagreed about bash. The fix is
the one the shared module was created for: put the rule in
`utils/shell_segmentation.py` and have both callers use it.

## Goals

- A quoted-delimiter heredoc body is treated as literal by every caller that
  splits a command into segments
- `enforce_llm_qa` stops denying git commit messages that merely mention the
  guarded script
- `pipe_blocker` keeps its behaviour exactly, delegating rather than duplicating
- An UNQUOTED `<<EOF` stays scanned — it really can execute

## Non-Goals

- Not the other Plan 00234 follow-ups; this is only finding H-3
- Not a change to which commands `enforce_llm_qa` guards, only to what counts
  as a command
- Not a change to `value_can_substitute`, whose narrower
  `"$(cat <<'EOF' ... )"` idiom check is about an argument VALUE and is
  unaffected

## Context & Background

`utils/shell_segmentation.py` exists because two handlers grew their own
scanners and each got the opposite half of the backslash rule, producing the
same bypass from opposite causes (Plan 00200 Task 3.7). Its docstring already
warns about precisely this heredoc failure mode:

> Scanning the body instead of recognising the idiom is not a safe fallback:
> newlines are segment separators, so the "command" before a pipe in the body
> resolves to a line of English prose.

That warning was written for `value_can_substitute` and covers only the
`"$(cat <<'EOF' ... EOF)"` argument-value shape. The plain
`command <<'EOF' ... EOF` shape was never covered, which is the gap.

## Tasks

### Phase 1: Share the rule

- [x] ✅ **Task 1.1**: RED — failing tests for `strip_quoted_heredoc_bodies` in
  `tests/unit/utils/test_shell_segmentation.py`, including guard cases that an
  unquoted delimiter is left alone and text outside the heredoc is untouched
- [x] ✅ **Task 1.2**: GREEN — add `strip_quoted_heredoc_bodies` to
  `utils/shell_segmentation.py`, moving the pattern out of `pipe_blocker`
- [x] ✅ **Task 1.3**: Delegate `pipe_blocker._strip_inert_spans` to it and
  delete its private copy; 367 pipe_blocker tests still pass

### Phase 2: Fix the handler that hit the bug

- [x] ✅ **Task 2.1**: RED — failing test in the co-located
  `test_enforce_llm_qa.py` reproducing the denied commit message, plus two guard
  tests (unquoted heredoc still matches; an invocation outside the heredoc still
  matches)
- [x] ✅ **Task 2.2**: GREEN — strip quoted heredoc bodies before splitting; all
  54 project-handler tests pass

### Phase 3: Verify

- [x] ✅ **Task 3.1**: Full QA green via `./scripts/qa/llm_qa.py all` — 21/21
- [x] ✅ **Task 3.2**: Daemon restarts RUNNING with the new project handler
- [x] ✅ **Task 3.3**: Live proof — the commit delivering this plan uses a
  quoted heredoc whose message names the guarded script. Before the fix that
  exact shape was DENIED. The tick is self-verifying: it can only exist in
  history if the commit carrying it was allowed through the live daemon

## Technical Decisions

### Decision 1: Lift into the shared module rather than import the private copy

**Context**: `enforce_llm_qa` is a project handler in `.claude/`, and the rule
lived as a module-private constant in `pipe_blocker`. Three options: import the
private name, duplicate the regex, or lift it into the shared scanner module.

**Decision**: Lift it. Importing a private name across the client/upstream
boundary is fragile across upgrades, and duplicating is the exact mistake
`shell_segmentation.py` was created to end — its docstring names two handlers
that independently got a bash rule wrong in opposite directions.

The behaviour is a fact about bash, not a policy of either handler, so the
shared scanner is where it belongs. `pipe_blocker` loses nothing: its placeholder
token changes from `<REDACTED>` to `HEREDOC_BODY`, which nothing asserts on and
which is equally inert.

**Date**: 2026-08-13

### Decision 2: This is NOT the intentional-false-positive class

**Context**: `CLAUDE.md` states that blocking handlers matching dangerous
patterns inside commit messages is INTENTIONAL and must not be "fixed", because
acceptance tests depend on embedding dangerous commands in strings.

**Decision**: That rule does not apply here, and the distinction matters enough
to record. Those handlers have no metadata exemption and are not supposed to
have one. `enforce_llm_qa` explicitly *intends* to exempt git metadata — it has
an allowlist, and its docstring documents repairing that allowlist once before.
The defect is that the exemption fails to reach one spelling of the thing it
exists to exempt, not that an exemption is being invented.

Concretely: `git commit -m '…<script>…'` was already allowed. Only the `-F -`
heredoc form was denied. Fixing that inconsistency does not weaken the guard — a
real invocation inside an unquoted heredoc still matches, and that is pinned by
a test in both suites.

**Date**: 2026-08-13

## Success Criteria

- [x] A git commit whose quoted-heredoc message mentions the guarded script is
  allowed, verified against the LIVE daemon and not only in tests — the delivery
  commit `e2295c51` is itself that shape
- [x] A real invocation of the guarded script is still denied — probed through
  `.claude/hooks/pre-tool-use` against the running daemon: `deny`
- [x] An invocation inside an UNQUOTED heredoc is still denied — probed the
  same way: `deny`
- [x] `pipe_blocker` behaviour unchanged (its full suite green — 367 passed)
- [x] Full QA green (21/21), daemon RUNNING

## Risks & Mitigations

| Risk                                                  | Impact | Probability | Mitigation                                                                    |
| ----------------------------------------------------- | ------ | ----------- | ----------------------------------------------------------------------------- |
| Blanking bodies creates a bypass via unquoted heredoc | High   | Low         | Unquoted `<<EOF` deliberately unmatched; pinned by tests in both suites       |
| `pipe_blocker` regresses via the delegation           | High   | Low         | Its full suite (367 tests) run before and after; no test couples to the token |
| The placeholder token itself reads as a command       | Medium | Low         | `HEREDOC_BODY` is in no allowlist and no block pattern; body shape preserved  |

## Delivery & Milestones

- Found by hitting it while committing Plan 00234's audit findings (H-3)
- Delivered at `e2295c51`: shared strip + `pipe_blocker` delegation +
  `enforce_llm_qa` fix + tests in both suites. QA 21/21, daemon RUNNING
- That commit's own message is the end-to-end proof: a quoted heredoc naming
  the guarded script, the exact shape denied before the fix
