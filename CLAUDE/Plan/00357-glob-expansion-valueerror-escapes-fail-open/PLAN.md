# Plan 00357: a ValueError escapes glob expansion and fails a security guard open

**Status**: Not Started
**Created**: 2026-09-08
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Single Agent

## Overview

`_expand_glob_token` in `src/claude_code_hooks_daemon/utils/secret_file_matching.py`
guards its glob expansion like this:

```python
try:
    matches = base.glob(pattern_str)
except (OSError, ValueError):
    continue
for match in matches:      # <-- iteration is OUTSIDE the try
```

`Path.glob` is a **generator function**. The call returns a generator without
executing the body, so the `ValueError` a malformed pattern raises fires on the
FIRST ITERATION — at `for match in matches:`, outside the `try`. The guard
catches nothing it was written to catch.

**Verified directly against the interpreter, not inferred**:

```text
glob is generator function: True
call returned OK: generator
raised ON ITERATION -> Invalid pattern: '**' can only be an entire path component
```

So a glob-shaped token containing a malformed recursive wildcard raises out of
`_expand_glob_token`, out of `find_protected_mention`, and into the calling
handler's `matches()`/`handle()`. The daemon's fail-open design then skips that
handler — meaning **a security guard silently does not run for that tool call**.

Found by the sub-agent working Plan 00356 and recorded there as a follow-up;
confirmed independently here before filing.

## Goals

- The exception cannot escape: expansion is guarded where the work actually
  happens, not where the generator is constructed.
- A regression test that FAILS on today's code — reproducing the escape, not
  merely asserting the happy path.
- Establish whether any other handler is reachable the same way, since the
  blast radius is what makes this High rather than Low.

## Non-Goals

- **Not** changing the daemon's fail-open policy. A handler that raises being
  skipped is a deliberate availability decision; the defect is that this
  handler raises at all. Re-litigating fail-open is a much larger argument and
  does not belong to a one-line bug.
- **Not** rewriting the glob heuristics. Plan 00356 has just reshaped the input
  those gates see; two changes to the same code path at once would make either
  one hard to attribute.

## Context & Background

| Plan  | Title                            | Status      | Relevance                                           |
| ----- | -------------------------------- | ----------- | --------------------------------------------------- |
| 00356 | secret guard bracket glob        | In Progress | Found this while fixing the adjacent bracket bug    |
| 00311 | v3.59.0 release review followups | Not Started | Carries the glob-heuristic maintenance-surface item |
| 00272 | secret guard live-probe gap      | Complete    | Added the stem-overlap heuristics this sits beside  |

**Blast radius — eight dependants of `secret_file_matching`**, and this is the
reason for the priority:

- `pre_tool_use/secret_file_guard.py` — security guard
- `pre_tool_use/quarantine_artefact_read_guard.py` — security guard
- `pre_tool_use/flaggable_content_channel_guard.py` — security guard
- `daemon/payload_capture.py` — redaction path
- `daemon/server.py` — redaction path
- `post_tool_use/lint_on_edit.py`
- `pre_tool_use/staged_lint_gate.py`
- `session_start/secret_file_hygiene_checker.py`

Not every dependant reaches `_expand_glob_token` — only callers going through
`find_protected_mention` with a glob-shaped token do. **Establishing which
actually do is Task 1.1**, and the list above is candidates, not a finding.

## Tasks

### Phase 1: Establish the true reach

- [ ] ⬜ **Task 1.1**: For each of the eight dependants, determine whether a
  realistic input reaches `_expand_glob_token`. Record the ones that do and the
  ones that cannot, with the reason. A guard that cannot be reached this way is
  as important to record as one that can — it bounds the fix's urgency and
  stops the next reader re-deriving it.

- [ ] ⬜ **Task 1.2**: Decide whether the redaction paths (`payload_capture`,
  `server`) can raise here. These are the worst case: a redaction step that
  throws may write an UNREDACTED capture, which is a different and larger
  failure than a skipped guard. If they cannot be reached, say so explicitly.

### Phase 2: Fix

- [ ] ⬜ **Task 2.1**: RED — a test that reproduces the escape on today's code.
  It must fail before the fix for the RIGHT reason (a `ValueError` propagating
  out), not merely assert that a token is allowed.

- [ ] ⬜ **Task 2.2**: GREEN — bring the iteration inside the guard. The
  obvious shape is materialising the generator under the `try`, but that
  changes the memory profile of a large expansion; whichever is chosen, record
  why.

- [ ] ⬜ **Task 2.3**: Audit the module for the same shape elsewhere — any
  other `try` wrapping the CONSTRUCTION of a lazy iterator rather than its
  consumption. The bug class is "guarding a generator's creation", and it is
  worth one sweep while the context is loaded.

### Phase 3: Verify

- [ ] ⬜ **Task 3.1**: Full QA green, daemon restart RUNNING.

- [ ] ⬜ **Task 3.2**: Confirm end-to-end that a tool call carrying such a
  token is now judged by the guard rather than skipping it — the behaviour the
  plan exists to restore, observed rather than assumed.

## Success Criteria

- [ ] A malformed recursive-wildcard token cannot raise out of
  `find_protected_mention`
- [ ] The regression test fails on the pre-fix code
- [ ] Every dependant is recorded as reachable or not, with its reason
- [ ] No other guarded-generator-construction remains in the module

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00357-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Filed from a sub-agent's incidental finding during Plan 00356, confirmed
  independently against the interpreter before filing rather than taken on
  report.
