# Plan 00388: failsafe marker wiped by other crons in multi cron sessions

**Status**: Complete
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

### Checked since: where each cron's prompt actually comes from

The three approaches were assessed against an assumption about provenance that
turns out to be wrong in a way that changes the answer. The three crons in this
session do NOT fall into two groups, but three:

| Cron                | Where its prompt text comes from                                                                                                                                                       |
| ------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| failsafe recovery   | **Daemon-authored verbatim** — `recovery_cron_advisor` prints it under "Paste the following text verbatim as the cron prompt"                                                          |
| issue-sdlc          | **Declared in config** — `persistent_crons.jobs[].prompt` in `.claude/hooks-daemon.yaml`                                                                                               |
| background watchdog | **Agent-composed** — `background_process_tracker` describes what the cron should DO and leaves the wording to the agent, which is why no copy of that prompt exists anywhere in `src/` |

That third row is the whole difficulty, and it is the cron that actually cleared
the marker. It also means:

- **Approach 1 covers issue-sdlc only.** Confirmed, as the plan already said.
- **Approach 2 covers failsafe and issue-sdlc, but not the watchdog** — the
  daemon never writes that prompt, so it cannot put a sentinel in it.

**This suggests an approach 2′ the original three did not include**: have
`background_process_tracker` supply its cron prompt VERBATIM, exactly as
`recovery_cron_advisor` already does for the failsafe. Then every cron the
daemon causes to exist carries daemon-authored text, and the sentinel in
approach 2 covers all of them — the remaining gap shrinks to a cron someone
invents with no daemon involvement at all, which is a much smaller and more
honest exposure than "an ad-hoc cron".

Recorded as an option, not a ruling. It is offered because it removes a
constraint the original framing treated as fixed, not to pre-empt the owner's
choice.

**Decided (unattended, 2026-09-24)**: approach 2′. Every daemon-authored tick
prompt carries a sentinel and `background_process_tracker` supplies its watchdog
prompt verbatim, so a tick can never be mistaken for the human; it is the only
option that covers the cron that actually wiped the marker. Assumption: the
owner's 'no known defects' instruction; the owner can reverse this with one
message.

**As built.** The sentinel is one bracketed token on the prompt's first line:
`[tick:failsafe]`, `[tick:watchdog]`, or `[tick:job:<id>]` for a declared job
(`utils/cron_tick.py`). The provenance table above now reads differently:
the watchdog prompt is daemon-authored verbatim, and a declared job's prompt is
rendered with its sentinel by `persistent_cron_assertor` and by the
`cron_stop_enforcer` block message. The remaining gap is a cron the daemon
never supplied the text for: an agent-composed prompt, a `/loop`, a
`ScheduleWakeup`, or a cron created before this change. Those still read as the
human, which is the over-clearing direction. `cron_enforcement` strips sentinels
before matching, so a pre-sentinel cron still satisfies its declaration.

## A second consumer arrived — the ruling question is UNCHANGED

Plan 00392 N1 graduated into this plan rather than becoming a third one. The
finding: the `issue-sdlc` cron has no stand-down mechanism at all, so a backlog
where every open issue is parked on a human costs a full model turn every hour,
indefinitely. Observed with all seven open issues carrying `agent-needs-human`,
so all three of the runbook's selection rules miss.

**Confirmed a second time, an hour later, on an identical label set** (#14, #22,
#23, #24, #31, #32, #33 — every one `agent-needs-human`, none `agent-working`,
none unlabelled). That matters for the ruling: a single observation could be a
momentary state, but an unchanged backlog across two consecutive ticks shows the
cost is standing rather than transient, and it recurs every hour until a human
acts. The tick itself is behaving correctly each time — it is a successful tick
by the runbook — which is precisely why nothing surfaces the accumulating cost.

**It is the same mechanism, not merely a similar one.** Suppressing that cron
with the existing `[awaiting-human]` marker needs the handler to recognise the
issue-sdlc tick as automated — which is exactly the question this plan is
blocked on. And it could not work before this plan's fix anyway, because the
marker is wiped by that very cron. Neither can ship usefully without the other:

- Fix this plan alone, and the marker survives but still suppresses only the
  failsafe cron — the issue cron keeps burning a turn an hour.
- Fix N1 alone, and the marker it depends on is cleared before it can be read.

**What this does NOT change is the decision in front of the owner.** The
question is still "how does the handler tell a human prompt from an automated
tick?", and the candidate approaches are unchanged. What is added is a second
CONSUMER of whatever answer is chosen, so one ruling covers both crons instead
of this resurfacing as a separate decision later.

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

- [x] ✅ **Task 1.1**: Owner picks one of the three approaches, approach 2′, or
  names another. Decided: approach 2′ (see the ruling above).

### Phase 2: Fix, once decided

- [x] ✅ **Task 2.1**: A failing test first, driven by the real watchdog and
  `issue-sdlc` tick prompts. The existing suite only ever exercises the canonical
  prompt and an ordinary human sentence, which is exactly the gap that let this
  through. `test_failsafe_cron_multi_cron_ticks.py` holds prompts lifted from
  this repository's session transcripts.
- [x] ✅ **Task 2.2**: Implement the chosen rule, keeping every fail-open path.
- [x] ✅ **Task 2.3**: Cover the cadence half explicitly — it rides the same
  branch and would otherwise be fixed by accident rather than on purpose.
- [x] ✅ **Task 2.4**: Apply the chosen rule to EVERY declared cron, not just
  the failsafe one, so an `[awaiting-human]` marker stands the `issue-sdlc` tick
  down too (Plan 00392 N1, graduated here). A declared job's tick is dropped
  under a live marker (`R-DECLARED-CRON-SUPPRESSED`), and the issue-sdlc runbook
  now tells a tick whose backlog is entirely `agent-needs-human` to stop with
  `[awaiting-human]`, which is what arms the marker.
- [x] ✅ **Task 2.5**: Pin that a suppressed `issue-sdlc` tick still resumes on
  a genuine human prompt. The failure to avoid is inverted here: a permanently
  stood-down issue loop is a backlog nobody is working, which is worse than an
  hourly no-op.

## Success Criteria

- [x] An armed marker survives a watchdog tick and an `issue-sdlc` tick, and is
  still cleared by a genuine human prompt. Holds for ticks whose prompt the
  daemon supplied; a pre-existing agent-composed watchdog prompt still clears,
  pinned as the known residual.
- [x] The cadence file behaves the same way under those same three prompts.
- [x] An armed marker stands the `issue-sdlc` tick down as well as the failsafe
  one, and BOTH resume on a genuine human prompt.
- [x] Every fail-open path is unchanged: no marker, wrong session, expired marker
  and missing project context all still ALLOW.
- [x] Every release-bound consequence is in the pending-release holding area, or
  this plan records why it has none. Release note 29, a truth-change entry.
- [x] Full QA passes and CI is green. CI green on main's HEAD `34c588dc`
  (run 36066507383), which includes this plan's delivered code (landed with
  integration batch B2).

## Delivery & Milestones

- Found by dogfooding: the loop declared `[awaiting-human]`, the next tick arrived
  anyway, and checking why rather than shrugging is what surfaced it.
- Sits at the intersection of Plan 00298 (the marker), Plan 00337 (the sentinel
  and cadence) and Plan 00384 (several crons per session). None of the three is
  wrong on its own.
- **Two residuals, accepted rather than fixed, stated plainly in the delivery
  report**: a cron that already existed before this landed keeps its
  old (sentinel-free) prompt until the session that re-creates it; and the
  canonical prompt still says to remove the failsafe cron once the session is
  genuinely finished, which Plan 00394's non-goal forbids rewording. Neither
  is closed by this plan or by anything else in integration batch B2. See the
  [delivery report](subagent-reports/260924-d-cron-opus-5-5.md#residual-risks-stated-plainly).
