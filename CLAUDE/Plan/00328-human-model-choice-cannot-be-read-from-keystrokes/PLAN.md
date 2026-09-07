# Plan 00328: human model choice cannot be read from keystrokes

**Status**: In Progress — Phase 1 delivered; Phase 2 channel chosen, build open
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

- [x] ✅ **Task 1.1**: A restore whose next reading does not show the target
  family has FAILED. Treat one failure as proof the family is unavailable and
  stop restoring for the session. Needs no new input channel, and would have
  prevented the coupled `/effort` and the `/compact` in the reproduction.
  Delivered: `_settle_awaited_restore` records the awaited `session:family` at
  injection time and judges the first reading rendered after it;
  `model_restore_due` returns `None` once the origin family is known
  unavailable.
- [x] ✅ **Task 1.2**: Do not arm the coupled effort correction for a `/model`
  injection that did not land. Effort was driven to fable's floor while the
  session was still on opus. Delivered: a missed restore clears
  `_coupled_effort_pending`.
- [x] ✅ **Task 1.3**: `flag_compact_due` must not read a FAILED restore as a
  downgrade flip-flop. A flip-flop means the classifier re-fired; an episode
  still open because the restore never took is a different fact. Delivered:
  the same unavailable-family gate short-circuits `flag_compact_due`.

### Phase 2: A detection channel that works

- [x] ✅ **Task 2.1**: Evaluated the user settings file as the signal —
  **rejected**, and a better channel found. Full write-up in
  [DETECTION-CHANNELS.md](DETECTION-CHANNELS.md). `~/.claude/settings.json`
  carries no session id, its mtime moves for `/effort` too, and its decisive
  premise (that an automatic downgrade does not write `model`) is unmeasured —
  if false, the auto-restore silently becomes dead code. Claude Code instead
  writes the automatic downgrade into the SESSION TRANSCRIPT as a
  `model_refusal_fallback` record; 25 genuine records were found across three
  sessions here, all `claude-fable-5` → `claude-opus-4-8`, category `cyber`,
  scope `session`.
- [x] ✅ **Task 2.2**: The restore now arms POSITIVELY off that record.
  Delivered as three pieces: `utils/model_fallback_records.py` (shared
  recognition of both transcript shapes, bounded tail scan — the SessionStart
  `model_fallback_detector` was refactored onto it so there is one parser);
  the `model_downgrade_recorder` PostToolUse handler, silent and enabled by
  default, publishing `<session>.model-downgrade` into the `context-sidecar`
  directory both sides already share; and the supervisor's
  `load_model_downgrade_signal` + `note_machine_downgrade`, which is now the
  ONLY thing that opens a downgrade episode. A drop with no record is logged
  as `unattributed` rather than acted on, so a disabled recorder is
  diagnosable instead of silent. The supervisor reads no transcripts (Plan
  00317's thin-host audit holds).
- [ ] ⬜ **Task 2.3**: Retire the keystroke-derived model recognition — the
  typed-argument parser, the stem match, the picker wildcard and its session
  key and restore-steal guard. Positive arming makes them redundant rather
  than merely replaceable: they all answer "was that the human?", which stops
  being asked. Deleting them is the main prize; leaving both channels doubles
  the surface. **Two halves, in order**: the daemon's `downgrade_indicator`
  status line READS `write_manual_model_marker` to suppress a false
  "downgraded" badge, and runs the same high-water guess the supervisor has
  just stopped running — migrate it onto the attributed signal FIRST, or
  deleting the writer makes the status line lie in exactly this plan's case.
  The `/effort` and `/compact` recognition in `HumanInputLine` stays; only the
  model half goes.

## Success Criteria

- [x] The reproduction in REPRODUCTION.md, replayed, produces no `/model`
  injection. Covered by
  `test_attributed_downgrade.py::test_an_unattributed_drop_never_injects_a_model_restore`
  — the same fable → opus observation the old rule armed on.
- [x] No `/compact` is ever injected as a consequence of a restore that failed.
  Delivered in Phase 1 (Task 1.3) and pinned by
  `test_futile_model_restore.py::test_a_failed_restore_does_not_fire_the_flag_compact`.
- [ ] Supervisor tests cover each of the four observed input shapes. Superseded
  in substance by the attribution rule — none of the four shapes is read any
  more — but left open until Task 2.3 deletes the parser, so the deletion is
  what closes it rather than a claim made ahead of it.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00328-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Milestone A — Phase 1: a futile restore stops at one attempt and escalates
  no further. Delivered in `c4e22ac0`.
- Milestone B — Phase 2: the restore arms on a positively-attributed automatic
  downgrade instead of on a guess about human intent, and the keystroke
  machinery it replaces is deleted. Attribution delivered (Task 2.2); the
  deletion (Task 2.3) is what completes the milestone.
