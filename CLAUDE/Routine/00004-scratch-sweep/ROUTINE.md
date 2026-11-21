# Routine 00004: scratch sweep

**Status**: Active
**Created**: 2026-11-21
**Owner**: joseph
**Trigger**: schedule
**Period**: 7 days
**Grace**: 3 days

## Purpose

Scratch entries under `untracked/scratch/` (and the configured sweep root) expire after their TTL, and anything worth
keeping is filed where git carries it (Plan 00627). The sweep is what moves expired entries into the archive store and
names the entries overdue for filing. If it stops running, scratch grows again until the caps fire; this routine's
dead-man's switch is what reports the stopped sweep before that (Plan 00627 DESIGN.md section 10, threat table).

## Scope

Every scratch root of this checkout: the entries the sweep judges due, the archives about to expire, and the cap
levels. Each run is a full run; there is no delta form.

## Procedure

1. Report: `bin/hooks-daemon scratch-sweep` (dry run; changes nothing). Read the verdict counts, the overdue-to-file
   list and the cap lines.
2. File each overdue entry worth keeping with the filing command the report prints, before it is packed.
3. Apply: `bin/hooks-daemon scratch-sweep --apply` from an interactive terminal (it asks for confirmation on a TTY;
   an unattended agent cannot run this step and records the run as `apply pending (TTY)`).
4. Record the run in `RUNS/<year>.md`.

## What a run records

Every run appends one row to `RUNS/<year>.md`, covering:

- the interval it covered, `from -> to` (a commit or tag at each end) —
  never a mutable "last run" pointer, so a gap between runs stays detectable;
- the outcome, including `no findings`, which is recorded as distinctly as a
  run that found something and is NOT the same as never having run;
- for a delta run, which checks it did NOT perform.

## Non-Goals

- Deciding what is worth keeping: the filing commands and the value test in Plan 00627 DESIGN.md section 3 do that.
- Removing anything without its hold window: removal is the archive store's job, never this routine's.
