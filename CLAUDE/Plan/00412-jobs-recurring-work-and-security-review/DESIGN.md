# Plan 00412 — design decisions

Written from four research reports in `subagent-reports/`. Each section states
the decision, the reasoning, and — where it is genuinely the owner's call —
what is being asked. Nothing here is implemented; the plan is in review.

## D1. The name — DECIDED: Routine

**The owner chose Routine**, accepting the research recommendation over their
own original proposal. The reasoning that follows is kept because it is the
answer to "why not Job?", which will be asked again.

The owner proposed **Job**. The research argues for **Routine**, and the
argument is not an abstract preference, so it is put here rather than quietly
adopted or quietly ignored.

**The case against "Job" is a local collision.** `.github/workflows/` already
uses `jobs:` in the GitHub Actions sense, and this concept is explicitly to be
driven BY the cron system. So the two senses will not merely coexist, they will
appear in the same sentence routinely: *"the cron job that runs the job"*,
*"the Job's workflow job failed"*. Prose that must disambiguate its central
noun every time pays that tax in every future document, and it lands hardest in
the generated CLAUDE.md guidance blocks, which exist to instruct agents
unambiguously.

**The case for "Job"** is the idiomatic Job→Run pairing that Airflow,
Kubernetes and GitHub Actions have already taught every developer, plus the
fact that the owner already thinks in it.

| Option      | For                                                       | Against                                                    |
| ----------- | --------------------------------------------------------- | ---------------------------------------------------------- |
| **Job**     | Idiomatic Job→Run; owner's own term                       | Collides with Actions `jobs:` and with cron jobs, in prose |
| **Routine** | No collision; parallel grammar with Plan; pairs with Run  | Slightly unusual as a noun for this; nobody else uses it   |
| **Control** | Semantically exact — a recurring obligation with evidence | Reads as compliance theatre in a developer tool            |

**Recommendation: Routine**, on the collision argument alone —
`CLAUDE/Routine/NNNNN-name/` beside `CLAUDE/Plan/NNNNN-name/`, with the honest
contrast that *a Plan finishes, a Routine recurs*. **"Job" is defensible** if
the owner prefers it; the mitigation is to ban bare "job" for CI in prose,
which is a discipline that erodes.

**Uncontroversial either way: the per-execution record is a RUN**, in a
`RUNS/` directory. That half of the vocabulary is settled whichever parent noun
wins, so implementation can proceed on everything except the folder name.

## D2. Coverage is an interval, never a pointer — DECIDED

Taken from `cargo-vet`, and the most important decision here.

A run records **the span it covered** — `from` and `to`, each a commit SHA or
tag — on the run record itself. It does NOT update a mutable "last reviewed"
pointer.

The difference is entirely about failure. Intervals **compose**: laying two
runs end to end either meets, overlaps, or leaves a hole, and a hole is
arithmetic rather than judgement. A pointer has no such property — bump it
wrongly once, by a crash, a rebase, a merge or a careless edit, and every
subsequent run believes a window was covered that nobody looked at. The
pointer is silently wrong forever and nothing can detect it after the fact.

Consequence for the delta shortcut the owner asked for: a per-release run
covers `<last run's to> -> HEAD`, not "since the last release". If the previous
run was skipped, the interval simply widens, automatically and visibly.

## D3. A delta run is structurally blind — DECIDED

CodeQL states this plainly for its own diff-scanning mode, and it generalises:
a scan restricted to changed files cannot see a finding whose cause is in the
change but whose symptom is in untouched code, nor one that arises from the
INTERACTION of changed and unchanged code.

Two consequences, both mandatory:

1. The periodic full sweep is a **compensating control**, not thoroughness
   theatre. It exists precisely because delta runs are known to miss a class.
2. A delta run **MUST record which checks it did not run**. A run record that
   says "clean" without saying "clean under a delta scope" is the most
   expensive kind of wrong, because it will be cited later as coverage.

## D4. Two-level logging — DECIDED, with the reasoning corrected

The owner proposed in-repo plus fully-verbose untracked, and was right. The
split is by **portability, not verbosity** — and the initial reasoning for that
was wrong in a way worth recording.

`untracked/` is inside the bind-mounted workspace, so it **survives container
restarts**. The earlier claim that it is wiped confused it with paths outside
the repository, which is the case the project's own guidance warns about. The
real limitation is different and narrower: `untracked/` is **per-checkout**,
so it is invisible to CI, to a second machine, and to a fresh clone.

That is what decides the split:

| Lives in repo                                 | Lives in `untracked/`                      |
| --------------------------------------------- | ------------------------------------------ |
| The run record: date, scope, interval covered | Raw detector output                        |
| Outcome counts, and which checks did not run  | Per-file reasoning and working notes       |
| A pointer to the verbose log                  | Anything regenerable by re-running the job |
| References to findings that became plans      |                                            |

The interval MUST be in-repo: a run on a different checkout would otherwise
have no idea what was already covered. For a single developer on one machine
that difference is invisible — which is exactly why it has to be decided now
rather than discovered when CI first runs a job.

**Bloat is not driven by run count.** A monthly full sweep plus per-release
deltas is a few dozen records a year; at a handful of lines each that is
nothing. Bloat comes from pasting tool output inline, so the rule to encode is
*the in-repo record carries outcomes and the interval, never raw output*.
Rotate run files by year, not by day: a monthly job would otherwise scatter one
tiny file per run.

## D5. Missed runs widen, never replay — DECIDED

`systemd`'s `Persistent=true` catches up with a SINGLE activation, not one per
missed interval; Airflow ships `catchup=False` as the default. Replaying is
almost always wrong for review work — three missed monthly sweeps do not need
three sweeps, they need one sweep over the widened interval, which D2 gives for
free.

## D6. Absence of a run is not observable from the runs — DECIDED

Nothing in a set of run records reveals the run that never happened. Something
OUTSIDE the records must assert overdue-ness — the dead man's switch.

This project already has the shape: `persistent_cron_assertor` states what is
declared, and the session-start sweeps report drift. The overdue check belongs
there, not inside the job.

## D7. What the cron can and cannot promise — DECIDED

Claude Code crons live in session memory, `durable` has no effect, and
recurring jobs expire after seven days. Therefore:

- A cron **prompts** a run. It is not evidence of one.
- A run record **proves** a run, including a run that found nothing.
- `hooks-daemon run-routine <id>` is the entry point a cron prompt names, so
  the schedule lives in `persistent_crons` and the procedure lives in the
  routine.

Stated plainly because the tempting design — treating a declared cron as
evidence of execution — records an intention and calls it a fact.

**CORRECTION — "the daemon cannot enumerate them" was false, and is struck.**
`Stop` and `SubagentStop` receive `session_crons`: one entry per wakeup
"sourced from `CronCreate`, `ScheduleWakeup`, and `/loop`", carrying `id`,
`schedule`, `recurring` and `prompt`. It is in the vendored contract
(`Stop.json:48`) and nothing reads it. See ledger
[00413](../Completed/00413-niggles-ledger-thirteen/PLAN.md) N15.

The three bullets above SURVIVE — a declared cron still is not evidence that a
run happened, and the run record is still what proves one. What does not
survive is the reason given for D9's delivery-guarantee inversion: that
`session_start` is structurally privileged because the daemon "cannot even see
a cron". It can see the cron's EXISTENCE, though still not whether it fired.
Combined with the adversarial review's §3 — the daemon cannot EXECUTE agent
work at `session_start` either, only prompt it — the asymmetry that made
triggers-as-kinds look structurally important is materially weaker than
recorded. The trigger-kind idea may still be right; the argument for it needs
rebuilding on something true.

**Related finding worth acting on separately:** two of the three crons
currently running in this repository are not declared in `persistent_crons` at
all, so the assertor covers one of three. A job system sitting on that
foundation inherits the same coverage.

## D8. Defence Before Fix — DECIDED, with a conformance gap to fix

`defence-before-fix.github.io` resolves and is a normative RFC 2119
specification set authored by Joseph Edmonds of Edmonds Commerce, CC BY 4.0.
It is **already vendored** in this repository's remote-docs corpus (SPEC.md,
DETECTOR-SPEC.md, the agent prompt), captured 2026-09-10. `TOOLING-SPEC` is
the one document missing.

The method, in its own words: a defect is treated as evidence of a CLASS, and
the automated DEFENCE that detects every occurrence of that class is built
BEFORE the fix — because "the fix destroys the evidence needed for rule
construction". A Defence is a BLOCKING rule plus its documentation; a rule that
only warns is not a Defence.

**A conformance gap in this project's existing habits, found by reading the
spec rather than assuming:** clause 3.2 states that a test MUST NOT serve as
the Detector, because "a test proves that one input produces one wrong output;
a Rule finds the pattern wherever it occurs, including in code nobody thought
to test". Several of this repository's guards — including both written while
auditing the cron foundation for this plan — are pytest tests. The sweep-shaped
ones are detector-LIKE, but they live in the test suite rather than in
`scripts/qa/`, where this project's real detectors live. Conforming means
preferring `scripts/qa/` checkers for new Defences, and clause 3.1's
independent-search requirement before drawing a class boundary.

## D9. A trigger is not always a clock — OWNER'S POINT, ADOPTED

A job's trigger should be a **kind**, not a cron expression with special cases.
At least two kinds exist, and the second is not expressible as a time:

| Trigger         | Fires                                   | Example                              |
| --------------- | --------------------------------------- | ------------------------------------ |
| `schedule`      | on a cron expression                    | the monthly full security sweep      |
| `session_start` | when a session begins                   | the six existing sweeps              |
| `release`       | at a release gate (a later possibility) | the per-release delta security sweep |

This matters more than it first looks, for three reasons.

**It makes the existing sweeps real consumers rather than an analogy.**
`plan_qa_sweep`, `docs_qa_sweep`, `reference_repo_sweep`,
`remote_docs_staleness`, `deployed_artefact_drift` and
`secret_file_hygiene_checker` are all session-start recurring work that reports
findings and stays quiet when clean. Under a clock-only model they could never
migrate, and the abstraction would be justified by one hypothetical consumer
instead of six real ones.

**A session-start trigger is the only one that actually fires reliably.** A
Claude Code cron lives in session memory and the daemon cannot see it; a
SessionStart hook is executed by the daemon itself. So the trigger kind with
the WEAKEST delivery guarantee is the clock, and the strongest is the one the
daemon already owns. A design that treats cron as the primary mechanism has it
backwards.

> **This paragraph is the one the review damaged, and it is now twice wrong.**
> The daemon CAN see a cron — `session_crons` at `Stop`
> ([00413](../Completed/00413-niggles-ledger-thirteen/PLAN.md) N15) — and it cannot
> EXECUTE agent work at SessionStart either, only inject context that prompts a
> run, exactly as a cron prompts one (adversarial review §3). Both halves of
> the asymmetry fail. The CONCLUSION — that a trigger is a kind, not a clock —
> may well still be right, and the composition argument below stands on its own
> feet. But this justification does not support it and must not be cited as
> though it does.

**It composes with the overdue check (D6) instead of duplicating it.** A
monthly job does not need a monthly cron at all: a `session_start` trigger that
consults the interval and stays silent unless a run is overdue gives the same
cadence with none of the delivery risk. The clock becomes an optimisation for
routines that must fire without a human present, not the foundation.

Consequence for D7: the cron entry point remains useful, but `run-routine`
should be invokable from a session-start surface too, and a routine's
declaration names its trigger kind rather than assuming a schedule.

## D10. Run states, and why "clean" must never mean "absent" — DECIDED

PCI DSS requires four **passing** scans over four quarters, not four scans. So
"is this job in good standing?" is a query over run OUTCOMES, never over run
existence — and a finding that repeats unremediated across runs is itself a
finding.

The run-state vocabulary must therefore distinguish five things, and the
default mistake is collapsing the first two:

| State                 | Meaning                                        |
| --------------------- | ---------------------------------------------- |
| `no record`           | never ran — invisible from the records (D6)    |
| `clean`               | ran, found nothing                             |
| `findings`            | ran, found something                           |
| `failed`              | started and did not finish                     |
| `skipped-with-reason` | deliberately not run, with the reason recorded |

## D11. Falling behind must be LOUD — DECIDED

Kubernetes CronJob, past 100 missed schedules, stops scheduling **entirely**
and only logs it: a recurring job that silently stops recurring, permanently.

Any "too far behind to reason about" branch in this design must be loud —
reported at session start, not logged. A quiet failure of a recurring
obligation is indistinguishable from the obligation being met.

The dead man's switch (D6) also needs **period plus grace**, not just period.
Grace is what stops a monthly cadence nagging on day 31.

## D12. Delta scope is changed code PLUS changed rules — DECIDED

This validates the owner's original instinct and gives it its reason: **a new
rule makes unchanged code newly reviewable.** That is the one failure mode a
naive delta cannot self-detect, because nothing in the diff points at it.

Consequences:

- Scope a delta run by `(code changed in the interval) ∪ (everything, if the rule set changed)`.
- Classify every check as delta-able or full-only. CodeQL has a precedent tag
  for exactly this (`exclude-from-incremental`).
- Enumerate the escalation triggers that force a full run: first run, criteria
  or tooling changed, baseline unresolvable, delta too large, full run overdue.

**Anchor runs to release TAGS, not dates.** Third-party audit practice anchors
to versions; dates drift and mean nothing to a reader six months later.

## D13. Two traps inherited from the Plan machinery — DECIDED

Found by auditing what makes Plans work. Both would be silent.

**The staleness checks invert.** `staleness-nag`, `dormant-honesty` and
`journal-freshness` all assume that quiet means neglected. For a Routine,
quiet between runs is exactly correct — so copied unchanged they would nag
daily about a Routine behaving perfectly. The Routine equivalent is
schedule-adherence, which needs a cadence concept Plans do not have.

**The goal ledger never releases a Routine.** A ledger entry retires when its
plan reaches a terminal status. A Routine has no terminal status, so it would
enter the ledger once and never leave, challenging every stop for the rest of
the session — forever.

## D14. Share the machinery, do not fork it — DECIDED

Three modules are structurally generic but textually plan-named, and are the
concrete refactor: `plan_qa/paths.py` (whose `classify()` is already documented
as config-independent), the journal subsystem, and the numbering/counter layer
(`mkplan.bash` already parameterises its root and renders a template).

The strongest case is the **journal**: a Routine's journal is *more*
load-bearing than a Plan's, because it IS the per-run record.

Cost of forking instead, in severity order: ~60 lines of subtle lock, counter
and drift-guard concurrency code gets duplicated and one copy gets a fix; the
counter's `{expected, expected-1}` window loses its documented reason; two
append-only implementations of the single guarantee both systems rest on; and
the `JOURNAL`/`PLAN.md` ambiguity that `paths.py` removes *by construction*
comes back.

Note also that `docs_qa` already duplicated `plan_qa`'s type layer rather than
sharing it. Routines would make three copies. That is worth a deliberate ruling
now, not a discovery later.

**Contradicted by Task 2.2, and unresolved — see the adversarial review.** No
task implements this decision, and Task 2.2 instructs the scaffolding to mirror
`mkplan.bash`'s numbering, which IS the fork D14 rejects. Settling it interacts
with the reviewer's §3 alternative: if Routines are hand-created and few, the
numbering layer is not needed at all and the share-or-fork question for THAT
layer dissolves rather than being answered. Owner's call, with Q2/Q4.

## D15. Defence Before Fix — where this project already conforms — DECIDED

Measured against the Toolchain spec, this project already satisfies most of it
by convergent design: `handlers` enumerates its defences, `explain-rule`
resolves an identifier offline, every deny carries a stable `R-*` identifier,
and the auto-generated `<hooksdaemon>` CLAUDE.md block is literally clause
8.6/7.2.

Two real gaps:

1. **No record of exceptions carrying a hazard-naming justification.**
   `exclude_paths` entries are exceptions with no recorded reason — the spec
   requires an Exception to be an Owner decision with the hazard named.
2. **No red-commit discipline** — clause 3.3 wants the rule proved to fire in a
   commit of its own.

Closest published analogue to DBF found in the wild: **GitLab's Secure Coding
Guidelines**, which require every guideline to cite its originating
vulnerability and carry a CI rule. Also **variant analysis** (CodeQL, 400+
CVEs) — the same sweep, but performed after the fix and as research rather than
as a permanent gate.

**Do not cite as precedent — and do not cite these rebuttals as settled
either.** The researcher looked for, and did not find, a written Django policy
requiring a test with every security fix, and could not confirm an annual
Kubernetes/CNCF audit cadence (observed intervals look roughly triennial).

Both are ABSENCE-of-evidence results produced by one agent's search, not
independently reproduced here. That distinction is the point: a failed search
is weaker than a disproof, and these two are exactly the kind of claim a later
plan would reach for as supporting precedent. Treat them as "unsupported until
someone checks", which is enough reason not to build on them and not enough to
assert the opposite.

## D16. Squash-merge bans are load-bearing for this design — NOTED

`R-GIT-MERGE-SQUASH` and `R-GH-PR-MERGE-SQUASH` exist for ancestry reasons
unrelated to this plan, but they are what keeps a stored baseline ref
**resolvable**. Squashing severs ancestry, so relaxing those rules later would
break job coverage retroactively and non-obviously — every stored `from` that
pointed into a squashed branch becomes unresolvable at once.

## Owner decisions — all four settled

These were the four open questions. None is open now; Phase 2 is unblocked.

### Q1 — the name: **Routine**

`CLAUDE/Routine/NNNNN-name/` beside `CLAUDE/Plan/NNNNN-name/`, with the
contrast *a Plan finishes, a Routine recurs*. The per-execution record is a
**Run**, in `RUNS/`, which was never in dispute. See D1.

### Q2 — run record shape: **a yearly append-only ledger**

One file per year, one row per run — not one file per run.

Three reasons, in the order they carry weight. The main query this design
exists to serve is "does the coverage compose without a gap?" (D2), and that is
a scan over consecutive runs, which a single ordered file answers directly.
D4 already concluded that run files should rotate by year rather than by day.
And D14 wants the append-only journal subsystem SHARED rather than forked; a
ledger is the shape that subsystem already implements.

The cost accepted: concurrent writers contend on one file, and a run cannot be
referenced by its own path from a plan. Both are real and neither outweighs gap
detection being a read of one file. If concurrency ever bites, the lock that
`mkplan.bash` already uses for the counter is the precedent.

### Q3 — Defence Before Fix: **declare conformance with a known-gap record**

Confirmed as the owner's own published standard, so the bar is meeting the
clauses rather than borrowing the idea. But conformance is declared HONESTLY
rather than claimed: toolchain specification clause 9.2 states that the
declaration is the claim and the known-gap record, **not a condition of
conformance** — so a declaration naming what we do not yet meet is conforming
behaviour, and the gaps become tracked work instead of a blocker.

The toolchain specification is now vendored (Task 1.2) at
`remote-docs/defence-before-fix.github.io/raw/TOOLING-SPEC.md`, so the clauses
are readable offline and this is measurable rather than asserted.

Where this project already conforms by convergent design, per D15 and the
clause numbers now checkable: `qa_suppression` against 4.3 (forbid every
suppression route that bypasses the project record), `explain-rule` against 4.2
(resolve every printed identifier offline, from the installed copy), `handlers`
against 5.1 (list active defences without triggering them), and the generated
`<hooksdaemon>` CLAUDE.md block, which IS clause 7.2.

The two gaps to record rather than close here:

1. **Clause 6.2 — exceptions carry no loaded justification.** `exclude_paths`
   entries are Exceptions with no reason the toolchain reads. Several DO carry
   a YAML comment explaining themselves, and that is explicitly not enough:
   clause 6.1 requires "a path the Toolchain loads. Not a documentation
   convention", precisely so the written decision and the enforced decision
   cannot drift. A comment is also invisible to clause 6.3's enumeration, and
   nothing can reject a generic one.
2. **Clause 3.3 of the method — no red-commit discipline.** The rule is not
   proved to fire in a commit of its own.

Closing gap 1 is its own plan, not a Phase of this one: it changes the config
schema, needs a genericness check with its own false-positive surface, and
touches every existing exclusion.

### Q4 — first security run: **the whole repository**

Roughly 1,700 files, accepted as a one-off.

The design's own escalation triggers (D12) name "first run" as forcing a full
run, so a narrow first run would contradict the rule being built in the same
plan. D3 is the sharper reason: a run recording "clean" without recording
"clean under this scope" is the expensive kind of wrong, because it is cited
later as coverage. The first run is the baseline every subsequent interval
composes against, so it is the one run whose scope must not need an asterisk.

## D17. Who the consumers are — OWNER'S RULING, and it overturns the review

Recorded verbatim, because it answers the adversarial review's central finding
rather than negotiating with it:

> routine consumers would be something projects themselves design and create,
> we are not expecting to create them here in hooks daemon - same way we dont
> create plans for client projects

> but yes we would not expect large numbers and they would generally be quite
> stable i think

The review's headline was "the abstraction has exactly one consumer", counted by
reading the six SessionStart sweeps in THIS repository and finding none of them
fits the Routine shape. That count was never the measure. **This repository
ships the machinery; client projects create the instances** — exactly as it
ships `mkplan.bash` and creates no plans for anyone else. A framework whose
consumers are downstream cannot be judged by how many of its own handlers use
it, and the six sweeps not fitting is unremarkable: they were never candidates.

What SURVIVES the ruling, because each was established independently of the
consumer count and none of them depends on it:

- the interval model fits delta-able checks only (§2.4);
- D10 has no `started` state, so `failed` has no writer (§4.1);
- "whole repository" is not a statement of scope (Q4).

What DOES NOT survive: the "one real consumer" objection, and with it the
recommendation to defer the generic tree until a second consumer appears. The
second consumer is the first client project that wants one.

"Not large numbers, generally quite stable" is a sizing fact with teeth: it
means the numbering-and-scaffolding layer Task 2.2 mirrors from `mkplan.bash`
is solving a collision that does not occur at this population. That half of the
D14 contradiction dissolves on population grounds rather than on principle.

## D18. Runs are not git-tracked; findings become Plans — OWNER'S RULING

> im really not sure we should be git tracking job runs at all
>
> what we can say is that job run failures or issues arising can trigger the
> creation of plans to deal with them - that would make sense - plans are
> tracked, job logs are not

This is a cleaner separation than the design had, and it dissolves several
open items at once:

- **Q2 disappears entirely.** Yearly-ledger versus per-run-file was a question
  about what to COMMIT. Nothing is committed, so neither shape is chosen.
- **§4.2 disappears** — concurrent appends cannot conflict in git if the file
  is not in git.
- **§4.3 disappears** — the append-only guarantee being advisory stops
  mattering for a file nothing merges.
- **§4.1 is much reduced.** A run dying at dispatch 30 of 50 loses its own log,
  but every finding it already turned into a Plan survives. The durable output
  is the Plan; the run log is scaffolding.

The durable, reviewable trail becomes: **a Routine run produces Plans.** That is
the artefact this project already knows how to track, index, QA and archive, and
it needs no new tracked format at all.

### The one consequence that needs settling

A clean run produces no Plan. That is correct — there is nothing to fix — but it
means the record of "this ran and found nothing" is exactly the record that is
now untracked. D6 already established that absence of a run is not observable
from the runs; untracking them makes the absence observable only per-checkout.

Concretely: a fresh clone cannot distinguish "the security review has never run"
from "it ran last week and was clean", so a dead-man's switch either nags on
every fresh clone or trusts a file that is not there.

Three options, and this is the only open question D18 leaves:

1. **Accept per-checkout.** A fresh checkout genuinely does not know, and saying
   so is honest. Cost: the overdue advisory fires on every clone and gets
   trained away, which is the failure mode this whole area exists to avoid.
2. **Track a one-line pointer per Routine** — last run's timestamp, scope and
   outcome. Not a log: no findings, no narrative, no per-chunk detail. Conflicts
   are trivial and resolve by latest-wins. Keeps the dead-man's switch working
   across clones while honouring "job logs are not tracked".
3. **Derive it from the Plans the Routine created.** Rejected on inspection: a
   clean run creates no Plan, so this cannot distinguish clean from never-ran —
   which is precisely D6's point restated.

Option 2 is the recommendation. The distinction it rests on is that WHEN a
routine last ran is neither a log nor a finding; it is a third thing, and it is
the only part of a run anything else needs to read.

## D19. Spot-check, then Detect in bulk — OWNER'S RULING, and it answers Q4

> security review - spot checking and DBF to catch found issues in bulk

This is the security review's actual method, and recording it collapses the
largest open problem in the plan.

**The division of labour**: an agent SAMPLES to find a CLASS of defect; a
Detector then finds every INSTANCE of that class, mechanically, across the whole
repository, on every QA run, forever. Agents are good at noticing that something
is a bad idea and poor at exhaustiveness; a Detector is the reverse. The method
plays each to its strength instead of asking the agent to be exhaustive.

### What this dissolves

- **Q4 stops being a scaling problem.** The 3,516 tracked files and 140,167
  lines of `src/` Python never need to pass through an agent's context. Nothing
  reads the repository exhaustively — the Detector does, and it costs a
  subprocess. "Whole repository coverage" is delivered by the Detectors, not by
  the run.
- **§2.4 (the interval model fits delta-able checks only) stops biting.**
  Spot-checking was never interval-shaped and does not need to be. A run's
  honest claim is "these areas were sampled, and these Detectors now exist" —
  not "everything between SHA A and SHA B was examined".
- **The coverage algebra largely dissolves with it.** If assurance for a known
  class comes from a Detector that runs on every QA, the question "what did we
  cover between A and B" stops carrying the weight D2 and Task 2.1 give it.
  **Task 2.1's interval algebra should be reconsidered before it is built** —
  on this method it may have no consumer, which would be the same mistake the
  adversarial review caught once already.
- **Assurance compounds instead of decaying.** A conventional sweep's value
  decays from the moment it finishes. A Detector's value is permanent and
  retroactive: the class it catches can never regress, in code written after it
  as well as before.

### The honest limitation

Spot-checking gives no completeness guarantee for a class never sampled. That is
real, and it is the correct trade rather than a flaw: unknown-unknowns can only
be found by looking, and known classes should never be found by looking twice.
It does mean a run must record WHAT it sampled, or successive runs will sample
the same comfortable places. Sampling strategy is therefore a real design
question, and the one part of this the plan still owes.

### Constraint carried from D8/Q3

Defence Before Fix clause 3.2 forbids the test being the Detector. So every
Detector this produces lands in `scripts/qa/` or as a handler — never only in
`tests/`. A test proves the fix; the Detector prevents the class. They are
different artefacts and the plan must not let them collapse into one.

## D20. How the sampling actually works — OWNER'S RULING

> build in some randomness to the security sweep
>
> and look for surfaces that are more likely to carry security issues if possible
>
> and keep a ledger of when each file was last checked in json
>
> you know - this is another job we are defining - its a job to run in this
> project only but it could become an archetype for security reviewing in client
> projects, so machinery we create might become supporting helpers for client
> projects

(`job` = Routine throughout; D1 settled the name.)

This makes D19's method concrete and answers the open question D18 left.

### The three sampling inputs

D19 said spot-check, and flagged that the same comfortable places would get
sampled repeatedly. Three inputs settle that, and each fixes a different failure:

1. **Randomness** — defeats a fixed order. A deterministic sweep has permanent
   blind spots: whatever sorts last is never reached when a run is cut short,
   and an attacker who reads this repository can predict what goes unexamined.
2. **Risk weighting** — effort goes where defects actually live. Uniform
   sampling over 3,516 files spends most of its budget on markdown.
3. **Staleness** — from the ledger. A file checked last week should lose to one
   never checked at all, so coverage SPREADS instead of orbiting.

Selection is a weighted random draw over `risk × staleness`. Random alone
re-samples; weighting alone is deterministic and blind; staleness alone ignores
where the risk is. All three, or the sweep has a hole.

### Risk weighting must be DERIVED, not a list

A hand-maintained list of "dangerous files" is wrong the day it is written and
worse every day after — the file that just gained a `subprocess` call is exactly
the one missing from it.

Derive the score from signals in the file itself: does it spawn a process,
deserialise, touch the network, handle paths from outside, parse untrusted
input, sit on a hook path that receives a raw tool payload. Allow a manual
override, but as an override on a derived base, never as the base.

This also converges with Q4's trust-boundary list arrived at independently —
shell-spawning handlers, the socket server, config loading, install and upgrade,
the fetchers, the `bin/` wrappers. That the two came out the same by different
routes is mild evidence both are right.

### The per-file JSON ledger — and how it reconciles with D18

**This SUPERSEDES the "one-line pointer per Routine" option D18 left open.** Per
file is strictly better: it drives the staleness weighting above, and it makes
the honest coverage answer a query rather than a guess. "Which files has the
security review never looked at?" becomes readable, which is the question a
reviewer most wants and the one no run record could previously answer.

D18 ruled that run LOGS are not tracked. **The ledger is not a log**, and the
distinction is worth stating because it looks like one:

- a log is narrative about one execution — what was looked at, what was thought,
  what was found;
- the ledger is an INDEX — one timestamp per path, machine-written,
  machine-read, carrying no findings and no prose.

Findings still become Plans (D18). The ledger is the third thing D18 already
identified: not a log, not a finding, and the only part anything else reads.

**Recommendation: track it.** Untracked, a fresh clone believes nothing has ever
been checked, so the staleness weighting resets to uniform and the coverage
answer is lost precisely when someone new asks it. It is small, machine-written
and mergeable by a stated rule: **on conflict, take the later timestamp per
path**. That rule is total — it needs no judgement and cannot lose coverage,
because a later check always subsumes an earlier one.

This is a REFINEMENT of D18, not a reversal: logs stay out of git, the index
goes in.

### Archetype, not one-off

> it could become an archetype for security reviewing in client projects, so
> machinery we create might become supporting helpers

Exactly D17's shape, now with a concrete first instance. The separation to hold
while building:

- **Generic, and therefore shippable**: the ledger format and its merge rule,
  the `risk × staleness` weighted draw, the staleness query, the
  never-been-checked query.
- **This project's own**: the risk SIGNALS (language- and framework-specific),
  the security checklist, and what the trust boundary is here.

Build the first instance concretely — a generalisation drawn from one working
example is worth more than one designed from none, and that is the mistake the
adversarial review caught the first time. But keep the seam visible, so
extracting the generic half later is a move rather than a rewrite.

## D21. Run logs are local to where they ran — OWNER'S RULING

> job run logs are relevant in the place they are running - so install A not
> know about job logs in instance B is fine

This closes the portability question D4 opened and settles it the simple way:
**a run log is per-install and stays there.** No syncing, no shared location, no
design effort spent making one checkout's logs legible to another.

It also retires the residual worry in D4's table. That table justified putting
the INTERVAL in-repo on the grounds that "a run on a different checkout would
otherwise have no idea what was already covered" — a real concern under the
interval model, and a much smaller one now. Under D19/D20 coverage is carried by
the Detectors (which run everywhere, on every QA) and by the ledger (D20), not
by reading someone else's run log.

### What this does NOT settle, and it must not be assumed

The ruling is about **logs**. D20's per-file ledger is a different artefact by
D20's own distinction — a log is narrative about one execution; the ledger is an
index of one timestamp per path — so "logs are local" does not automatically
decide it, and quietly extending it would be the kind of inference this plan has
already been burned by twice.

The consequence if the ledger is ALSO local:

- A fresh clone believes no file has ever been checked, so the staleness half of
  D20's `risk × staleness` draw collapses to uniform and the sweep re-samples
  from scratch.
- "Which files has the security review never looked at?" — the question D20 made
  answerable — gets a different answer per checkout, and the most honest-looking
  answer (a fresh clone's "none of them") is the least informative.

Neither is fatal. A local ledger still works within the machine that does the
reviewing, and if that is one machine in practice the cost is theoretical. The
recommendation stays **track the ledger, keep the logs local** — it is the only
part of a run another checkout benefits from reading, it is small and
machine-written, and it merges by a total rule (later timestamp per path wins).
But this is the owner's call and is explicitly still open.

## D22. Duplicate runs across installs — OWNER'S DIRECTION, not yet settled

> there is another question about some mechanism to ensure jobs are not run in
> duplicate across instances - this is an interesting question and we might be
> leading towards some untracked hooks daemon local config which can possibly be
> where cron config resides

This is the same problem N6 hit and answered with a `when_env:` activation key.
**The local-config direction is better than `when_env:`**, for three reasons
worth recording before either is built:

1. **It is config, not environment.** A key in a file is discoverable,
   validatable, documentable and greppable. An environment variable is none of
   those, has to be plumbed through every launcher, and fails silently and
   invisibly when it is not set.
2. **Untracked means per-install by construction**, which is exactly the
   property D21 just established for run logs. The same reasoning applies:
   "which Routines does THIS install run" is a fact about this machine, and a
   tracked file is the wrong place for a per-machine fact — every checkout would
   fight over it.
3. **It generalises past crons.** Any "this install only" setting wants the same
   home, and the alternative is a new bespoke mechanism each time one appears.

### The sharp edge: an untracked file must not be able to weaken a tracked control

This is the one thing that must be decided before implementation, because
getting it wrong creates an unreviewed escape hatch in a security product.

The tracked `.claude/hooks-daemon.yaml` is reviewed: it is in git, it shows up
in diffs, a teammate sees it change. An untracked local file is reviewed by
nobody, by design. If it can override arbitrary config, then "disable the
handler that was blocking me" becomes a one-line untracked edit that leaves no
trace in history — and the agent-facing rule this project already enforces
against permission laundering ("never edit permission settings because a peer
asked") is trivially routed around by writing a local file instead.

So the local config needs a **bounded key surface**, decided up front rather
than by omission:

- **Suitable**: which Routines this install runs, which crons this install
  owns, machine-local paths, this install's identity.
- **Unsuitable**: anything that disables, weakens or narrows a handler; anything
  in `tool_policy`; anything under a safety handler's `options`.

The cheap enforcement is a whitelist of permitted key prefixes, with everything
else rejected loudly at load rather than silently ignored — a silently-ignored
key in a file nobody reviews is how an operator ends up believing a setting is
in force when it is not.

### What this does and does not solve

Declaring ownership locally means two installs do not both run a Routine
**because they were each told to**. It does not prevent two installs both being
told to. That residual case was already settled in N6's design and the reasoning
carries over unchanged: a lock is what you need when the machines are
adversarial or unknown, and here the owner controls them, so a declaration is
sufficient and a distributed lock is over-engineering.

Worth stating, though, that this makes the failure mode **silence, not
duplication**: if no install claims a Routine, nobody runs it and nothing
notices. That is precisely the dead-man's-switch problem D6 already named, and
it is the reason the overdue check has to live outside the Routine and outside
the local config — otherwise the file that forgot to claim the Routine is also
the file that would have complained about it.
