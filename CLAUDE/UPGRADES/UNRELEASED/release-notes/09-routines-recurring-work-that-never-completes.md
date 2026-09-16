# Callout: routines — recurring work that never completes

**Plan**: 00412
**Audience**: everyone

This project models work as PLANS: numbered, one-shot, archived when done. That
shape fits a change with an end, and fits nothing that has to happen *again* —
a security review, a dependency audit, an access re-check. Recurring work was
therefore either filed as a plan that could never honestly close, or not filed
at all and remembered by whoever remembered it.

`CLAUDE/Routine/` is the tree for that second kind. A Plan finishes; a Routine
recurs. Each routine declares its cadence and its procedure, and records every
run in a `RUNS/` ledger. `hooks-daemon run-routine <id>` starts a run, prints
the procedure, and derives the interval from the ledger rather than asking the
operator to remember it; `--finish --outcome clean|findings|skipped` closes it.

**A run that finds nothing is recorded as `clean`, which is not the same as
leaving no record.** That distinction is the whole point of the ledger, and it
is what makes the next run's interval derivable instead of recollected.

## The dead-man's switch

The hard problem is that **a run that never happened leaves no record at all**,
so its absence cannot be observed from the records themselves. Something
outside the records has to know a routine exists and assert that a run is
overdue. That is `routine_qa_sweep`, an opt-in `SessionStart` handler, and
session start is chosen because it is a surface the daemon executes itself
rather than one it can only hope fired.

It runs five checks: `routine-never-run`, `routine-overdue` (counting only a
FINISHED run), `routine-run-gap` (commits between two runs that neither
covered), `routine-ledger-unreadable`, and `routine-not-configured`.

It is silent on a clean tree and never raises. A sweep that dies must report
nothing and so must a healthy tree — but those two outcomes must never be
confused, so a read failure reports "could not read" rather than silence.

## Opt-in, and why

`routine_qa_sweep` ships disabled. Most projects have no `CLAUDE/Routine/`
tree, and a handler that fires with nothing to say becomes scenery nobody
reads. Enabling it needs no other action: `matches()` fires only when the tree
actually declares at least one routine.

## What running it found

The machinery was exercised end to end before shipping, and three defects came
out of RUNNING it that READING it had not produced — all one class, **a record
of non-coverage read as coverage**. A skip reset the overdue clock; a routine
whose only rows were skips or an unfinished start was reported by no check at
all; and both procedures derived the interval start as "the last recorded run
(any outcome)", which is undefined after a skip. Each was fixed with its
Detector proved red first.

If you adopt routines, that is the failure mode to watch for in your own: the
gap between a routine that is healthy and a routine nobody has run is invisible
unless something is built specifically to see it.
