# Plan 00321: injected goal has no retraction path

**Status**: In Progress
**Created**: 2026-09-02
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Single-Agent

## Overview

The supervisor can SET Claude Code's session `/goal` slot but can never clear
it. `load_goal_signal` reads a `<session>.goal-intent` file and injects
`/goal <line>`; `hooks-daemon inject-goal NNNNN` does the same on demand and
requires an ACTIVE plan number. Nothing in the supervisor, the daemon CLI, or
the handler set emits a clearing `/goal`. The slot holds one condition on
last-writer-wins, so once a condition is in it, the only ways out are a human
typing `/goal`, another plan flipping to In Progress and displacing it, or the
session ending.

That makes a stale condition unclearable from inside the session, and the Stop
challenge keeps evaluating against it every turn. Plan 00320 fixed the two
defects that let a stale goal be CREATED — the sidecar was not retracted when
the ledger emptied, and a plan-shaped path anywhere on disk could emit a goal
naming a project path that does not exist. Neither helps a condition already
sitting in the slot: those fixes stop the next one, and this plan is about the
current one.

Observed at the end of the v3.60.0 release session. The `/goal` slot holds
`Work on Plan 00099 (Plan 00099) at CLAUDE/Plan/00099-test` — a folder that has
never existed (the real 00099 is `00099-python-fingerprint-venv-isolation`,
archived Complete). The daemon-side goal ledger holds zero live entries and no
`.goal-intent` sidecar remains, so every daemon-side source agrees no goal is
owed; only the upstream slot disagrees, and it is the one the Stop challenge
reads. The condition is unsatisfiable by construction: no work can complete a
plan whose folder is absent, so the session can only stop by arguing with the
challenge rather than by discharging it.

## Goals

- When the goal ledger goes from some live entries to zero, the supervisor
  RETRACTS the session goal rather than leaving the last condition standing.
- A stale or unsatisfiable condition can be cleared without ending the session
  and without a human typing `/goal`.
- The daemon's three goal surfaces (ledger, sidecar, upstream `/goal` slot)
  cannot disagree about whether a goal is owed. Two of the three already agree
  after Plan 00320; this closes the third.

## Non-Goals

- Re-opening Plan 00320. Its two fixes are correct and live-verified; they
  govern goal CREATION, and this plan governs goal RETRACTION.
- Teaching the Stop handler to ignore a condition whose plan folder is missing.
  That hides an unsatisfiable goal instead of retracting it, and a stale goal
  naming a plan that DOES exist would still slip through.

## Answered: the `/goal` clearing contract (verified, not inferred)

`/goal` DOES accept a clearing form. Read directly out of the shipped Claude
Code binary
(`/usr/local/lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe`), which
is ground truth rather than documentation that could lag:

```js
hOe = 4000,
k = new Set(["clear", "stop", "off", "reset", "none", "cancel"]);
function oAe(t) { return k.has(t.toLowerCase()) }
// command handler:
//   if (oAe(e)) { let t = sAe(o);
//                 return t === null ? "No goal set" : `Goal cleared: ${t}` }
```

Consequences that matter for the implementation:

- **The clearing tokens are `clear`, `stop`, `off`, `reset`, `none`, `cancel`**,
  matched case-insensitively on the whole argument. `/goal clear` is the
  canonical one.
- **A BARE `/goal` does NOT clear.** The empty string is not in the set, so it
  falls through to the status branch (`Goal active: …` / `No goal set`). An
  implementation that sent a bare `/goal` expecting a clear would silently do
  nothing — this is exactly the wrong guess the plan was written to avoid.
- `sAe` is the clear implementation: it removes the session-scoped Stop hooks
  from `sessionHooksRegistry` and unsets `activeGoal` with reason `user_clear`.
  So clearing is a real retraction of the hook, not a cosmetic reset.
- A goal condition is capped at 4000 characters.

## Design decision: the clear signal is a TRIGGER, not a payload

The retraction must NOT ride the existing `.goal-intent` channel. That
channel's validator is a shape allowlist requiring the verbatim machine-origin
header, and that requirement is a security control: anything able to write the
signal file (a bash redirect is enough) would otherwise be able to type
arbitrary text into the session, including asserted human consent. Relaxing it
to admit a clearing form would widen exactly the hole it exists to close.

So retraction gets its own signal file, `<session>.goal-clear`, whose PRESENCE
is the entire message. The supervisor types the fixed literal `/goal clear` and
interpolates nothing from the file. A forged `.goal-clear` can therefore do
only one thing — clear a goal — which is the safe direction: the failure mode
of a spurious clear is a lost reminder, whereas the failure mode of a forged
payload is injected instruction text.

## Tasks

### Phase 1: Establish and implement retraction

- [x] ✅ **Task 1.1**: Answered from the shipped binary — see the clearing
  contract above. `/goal clear` retracts; a bare `/goal` does not.
- [x] ✅ **Task 1.2**: `clear_goal_signal` now writes a `<session>.goal-clear`
  trigger alongside removing the sidecar, and the supervisor consumes it at the
  same idle choke point as every other family, typing the fixed literal
  `/goal clear`. It is subordinate to goal INJECTION, so a fresh goal wins and
  a clear waits a tick; in practice they are mutually exclusive because the
  daemon removes the `.goal-intent` in the same call that writes the trigger.
  `mark_goal_clear_injection` also resets the Plan 00299 thrash guard — without
  that, a plan cycling In Progress → Complete → In Progress would have its
  second, legitimate goal swallowed as a duplicate of a condition no longer set.
- [x] ✅ **Task 1.3**: `hooks-daemon clear-goal` added. It takes NO plan number
  by design: `inject-goal` requires an ACTIVE plan and would refuse in exactly
  the already-empty-ledger case this exists for — which is the case that
  stranded the v3.60.0 session.
- [x] ✅ **Task 1.4**: Regression tests on both sides. Supervisor:
  `tests/unit/supervise/test_goal_clear_signal.py` pins the upstream clearing
  token (a bare `/goal` would silently no-op), the injection, dry-run,
  consumption, staleness/foreign-session/malformed scoping, precedence under a
  competing goal, the cap, the state round-trip, and — most importantly — that
  no file content ever reaches the PTY. Daemon: the some-to-zero transition and
  the still-live boundary, plus the CLI's five cases.

## Success Criteria

- [ ] A retirement that empties the ledger leaves no condition in the `/goal`
  slot, verified live by a Stop that is not challenged.
- [ ] The three goal surfaces agree in every state, with a test per surface.
- [ ] `./scripts/qa/llm_qa.py all` passes 25/25.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00321-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- <!-- milestone or delivery commit hash -->
