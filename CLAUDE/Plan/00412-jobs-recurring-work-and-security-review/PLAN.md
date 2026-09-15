# Plan 00412: jobs recurring work and security review

**Status**: In Progress
**Created**: 2026-09-15
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Direct

## Overview

This project models work as PLANS: numbered, one-shot, archived on completion.
That shape fits everything it has ever been asked to do, and it fits recurring
work badly. A plan that is never finished sits in the Active list forever,
which is how a recurring obligation becomes indistinguishable from a stalled
one.

So this adds a SECOND work concept for work that recurs and never completes,
with a per-RUN record rather than a completion. The first consumer is a
security review — a full sweep on a calendar cadence plus a narrower one per
release — but the system is deliberately generic, because this repository
already has about six recurring sweeps implemented as bespoke session-start
handlers (`plan_qa_sweep`, `docs_qa_sweep`, `reference_repo_sweep`,
`remote_docs_staleness`, `deployed_artefact_drift`,
`secret_file_hygiene_checker`). Each independently reinvents "run
periodically, report findings, stay quiet when clean". The abstraction has
existing consumers waiting, which is a stronger justification than one new use
case.

It builds on machinery that already exists rather than replacing it. Plan
00384 gave the project `persistent_crons` (declaration) and
`persistent_cron_assertor` (re-assertion each session). That is the
persistence layer and it works. What it cannot do — by construction, not by
oversight — is know whether anything ran: Claude Code crons live in session
memory, `durable` has no effect, and the daemon cannot read them. The gap this
plan fills is the RECORD, and the record is what makes a recurring obligation
auditable.

Research is in `subagent-reports/` (four reports, ~2,300 lines) and the design
decisions it produced are in [DESIGN.md](DESIGN.md).

## Goals

- A generic recurring-work concept: a definition document, and a separate
  record per RUN, mirroring the Plan tree's conventions where they transfer
  and deliberately not where they do not.

- **Coverage recorded as an INTERVAL, not a pointer.** Each run records the
  span it covered (`from -> to`, a commit or tag). Intervals compose, so a gap
  between runs is DETECTABLE; a mutable "last run" pointer that is bumped
  wrongly is silently wrong forever. This is the single most important
  decision in the plan, taken from `cargo-vet`.

- **A run that found nothing is recorded as distinctly as one that found
  something**, and both are distinct from never having run. Absence of a
  record is not observable from the records themselves, so something outside
  the routine must assert "a run is overdue".

- **Two-level logging, split by portability rather than verbosity.** The
  in-repo record carries the outcome and the interval; raw output goes to
  `untracked/`, which survives restarts but is per-checkout and invisible to
  CI, another machine or a fresh clone.

- A `hooks-daemon run-routine <id>` CLI the cron system can invoke, with the
  honest contract that the cron PROMPTS a run and the record PROVES one.

- **A trigger is a KIND, not always a clock.** `session_start` is a
  first-class trigger beside `schedule`, which is what makes the six existing
  sweeps real consumers rather than an analogy — and it is the trigger with
  the STRONGEST delivery guarantee, since the daemon executes SessionStart
  itself while a Claude Code cron it cannot even see.

- The first routine conforms to Defence Before Fix: every confirmed defect
  produces a blocking Detector before the fix lands.

## Non-Goals

- **Becoming a scheduler.** The daemon cannot guarantee anything ran. "Runs
  every hour" is unsupportable; "declared, plus every run that recorded
  itself" is supportable. Any design that treats a declared cron as evidence
  of execution is recording an intention and calling it a fact.

- **Over-fitting to security.** Security review is the first CONSUMER, not the
  shape. Anything in the core that only makes sense for a security sweep
  belongs in that routine's own definition instead.

- **Replaying missed runs.** A missed run widens the NEXT run's interval
  rather than queueing catch-up executions — systemd's `Persistent=` semantics
  rather than a replay queue, and Airflow ships `catchup=False` by default for
  the same reason.

- **Migrating the existing sweeps in this plan.** They are the evidence the
  abstraction is real and they are the obvious later consumers, but converting
  them is its own plan; doing it here would couple a new concept's first
  release to six behaviour changes.

## Tasks

### Phase 1: Decide the shape

- [x] ✅ **Task 1.1**: Settle the open decisions in
  [DESIGN.md](DESIGN.md) with the owner — principally the NAME (the research
  argues "Job" collides locally and recommends "Routine"), the directory, and
  whether the run record is one file per run or an append-only ledger.
  All four settled; see "Owner decisions" in DESIGN.md. **Routine**, in
  `CLAUDE/Routine/NNNNN-name/`, with runs in `RUNS/`; the run record is a
  **yearly append-only ledger**; Defence Before Fix conformance is **declared
  with a known-gap record** under toolchain clause 9.2; the first security run
  covers the **whole repository**. This plan's folder keeps its original name —
  plan folder names are historical and renaming one breaks every inbound link.

- [x] ✅ **Task 1.2**: Capture the one Defence Before Fix document the
  remote-docs corpus is missing (`TOOLING-SPEC`), and correct the
  `licence: unreviewed` frontmatter on the vendored copies, which state CC
  BY 4.0 on the site itself. Toolchain specification 0.2.0 is now vendored;
  the licence is recorded once for the DOMAIN under
  `documentation.remote.known_sources` rather than five times in
  frontmatter, which is what the capture advisory asks for.

### Phase 2: The generic system

- [x] ✅ **Task 2.1**: The interval algebra, RED first, in
  `src/claude_code_hooks_daemon/routines/intervals.py` with 16 tests. Gap,
  overlap and full coverage each compose to their own answer, and a fourth —
  `UNRELATED` — exists because a rebase or a diverged branch leaves refs where
  neither precedes the other, and reporting that as `MEETS` would be the
  pointer bug wearing an interval's clothes.

  **Detection needs no oracle; classification does.** Whether two runs are
  discontinuous is string inequality, which is all the dead-man's switch needs
  and is what "without consulting anything mutable" comes to. Telling a gap
  from an overlap needs to know which ref came first, so git ancestry arrives
  as an injected `Ancestry` protocol: the arithmetic stays pure, the
  subprocess stays at the edge, and the healthy case — every consecutive pair
  in a well-run Routine — short-circuits on equality and never pays for a
  lookup.

  D5's "missed runs widen, never replay" is pinned as a test rather than left
  as prose: a skipped run leaves no hole, because the next run's `from` is
  still the last completed run's `to`.

  D6 is pinned by its absence: `discontinuities([])` is empty, because a
  Routine that never ran has no runs to compose. Conflating "never ran" with
  "continuous" would let an unrun Routine report as covered — so the overdue
  assertion stays Task 2.5's job, outside this algebra.

  Independent of D18/D22, which decide WHERE run records live. The composition
  is the same arithmetic whether they are tracked or per-checkout.

- [x] ✅ **Task 2.2**: The document tree (`CLAUDE/Routine/` with its index) and
  `mkroutine.bash`, RED first, with 15 tests driving the real script in a real
  temporary git repository — the behaviour under test is shell semantics and
  git-config state, neither of which a Python-level assertion could observe.

  **The two counters are separate keys, and a test pins it.** Both trees live
  in one repository and both counters live in one git config, so a copy-paste
  that left `latestPlanNumber` in place would work perfectly while silently
  consuming plan numbers — unrecoverable once a plan is filed against one.
  That is the guard that matters most here, so it is asserted directly rather
  than implied by the happy path.

  **The duplication with `mkplan.bash` is deliberate, not laziness.** That
  script documents self-containment as a design property: the installer
  deploys it standalone into client projects, so factoring the numbering into
  a sourced library would break what makes it deployable. The cost — a fix
  applied to one and not the other — is paid in the test file, which pins the
  properties both must agree on: counter-over-scan, the drift guard, the
  archived-routine high-water mark, and the lock that makes two concurrent
  runners take distinct numbers.

  `RUNS/` is created empty rather than on first use, so an empty directory
  always means never ran — D6's distinction made structural instead of
  remembered.

  **Not deployed to client projects**, and that is a scope decision rather
  than an oversight: Tasks 2.3–2.5 still owe the run CLI, the QA checks and
  the overdue assertion, so shipping the scaffolder now would put half a
  feature in other people's repositories.

- [ ] ⬜ **Task 2.3**: `hooks-daemon run-routine <id>`: resolve the definition,
  open a run record, hand the agent the procedure, and record the outcome. The
  existing `daemon/housekeeping.py` step-registry and
  `config_optimisation/state.py`'s `record_run` are the closest existing
  shapes to reuse.

- [ ] ⬜ **Task 2.4**: QA checks for the new tree, mirroring `plan_qa`: an
  overdue run, a run with no recorded interval, a gap between consecutive
  runs, a definition with no runs at all.

- [ ] ⬜ **Task 2.5**: The overdue assertion — the dead-man's switch. A run
  that never happened leaves no record, so a session-start surface must notice
  the absence.

### Phase 3: The first routine — security review

- [ ] ⬜ **Task 3.1**: The routine definition: a full sweep on a calendar cadence,
  a narrower per-release sweep over changed code and changed rules, and an
  explicit list of which checks are delta-able and which are full-only. A
  delta run MUST record which checks it did not run — a delta scan is
  structurally blind to a class of finding, which is what makes the periodic
  full sweep a compensating control rather than belt-and-braces.

- [ ] ⬜ **Task 3.2**: Living security documentation that grows by category as
  findings arrive, with each category naming its Defence.

- [ ] ⬜ **Task 3.3**: A specialist security-review sub-agent, and the run
  procedure that dispatches it.

- [ ] ⬜ **Task 3.4**: Run it once, end to end, and fix what it finds under
  Defence Before Fix — the Defence before the fix, every time. Each Defence is
  a Detector in `scripts/qa/`, wired into `run_all.sh` like every other check.
  Named explicitly because DBF clause 3.2 forbids the test from BEING the
  Detector: a regression test proves one instance was fixed, while a Detector
  finds the whole class and keeps finding it. Left implicit, this gets
  re-litigated at each finding and settled the cheap way.

## Success Criteria

- [ ] ⬜ A second run of any routine can state, from the records alone, exactly
  what interval it must cover, with no mutable pointer consulted.

- [ ] ⬜ A deliberately skipped run is detectable: the QA sweep reports the
  gap rather than the records reading as continuous.

- [ ] ⬜ The security routine has run once for real, its findings are recorded,
  and every confirmed defect has a BLOCKING Detector that was proved to fire
  before its fix landed.

- [ ] ⬜ Nothing in the generic core mentions security.

- [ ] ⬜ Full QA passes, the daemon is restarted, and CI is green.

## Delivery & Milestones

- Requested by the owner, who also drew the Plans/Jobs distinction, flagged
  repository bloat as the risk in journalling every run, and corrected two of
  this plan's early assumptions: that `untracked/` is wiped on container
  restart (it is bind-mounted and survives; the real limitation is that it is
  per-checkout), and that the persistent-cron foundation still needed
  building (it exists and works — what it lacks is the run record).

- Auditing that foundation before building on it found two defects shipped in
  v3.64.0, both fixed at `091ceacd` with the detector written before the
  patch: the upgrade manifest documented a `name` field the schema calls `id`
  and forbids, so a client pasting the documented example got a daemon that
  would not start; and `persistent_cron_assertor` shipped with no tags at all
  while the same manifest described it as PLANNING tagged.
