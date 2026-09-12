# Plan 00388: failsafe marker wiped by other crons in multi cron sessions

**Status**: Not Started
**Created**: 2026-09-12
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Direct

## Overview

`[awaiting-human]` exists to stop hourly failsafe-cron ticks costing a full model
turn each while a session waits on its owner. **In any session running more than
one cron it never suppresses anything**, and it fails silently — the only symptom
is ticks that keep arriving, which looks exactly like the feature not being
needed.

`FailsafeCronBlockageSuppressorHandler.matches()` returns True for ANY prompt once
a marker or cadence file exists. That is deliberate: the owner's reply has to be
able to clear both. `handle()` then decides whether that prompt WAS the owner by
a single test — `CANONICAL_CRON_PROMPT_MARKER in prompt`, where the constant is
the literal string `"FAILSAFE RECOVERY CHECK"`. Any OTHER cron's tick fails that
test, is read as "the owner is back", and calls `clear_marker()` and
`reset_cadence()`.

That was correct when written: Plan 00298 lived in a world with exactly one cron.
**Plan 00384 invalidated the assumption three plans later** by giving the daemon
`persistent_crons`, so a session now routinely carries several.

## Reproduced, not inferred

Observed live first: `[awaiting-human]` was declared in a well-formed
`STOPPING BECAUSE:` line, `untracked/human-input-blockage-marker.json` was absent
afterwards, and the next failsafe tick arrived undropped. Then reproduced against
the real handler with a temporary untracked dir
(`untracked/scratch/probe_marker_cleared_by_other_cron.py`):

```text
watchdog    matches=True  marker_survived=False
issue-sdlc  matches=True  marker_survived=False
```

Both prompts are real ticks from this session. The armed marker survives neither.

The cadence backoff (Plan 00337) rides the same branch via `reset_cadence()`, so
it is defeated identically and for the same reason.

**Worth recording rather than hiding: the `issue-sdlc` cron built in Plan 00384
is itself one of the two clearers.** The feature that exposed this bug is also a
cause of it.

## The open question — why this is Not Started

The intent is "clear when the HUMAN returns". The code asks "is this prompt not
the failsafe cron?", which is only the same question in a single-cron session.
Replacing it needs an owner call, because the two failure directions are both bad
and not symmetric:

- **Over-clearing** (today): the feature is silently inert and every tick costs a
  turn.
- **Under-clearing**: the owner returns and ticks stay suppressed or sparse until
  the marker expires — a withdrawn safety net, which is worse.

Three candidate approaches:

1. **Recognise declared crons.** The daemon already holds every
   `persistent_crons.jobs[].prompt`, so it can classify those exactly. Clean and
   truthful — but it does NOT fix the observed case, because the watchdog cron
   that bit me was created ad hoc and is not declared. A fix that leaves the
   reported symptom in place while looking complete is worse than none.
2. **A shared automation sentinel** carried by every daemon-authored tick prompt,
   clearing only on prompts that lack it. Robust for prompts the daemon writes; an
   ad-hoc cron a human or agent invents still misclassifies.
3. **Invert the default** — treat an unrecognised prompt as automated unless it
   looks human. Safest against over-clearing, most exposed to under-clearing, and
   the hardest to reason about.

None is obviously right and the control is safety-adjacent, so the issue-SDLC
runbook's own stopping rule applies: stop and ask rather than guess.

## Goals

- `[awaiting-human]` actually suppresses ticks in a session with several crons.
- The cadence backoff survives the same conditions.
- The replacement rule is pinned by tests using REAL tick prompts from more than
  one cron, not only the canonical one.

## Non-Goals

- Changing what `[awaiting-human]` means, or how it is declared.
- Removing the fail-open contract: every failure mode must still ALLOW the tick.
- Making the marker survive a genuine human reply.

## Tasks

### Phase 1: Owner decision

- [ ] ⬜ **Task 1.1**: Owner picks one of the three approaches, or names a
  fourth. Nothing below starts until then: the choice determines the test matrix,
  not merely the implementation.

### Phase 2: Fix, once decided

- [ ] ⬜ **Task 2.1**: A failing test first, driven by the real watchdog and
  `issue-sdlc` tick prompts. The existing suite only ever exercises the canonical
  prompt and an ordinary human sentence, which is exactly the gap that let this
  through.
- [ ] ⬜ **Task 2.2**: Implement the chosen rule, keeping every fail-open path.
- [ ] ⬜ **Task 2.3**: Cover the cadence half explicitly — it rides the same
  branch and would otherwise be fixed by accident rather than on purpose.

## Success Criteria

- [ ] An armed marker survives a watchdog tick and an `issue-sdlc` tick, and is
  still cleared by a genuine human prompt.
- [ ] The cadence file behaves the same way under those same three prompts.
- [ ] Every fail-open path is unchanged: no marker, wrong session, expired marker
  and missing project context all still ALLOW.
- [ ] Every release-bound consequence is in the pending-release holding area, or
  this plan records why it has none.
- [ ] Full QA passes and CI is green.

## Delivery & Milestones

- Found by dogfooding: the loop declared `[awaiting-human]`, the next tick arrived
  anyway, and checking why rather than shrugging is what surfaced it.
- Sits at the intersection of Plan 00298 (the marker), Plan 00337 (the sentinel
  and cadence) and Plan 00384 (several crons per session). None of the three is
  wrong on its own.
