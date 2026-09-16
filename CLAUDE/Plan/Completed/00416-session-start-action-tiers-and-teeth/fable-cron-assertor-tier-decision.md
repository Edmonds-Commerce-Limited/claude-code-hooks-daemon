# Decision: `persistent_cron_assertor` and the computed tier

Supporting document for Plan 00416 Task 2.1, the struck-through task that ends
"Owner-gated between the two". Decision only — nothing here was implemented.

## The ruling

**DECISION: endorse the plan's own recommendation — `persistent_cron_assertor`
stays OUT of the computed `ACTION_REQUIRED` tier, and the `Stop` block
(`cron_stop_enforcer` / `cron_subagent_stop_enforcer`) carries enforcement
alone. Endorsing it IS the decision; there is no third option to invent.**

The plan's argument holds. It also understates its own case: the reason is not
"a SessionStart-checkable signal probably does not exist" (PLAN.md:136-138),
which leaves a door open to go searching. The reason is that the tier
mechanism as built cannot compute a per-session fact at all, so no signal —
found or not — could make the verifier correct. That is the answer to the
brief's sharper question: a verifier is **impossible within the mechanism**,
not merely absent from it. "Merely absent" would require redesigning the
mechanism, which is a different plan.

## Evidence

### The plan's factual claims, checked by reading

- `find_missing_crons([job], [])` returns `[job]` — by construction:
  `utils/cron_enforcement.py:194-207` is a list comprehension over declared
  jobs filtered by `cron_is_asserted`, which is `any(...)` over an empty list
  and therefore False for every job.
- `matches()` fires whenever any job is declared:
  `handlers/session_start/persistent_cron_assertor.py:98-100`. This repo
  declares one (`issue-sdlc`, `.claude/hooks-daemon.yaml:1118-1121`), so the
  verifier would be failing in every session here, without exception.
- `session_crons` is not delivered to SessionStart:
  `contracts/claude-code-hooks/SessionStart.json` carries no cron field in
  either `input_example` or `notes`; the vendored upstream text names the
  field for `Stop` (`untracked/hooks-raw.md:2515`) and `SubagentStop`
  (`hooks-raw.md:2372`) only.

### Why no verifier can be correct — the categorical mismatch

The tier is computed in two places, and neither has a session to ask about:

1. **The verifier takes no payload.** `core/session_start_tiers.py:101` —
   `verify_still_needed(self) -> bool`; `compute_tier(handler)` at
   `session_start_tiers.py:145-177` calls it with nothing but the handler
   instance. It cannot see `session_id`, `source` or anything else from the
   SessionStart event.
2. **The collector instantiates handlers cold.**
   `utils/session_action_items.py:104-126` walks the registry, constructs each
   SessionStart handler with no hook input, and asks `compute_tier`. Both
   consumers use it: the CLI (`daemon/cli.py:7348-7356`, which resolves a
   project root and nothing session-shaped) and the supervisor directive
   (`handlers/session_start/session_actions_directive.py:154`).

Cron presence is a **per-session** fact (crons live in session memory —
`persistent_cron_assertor.py:3-7`). The tier system asks a **per-project**
question ("what does this project require right now?"). The plan's Task 2.3
made agreement between the two consumers load-bearing: "a directive that fired
while that command reported nothing would teach the agent to ignore the next
one" (PLAN.md:196-198), and a test pins that the CLI has no collector of its
own (JOURNAL 15 Sep, Task 2.3 entry). So even a perfect session-start signal
would produce a tier the CLI cannot reproduce, breaking the invariant the
mechanism was built on.

### The signals that DO exist, and why each fails the admission test

The plan's admission test is PLAN.md:45-48: something on disk or in a hook
payload must distinguish "done" from "not done".

- **`source: startup` on the SessionStart payload** (SessionStart.json:28).
  On a fresh start crons certainly do not exist, so "not done" would be TRUE,
  not a guess. But the verifier cannot see the payload (point 1), the CLI
  never has one (point 2), and on `resume`/`compact`/`fork` the fact is
  unknown. It also stays "not done" after the agent complies, because nothing
  at SessionStart observes the `CronCreate` — the tag would be true for one
  instant and false for the rest of the session.
- **The daemon sees cron tool calls.** `CronCreate`, `CronList` and
  `CronDelete` arrive as `PreToolUse` (the real session's record shows
  CronList 12, CronCreate 1, CronDelete 1), so an event ledger keyed by
  `session_id` is buildable. Three things sink it: `DESIGN-cron-enforcement.md:69-72`
  already rejected event-over-state for the Stop check ("State beats event"),
  and the reasons — a cron created before the daemon started, deleted after,
  or created by `/loop`, which is not a tool call the hook sees — apply at
  least as hard here; the CLI has no `session_id` to look the ledger up by;
  and it would be a second, weaker source of truth beside the `Stop` payload
  the daemon is already handed.
- **The last Stop's `session_crons`** (the daemon logs Stop events). A
  previous session's crons say nothing about this one; crons do not persist
  across sessions, which is the whole reason the assertor exists.

None distinguishes done from not-done at the points where the tier is
computed. The admission test fails, so the honest tier is the one computed
today: `INFO` from a handler with no verifier.

### Why an always-failing verifier is the wrong shape even though it is "true"

On a fresh startup `ACTION_REQUIRED` would be truthful. It stops being truthful
the moment the cron is created, and the tier has no way to notice — so
`session-actions` would list the cron after the agent had complied, the
directive would fire on every start regardless of state, and the tier that
"is always at its maximum carries no information" (PLAN.md:129-131). The plan
is right that this is the flat-noise failure re-introduced one word louder.

## What it costs, and who bears it

- **Cron creation is enforced at the first `Stop`, not at session start.** The
  assertor's advisory is `INFO`, which the owner's own observation says is
  read as background; the teeth (`cron_stop_enforcer.py:115-135`) bite when the
  first turn ends. For a long first turn the hourly `issue-sdlc` tick
  (`23 * * * *`) is late by up to that turn's length. The owner's automated
  pipeline in this repository bears it. `DESIGN-cron-enforcement.md:45-46`
  already accepted this: "the cron only has to exist before the session ends".
- **A session killed before its first Stop never creates the cron.** The
  supervisor backstop covers this by design (`DESIGN-cron-enforcement.md:61-66`);
  it is the case the daemon cannot see and was never going to.
- **Nothing else.** The Stop block is shipped, tested
  (`TestADeclaredCronAbsentFromSessionCronsBlocks`,
  `TestAbsentSessionCronsNeverBlocks`) and observed live; option one adds no
  code and removes no protection.

## The strongest argument against, stated fairly

The owner proved that a session-START directive works — one typed line and the
agent ran `CronList`, created the job and confirmed it
(`DESIGN-cron-enforcement.md:92-104`) — and ruled that "the system MUST have
teeth". Option one takes the cron case out of the only session-start channel
that reaches the agent as a turn, and defers it to `Stop`. If every other
verifier is passing (the normal case here — `session-actions` is empty on a
healthy session, PLAN.md:167-169), the directive never fires and the cron is
created only when the Stop block forces it. That is later than the owner's
experiment achieved, and it is a real regression in *timing* relative to what
a nudge could do.

The rebuttal is that the directive's whole authority rests on its count being
verifiable, and the cron count is not. A directive that fires every session
because of an item the agent cannot clear teaches the agent that the directive
lies — the same failure Task 2.3 pinned a test against. The owner's ruling was
"teeth", and the teeth are the Stop block; the nudge was always the backstop
(`DESIGN-cron-enforcement.md:61-66`). Timing is the price of keeping the tier
honest, and it is bounded by one turn.

## Human gate?

**None.** The owner's rulings — teeth, not wording; verification at `Stop`;
`ACTION_REQUIRED` computed, never declared — are already recorded and this
decision is their consequence. What remained was whether a mechanism built to
answer a per-project question can answer a per-session one, and it cannot;
that is a determinate reading of `session_start_tiers.py` and
`session_action_items.py`, not a risk appetite. No installing project's
refusal surface changes: the assertor keeps emitting exactly what it emits
today, tagged `[INFO]`.

## One footnote, not a third option

PLAN.md:148 worries the assertor "stays unclassified while every other handler
has a tier". It is classified — every handler without a verifier computes to
`INFO`. If a tier above `INFO` is wanted for consistency with Task 2.2's two
handlers, the assertor may declare `ACTION_SUGGESTED` as its floor
(PLAN.md:157; `session_start_tiers.py:81-99`), which is author-chosen and
carries no enforcement, so it cannot be gamed into teeth. That is a
presentation choice available under option one, not an alternative to it, and
it is not needed to close the task.

With this decision recorded, Task 2.1 is settled and the plan's remaining open
criterion is the QA/CI line (PLAN.md:226).
