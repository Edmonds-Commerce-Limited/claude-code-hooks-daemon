# Decision: how the daemon recognises an automated cron tick (Task 1.1)

Supporting document for [PLAN.md](PLAN.md) Phase 1. It records the ruling the
plan is gated on, the evidence behind it, what it costs, the best case against
it, and whether any owner-only question remains.

## The decision, in one sentence

**A prompt is an automated tick if, and only if, it matches a prompt Claude Code
itself reported in `session_crons` at the session's most recent `Stop` — every
other prompt is the human and clears the marker and cadence.** Call this
approach 4, "registry attribution". It is none of the plan's options 1, 2, 2′
or 3, and it makes 2′ unnecessary.

## Why the plan's four options all fall short of the observed case

PLAN.md's own provenance table (lines 87-91) is the key: the three crons in
this session come from three different places, and the one that actually
cleared the marker is the one whose text the daemon never writes.

| Option | What it recognises                                         | The watchdog?                                                                   |
| ------ | ---------------------------------------------------------- | ------------------------------------------------------------------------------- |
| 1      | `persistent_crons.jobs[].prompt` (`config/models.py:1800`) | No — undeclared (PLAN.md:96)                                                    |
| 2      | a daemon-authored sentinel in the prompt                   | No — its prompt is agent-composed (`background_process_tracker.py:200-204`)     |
| 2′     | 2, plus making the watchdog prompt verbatim                | Only if the agent obeys the advisory; still not a `/loop` or a `ScheduleWakeup` |
| 3      | anything that does not "look human"                        | Yes, by inverting the default — and so does any unusual human phrasing          |

Options 1, 2 and 2′ all try to enumerate the automation from the daemon's
side. That set is open: the hooks reference lists three producers of
session-scoped crons — `CronCreate`, `ScheduleWakeup` and `/loop`
(`untracked/hooks-raw.md:2535`, the fetched Claude Code hooks reference) — and
only the first is something the daemon ever influences. Option 3 enumerates
the human instead, which is the direction PLAN.md:59-62 rightly calls worse.

## The signal the options missed: Claude Code's own cron registry

Claude Code delivers, on every `Stop` and `SubagentStop`, a `session_crons`
array with one entry per live session-scoped cron: `id`, `schedule`,
`recurring`, and `prompt` (capped at 1000 characters with an in-string
`… [+N chars]` marker) — `untracked/hooks-raw.md:2515-2542`, vendored contract
`contracts/claude-code-hooks/Stop.json`. Three properties make it the right
signal here:

1. **It is positive attribution, not negative inference.** It names the
   automation directly, which is the exact move Plan 00328 made for `/model`
   (`Completed/00328-…/DETECTION-CHANNELS.md:7-26`): stop asking "was that the
   human?" and read the machine's own record of the machine's cause. A human
   reply produces no `session_crons` entry, so needs no recognition at all.
2. **It sees every provenance row, including the third.** The daemon's own
   capture of a real `Stop` payload showed "the three live crons disagreeing
   with each other" on whitespace (`utils/cron_enforcement.py:73-75`) — three
   live crons in this session is failsafe + issue-sdlc + watchdog. The
   agent-composed prompt is invisible in `src/`, but it is not invisible to
   Claude Code, and Claude Code hands it to us.
3. **The daemon already consumes and normalises it.** Plan 00416 built
   `parse_session_crons` (`utils/cron_enforcement.py:100-128`), the
   truncation-aware, layout-tolerant `_prompts_match` (`:147-165`), and a
   `Stop` handler that reads the field every turn
   (`handlers/stop/cron_stop_enforcer.py:127-131`). The new work is a
   persistence step and a lookup, not a parser.

### Timing makes the registry always current when a tick lands

A cron can only fire while the session is idle, and a session is idle only
after a `Stop`. `CronCreate` is a tool call inside a turn; that turn's `Stop`
carries the new entry. So the registry recorded at the last `Stop` is, by
construction, the set of crons that can fire next.

## The rule, precisely

On `Stop`/`SubagentStop` (a small new handler, or a branch in an existing
one — implementation detail, not a decision):

- `parse_session_crons(hook_input)` is `None` → **write nothing**. Absent is
  "no information", never "no crons" (`cron_enforcement.py:14-17`); the
  previously recorded registry stands.
- Otherwise persist the list of `(schedule, prompt)` pairs, session-scoped,
  next to the marker in the daemon's untracked dir. Same fail-open write
  discipline as `blockage_marker.write_marker`
  (`utils/blockage_marker.py:55-71`).

On `UserPromptSubmit`, replacing the literal test at
`failsafe_cron_blockage_suppressor.py:269`:

- **Recognised as automated** iff the submitted `prompt` matches a recorded
  prompt under `_prompts_match` semantics (truncation-aware prefix when the
  recorded copy was capped; whole-text equality after whitespace
  normalisation otherwise). The canonical failsafe prompt is 980 characters
  declared (`recovery_cron_advisor.py:169-183`) and re-flows on the round trip
  (`cron_enforcement.py:27-33`), so it may arrive capped — the prefix branch is
  load-bearing, not theoretical. The literal `FAILSAFE RECOVERY CHECK` test is
  kept as a belt for the canonical prompt only, so a missing registry can never
  make the failsafe tick less recognisable than it is today.
- **Recognised as automated → do NOT clear** the marker or cadence.
- **Not recognised → the human is back**: `clear_marker` and `reset_cadence`,
  exactly the branch at `failsafe_cron_blockage_suppressor.py:271-279`.

**Suppression (the DENY under a live marker) is a narrower set than
recognition.** It applies to the failsafe tick and to ticks matching a
declared `persistent_crons` job (Task 2.4's "every declared cron"). A
recognised-but-undeclared cron — the watchdog — is classified as automated (so
it stops wiping the marker) but is **not** suppressed: its job is harvesting
runaway background processes, that job is not blocked on the human, and the
idle window while awaiting a human is precisely the window it was created to
cover (`background_process_tracker.py:15-16`). Suppressing it would withdraw
the coverage it exists for.

## What must be verified in Task 2.1, not assumed

The rule assumes the tick's submitted `prompt` is the same text Claude Code
holds in `session_crons[].prompt` — both are Claude Code's copy after
`CronCreate`, so the layout drift in `cron_enforcement.py:27-33` (declared vs
delivered) should not recur between delivered-at-Stop and submitted-at-tick.
That is a property of Claude Code, not of this repository, and it is the one
thing this document cannot settle. Task 2.1's RED test must be driven by a
captured real `Stop` payload and the captured real tick prompts from the same
session, for all three crons. If a tick arrives wrapped or prefixed, the match
becomes "submitted prompt contains the recorded prompt after normalisation" —
decide from the capture. Either way the existing tests, which only ever used
the canonical prompt and a human sentence (PLAN.md:167-170), are the gap.

## What it costs, and who bears it

- **Cross-event state.** Today the handler is stateless per prompt; this adds
  a `Stop`-written registry read at `UserPromptSubmit`. Borne by daemon
  maintainers as one more session-scoped untracked file to write, read and
  reap. The owner's Plan 00298 ruling asked for minimal
  (`Completed/00298-…/PLAN.md:61-64`); this is one lookup replacing one
  literal, with the parser already in the tree. It is less machinery than a
  sentinel convention (option 2) that every future cron author must know
  about.
- **A `Stop`-time write per turn.** Negligible: `Stop` already appends to
  `stop-events.jsonl` and runs the goal ledger.
- **A human who pastes a cron prompt verbatim** is read as automation until
  their next ordinary message or the 24-hour expiry
  (`failsafe_cron_blockage_suppressor.py:106`). Bounded and self-correcting.
- **When the registry is unavailable** (no `Stop` yet, field never delivered,
  write failed), behaviour is today's: the literal test alone, over-clearing
  in a multi-cron session. The floor is never below the status quo, and the
  failure direction is the one PLAN.md:59-62 ranks as the lesser harm.

## The strongest argument against, stated fairly

"You were asked for the simplest thing, and you are proposing a registry."
Option 2′ needs no new event coupling: a sentinel constant in three prompt
authors plus one `in` test, and it covers all three crons *in this session*.
The honest reply is that 2′ covers them by asking the agent to copy text
verbatim (`recovery_cron_advisor.py:207` already asks this, and
`cron_enforcement.py:27-33` shows the agent re-flows even that), and it
cannot cover a `/loop` or a `ScheduleWakeup` at all. The registry needs no
cooperation from any prompt author, present or future, which is the property
Plan 00337 valued most ("the strongest fix is the one that needs no
cooperation from the agent", `failsafe_cron_blockage_suppressor.py:28-31`).
Simpler-to-write and simpler-to-keep-correct point in different directions
here, and this ruling picks the second.

## Does a genuine human gate remain?

**No.** Every question in Phase 1 has a defensible technical answer from the
repository:

- Which signal: the one that is positive, complete over the observed
  provenance rows, and already parsed — established above.
- Which failure direction to accept on registry failure: the status quo, which
  the plan itself ranks as the lesser harm (PLAN.md:59-62).
- Whether to suppress undeclared crons: no, because their work is not blocked
  on the human — a fact about what the watchdog does, not a preference.

The single open item — whether a tick's submitted prompt is byte-stable
against the `Stop`-delivered copy — is an empirical property of Claude Code
answered by Task 2.1's capture, not by anyone's risk appetite or any promise
to users. Task 1.1 can be marked decided on the strength of this document, and
Phase 2 can start.
