# Crons as a first-class daemon concept — a proposal

Supporting document for [PLAN.md](PLAN.md). It answers a wider question than
Task 1.1 does: not just "how does the daemon recognise a tick?" but "what is a
cron, to this daemon, and who may do what to one?".

**This is a proposal, not a finding and not a ruling.** Everything labelled
RECOMMENDED is an opinion with its consequences stated. Everything labelled
MEASURED was run or read in the tree. Everything labelled INFERRED is reasoning
from a measurement, and says what would settle it.

It reconciles [PLAN.md](PLAN.md), the earlier
[fable-cron-identity-decision.md](fable-cron-identity-decision.md),
[00422 N4](../00422-niggles-ledger-fifteen/NIGGLES.md) and
[00423](../00423-per-handler-scope-main-sub/PLAN.md). Where it disagrees with
any of them it says so in [Disagreements](#disagreements-with-the-existing-framing).

## What was measured

Each row was checked against the source in this checkout, not taken from the
plan prose.

| Claim                                                                         | Verdict   | Evidence                                                                                                                                                       |
| ----------------------------------------------------------------------------- | --------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Identity is one literal substring test                                        | CONFIRMED | `failsafe_cron_blockage_suppressor.py:269`, constant at `recovery_cron_advisor.py:166`                                                                         |
| `matches()` fires on ANY prompt once marker or cadence file exists            | CONFIRMED | `failsafe_cron_blockage_suppressor.py:194-205`                                                                                                                 |
| Any non-canonical prompt clears marker AND cadence                            | CONFIRMED | `failsafe_cron_blockage_suppressor.py:271-279`                                                                                                                 |
| `UserPromptSubmit` carries no cron identity of any kind                       | CONFIRMED | `contracts/claude-code-hooks/UserPromptSubmit.json` — no `conditional_input_fields` at all                                                                     |
| `session_crons` reaches only `Stop` / `SubagentStop`                          | CONFIRMED | `Stop.json:26`, `SubagentStop.json:24`                                                                                                                         |
| Three producers feed `session_crons`: `CronCreate`, `ScheduleWakeup`, `/loop` | CONFIRMED | `Stop.json:26`                                                                                                                                                 |
| The three crons' prompts have three different provenances                     | CONFIRMED | `recovery_cron_advisor.py:207` (verbatim), `.claude/hooks-daemon.yaml` `persistent_crons` (declared), `background_process_tracker.py:200-204` (agent-composed) |
| A declared prompt re-flows on the round trip to `CronCreate`                  | CONFIRMED | `cron_enforcement.py:27-39` — 576 chars declared arrived as 580, blank lines inserted, untruncated                                                             |
| Declared `issue-sdlc` prompt is 576 characters                                | MEASURED  | parsed from `.claude/hooks-daemon.yaml`                                                                                                                        |
| Canonical failsafe prompt is 986 characters                                   | MEASURED  | parsed from `recovery_cron_advisor.py` — **14 characters of headroom under the 1000-char cap**                                                                 |
| N4: a declared cron cannot be cancelled for one session                       | CONFIRMED | `cron_stop_enforcer.py:111-135` + `models.py:1867-1876` — the only off-switches are committed config                                                           |
| `auto_continue_stop` only ever ARMS the marker, never disarms it              | CONFIRMED | `auto_continue_stop.py:52` imports `write_marker` alone; no `clear_marker` call anywhere in the file                                                           |
| `PreToolUse` carries `agent_id`, so a coordinator-only tool gate is buildable | CONFIRMED | `contracts/claude-code-hooks/PreToolUse.json` `conditional_input_fields`                                                                                       |

Two of these change the answer and neither is in the brief or in the earlier
decision document:

**The canonical prompt has 14 characters of headroom under the delivery cap,
and the one measured round trip consumed 4 on a shorter prompt.** (MEASURED for
the lengths; INFERRED for the consequence.) Any design that matches the
canonical prompt by whole-text equality is one re-flow away from silently
failing. The truncation-prefix branch at `cron_enforcement.py:163-164` is
load-bearing here, not theoretical. What would settle it: capture a real `Stop`
payload in a session running the failsafe cron and measure the delivered
length. Task 2.1 must do this.

**The marker is armed at `Stop` and disarmed only at `UserPromptSubmit`.** That
asymmetry is the sole reason the identity question exists. It is not forced by
anything; it is an unbuilt lever, and it makes a fifth option available that
none of the plan's candidates considered — see "Option 5 — never ask the
question" under Q1.

## The reframe: this is three questions, not one

The current code answers all three with one boolean — `is_cron_prompt` — and
that conflation is the defect underneath the reported symptom. They have
different subjects, different evidence and different safe-failure directions.

| #   | Question                         | Subject     | Consequence of "yes"   | Must fail toward   |
| --- | -------------------------------- | ----------- | ---------------------- | ------------------ |
| Q1  | Is this prompt a human?          | the prompt  | clear marker + cadence | **human** (clear)  |
| Q2  | Should this tick be delivered?   | the job     | ALLOW the tick         | **deliver**        |
| Q3  | Should this job exist right now? | the session | let the Stop through   | **allow the stop** |

All three fail directions point the same way: toward full coverage, toward
spending a turn rather than withholding one. That is the asymmetry the brief
calls load-bearing, and it is worth naming what it implies about today's bug.

**Today's behaviour is a precision bug in the SAFE direction, not a safety
bug.** Over-clearing wastes turns — which is exactly the cost the feature was
built to avoid, so the feature is inert — but nothing is left unprotected. The
risk budget for any fix follows directly: a change may improve precision, but
it must not move the failure direction. Concretely, that means **recognition of
automation must be positive evidence, and absence of evidence must resolve to
"human"**. Any design that infers automation from the ABSENCE of human-looking
features (PLAN.md's approach 3) inverts this and should be rejected on that
ground alone, independent of how well it performs.

## The concept: a cron record

"First-class" here means one thing: **the daemon holds a uniform record per
cron, instead of three incompatible half-representations.** Today the failsafe
cron's identity is a hardcoded constant inside a `PostToolUse` advisory, the
`issue-sdlc` cron's is a YAML block read by two Stop handlers, and the
watchdog's exists nowhere in `src/` at all. Nothing can ask a general question
about "the crons" because there is no such set.

A cron record carries three groups of fields, sourced from up to three places:

```text
identity   id, schedule, prompt            <- config, daemon built-in, or session_crons
provenance declared | built-in | observed  <- which source supplied it
policy     stand_down, enforce, deletable  <- config, or a built-in default
```

Records are assembled from three sources, which explains the provenance table
in PLAN.md rather than working around it:

- **built-in** — the failsafe cron. Its prompt is authored in `src/`, so the
  daemon already holds its identity; it just does not hold it in the same shape
  as the others.
- **declared** — `persistent_crons.jobs[]`. Already a record; add policy fields.
- **observed** — anything in `session_crons` that matches neither. The watchdog,
  a `/loop`, a `ScheduleWakeup`. The daemon learns these exist without knowing
  what they are for, which is the honest state and should be representable.

**What I am NOT proposing.** No scheduler, no cron DSL, no daemon-side
execution, no new event, no change to how `[awaiting-human]` is declared. The
daemon cannot run a cron — Claude Code does — and this proposal does not try to
change that. The concrete build is one state file, one new verb, three config
fields and one `PreToolUse` gate, three of which reuse primitives already
shipped (`blockage_marker`'s write discipline, `cron_cadence`'s capped backoff,
`cron_enforcement`'s matcher).

## Q1 — what makes a tick identifiable as automated?

### The options, and what each actually covers

Coverage assessed against the four producers that exist: the built-in failsafe
cron, a declared job, an agent-composed `CronCreate`, and `/loop` /
`ScheduleWakeup`.

| Option                              | Failsafe | Declared | Agent-composed | `/loop` | Needs cooperation from |
| ----------------------------------- | -------- | -------- | -------------- | ------- | ---------------------- |
| 1 Recognise declared crons          | via belt | yes      | no             | no      | nobody                 |
| 2 Shared sentinel in authored text  | yes      | yes      | no             | no      | every prompt author    |
| 2′ 2, plus watchdog prompt verbatim | yes      | yes      | if obeyed      | no      | every agent, each time |
| 3 Invert the default                | yes      | yes      | yes            | yes     | nobody — but see below |
| 4 Registry attribution              | yes      | yes      | yes            | yes     | nobody                 |
| 5 Never ask the question            | n/a      | n/a      | n/a            | n/a     | nobody                 |

**Option 3 is disqualified by the asymmetry, not by its coverage.** It is the
only option that resolves an unknown prompt to "automated", which is the
under-clearing direction — the withdrawn safety net the brief ranks as strictly
worse. Its full coverage is bought with exactly the property the design must
not have.

**Option 2′ does not survive scrutiny, but not for the reason the earlier
document gives.** That document argues re-flow defeats it, citing
`cron_enforcement.py:27-39`. That argument is wrong: re-flow rewrites layout,
and a short substring sentinel survives layout changes — which is precisely why
`FAILSAFE RECOVERY CHECK` works today despite the re-flow. The real objections
are coverage and cooperation. 2′ cannot reach a `/loop` or a `ScheduleWakeup` at
all, because the daemon never authors those prompts; and for the watchdog it
asks an agent to copy text faithfully, which is a request this repository has
already measured going unfulfilled in a neighbouring case. A guard whose
correctness depends on an agent following an advisory is a guard that degrades
silently when the advisory is skimmed.

**Option 2 is still worth something as a belt.** It costs one constant and one
`in` test, and it covers the case where `session_crons` was never delivered at
any Stop this session. It should not be the primary mechanism, but discarding it
entirely gives up cheap redundancy.

### Option 5 — never ask the question

This one is not in PLAN.md and follows from the measurement that
`auto_continue_stop` never disarms the marker.

Move the clearing decision from `UserPromptSubmit` to `Stop`. The marker is
armed by a Stop that declares `[awaiting-human]`; disarm it on any Stop that
does **not**. "The human came back" then needs no prompt classification at all,
because a human's return is observable as a turn of work ending in a stop that
makes no blockage declaration.

It holds up better than it first looks. A suppressed tick produces no turn and
therefore no Stop, so it cannot disarm anything. An ALLOWED tick that found work
and did it ends in a non-blocked Stop and disarms — which is correct, since the
session was not blocked after all. A tick that correctly no-ops ends in a Stop
that re-declares, and the marker stays armed — also correct.

Two costs, both real:

- **One turn of latency.** The marker stays armed from the human's message until
  that turn's Stop. Harmless in practice: a cron cannot fire while the session is
  busy. (INFERRED from "a cron fires only while the REPL is idle" — stated in
  `failsafe_cron_blockage_suppressor.py:4-5`, not independently measured here.)
- **Under-clearing on the error path.** A turn that dies before `Stop` leaves the
  marker armed. Bounded by the 24-hour expiry, but this is the wrong direction
  and it is the one path in the whole proposal that fails unsafe.

It also does not answer Q2 at all — knowing when the human returned tells you
nothing about which ticks to stand down. So it is a genuine alternative for Q1
and a non-answer for the rest of the design.

### RECOMMENDED: option 4 as the mechanism, option 2 as a belt

Record the session's crons from `session_crons` at each `Stop`, session-scoped,
in the daemon's untracked directory. At `UserPromptSubmit`, a prompt is
automated if and only if it matches a recorded prompt under the existing
`_prompts_match` semantics; anything else is the human and clears.

Three reasons, in order of weight:

1. **It is positive attribution and therefore preserves the safe failure
   direction by construction.** A human reply produces no `session_crons` entry
   and so needs no recognition; every unknown resolves to "human". This is the
   property option 3 cannot have and option 1 has only partially.
2. **It needs cooperation from nobody** — no prompt author, present or future.
   `failsafe_cron_blockage_suppressor.py:28-31` already records that the project
   values this property most.
3. **The parser exists.** `parse_session_crons`, `_prompts_match` and the
   truncation handling all shipped in Plan 00416. The new work is a persist step
   and a lookup.

Keep the `FAILSAFE RECOVERY CHECK` literal as a belt for the canonical prompt
only, so a registry that is missing for any reason can never make the failsafe
tick less recognisable than it is today. That is option 2 at its cheapest.

Option 5 should be considered on its own merits as an ADDITION, not an
alternative: disarming at a non-blocked Stop closes the case where the human
returns and the session works for a long while without the registry being
consulted. It is independently useful and independently rulable.

### Open, and only Task 2.1 can close it

The rule assumes the prompt submitted at tick time is the same text Claude Code
reported in `session_crons`. Both are Claude Code's own copy, so they should
agree — but that is a property of Claude Code, not of this repository, and it
is unverified here. The RED test must be driven by a captured real `Stop`
payload and the captured real tick prompts from the same session, for all
three crons. If a tick arrives wrapped or prefixed, the match becomes
"submitted prompt contains the recorded prompt after normalisation". The
existing suite, which only ever exercises the canonical prompt and an ordinary
human sentence, is exactly the gap that let this through.

## Q2 — how should "blocked on a human" interact with crons generally?

The brief states the distinction correctly and it should be built into the
design rather than left as prose: **a session that cannot act** and **a job with
nothing to do** are different facts with different remedies.

| Fact                       | Whose property | Evidence available to the daemon    | Correct remedy          |
| -------------------------- | -------------- | ----------------------------------- | ----------------------- |
| The session cannot act     | the session    | `[awaiting-human]` marker           | hard suppress, expiring |
| This job has nothing to do | the job        | none today — the daemon cannot know | capped backoff          |

### Not every cron should stand down on `[awaiting-human]`

The watchdog is the counter-example and it is decisive. Its job is harvesting
runaway background processes (`background_process_tracker.py:15-16`), that job
is not blocked on the human, and the idle window while awaiting a human is
precisely the window it was created to cover. Suppressing it would withdraw the
coverage it exists for. So a blanket "an armed marker suppresses every
recognised cron" is wrong.

RECOMMENDED: **stand-down is a per-job declared policy, defaulting to off.**

```yaml
persistent_crons:
  jobs:
    - id: issue-sdlc
      stand_down: never            # never | when_session_blocked
```

The failsafe cron's built-in record carries `when_session_blocked`, which is
its behaviour today, now expressed as a record field rather than as the shape
of an `if`. An observed cron — one the daemon only knows from `session_crons` —
gets `never`, because the daemon does not know what it is for and withholding
an unknown job's ticks is a decision it has no basis to make.

### The `issue-sdlc` case should NOT be solved with the marker

This is a disagreement with PLAN.md Task 2.4, which says to apply the chosen
rule so that an `[awaiting-human]` marker stands the `issue-sdlc` tick down too.
The problem it targets is real and well evidenced — seven open issues, all
`agent-needs-human`, unchanged across two consecutive ticks. The mechanism is
the wrong one.

A marker-driven DENY is a hard off-switch that persists until a human returns or
the marker expires. For the failsafe cron that is justified, because the marker
means precisely "there is nothing to recover". For `issue-sdlc` the equivalent
claim is not true: the backlog can change without a prompt arriving in this
session — someone comments on an issue, CI turns a label over, another session
merges something. A hard off-switch there produces the failure PLAN.md Task 2.5
itself names: a permanently stood-down issue loop is a backlog nobody is
working, which is worse than an hourly no-op.

RECOMMENDED: give `issue-sdlc` a **per-job capped backoff**, reusing
`cron_cadence` exactly as the failsafe cron already does — hourly, then 2, then
4, and no sparser. The signal is a tick reporting its own no-op, declared the
same way `[awaiting-human]` is declared, in the `STOPPING BECAUSE:` line:

```text
STOPPING BECAUSE: [cron-noop:issue-sdlc] every open issue carries agent-needs-human.
```

A real human prompt resets every job's cadence to hourly, which is one clearing
concept rather than two. The cost of a wrong `[cron-noop:...]` declaration is
capped at a thinner cadence, never silence — so the mechanism cannot produce the
unworked-backlog failure even when the agent's self-report is wrong. That
containment is the reason to prefer it over the marker.

This requires the per-job cadence file to be keyed by job id rather than being
one global file. That is a small generalisation of shipped code, and it has a
consequence worth stating: the existing global cadence file's semantics change,
so the migration must treat an old-format file as absent rather than
mis-parsing it — which the fail-open contract below already requires.

## Q3 — how is a session-scoped pause expressed? (N4)

N4 reports two moves that each fail the other's test: obeying an instruction to
cancel a declared cron fails the stop gate; satisfying the stop gate disobeys
the instruction. It files this under a class of "a gate judging a state
correctly, in a workflow where that state is a legitimate temporary".

The reading I would offer instead: **the conflict exists only because "cancel"
was implemented as `CronDelete`.** Those are different acts, and the first-class
framing is what makes the difference expressible.

The owner's intent in "cancel it for now" is *no more ticks reaching the model*.
`CronDelete` is one way to achieve that and the most destructive one — it
destroys the session's only copy of a job that cannot be persisted, which is why
the enforcer objects. But the daemon can already drop a tick before the model
sees it; that is exactly what `failsafe_cron_blockage_suppressor` does, and it is
genuinely zero-token, not merely cheaper.

So a paused cron is one that still EXISTS and whose ticks are dropped:

- the owner's instruction is honoured — no tick costs a turn;
- `cron_stop_enforcer` is satisfied — the declared job is present in
  `session_crons`, so it never blocks the stop;
- **the enforcer keeps every tooth it has.** Nothing is relaxed, no check moves,
  no authority is handed to the session over a guard the project declared. This
  matters because N4 flags remedy (1) as owner-gated on exactly that ground —
  and pause-as-suppression is not that remedy. The enforcer is never consulted
  about a pause and never overridden by one;
- it is session-scoped and expiring, so the next session re-creates and resumes
  the job with no config edit and nothing to remember to undo.

RECOMMENDED: **add `pause` as a verb, implemented as suppression, and never as
deletion.** Spelled as a marker in the daemon's untracked directory,
session-scoped and expiring, written the same way the blockage marker is.

| Verb    | What it does               | Blast radius                | Reversal                                    |
| ------- | -------------------------- | --------------------------- | ------------------------------------------- |
| pause   | drop this job's ticks      | one session, expiring       | resume, a human prompt, expiry, new session |
| disable | `jobs[].enabled: false`    | every session, every branch | a commit                                    |
| delete  | remove from session memory | this session, irreversible  | re-create by hand                           |

N4's own remedy (2) — making the enforcer's deny text name the config knob —
remains worth doing regardless, and becomes more useful once there is something
better to name than "edit committed config": the deny text should say that a
session-scoped pause exists and how to spell it.

The three-sighting class N4 identifies is not dissolved by this. It is one
instance resolved by giving the workflow a move it was missing, which is a
different remedy from 00419 N3's (move the check to where the state settles) and
does not generalise to the other two sightings. Worth recording as a second
remedy shape for that class, not as a fix for it.

## Q4 — who may create, pause and delete a cron?

Coordinator-only deletion is approved (00423 Task 1.3, RULED) and is a
tightening. Nothing below weakens it; the pause verb exists so that the
tightening does not make an ordinary intent unreachable.

| Verb              | Who                   | Enforced where                                     | Failure direction     |
| ----------------- | --------------------- | -------------------------------------------------- | --------------------- |
| create            | anyone                | advisory only — reconcile against `CronList` first | allow                 |
| pause / resume    | anyone in the session | nothing to enforce — it is reversible and expiring | allow                 |
| delete (failsafe) | coordinator only      | `PreToolUse` on `CronDelete`                       | **allow** (see below) |
| disable           | a human, via a commit | already — it is committed config                   | n/a                   |

**Deletion is enforceable, and this is a measurement worth recording for
00423 Task 3.2**: `PreToolUse` carries `agent_id` as a conditional input field
(`contracts/claude-code-hooks/PreToolUse.json`), and `agent_id` is absent on the
main thread and present inside a subagent — the same discriminator 00423 Task
2.1 is dogfooding at `Stop`/`SubagentStop`. A `PreToolUse` gate on `CronDelete`
is therefore buildable without any new signal. It is subject to 00423's binding
condition: measure the discrimination at `PreToolUse` before building on it,
rather than assuming it transfers from the Stop measurement.

The fail direction for that gate needs care, because it is the one place in this
proposal where fail-open and safety point in opposite directions. If `agent_id`
is absent, the caller is either the coordinator (allowed) or a subagent whose
payload omitted the field (must be denied). RECOMMENDED: **fail open — allow the
delete, and emit an advisory recording that the scope could not be
determined.** Rationale: the harm being prevented is a subagent deleting a
shared recovery cron, which is recoverable by re-creating it; the harm of a
false deny is a coordinator unable to clean up its own session, which the guard
has no way to distinguish from the attack it is defending against. This is a
judgement call and the opposite ruling is defensible; it is flagged here rather
than buried because it is a permissions decision on a safety control.

## Q5 — the fail-open contract, stated per path

The existing rule — a failure must always ALLOW the tick — **still holds, and
nothing below relaxes it.** Every DENY remains a positive assertion made only
when every condition is individually verified.

| Failure path                               | Resolves to                             | Net effect                           |
| ------------------------------------------ | --------------------------------------- | ------------------------------------ |
| Registry file missing                      | no recognition → prompt reads as human  | clear + ALLOW — today's behaviour    |
| Registry file corrupt or unreadable        | as above                                | clear + ALLOW                        |
| Registry belongs to another session        | ignored                                 | clear + ALLOW                        |
| `session_crons` absent at `Stop`           | write nothing; previous registry stands | never read as "no crons"             |
| `session_crons` present but empty          | registry rewritten empty                | nothing recognised → ALLOW           |
| Pause marker missing / corrupt / expired   | no pause                                | ALLOW                                |
| Pause marker for another session           | ignored                                 | ALLOW                                |
| Cadence file in the old global format      | treated as absent                       | hourly — the most generous state     |
| Config unloadable                          | no declared jobs                        | enforcer silent; canonical belt only |
| `ProjectContext` unresolvable              | handler returns early                   | ALLOW                                |
| Any unanticipated exception in the handler | outer guard                             | ALLOW                                |
| `agent_id` absent at `CronDelete`          | scope undetermined                      | ALLOW + advisory (see Q4)            |

Two properties are worth stating explicitly because they are easy to lose in a
later refactor:

**Fail-open means two different actions here, and they point the same way.** For
Q1 it means *clear* (the more generous act — it restores ticks). For Q2 and Q3
it means *deliver*. Both restore full coverage, so there is no path where one
failure mode's safe default is another's unsafe one.

**The floor is never below the status quo.** Every degraded path lands on
today's behaviour — the literal test alone, over-clearing in a multi-cron
session — which PLAN.md:59-62 ranks as the lesser harm. A design whose worst
case is the current behaviour cannot make things worse than not shipping.

## How this fails safe

The brief asks for this directly, so it is stated as a closed list rather than
left implicit.

**Over-clearing** (wasted turns) is possible in every degraded path above, by
construction, and that is the intended direction.

**Under-clearing** (withdrawn safety net) has exactly three exposures in this
design, and each is bounded:

1. **A human pastes a cron prompt verbatim.** Read as automation until their
   next ordinary message, or the 24-hour expiry. Self-correcting, and the
   registry contains only prompts of crons that actually exist, so the surface
   is small.
2. **A stale registry entry for a deleted cron.** Mitigated by rewriting the
   registry wholesale on every `Stop` that carries the field, never merging —
   so a deletion propagates at the next `Stop`. State this in the
   implementation; a merge would make the exposure unbounded.
3. **Option 5's error path**, if option 5 is adopted: a turn that dies before
   `Stop` leaves the marker armed. Bounded by expiry only. This is the single
   strongest argument for treating option 5 as a separate ruling rather than
   folding it in.

Nothing else can withhold a tick. Suppression requires a live, session-matched,
unexpired marker plus a job whose declared policy says to stand down; backoff is
capped and never reaches silence; pause is session-scoped and expiring.

## Disagreements with the existing framing

Recorded because the brief asks for them explicitly, and because agreeing with a
framing that is wrong is the expensive failure here.

1. **The premise that crons should become more first-class holds, but for a
   narrower reason than "we are doing more with crons now."** The evidence
   supports unifying two things only — identity and lifecycle — because both are
   currently represented three incompatible ways and neither can be reasoned
   about as a set. It does not support a general cron subsystem, and the
   proposal above deliberately stops there.

2. **The earlier decision document's case against 2′ is not sound as written.**
   It cites re-flow, but re-flow does not defeat a substring sentinel — as
   `FAILSAFE RECOVERY CHECK` demonstrates daily. 2′ fails on coverage and on
   requiring agent cooperation. The conclusion it reaches is right; one of its
   reasons is not, and a later reader relying on that reason would draw the wrong
   lesson about what re-flow breaks.

3. **The earlier document states the canonical prompt is 980 characters.** It is
   986 (MEASURED). The difference is immaterial to its argument and material to
   the test matrix, since it halves the apparent headroom under the 1000-char cap.

4. **PLAN.md Task 2.4 names the wrong mechanism for a real problem.** Applying
   the marker to `issue-sdlc` buys the failure Task 2.5 warns against. A capped
   per-job backoff gets the same saving with a bounded worst case. This is the
   proposal's most substantive departure from the plan as written.

5. **The earlier document's claim that no genuine human gate remains is too
   strong.** It is defensible for Q1 alone. Q3's pause verb hands a session a new
   way to stop work the project declared; Q4's fail-open ruling on `CronDelete`
   is a permissions decision on a safety control; and Q2 changes what a declared
   cron's stand-down means. Those are owner decisions on the same grounds 00423
   Task 1.3 was recorded as one, not technical questions with a right answer in
   the repository.

## The decision sheet

Five separable rulings. Each can be taken on its own; none silently depends on
another except where noted.

| #   | Question                          | Options                                               | RECOMMENDED                              |
| --- | --------------------------------- | ----------------------------------------------------- | ---------------------------------------- |
| D1  | Tick identity                     | 1 / 2 / 2′ / 3 / 4 / 5                                | 4 (registry) + 2 as a belt               |
| D2  | Disarm at a non-blocked `Stop`?   | yes / no                                              | yes, as a separate addition to D1        |
| D3  | `issue-sdlc` stand-down mechanism | marker suppression / capped per-job backoff / neither | capped backoff, declared per job         |
| D4  | A session-scoped `pause` verb     | build it / deny text only / nothing                   | build it, as suppression, never deletion |
| D5  | `CronDelete` gate fail direction  | fail open + advisory / fail closed                    | fail open + advisory                     |

D3 depends on D1 only in that a backoff for `issue-sdlc` needs its tick to be
recognisable; D1 option 4 supplies that. D4 is fully independent of the others
and resolves N4 on its own. D2 is independent and is the only item that touches
`auto_continue_stop`.
