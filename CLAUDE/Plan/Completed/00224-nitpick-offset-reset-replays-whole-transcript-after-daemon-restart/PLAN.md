# Plan 00224: nitpick offset reset replays whole transcript after daemon restart

**Status**: Complete
**Created**: 2026-08-13
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

The nitpick pseudo-event audits assistant messages incrementally, from a byte
offset held in `NitpickState`. That state is in-memory only, and its docstring
says so. A daemon restart destroys it, `last_byte_offset` returns to `0`, and
the next fire re-audits the **entire transcript** — replaying every historical
finding as though it had just happened.

This repository mandates a daemon restart after every handler change, so the
misfire is not an edge case here: it is the normal case. The cost is that the
hedging and dismissive advisories become noise, and a guard that cries wolf is
one that gets switched off — the failure mode CLAUDE.md's DBF standard exists
to prevent.

## The evidence (measured 2026-08-13, during Plan 00203)

Six advisories fired at Stop — three hedging categories, three dismissive —
while the message they appeared to describe contained none of the patterns:

| measure                                               | value                              |
| ----------------------------------------------------- | ---------------------------------- |
| assistant messages in the live transcript             | 2,231                              |
| pattern hits across the 6 most recent messages        | **0**                              |
| messages matching somewhere in the transcript         | 42                                 |
| distance from newest message to the most recent match | **114 messages ago**               |
| daemon restarts during the session                    | 2 (six advisories seen after each) |

`HedgingLanguageDetectorHandler._get_last_assistant_message()` on the same
transcript returns a **zero-length** string, which rules the Stop-event
detectors out as the emitters. The text is produced by
`handlers/nitpick/hedging_language.py` and
`handlers/nitpick/dismissive_language.py`.

## Goals

- A daemon restart must not resurface findings already reported
- Keep the audit useful: new messages after a restart are still audited
- Fix the guard rather than the instance

## Non-Goals

- Changing which phrases either detector matches
- Changing the Stop-event detectors, which behave correctly
- Persisting findings themselves; only the audit POSITION is at issue

## Context & Background

`pseudo_events/nitpick.py` holds `_states: dict[str, NitpickState]` on the
`NitpickSetup` instance. `nitpick/protocol.py` documents `NitpickState` as
"Persisted in DaemonDataLayer (in-memory, keyed by session_id). Reset on
context compaction." with `last_byte_offset: int = 0`.

Plan 00082 introduced this design, and its Task 5.5 did include "Daemon restart
verification" — but that verified the daemon *starts*, not that the audit
position survives one. The restart consequence was never considered.

## Tasks

### Phase 1: Reproduce

- [x] ✅ **Task 1.1**: Failing test — a cold `NitpickSetup` pointed at an
  existing transcript must not emit messages written before it started.
  Three tests: the skip, the still-audited half (so a fix that merely MUTED
  the audit cannot pass), and the fail-open no-timestamp case
- [x] ✅ **Task 1.2**: Confirm the test fails for the stated reason — RED on
  `started_at` not existing, then on the unfiltered messages

### Phase 2: Decide and implement

- [x] ✅ **Task 2.1**: Choose between the options in Decision 1 — **Option 4**,
  which only became visible once the failing test showed why Options 2 and 3
  break genuinely-new sessions
- [x] ✅ **Task 2.2**: Implement, keeping `NitpickSetup` the single owner of
  the audit position — `_is_after_start()`, fail-open, no persistence
- [x] ✅ **Task 2.3**: Full QA + daemon restart verification
  - [x] ✅ Verified the production assumption that makes this correct:
    `NitpickSetup()` is constructed exactly once, in
    `controller._get_pseudo_event_setup_registry()` during startup
    registration — so its construction time IS the daemon start time

### Phase 3: Make the class detectable (DBF)

- [x] ✅ **Task 3.1**: Ask what OTHER per-session daemon state resets on restart
  and produces user-visible output; cover anything found by the same test, or
  record why it is safe — see Decision 2. Nitpick is the only replayer; the
  rest re-arm a counter and are bounded
- [x] ✅ **Task 3.2**: Make the class MECHANICALLY detectable, not just
  classified — `tests/integration/test_pseudo_event_restart_safety.py`
  enumerates the pseudo-event setup registry and requires every entry to
  either accept `started_at` and pass the replay property, or carry a recorded
  exemption. See Decision 3

## Technical Decisions

### Decision 1: Where the audit position comes from on a cold start

**Context**: A restarted daemon has no record of what was already audited.

**Options Considered**:

1. **Persist `last_byte_offset` to disk** per session. Nothing is missed across
   a restart. Costs a file format, a write path and cleanup — and the
   transcript archiver already moves transcripts, so a persisted offset can
   point past the end of a replaced file.

2. **Seed the offset to the current end of file on cold start.** A daemon with
   no state has no basis for calling anything "new", so it audits only what
   arrives after it comes up. No I/O, no format, no staleness. Cost: messages
   written while the daemon was down are never audited.

3. **Cap the audit window** to the last N messages. Bounds the blast radius
   without addressing the cause, and picks an arbitrary N.

4. **Skip messages older than the daemon's own start time.** Discovered while
   writing the failing test, and it is the option the first three missed.

**Decision**: Option 4.

**Why Options 2 and 3 are wrong.** The existing test
`test_only_reads_new_messages` asserts that a fresh `NitpickSetup` reading an
existing transcript DOES return the pre-existing message — and that is correct
for a genuinely new session. So a cold setup cannot simply skip what is already
there. It has to distinguish two situations that look identical from the
offset alone:

- a genuinely new session, where existing messages SHOULD be audited
- a restarted daemon resuming an audited session, where they should NOT

`last_byte_offset` cannot tell them apart; both present as `0`.

**Why Option 4 can.** Real transcript entries carry an ISO `timestamp`
(verified on the live transcript: `2026-08-07T06:52:34.866Z`). The daemon knows
when it started. That separates the two cases exactly:

| situation                      | message timestamps vs daemon start | audited? |
| ------------------------------ | ---------------------------------- | -------- |
| new session, daemon already up | after                              | yes      |
| daemon restarted mid-session   | before                             | no       |

No persistence, no file format, and no stale-offset problem when the
transcript archiver replaces a file.

**Fail-open on a missing timestamp**: an entry with no `timestamp` is audited,
as today. That keeps the existing fixtures (which omit it) meaningful, and errs
toward a redundant advisory rather than a silently dropped one.

### Decision 2: Only state that INDEXES a durable record can replay

**Context**: Task 3.1 — the defect class is "in-memory per-session state lost
on restart", and several handlers hold such state. Fixing one instance and
stopping is the failure mode Core Standard 15 exists to prevent.

**Finding**: the surfaces divide cleanly, and only one of them can replay.

| surface                      | state held                 | effect of a restart                    |
| ---------------------------- | -------------------------- | -------------------------------------- |
| `pseudo_events/nitpick`      | offset INTO the transcript | **replays every past finding** — fixed |
| `standing_authorisations`    | delivery count             | full text sent a few extra times       |
| `idle_housekeeping_advisor`  | no-op tick count           | fires LESS, not more                   |
| `command_hints`              | per-hint cooldown          | one extra hint                         |
| `background_process_tracker` | rate-limit state           | one extra advisory                     |
| `lsp_enforcement`            | `block_once` seen-set      | one extra block                        |

**The rule**: state that is *merely a counter* re-arms on restart, and the
worst case is one extra advisory — bounded, and in `command_hints`' case
already disclosed in its own resident guidance ("state resets on daemon
restart, so a hint may fire once more after a restart"). State that *indexes
into a durable external record* replays, and the worst case scales with the
size of that record — here, 2,231 messages.

**Decision**: no further fixes. Nitpick was the only surface holding an index
rather than a counter. Recorded so the next person asking "what else resets on
restart?" gets the discriminator instead of re-deriving it.

**Confidence**: the surface inventory is from a direct search for per-session
state; the per-surface effects are reasoned from what each counter gates rather
than separately reproduced. `command_hints` is confirmed by its own shipped
guidance text.

**Date**: 2026-08-13

### Decision 3: The classification needed a guard behind it

**Context**: Decision 2 is a hand-audit, and Core Standard 15 is explicit that
a defect fixed by hand recurs while one the guard can see cannot. A table in a
plan document is exactly the artifact that goes stale — it describes the six
surfaces that existed on the day it was written and says nothing about the
seventh.

**What is mechanically enumerable**: not "classes holding per-session state" —
a source scan for that is both lossy and imprecise. But
`DaemonController._get_pseudo_event_setup_registry()` **is** the authoritative
list of setups the daemon runs, and the replay property is testable against any
of them.

**Decision**: `tests/integration/test_pseudo_event_restart_safety.py` gates the
registry. Every entry must accept `started_at` and, given a transcript whose
messages all predate it, return nothing — or appear in
`_EXEMPT_FROM_REPLAY_GUARD` with a reason. The suite also refuses to pass
vacuously (empty registry fails) and refuses stale exemptions.

**Scope, stated honestly**: the registry holds ONE entry today, so the gate
covers exactly the bug just fixed. Its value is entirely prospective — the day
pseudo-event #2 is registered, nitpick's own unit test stays green while the
new setup inherits the bug silently. That is the gap this closes.

**Not covered**: the five counter-shaped surfaces in Decision 2 are not gated,
because they are not in this registry and their worst case is one extra
advisory. If one of them ever grows an index into a durable record, this gate
will not see it.

**Date**: 2026-08-13

## Success Criteria

- [x] A restart no longer resurfaces previously-reported findings — measured
  against the live transcript: 9,680 replayed messages suppressed
- [x] Messages arriving after a restart are still audited — 16 genuinely-new
  messages still audited in the same measurement
- [x] Regression test covers the cold-start case, plus a registry-wide gate so
  a future pseudo-event cannot inherit the bug silently
- [x] All QA passing (20/20, 12,502 tests, 95.3% coverage); daemon restart
  verified RUNNING on the fixed code

## Risks & Mitigations

| Risk                                                              | Impact | Probability | Mitigation                                                    |
| ----------------------------------------------------------------- | ------ | ----------- | ------------------------------------------------------------- |
| Option 2 silently drops messages written while the daemon is down | Low    | Medium      | Only the AUDIT is skipped; the transcript itself is untouched |
| Option 1's offset goes stale when a transcript is archived        | Medium | Medium      | Counts against Option 1; recorded in the decision             |

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes (git is the SSoT for "when"). -->

- Bug found by dogfooding during Plan 00203; evidence recorded above
