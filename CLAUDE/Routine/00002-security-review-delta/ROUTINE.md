# Routine 00002: security review delta

**Status**: Active
**Created**: 2026-09-15
**Owner**: dev
**Trigger**: release

## Purpose

Keep the amount of unreviewed change small, so the periodic full sweep
([Routine 00001](../00001-security-review-full/ROUTINE.md)) is never the first
time anybody looks at a quarter of the repository at once.

A review whose interval is one release is a review somebody can actually do.
A review whose interval is ninety days of work is one that gets skimmed, and a
skimmed review records itself as a run.

## Scope

Only the **delta-able** checks in
[CHECKS.md](../00001-security-review-full/CHECKS.md) — `D-EXEC`, `D-EVAL`,
`D-PATH`, `D-NET`, `D-SEC`, `D-RULE`, `D-DEP`, `D-PUB` — over the diff between
two release tags (D12: runs anchor to tags, not dates).

The **full-only** checks in that document are not attempted here and must not
be. They cannot be answered from a diff — an unchanged dependency that acquired
a CVE, an exemption list that only became too broad on its ninth entry — so
attempting them would produce a confident "nothing found" from a method
structurally incapable of finding anything.

**This routine has no clock, deliberately.** It is prompted by a release, and
its backstop is Routine 00001 rather than an overdue date: a delta run that
never happened simply widens the next full run's interval (D5). Giving it a
period as well would nag about a cadence nobody keeps, and a nag that arrives
reliably is ignored just as reliably.

## Procedure

1. Open the run: `bin/hooks-daemon run-routine 00002-security-review-delta`.

   It **states the interval**, so `from` is derived rather than remembered: it
   is the `to` of the last run that recorded COVERING something, read out of
   `RUNS/`. A skipped run carries no `to` because it covered nothing, so it
   leaves the start where it was and widens this run's interval instead (D5).
   A first run's `from` is the previous release tag, which the ledger cannot
   know and will say so rather than guess.

2. Choose `to`: the tag being reviewed.

3. Produce the diff for the interval and dispatch the `security-reviewer` agent
   once per delta-able check, giving it the diff and that check alone. A
   dispatch that names two checks, or none, is one the agent is told to refuse.

4. Record confirmed findings in the [security register](../../Security/README.md),
   and fix under **Defence Before Fix** — the Defence, as a Detector in
   `scripts/qa/`, lands before the fix.

5. Close the run, naming the checks not performed:

   ```
   bin/hooks-daemon run-routine 00002-security-review-delta --finish \
     --outcome clean --from v1.2.3 --to v1.2.4 \
     --note "delta run; full-only not performed: F-CVE F-EXPT F-BYPS F-GAP F-DEPL F-HYG F-PRIV"
   ```

   The note is not bookkeeping. Without it the record claims the interval was
   reviewed, and the next reader has no way to learn that seven checks never
   ran over it.

## What a run records

Every run appends rows to `RUNS/<year>.md`, covering:

- the interval it covered, `from -> to`, tag to tag;
- the outcome, `clean` recorded as distinctly as `findings`;
- **which checks it did not run** — always at least the full-only set, plus any
  delta-able check it skipped and why.

This routine's ledger is separate from Routine 00001's, because the two cover
different check sets. A shared ledger would let a delta run reset the full
sweep's overdue clock, and a project that releases often would defer its full
sweep indefinitely while every record read as healthy.

## Non-Goals

- **Not a release gate.** Releases are human-gated; this routine runs beside a
  release and never blocks one.
- **Not a substitute for the full sweep.** It is structurally blind to a class
  of finding, which is the entire reason Routine 00001 exists.
- **Not a place to record findings.** Those live in the living security
  documentation, by category.
