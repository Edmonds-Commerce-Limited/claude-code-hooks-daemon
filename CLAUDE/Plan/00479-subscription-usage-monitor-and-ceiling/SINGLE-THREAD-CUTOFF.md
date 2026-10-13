# Single-thread cutoff: a softer tier below the usage pause (#104)

The owner filed #104 for later pickup. It is folded into this plan because it reuses this plan's usage
snapshot and host resolution, and sits below the Phase 4 pause. No work is scheduled until the owner
answers the questions below.

## The proposal, as filed

At a usage threshold (95% by default, per host like `usage_ceiling`), once either window reaches it:

1. `PreToolUse` denies new parallel work: `Agent`/`Task`, and background spawns such as `Bash` with
   `run_in_background` and `Workflow`. Main-thread single-threaded work continues.
2. The main thread is told once, when the threshold is first crossed, and again in each deny reason, to
   wind up: let running sub-agents finish and harvest them, commit and push, journal.
3. Running sub-agents are not killed.

Ordering: below the pause, so a host can have a cutoff at 95% and a pause at 98%. It applies with no
`usage_ceiling` configured, because 95% is the default. While active it wins over the orchestrator-only
mode (Plan 00418, which runs in record-only simulated mode in this repository).

## How it relates to work already on file

- **Open question 5 of this plan** (a backstop the override cannot suppress) has option (b), a hard
  backstop at about 95%. A cutoff that applies under an override is one answer to question 5, so the two
  should be decided together.
- **Plan 00471** (sub-agent token budget protection) bounds how much context each sub-agent spends, by
  forcing a handoff. The cutoff bounds how many start. Different levers on the same incident class (work
  lost to the 5-hour limit); they stay separate plans.
- **Plan 00501** (session modes) models `usage-paused` as a session mode. A cutoff is a second
  usage-driven state, so it belongs in that model if 00501 is built first.

## Questions for the owner

1. **Default on, or opt-in?** The issue makes 95% a default that applies on every host, including client
   projects that configured nothing. The pause, the only usage behaviour here that stops work, applies
   only on a host with a `usage_ceiling` entry. A default-on
   deny is a behaviour change for every installation at the next release.
2. **Which window and threshold:** either window at 95%, or a lower default for the seven-day window?
3. **Which spawns count:** `Agent`/`Task`, `Workflow`, `Bash` `run_in_background`. Is a background
   `Bash` that runs QA (the coordinator's own integration gate) also a "fan-out" to deny?
4. **Under an override:** does `usage-pause clear` also clear the cutoff, or does the cutoff hold (question
   5 option (b))? And does the cutoff have its own override for the rest of the window?
5. **Status line:** a marker while the cutoff is active?

Settled by existing rules, not questions: a stale or absent snapshot never fires the cutoff (Task 4.7's
rule), and sub-agents already running are never killed.
