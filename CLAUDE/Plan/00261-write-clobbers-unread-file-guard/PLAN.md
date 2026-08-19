# Plan 00261: `Write` clobbers an existing file nobody read

**Status**: Not Started
**Created**: 2026-08-19
**Owner**: Unassigned
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

`Write` replaces a file's entire contents. When the target already exists and
the agent has not read it, everything in it is destroyed with no warning and no
diff — the agent cannot even report what was lost, because it never knew.

This is not hypothetical. It happened in this repository on 2026-08-19: a
`Write` to `00260-Journal-26-08-19.md` destroyed a tracked 58-line journal that
a sub-agent had committed minutes earlier. One of the destroyed entries recorded
a secret-list term arriving by `mv` — evidence filed for Plan 00252. It was
caught only because that particular path happens to be covered by the
`journal-append-only` plan-QA rule, which **advises** and does not block. Had
the file been anything else, the loss would have entered a commit looking clean.

**The harness does not prevent this.** The `Write` tool's own description states
"Overwriting an existing file you haven't Read will fail." Measured on
2026-08-19 in `bypassPermissions` mode, it does not: a file created outside the
harness's knowledge was `Write`-clobbered with no prior `Read`, and the content
was destroyed. Reproduced twice — once under `/tmp`, once inside the repository
to rule out a project-scope confound. The tool reported "has been updated
successfully", so it knew the file existed. In non-bypass permission modes the
approval prompt is a real net; **the gap is specific to YOLO mode**, which is
exactly where agents run unattended.

## Goals

- An agent cannot destroy an existing file's contents with a `Write` it has
  not read first.
- Creating a NEW file stays completely unimpeded — that is the common case and
  must not acquire friction.
- The block message names the cheap remedy (`Read` then retry, or use `Edit`).

## Non-Goals

- **Not** a size or shrink threshold. See Decision 1 — the incident that
  motivates this plan would have defeated one.
- **Not** a general undo/backup system. Git is the recovery mechanism for
  tracked files; this plan is about not needing it.
- **Not** covering Bash-mediated writes (`>`, `tee`, heredoc). Plan 00260 owns
  that surface. A `Write`-only guard is still worth having: `Write` is the tool
  agents reach for by default.

## Context & Background

What already exists, and why none of it covers this:

| Mechanism                     | Scope                  | Strength         |
| ----------------------------- | ---------------------- | ---------------- |
| `journal-append-only`         | plan journals only     | ADVISE           |
| `plan-shrink-without-journal` | `PLAN.md`, 2,000 bytes | ADVISE           |
| `plan-doc-size` tiering       | plan documents         | blocks growth    |
| `lock_file_edit_blocker`      | lock files, by path    | BLOCKS           |
| harness read-before-overwrite | all files              | **not enforced** |

So the daemon already has the *concept* — three of its plan-QA rules reason
about destructive edits — but every instance is scoped to plan documents or to
a named path list. No guard covers an arbitrary file.

## Tasks

### Phase 1: Confirm the mechanism

- [ ] ⬜ **Task 1.1**: Re-confirm the harness behaviour on the current Claude
  Code version before building anything — if read-before-overwrite starts being
  enforced, this plan is obsolete and should be cancelled rather than shipped.
  Record the version tested.
- [ ] ⬜ **Task 1.2**: Confirm the daemon sees `Read` tool calls as PreToolUse
  events (capture a real payload via `payload_capture`, as Plan 00259 Task 1.1
  did — do not assume). The whole design depends on it.

### Phase 2: TDD implementation

- [ ] ⬜ **Task 2.1**: RED — `matches()`: fires on `Write` to a path that
  exists on disk and has not been read this session; does NOT fire on `Write`
  to a non-existent path; does NOT fire on `Edit`; does NOT fire on any other
  tool.
- [ ] ⬜ **Task 2.2**: RED — session-state tests: a `Read` of the path clears
  the block for that path; a `Read` of a DIFFERENT path does not.
- [ ] ⬜ **Task 2.3**: GREEN — implement, following `lsp_enforcement`'s
  established per-session-state pattern.
- [ ] ⬜ **Task 2.4**: `get_claude_md()` and `get_acceptance_tests()` with both
  a DENY case and an ALLOW case (a new-file write), since a deny-only suite
  cannot catch over-broad matching.

### Phase 3: Wiring

- [ ] ⬜ **Task 3.1**: Register default-ON, dogfood in this repo, and decide the
  priority band (safety, 10-20).
- [ ] ⬜ **Task 3.2**: `config-changes` manifest. Consider whether a
  `truth-changes` entry is warranted — this changes what a `Write` call does in
  every client project, so probably yes.
- [ ] ⬜ **Task 3.3**: Full QA, daemon restart RUNNING, live verification.

## Technical Decisions

### Decision 1: track reads, do NOT threshold on size

**Context**: the obvious design is to generalise `plan-shrink-without-journal` —
compare incoming byte count to what is on disk and block a large loss.

**Decision**: reject the size threshold; track reads instead.

**Rationale — the motivating incident refutes the threshold directly.** The
`Write` that destroyed the 58-line journal produced a file of roughly 67 lines.
It **grew**. Every shrink-based rule would have passed it. The destructive
property was not that content got smaller, it was that content was *replaced*
by content written without knowledge of what was there.

Tracking reads targets that property exactly, and it is what the harness already
documents as its own contract — so the guard restores an expected behaviour
rather than inventing a new rule agents must learn. The false-positive cost is
also close to nil: the remedy is one `Read`, which is what the agent should have
done regardless.

### Decision 2: no `MUST_..._BECAUSE` escape hatch is needed

**Context**: several handlers accept an inline declaration.

**Decision**: none here — but for a different reason than Plan 00259's. There it
was withheld because the action is irreversible. Here it is simply unnecessary:
`Read` IS the escape hatch, it costs one call, and unlike a typed justification
it actually removes the hazard rather than declaring it acceptable.

## Success Criteria

- [ ] `Write` to an existing, unread file is denied
- [ ] `Write` to a new path is unaffected
- [ ] A prior `Read` of that path allows the write
- [ ] Handler carries guidance and both acceptance-test cases
- [ ] QA green, daemon restart RUNNING, verified live

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes. Blow-by-blow log lives in JOURNAL/. -->

- Filed from a live incident in this repository plus a measured harness
  behaviour, not from a hypothetical.
