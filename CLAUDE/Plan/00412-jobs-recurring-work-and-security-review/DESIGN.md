# Plan 00412 — design decisions

Written from four research reports in `subagent-reports/`. Each section states
the decision, the reasoning, and — where it is genuinely the owner's call —
what is being asked. Nothing here is implemented; the plan is in review.

## D1. The name — OWNER DECISION REQUIRED

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

Claude Code crons live in session memory, `durable` has no effect, recurring
jobs expire after seven days, and the daemon cannot enumerate them. Therefore:

- A cron **prompts** a run. It is not evidence of one.
- A run record **proves** a run, including a run that found nothing.
- `hooks-daemon run-job <id>` is the entry point a cron prompt names, so the
  schedule lives in `persistent_crons` and the procedure lives in the job.

Stated plainly because the tempting design — treating a declared cron as
evidence of execution — records an intention and calls it a fact.

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

**It composes with the overdue check (D6) instead of duplicating it.** A
monthly job does not need a monthly cron at all: a `session_start` trigger that
consults the interval and stays silent unless a run is overdue gives the same
cadence with none of the delivery risk. The clock becomes an optimisation for
jobs that must fire without a human present, not the foundation.

Consequence for D7: the cron entry point remains useful, but `run-job` should
be invokable from a session-start surface too, and a job's declaration names
its trigger kind rather than assuming a schedule.

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
`journal-freshness` all assume that quiet means neglected. For a recurring job,
quiet between runs is exactly correct — so copied unchanged they would nag
daily about a job behaving perfectly. The Jobs equivalent is
schedule-adherence, which needs a cadence concept Plans do not have.

**The goal ledger never releases a Job.** A ledger entry retires when its plan
reaches a terminal status. A Job has no terminal status, so it would enter the
ledger once and never leave, challenging every stop for the rest of the
session — forever.

## D14. Share the machinery, do not fork it — DECIDED

Three modules are structurally generic but textually plan-named, and are the
concrete refactor: `plan_qa/paths.py` (whose `classify()` is already documented
as config-independent), the journal subsystem, and the numbering/counter layer
(`mkplan.bash` already parameterises its root and renders a template).

The strongest case is the **journal**: a Job's journal is *more* load-bearing
than a Plan's, because it IS the per-run record.

Cost of forking instead, in severity order: ~60 lines of subtle lock, counter
and drift-guard concurrency code gets duplicated and one copy gets a fix; the
counter's `{expected, expected-1}` window loses its documented reason; two
append-only implementations of the single guarantee both systems rest on; and
the `JOURNAL`/`PLAN.md` ambiguity that `paths.py` removes *by construction*
comes back.

Note also that `docs_qa` already duplicated `plan_qa`'s type layer rather than
sharing it. Jobs would make three copies. That is worth a deliberate ruling
now, not a discovery later.

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

## Open questions for the owner

1. **D1 — the name.** Job (yours) or Routine (research recommendation)?
   Everything else can proceed either way.
2. **Run record shape**: one file per run, or an append-only yearly ledger with
   one row per run? The ledger is cheaper to scan for gaps; separate files are
   easier to write concurrently and to reference from a plan.
3. **Is Defence Before Fix yours?** If so, "engage with it" means conform this
   project to our own published standard, which raises the bar from "borrow
   the good idea" to "meet the clauses" — including the test-is-not-a-Detector
   rule above.
4. **Scope of the first security run**: whole repository, or start with the
   handler surface and widen? The full sweep over ~1,700 files is a large
   first run.
