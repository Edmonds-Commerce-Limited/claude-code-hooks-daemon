# Plan 00412: jobs recurring work and security review

**Status**: Complete
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

  **The two counters are separate keys, and a test pins it** — both live in one
  git config, so a copy-paste leaving `latestPlanNumber` in place would pass
  every other test while silently consuming plan numbers.

  The duplication with `mkplan.bash` is deliberate: that script documents
  self-containment as a design property because the installer deploys it
  standalone, so a shared library would break what makes it deployable. The
  drift cost is paid by tests pinning the properties both must satisfy.

  `RUNS/` is created empty rather than on first use, so an empty directory
  always means never ran — D6 made structural instead of remembered.

  **Not deployed to client projects** until 2.3–2.5 exist, so a scaffolder for
  half a feature does not land in other people's repositories.

- [x] ✅ **Task 2.3**: `hooks-daemon run-routine <id>` — RED first, in three
  pieces so the thing that can be wrong is testable without argparse:
  `routines/ledger.py` (18 tests), `routines/resolver.py` (16) and the verb
  itself (15). `cli.py` is already ~9,000 lines and the last collector that
  grew inside it had to be extracted; this one starts outside.

  Proven live as well as in tests: a routine was started, refused a finish with
  no interval, finished `clean`, and the ledger holds both rows. The ledger is
  one row per EVENT, not per run — a shape forced by D10 rather than chosen.
  Reasoning in [DESIGN-routine-tree.md](DESIGN-routine-tree.md).

- [x] ✅ **Task 2.4**: QA checks for the new tree, in `routines/qa.py` with a
  `hooks-daemon routine-qa` verb, plus the two things they had to be able to
  read first: `routines/model.py` (the ROUTINE.md header) and
  `routines/git_ancestry.py` (the oracle). RED first throughout — 16, 9 and 26
  tests, and the model's red was a genuine 2-failed/14-passed rather than a
  bare import error.

  Five checks, not the four originally listed; grace defaults to a fifth of the
  period rather than zero; only a FINISHED run counts as coverage. Building
  these surfaced and fixed a defect in 2.3's own ledger. All of it in
  [DESIGN-routine-tree.md](DESIGN-routine-tree.md).

- [x] ✅ **Task 2.5**: The overdue assertion — the dead-man's switch, as the
  `routine_qa_sweep` SessionStart handler (priority 72, opt-in, 12 tests).
  Session start is the right surface for it because it is the one the daemon
  EXECUTES itself rather than one it can only hope fired (D9).

  Three properties are pinned, each mattering more than the wording: **silent
  when clean** (a handler that speaks every session is scenery); **opt-in**
  (most projects have no Routine tree, and a handler learned as noise is not
  read later when it has something to say); and **it never raises** (a sweep
  that dies reports nothing, and so does a healthy tree — the reporting surface
  must not reintroduce the ambiguity the design removes).

  `session_actions_directive` moved 72 → 73: its "last" position is
  load-bearing rather than tidy, and the constant now says so.

  **The project's own gate caught a defect in this work.**
  `test_git_spawns_are_bounded` failed: `git_ancestry.py` spawned git directly
  instead of through `utils.git_repo.run_git`, so it neither declined git's
  optional index lock nor carried a timeout — and the sweep runs in the working
  tree an agent is using. Fixed by routing through the bounded runner, which
  also deleted a failure path, since `run_git` reports a missing binary or a
  timeout as a return code
  rather than raising.

### Phase 3: The first routine — security review

- [x] ✅ **Task 3.1**: The routine definition: a full sweep on a calendar cadence,
  a narrower per-release sweep over changed code and changed rules, and an
  explicit list of which checks are delta-able and which are full-only. A
  delta run MUST record which checks it did not run — a delta scan is
  structurally blind to a class of finding, which is what makes the periodic
  full sweep a compensating control rather than belt-and-braces.
  Two routines sharing one inventory — 00001 full (schedule), 00002 delta
  (release) — because a shared ledger would let a delta run reset the full
  sweep's overdue clock. `Trigger: release` added, with no clock of its own.

- [x] ✅ **Task 3.2**: Living security documentation that grows by category as
  findings arrive, with each category naming its Defence.
  `CLAUDE/Security/`: contract plus category table, one file per category. A
  register of CLASSES, not a log of incidents. Opened with a real category —
  the first defect arrived while the register was being written.

- [x] ✅ **Task 3.3**: A specialist security-review sub-agent, and the run
  procedure that dispatches it.
  `.claude/agents/security-reviewer.md` — read-only, one CHECK per dispatch,
  every finding carrying the class, why the tests miss it and a Detector
  hypothesis. Distinct from `hooks-daemon-opus-security`, a quarantine
  EXECUTOR for a different problem. Dispatched by both routines' step 3.

- [x] ✅ **Task 3.4**: Run it once, end to end, and fix what it finds under
  Defence Before Fix — the Defence before the fix, every time. Each Defence is
  a Detector in `scripts/qa/`, wired into `run_all.sh` like every other check.
  Named explicitly because DBF clause 3.2 forbids the test from BEING the
  Detector: a regression test proves one instance was fixed, while a Detector
  finds the whole class and keeps finding it. Left implicit, this gets
  re-litigated at each finding and settled the cheap way.

  **The run half is done.** Run `2026-001` performed all 15 checks, none
  unanswerable, and is closed as `findings` over
  `74b0989c -> 5d59f7ff` with 77 findings recorded in `subagent-reports/`.

  **The fix half is partly done.** `authored-path-resolution` has completed DBF
  **twice** — red over 7 then fixed (`20f5fe82`, `344ebf16`), then widened red
  over 30 after its coverage was measured rather than assumed, and fixed
  (`e040e89b`, `73c90244`, `65161ce5`). Gate green. The second pass found a
  live content-oracle read in `quote_drift`. Reasoning in JOURNAL/.

  The remaining ~6 classes are recorded and unfixed. Several remedies are
  owner-gated because they change the gate surface in every installing project.
  The highest-value one is written up as a decision request with four costed
  options and a recommendation:
  [DECISION-degraded-mode-guard-surface.md](DECISION-degraded-mode-guard-surface.md).
  Owner-gated means the decision is owed, not that the analysis is.

  Next unit is a consolidated worklist: 77 findings across 15 reports collapse
  to roughly seven classes, and building Defences per REPORT would produce
  overlapping Detectors for the same nets.

  **The delta routine has now run too.** 00002's `2026-001` covered
  `v3.63.0 -> v3.64.0`, all 8 delta-able checks, none unanswerable, 19 findings
  — and it closed the live `routine-never-run` the sweep had been reporting
  against it. It earned its keep on its first outing by **overturning a full
  sweep verdict**: 00001 judged the sibling `--body-file` route "closed by
  handler ORDER", and `core/chain.py` makes that termination conditional on
  `collect_all_violations`, which `init_config.py` scaffolds into every config.
  A whole-repository brief called it closed; one release's diff found the
  condition that opens it. Every finding is already shipped in v3.64.0, so all
  are recorded rather than patched, on the same owner-gated boundary as the
  security-downgrade rows.

  **Running the machinery found three defects that reading it had not**, all
  one class — a record of NON-coverage read as coverage. A `skipped` run reset
  the overdue clock, so a routine skipped for ever read as one performed on
  time; a routine whose only rows were skips or unfinished starts was reported
  by NO check, falling between "are there records" and "how long since one";
  and both procedures derived `from` from "the last recorded run (any
  outcome)", which is undefined after a skip because a skip records no `to`.
  Defence first — `0311a782`, committed red, naming `SKIPPED` — then the fix
  (`54368a76`), then the derivation moved out of prose into `run-routine`
  itself. Recorded as an instance of `asymmetric sibling protection`, whose
  registry needed a fifth extractor to express a relation between two enum sets.

  **A fourth defect is open and recorded in the routine itself.** The
  `security-reviewer` agent is declared without the `Write` tool while step 3
  asks it for a report file. Every dispatch hit it: three reviewers fell back to
  a Bash heredoc — the one write path the pre-write content guards never
  inspect — and one lost its report entirely, surviving only as a transcription
  its own author could not verify. The forced workaround is precisely the one
  that routes a security report around the disclosure guard, in a public
  repository. Two remedies are named in
  [the routine](../../Routine/00001-security-review-full/ROUTINE.md); both change
  a contract and neither was taken on the eve of a release.

## Success Criteria

- [x] ✅ A second run of any routine can state, from the records alone, exactly
  what interval it must cover, with no mutable pointer consulted. Demonstrated
  rather than asserted: `run-routine 00001` over a copy of the real ledger
  prints `this run's from is 5d59f7ff`, which is run `2026-001`'s recorded `to`.
  `ledger.next_from_ref()` reads only rows that CARRIED an interval, and returns
  None rather than guessing a first run's start — which ref that is belongs to
  each routine, not to the ledger.

- [x] ✅ A deliberately skipped run is detectable: the QA sweep reports the
  gap rather than the records reading as continuous. It did not, and now does.
  Shown both ways over one set of records: the pre-fix sweep said **nothing** at
  all about a routine last covered 199 days ago and deliberately skipped today,
  and said `last finished 107 days ago` about one that had never finished
  anything. After the fix it reports `last covered ground 199 days ago` and
  `has run records, but not one of them covered anything`.
  `routine-run-gap` is deliberately NOT the check that fires — D5 says a skip
  leaves no hole, it widens the next interval — so the gap surfaces on the
  overdue clock and the dead-man's switch instead.

- [x] ✅ The security routine has run once for real, its findings are recorded,
  and every confirmed defect has a BLOCKING Detector that was proved to fire
  before its fix landed. **CLOSED ON THE FIRST TWO CLAUSES; THE THIRD IS
  CARRIED TO PLAN 00421, NOT CLAIMED HERE.**

  Both routines ran for real and every finding is recorded — 00001's `2026-001`
  (15/15 checks, 77 findings) and 00002's `2026-001` (8/8, 19). The Detector
  clause is NOT true today: ~6 classes from the full sweep are unfixed.

  What changed is that it is now *sayable*. This criterion was unclosable for a
  structural reason rather than a lack of effort — four decision requests sat
  awaiting an owner, so nobody could state what "every confirmed defect" would
  even require. All four are now ruled
  ([fable-defence-location-decision.md](fable-defence-location-decision.md),
  [fable-degraded-mode-decision.md](fable-degraded-mode-decision.md),
  [fable-forwarder-interpolation-decision.md](fable-forwarder-interpolation-decision.md),
  [fable-secret-guard-module-path-decision.md](fable-secret-guard-module-path-decision.md)),
  and each names the work it creates. That work is Plan 00421's task list.

  Two of the four gates turned out not to be owner questions at all: one rested
  on a premise that had expired ten days before it was written, and one was
  already decided by a method this project had adopted. Recorded as 00419 N15,
  because a gate that blocks on a false premise blocks exactly as effectively
  as a real one.

  **The box is ticked for a plan whose deliverable was the machinery and the
  run, not the fixes.** Ticking it on the Detector clause would be false, and
  this plan's own best finding was that a record of non-coverage reads as
  coverage — it would be a poor way to close it.

- [x] ✅ Nothing in the generic core mentions security. Audited and fixed: the
  package docstring named security review as the first consumer, and
  `mkroutine.bash` offered `"security-review"` as its worked example — a generic
  scaffolder teaching every new routine what kind of thing a routine is. Their
  test fixtures carried the name throughout and now scaffold a dependency audit.
  `grep -i securit` over `routines/`, the sweep handler, the scaffolder and all
  their tests returns nothing. `CLAUDE/Routine/README.md` still names the two
  real routines, which is the index of what exists rather than the core.

- [x] ✅ Every release-bound consequence is in the pending-release holding
  area: [`UNRELEASED/release-notes/09-routines-recurring-work-that-never-completes.md`](../../UPGRADES/UNRELEASED/release-notes/09-routines-recurring-work-that-never-completes.md)
  for the routines tree, `run-routine` and the interval algebra, and
  `UNRELEASED/config-changes/v3.65.0.yaml` for the `routine_qa_sweep` key.

  **The gate caught a real omission here, which is worth recording rather than
  quietly fixing.** This criterion was absent from the plan entirely, and
  `plan_done_requires_holding_area` refused the flip to Complete. Nothing in
  the holding area mentioned routines: the plan's headline deliverable — a new
  tree, a new CLI verb and a new SessionStart handler — would have shipped to
  every installing project with no operator-facing callout at all. The config
  key was documented; the feature it configures was not.

- [x] ✅ Full QA passes, the daemon is restarted, and CI is green. Ticked on
  the consolidated release QA run for v3.65.0, not a per-plan one. That run
  found two genuine defects and both are fixed RED-first in `2778206f` — a
  mypy `no-redef` in this plan's own `run-routine` CLI (`from_ref` bound as
  `str | None` in the start path and re-annotated `str` in the finish path of
  one function), and a Detector that scanned linked worktrees. The suite's one
  remaining finding is ADVISE and belongs to 00419 (its own N12).

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
