# Plan 00417: supervisor operator signals

**Status**: In Progress
**Created**: 2026-09-15
**GitHub Issue**: #39
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Interactive sessions run in a container on a machine the operator — or an
automated patch cycle — will sometimes reboot. Nothing tells the agent today, so
work in flight is cut off mid-step, uncommitted changes are lost, and the next
session re-derives where things were.

The supervisor is the right delivery point and already has the machinery: it
knows when Claude is idle with an empty input box, and it already consumes
session-keyed signal files for `/goal` (`*.goal-intent`) and `/model`
(`*.model-switch-intent`). This adds a third family for operator signals.

**The security shape is the design, not a detail.** A channel from outside the
container into a running agent's context is a prompt-injection surface by
default, so this one is built closed: a fixed set of kinds, an integer payload
at most, and no free text or reason field anywhere. The wording the agent sees
is owned by the daemon, in code, under test. Nothing on the host can put words
into a session — it can only select one of a handful of pre-written messages.

## Goals

- A host-side tool can warn every session of this project that the machine
  reboots in N minutes, and the agent reliably commits, pushes, journals and
  stops starting new work.

- The channel cannot carry attacker-controlled text into a session, proven by
  test rather than by convention: an unknown kind and a non-integer payload are
  both rejected.

- A human watching the terminal sees the same countdown.

## Non-Goals

- **Deciding WHEN to send a signal, and performing the reboot.** That is
  host-side tooling which calls the CLI this plan adds.

- **Restoring sessions after a reboot.** A separate host-side capability.

- **A free-text operator channel.** Explicitly rejected by the issue and by this
  plan. If a future need seems to require prose, that is a signal to add a new
  KIND, not a text field.

## Open question — carried from the issue, needs an owner ruling before Phase 2

Whether a session should be able to answer "not yet" (for example, mid-way
through a long run) by writing a file the host-side tooling reads before it
reboots. If wanted it must be a fixed token too, not text. Phase 1 does not
depend on this and should not wait for it.

## Tasks

### Phase 1: The closed channel

- [ ] ⬜ **Task 1.1**: Failing tests first, covering the rejection cases before
  the happy path: an unknown kind is refused, a non-integer payload is refused, a
  negative or zero payload is refused, and a file past its TTL does not fire.
  These are the security properties, so they are the RED tests, not an
  afterthought.

- [ ] ⬜ **Task 1.2**: The supervisor signal family, consumed at the existing
  idle choke point ahead of the goal and model injections, with the same
  semantics as the goal signal: session-keyed file in the status directory,
  injected only when idle with an empty input box, unlinked on injection, TTL
  bounded.

- [ ] ⬜ **Task 1.3**: The three kinds and their daemon-owned wording:
  `reboot-warning` (minutes), `shutdown-warning` (minutes, and ask for a handoff
  entry since no restore follows), `reboot-cancelled` (no payload).

- [ ] ⬜ **Task 1.4**: `hooks-daemon signal <kind> [--minutes N] [--all-sessions]`, mirroring `inject-goal`.

- [ ] ⬜ **Task 1.5**: Status-line transient warning on the existing message
  channel (the one the Ctrl+Z notice uses), so the human sees the countdown.

- [ ] ⬜ **Task 1.6**: Document the signal set, the no-free-text rule and its
  reasoning, and the CLI.

## Success Criteria

- [ ] ⬜ Raising `reboot-warning` with a payload of minutes reaches an idle
  session as the daemon's own wording, and is consumed exactly once.

- [ ] ⬜ An unknown kind, a non-integer payload and a stale file each produce
  nothing, each proven by its own test.

- [ ] ⬜ No code path can render host-supplied text into the injected message —
  the payload's only use is a number in a daemon-owned sentence.

- [ ] ⬜ `--all-sessions` reaches every session of this project and no other.

- [ ] ⬜ Full QA passes, the daemon restarts, CI green.

## Delivery & Milestones

- Filed from issue #39, which arrived with the design already worked through,
  including the closed-channel constraint. The issue is the specification; the
  verification that it is the right shape is this plan's job, per the standing
  rule that an issue is a hypothesis rather than a patch.
