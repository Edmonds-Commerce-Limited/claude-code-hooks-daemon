# Plan 00480: plan fact checker and debounce

**Status**: In Progress
**Created**: 2026-10-02
**Owner**: dev
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Ledger 00474 N290: the coordinator wrote a confident, unsearched, false claim into Plan 00479
("the ccy supervisor is outside this repository"). The claim changed a task's design until
the owner caught it. Wording checks cannot catch a claim stated flatly. The owner's ruling:
the remedy is a cheap Sonnet fact ITEMISER and VERIFIER ("anything else is really hit and
miss"), wired into the plan QA system, so that every plan edit has its diff fact-checked.
Debouncing is a first-class daemon feature, so a burst of edits triggers one check.

The experiment (Phase 1) has run. Plan 00479 as filed at c77a23ffd is kept as
[ARTEFACT-00479-AS-FILED.md](ARTEFACT-00479-AS-FILED.md). A Sonnet fact checker, briefed
generically with no hint, found three things
([report](subagent-reports/261002-fact-check-experiment-sonnet.md)):

- **The false claim**, in both places it appeared, refuted with the in-repository paths.
- **A second real defect the coordinator had missed**: at the time, `PRE_TOOL_USE_SCHEMA` could not
  carry `continue: false` (`additionalProperties: False`). Since fixed: `core/response_schemas.py`
  now declares `continue` and `stopReason`.
- **An existing mechanism the plan overlooked**: `src/claude_code_hooks_daemon/utils/cron_pause.py`.

One caveat: the checker also noticed the correcting commit in git history, so its view of
history was not blind. Its refutation still stands on the files alone.

Facts this plan builds on, each checked:

- **Plan QA on edits and commits**: plan QA judges edits in
  `src/claude_code_hooks_daemon/handlers/pre_tool_use/plan_qa_edit.py` and commits in
  `plan_qa_commit_gate.py`.
- **A turn channel**: one already exists for daemon-to-session work.
  `src/claude_code_hooks_daemon/handlers/session_start/session_actions_directive.py` drops a
  `<session>.session-actions` signal, and the ccy supervisor (`.claude/ccy/claude-supervise.py`)
  types it as a turn.
- **No debounce or timer** (at planning time): no debounce or timer primitive existed in `src/`, so one
  had to be built. Phase 3 built it: `core/debouncer.py` (`get_debouncer()`).
- **No headless `claude -p`**: nothing in `src/` invokes one (a search found none).

The "always verify, never assume" principle landed in the plan workflow core doc in 51d3ad812,
as principle 1.

## Goals

- A fact-checker agent definition (Sonnet). It itemises a document's claims about the
  codebase, tries to disprove each against the repository, and reports VERIFIED, REFUTED or
  UNVERIFIABLE-HERE with evidence.
- A first-class debounce primitive in the daemon: a keyed, quiet-period trigger that fires
  once after a burst of events.
- Plan edits trigger a debounced fact check of the diff since the last checked revision.
  Refuted claims reach the session as work to do, not as background scenery.

## Non-Goals

- A regex or wording-based claim detector (option 1 in N290). The owner ruled it hit and miss.
- Fact-checking documents outside the plan directory, for now. That is a natural follow-on
  once the plan path proves itself.

## Tasks

### Phase 1: Experiment

- [x] ✅ **Task 1.1**: Keep the incorrect plan as an artefact and run a generically briefed
  Sonnet fact checker on it. It caught the false claim and two further real issues.

### Phase 2: The fact checker

- [x] ✅ **Task 2.1** (2fbb24bbd): Write the agent definition `.claude/agents/plan-fact-checker.md` (Sonnet,
  read-only apart from its report file), turning the experiment's brief into a reusable contract.
  - **Input**: a plan path and a diff, or a whole document.
  - **Output**: a fixed, machine-readable verdict table written to the plan's
    `subagent-reports/`, plus a one-line summary.
  - **History**: it must not consult git history for the claim under test, so it judges
    against the current tree only.
- [x] ✅ **Task 2.2**: Run it on two or three more real plan diffs from git history, including
  one known to be correct, to measure false refutations before wiring it in.
  - **Blind re-run**: refuted the supervisor claim again.
  - **Plan 00475**: 2 genuine errors, fixed there, plus 4 stale problem statements; no outright
    false refutation.
  - **Recall varies**: 9 claims itemised in one run against 26 in another.
  - **Lesson**: check the DIFF at edit time (JOURNAL 26-10-02).

### Phase 3: Debounce as a daemon primitive (TDD)

- [x] ✅ **Task 3.1** (merged; `core/debouncer.py`, `get_debouncer()`; pending triggers are
  dropped on shutdown, not persisted; documented in `CLAUDE/HANDLER_DEVELOPMENT.md`): Design
  and build a keyed debouncer in the daemon. Its behaviour:

  - each event for a key resets that key's quiet-period timer;
  - the callback fires once, after the period passes with no further event;
  - it stays bounded in memory, is thread-safe, and is cancelled on shutdown.

  Decide whether pending triggers survive a daemon restart. Document it as a reusable
  facility for other handlers.

### Phase 4: Wire into plan QA (TDD)

- [x] ✅ **Task 4.1**: A `PostToolUse` handler on writes and edits under the plan directory feeds
  the debouncer, keyed by plan folder (default quiet period 5 s, configurable).
  - **Handler**: `PlanFactCheckFeedHandler` (`plan_fact_check_feed`, priority 37), non-terminal,
    never blocks, ships `default_enabled = False` and is off in the template; this repository enables it to
    dogfood it. Option `quiet_seconds`.
  - **Scope**: any tracked markdown document of a plan folder, written by `Write`, `Edit` or a
    Bash command whose authored paths `get_written_file_paths` can name. `subagent-reports/` and
    `JOURNAL/` are excluded, so the checker's own reports cannot re-trigger it.
- [x] ✅ **Task 4.2**: When the debouncer fires, compute the diff since the last fact-checked
  content of that plan (record a per-plan checked hash), and deliver the check (open
  question 1).
  - **Done**: `utils/plan_fact_check.py` keeps per-plan state under the daemon untracked dir
    (`plan-fact-check/`): the last fact-checked content and hash, and a pending record. The
    fire computes the diff since that content and stores it as a **pending fact-check**.
  - **Boundary**: the fire callback does NO dispatch. It logs at info level and stores the
    pending record. Delivery is owner open question 1.
  - **Done (delivery)**: the pending record also stores the plan root and the content snapshot.
    `deliver_pending` writes the diff to `<folder>.diff`, calls `record_checked` with the stored
    snapshot, clears the record and returns the instruction, once per record.
- [x] ✅ **Task 4.3**: Deliver the result. REFUTED claims reach the session as work, naming the
  claim, the evidence and the file. Decide whether an unresolved REFUTED claim blocks the
  plan's next commit through `plan_qa_commit_gate` (open question 2).
  - **Done**: the next PostToolUse event of any tool delivers the instruction as
    `additionalContext` (the feed handler now also matches when a check is owed). It tells the
    session to dispatch `plan-fact-checker` on the plan with the diff file, and to fix every
    REFUTED claim (claim, evidence, file).
  - **Route**: not the supervisor channel. Its signal carries a bare count and a fixed
    template pointing at `hooks-daemon session-actions`, which lists SessionStart items only.
  - **Blocking**: none (open question 2 ruling and owner ruling A1); `plan_qa_commit_gate` is
    untouched.
- [ ] 🔄 **Task 4.4**: Acceptance tests, plus a live run: edit a plan to add a false claim, see
  one debounced check fire, and see the refutation delivered.
  - **Done**: automated tests (`TestDelivery` in the feed handler and util tests) and the
    handler's acceptance tests.
  - **Live run (2026-10-06)**: one debounced check fired for a deliberate false claim (the feed handler
    placed under `pre_tool_use/`), and `plan-fact-checker` refuted it from the diff, along with four
    stale claims in this plan, now corrected. But the delivery text never reached the session, and
    the delivered instructions showed three more defects. All four are 00474 N359.
  - **Delivery seen (2026-10-06)**: filing Plan 00495 produced "PLAN FACT-CHECK OWED for
    00495-performance-improvement-programme" in the session on the next PostToolUse. The path was correct and the
    diff file existed. The coordinator dispatched `plan-fact-checker` on it.
  - **Remains**: the N359 path defects (worktree and archived-plan paths, whole-folder first diffs), then one more live
    run free of them.

## Open questions for the owner

1. **Who runs the check**:

   - **(a)** The daemon signals the session, through the supervisor turn channel that
     `session_actions_directive` uses, to dispatch the `plan-fact-checker` agent itself.
     This uses the session's tools and permissions, and needs a supervised session.
   - **(b)** The daemon runs a headless `claude -p --model sonnet` subprocess. This is
     independent of the session, but spends usage outside it, needs the CLI and its
     credentials in the daemon's environment, and is new territory: nothing in `src/` does
     it today.

   Recommended: (a) when a supervisor is present, else an advisory on the next hook event.

   **Coordinator call (2026-10-05, under the owner's "go with the clear winners" instruction):** (a), the session via the supervisor. Resolved; not an owner ruling.

2. **Should an unresolved REFUTED claim block the plan commit**, or only report? Recommended:
   report first, and decide on blocking once Task 2.2 shows the false-refutation rate.

   **Coordinator call (2026-10-05, under the owner's "go with the clear winners" instruction):** report, do not block yet. Resolved; not an owner ruling.

## Success Criteria

- [ ] The fact checker, run on the artefact without hints, refutes the supervisor claim.
  Met once, by the experiment; to be repeated by the final agent definition.
- [ ] A burst of plan edits produces exactly one fact check, about 5 s after the last edit.
- [ ] A false claim added to a plan is refuted and reaches the session without anyone asking.

## Delivery & Milestones

- Principle 1 "always verify, never assume": 51d3ad812.
- Experiment: report in `subagent-reports/`.
