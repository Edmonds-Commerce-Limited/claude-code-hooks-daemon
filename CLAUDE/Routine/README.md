# Routines Index

A Plan finishes; a Routine recurs.

This directory holds **recurring work that never completes** — the second work
concept beside [Plans](../Plan/README.md). A Plan is numbered, one-shot and
archived on completion, which fits recurring obligations badly: a plan that is
never finished sits in the Active list for ever, and a recurring obligation
becomes indistinguishable from a stalled one.

A Routine has no completion. It has a definition (`ROUTINE.md`) and a record
per **run**, in `RUNS/`.

Design rationale, decisions and the research behind them:
[Plan 00412](../Plan/00412-jobs-recurring-work-and-security-review/DESIGN.md).

## Active Routines

| Routine                                                               | Trigger           | Covers                                                           |
| --------------------------------------------------------------------- | ----------------- | ---------------------------------------------------------------- |
| [00001 security review full](00001-security-review-full/ROUTINE.md)   | schedule, 90 days | Every check in [CHECKS.md](00001-security-review-full/CHECKS.md) |
| [00002 security review delta](00002-security-review-delta/ROUTINE.md) | release           | The delta-able checks only, over one release's diff              |

The two are a pair, not a duplicate. The delta sweep is structurally blind to
any finding whose cause is not in the diff — a dependency that acquired a CVE
without changing, an exemption list that only became too broad on its ninth
entry — and the full sweep is the compensating control for exactly that. They
keep **separate ledgers** so that a delta run cannot reset the full sweep's
overdue clock; sharing one would let a project that releases often defer its
full sweep for ever while every record read as healthy.

## Directory shape

```
NNNNN-name/
  ROUTINE.md      the definition: purpose, scope, procedure, trigger
  RUNS/
    <year>.md     append-only ledger, one row per run
```

`RUNS/` is created empty when a routine is scaffolded — and git does not track
an empty directory, so on a fresh clone it is simply absent until the first run
writes to it.

That is fine, and it is worth saying why rather than propping the directory up
with a placeholder file. "This routine has never run" and "nobody created the
runs directory" are different facts, but only the first is interesting, so the
reader collapses them on purpose: a missing `RUNS/` and an empty one both yield
no events, and the writer creates the directory on its first append. Nothing
anywhere has to decide which of the two it is looking at.

Discovery does not depend on it either — a routine is a numbered folder holding
a `ROUTINE.md`, so a clone finds every routine whether or not any has run.

## What ROUTINE.md declares

```
**Status**: Active | Retired
**Trigger**: schedule | session_start | release
**Period**: 30 days        # schedule only
**Grace**: 7 days          # optional
```

`Trigger` is a closed set rather than free text. A cadence written in prose has
to be interpreted, and a misread cadence produces an overdue date that is wrong
without being detectably wrong.

**A `release` trigger carries no clock, deliberately.** A routine prompted by
a release is expected to sit beside a scheduled full sweep of the same ground,
and that full sweep is its backstop: a delta run that never happened simply
widens the next full run's interval, which is the compensating control rather
than a second thing to nag about. Declaring a `Period` on one is therefore
ignored for overdue purposes — reporting it late against a calendar nobody
keeps would be a nag that trains its reader to skim.

**A period on its own is not enough.** A monthly routine with no grace is
overdue on day 31, every month, for ever — a nag that arrives reliably and is
ignored just as reliably, which is how a recurring obligation stops being one.
An omitted `Grace` therefore takes a fifth of the period (minimum one day)
rather than zero, since zero is exactly the value that causes that. A `Grace`
declared as `0 days` is honoured: only an omission takes the default.

A scaffolded routine leaves these as placeholders, which read as **not
declared**. That is deliberate too — writing a plausible cadence into the
skeleton would hand every new routine a schedule nobody chose.

## Creating a routine

```
CLAUDE/Routine/mkroutine.bash "descriptive-kebab-name"
```

The number comes from the git-anchored counter `hooksdaemon.latestRoutineNumber`
under a lock, never from a folder scan — a scan misses archived routines and
disagrees across branches, which is how two routines end up sharing a number
and the collision surfaces only at the commit gate. Routines number
**independently of Plans**: the two counters are separate keys, so a Routine
never consumes a Plan number.

The script prints the new folder path on stdout and everything human-facing on
stderr, so `dir=$(CLAUDE/Routine/mkroutine.bash "name")` works. You still add
the index row above yourself.

It is not deployed to client projects. The machinery is all here — a run CLI
(`hooks-daemon run-routine`), the drift checks (`hooks-daemon routine-qa`) and
the session-start dead-man's switch — but this repository is the only one so
far with routines to run, and a scaffolder deployed before anyone has a use for
it becomes a file people delete rather than a tool they reach for.

## Two things a run record must hold

**Coverage is an INTERVAL, never a pointer.** Each run records the span it
covered, `from -> to`, each end a commit or a tag. Intervals compose: laying
two runs end to end either meets, overlaps or leaves a hole, and a hole is
arithmetic rather than judgement. A mutable "last run" pointer bumped wrongly
once — by a crash, a rebase or a careless edit — is silently wrong for ever and
nothing can detect it afterwards. The algebra is
[`routines/intervals.py`](../../src/claude_code_hooks_daemon/routines/intervals.py).

**A run that found nothing is recorded as distinctly as one that found
something**, and both differ from never having run. Absence of a record is not
observable from the records themselves, so something outside a Routine has to
assert that a run is overdue.

## What this is not

Not a scheduler, and it must not become one. Claude Code crons live in session
memory and the daemon cannot read them, so "runs every hour" is unsupportable
while "declared, plus every run that recorded itself" is supportable. A
declared cron PROMPTS a run; the record PROVES one. Any design that treats the
declaration as evidence of execution is recording an intention and calling it a
fact.
