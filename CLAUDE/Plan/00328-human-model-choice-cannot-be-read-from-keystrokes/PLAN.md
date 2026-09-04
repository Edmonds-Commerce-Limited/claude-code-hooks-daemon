# Plan 00328: human model choice cannot be read from keystrokes

**Status**: Not Started
**Created**: 2026-09-04
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Direct

## Overview

The ccy supervisor's model auto-restore must never override a model the HUMAN
chose. Plan 00316 implemented that by recognising a typed `/model` from the
raw PTY input tap. A live dogfood on an allowance-exhausted account proved
that channel cannot carry the signal.

See [REPRODUCTION.md](REPRODUCTION.md) for the captured evidence: the raw
Claude Code output, the supervisor's decision log, and the four input shapes
observed.

The human did one thing — `/model` then picked Opus. The supervisor saw the
keystrokes `'/moBBA'` (a stem plus three arrow keys), recognised nothing, read
the fable to opus move as a security downgrade, and answered with `/model fable` (HTTP 429 — the account cannot serve fable), then `/effort low`, then
an unrequested `/compact`. The compaction was escaped manually; unattended it
would have destroyed the session context.

Claude Code renders autocomplete and the model picker in its own UI above the
PTY. The completed word never crosses it, and arrow-key navigation carries no
text at all.

## Scope note

The auto-restore's purpose is unchanged and narrow (owner ruling, 2026-09-04):
counteract the automated fable SECURITY downgrade, nothing more. Allowance
exhaustion is a separate cause with no remedy — trying to switch back is
futile — but the supervisor's BEHAVIOUR under it is in scope, because it
currently flails.

## Goals

- A human model change is never overridden, whichever UI route produced it.
- A restore that cannot succeed is attempted at most once, and never escalates
  into a coupled effort injection or a flip-flop `/compact`.
- Recognition no longer depends on parsing text the PTY does not carry.

## Non-Goals

- **Not** restoring fable when the account cannot serve it. That is futile by
  the owner's ruling; the aim is to stop trying, not to try harder.
- **Not** widening the auto-restore beyond fable-origin drops.
- **Not** adding general child-OUTPUT content inspection to the PTY host
  unless a task below concludes it is the only viable signal — Plan 00317's
  audit deliberately keeps that tier thin.

## Tasks

### Phase 1: Stop the escalation (independent of detection)

- [ ] ⬜ **Task 1.1**: A restore whose next reading does not show the target
  family has FAILED. Treat one failure as proof the family is unavailable and
  stop restoring for the session. Needs no new input channel, and would have
  prevented the coupled `/effort` and the `/compact` in the reproduction.
- [ ] ⬜ **Task 1.2**: Do not arm the coupled effort correction for a `/model`
  injection that did not land. Effort was driven to fable's floor while the
  session was still on opus.
- [ ] ⬜ **Task 1.3**: `flag_compact_due` must not read a FAILED restore as a
  downgrade flip-flop. A flip-flop means the classifier re-fired; an episode
  still open because the restore never took is a different fact.

### Phase 2: A detection channel that works

- [ ] ⬜ **Task 2.1**: Evaluate the user settings file as the signal. Claude
  Code writes the chosen family there on every `/model`. Verified in the
  reproduction: it held `opus` after the failed fable attempt, so it tracks
  what took effect, not what was attempted. Risks to settle: it is user-level
  and shared by concurrent sessions, and the supervisor's own injections write
  it too (it knows when it injects).
- [ ] ⬜ **Task 2.2**: If 2.1 is sound, retire the keystroke-derived model
  recognition it replaces — the typed-argument parser, the stem match, the
  picker wildcard and its session key and restore-steal guard. Deleting them
  is most of the value; leaving both channels doubles the surface.
- [ ] ⬜ **Task 2.3**: If 2.1 is not sound, record why, and fall back to
  Phase 1 only — one failed attempt is a tolerable floor.

## Success Criteria

- [ ] The reproduction in REPRODUCTION.md, replayed, produces no `/model`
  injection.
- [ ] No `/compact` is ever injected as a consequence of a restore that failed.
- [ ] Supervisor tests cover each of the four observed input shapes.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00328-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Milestone A — Phase 1: a futile restore stops at one attempt and escalates
  no further.
- Milestone B — Phase 2: human intent is read from a channel that carries it,
  and the keystroke machinery it replaces is deleted.
