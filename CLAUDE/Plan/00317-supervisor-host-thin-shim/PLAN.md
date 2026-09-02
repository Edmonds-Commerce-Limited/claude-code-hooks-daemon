# Plan 00317: supervisor host thin shim

**Status**: In Progress
**Created**: 2026-09-02
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single python-developer agent, TDD; audit first

## Overview

Plan 00316 exposed an architectural defect in the ccy supervisor's
two-tier design, confirmed by the owner: the PTY HOST process — which by
design never reloads because it owns the live `claude` child — is doing
real LOGIC (parsing typed `/model`, `/effort` and `/compact` commands out
of the input stream, plus the Ctrl+C gate's decision-making from Plan
00312), instead of only delegating to the hot-reloadable `--worker`. Every
piece of logic that lives host-side is a piece that silently requires a
full session restart to update, defeating the very purpose of the split —
Plan 00316's manual-model recognition ships dark until the next session
purely because its input tap is host-tier.

The fix direction: the host becomes a THIN, STABLE SHIM — forward bytes,
own the PTY/child lifecycle, restart the worker when stale, and nothing
else. All recognition/decision logic moves worker-side, fed by a
raw-input tap the host forwards (bounded buffer, fail-open: a worker
outage must never block or corrupt keystroke forwarding). After this, new
input-recognition features hot-reload like every other worker feature.

## Goals

- An audit table of EVERYTHING the host tier currently does beyond
  forwarding + lifecycle (input command parsing, Ctrl+C gate, anything
  else found), each classified: moves to worker / genuinely must stay
  host-side (with the reason recorded).
- Host forwards raw input to the worker over the existing host↔worker
  channel; all typed-command recognition (model/effort/compact) and the
  Ctrl+C double-press decision move worker-side. Latency budget: the gate
  must still act on the byte BEFORE it is forwarded to the child, so the
  design must either keep a minimal host-side hold-and-ask primitive or
  prove the round-trip is fast enough — the audit decides, and "stays
  host-side" is an acceptable audited outcome for the Ctrl+C byte-level
  swallow specifically.
- Fail-open: worker dead/stale/slow ⇒ keystrokes forward unmodified with
  no added latency; nothing the worker does can wedge the PTY.
- After the refactor, a supervisor logic change (e.g. a new typed-command
  recognition) takes effect via worker hot-reload in the LIVE session —
  proven by a test that simulates a mid-session worker reload picking up
  changed recognition behaviour.
- The host-tier surface that remains is small enough to be listed in the
  supervisor's module docstring, and the hot-reload contract doc
  (`.claude/ccy/` notes / global contract) is updated to name it.

## Non-Goals

- Any behaviour change to what the supervisor DOES (00312 gate semantics,
  00316 manual-choice semantics stay exactly as shipped).
- Making the host itself hot-reload (owning the PTY means it cannot).
- Changing the worker reload mechanism (content-hash + mtime pre-check
  stays as is).

## Tasks

### Phase 1: audit

- [ ] ⬜ **Task 1.1**: Enumerate every host-tier responsibility in
  `claude-supervise.py` beyond byte forwarding and child/worker
  lifecycle; produce the classification table (move / must-stay + why) as
  a supporting doc `AUDIT.md` in this plan folder. Owner pre-approved
  proceeding straight into Phase 2 ("I thought this was how it already
  was, so yes let's get this done") — no pause; the audit table travels
  in the report for after-the-fact review.

### Phase 2: refactor

- [ ] ⬜ **Task 2.1**: Raw-input tap host→worker (bounded, fail-open,
  never adds forwarding latency); move typed-command recognition
  worker-side; TDD including worker-dead and worker-slow paths.
- [ ] ⬜ **Task 2.2**: Ctrl+C gate per the audit decision (move with a
  hold-and-ask primitive, or documented stay with its logic minimised to
  the byte-level swallow only).
- [ ] ⬜ **Task 2.3**: Mid-session reload proof test (changed recognition
  behaviour picked up by worker restart without touching the host), docs
  updated (module docstring host-surface list + hot-reload contract
  notes).

### Phase 3: verification

- [ ] ⬜ **Task 3.1**: Full QA 25/25; live dogfood checklist journalled
  for the next session (typed-command recognition change applied via
  worker reload only).

## Success Criteria

- [ ] Audit table exists and every remaining host-side responsibility is
  named and justified.
- [ ] A typed-command recognition change hot-reloads mid-session (test-
  proven; live-confirmed at next opportunity).
- [ ] Keystroke forwarding provably unaffected by worker outage.
- [ ] QA 25/25.

## Delivery & Milestones

- <!-- delivery commit hashes -->
