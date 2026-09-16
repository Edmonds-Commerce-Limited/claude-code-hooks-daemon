# Routine 00001: security review full

**Status**: Active
**Created**: 2026-09-15
**Owner**: dev
**Trigger**: schedule
**Period**: 90 days
**Grace**: 14 days

## Purpose

This repository's whole product is guards: handlers that deny a dangerous
command, refuse a dangerous write, or refuse to reveal protected material. A
defect in one of them does not look like a defect. It looks like a command
being allowed, which is what the overwhelming majority of commands are.

That is the obligation this routine discharges: nothing in the normal working
of the project ever reports "this guard stopped covering the thing it was
written for". A test suite proves the guards still do what their tests say;
it cannot notice that the set of things worth guarding has moved.

If this routine stops running, nothing breaks, nothing goes red, and the
protection decays silently. The decay is the failure mode — not any single
finding.

## Scope

A **full** sweep: every check in
[CHECKS.md](CHECKS.md), over the whole tree, with no reliance on what changed.

Its counterpart is [Routine 00002](../00002-security-review-delta/ROUTINE.md),
a narrower per-release sweep over changed code and changed rules. The two are
not duplicates and neither replaces the other:

- a **delta** run is fast, runs often, and is **structurally blind** to every
  finding whose cause is not in the diff — an unchanged dependency that
  acquired a CVE, an exemption list that only became too broad on its ninth
  entry, a bypass created by two files that both stayed still;
- this **full** run is the compensating control for exactly that blindness.

Because they cover different check sets, they keep **separate ledgers**. That
is deliberate, and it is the load-bearing reason they are two routines rather
than two modes of one: a shared ledger would let a delta run reset this
routine's overdue clock, and a project that releases often would defer its
full sweep for ever while every record read as healthy.

## Procedure

1. Open the run: `bin/hooks-daemon run-routine 00001-security-review-full`.
   This writes a `started` row. A run that dies from here on is derivable as
   `failed` — started and did not finish — which is a different fact from
   never having started.

   It also **states the interval**, so `from` is derived rather than
   remembered: it is the `to` of the last run that recorded COVERING
   something, read out of `RUNS/`. A skipped run carries no `to` because it
   covered nothing, so it leaves the start where it was and widens this run's
   interval instead (D5). A first run's `from` is the repository's root commit,
   which the ledger cannot know and will say so rather than guess.

2. Choose `to`: the current release tag, or `HEAD` if there is no tag since.

3. Dispatch the `security-reviewer` agent once per check in
   [CHECKS.md](CHECKS.md), giving it the interval and that check alone. One
   check per dispatch: a reviewer asked for "anything security-relevant"
   returns the findings that are easy to phrase, and a clean result from such a
   brief cannot be told apart from a thorough one.

   Each dispatch must state the check id, the interval `from -> to`, and where
   to write its report. The agent reports; it never fixes. If it says a check
   was **not answerable**, that is not a clean result — record it as a check
   this run did not perform, exactly as a delta run records its full-only set.

   **OPEN DEFECT — the reviewer cannot write the report this step demands.**
   `.claude/agents/security-reviewer.md` declares `tools: Read, Grep, Glob, Bash`
   and no `Write`, so the contract above and the agent's tool list disagree.

   This is not theoretical and it is not cosmetic. Every dispatch in Routine
   00002's run 2026-001 hit it: three reviewers independently reached for a Bash
   heredoc — the one write path that the pre-write content guards never
   inspect — and one lost its report entirely, surviving only because its
   findings were transcribed from the returned message by the dispatching agent,
   who could not verify them. **So the workaround this defect forces is
   specifically the one that routes a security report around the guard that
   would check it for disclosure, in a public repository.**

   Until it is closed: after every run, READ each report before staging it, and
   if any is missing, transcribe it from the returned message and mark the file
   as recovered rather than authored.

   Two candidate remedies, neither taken here because both change a contract on
   the eve of a release: give `security-reviewer` the `Write` tool scoped to the
   reports directory, or make the DISPATCHING agent write each report from the
   returned summary. Nothing should be loosened to paper over it.

4. Record every confirmed finding in the [security register](../../Security/README.md),
   under its category, naming its Defence. A category with no Defence yet is
   written only once the Defence exists — the register must not claim coverage
   it does not have.

5. Fix under **Defence Before Fix**: the Defence lands before the fix, every
   time, and each Defence is a Detector in `scripts/qa/` wired into
   `run_all.sh`. A regression test proves one instance was fixed; a Detector
   finds the whole class and keeps finding it.

6. Close the run:
   `bin/hooks-daemon run-routine 00001-security-review-full --finish --outcome clean|findings --from <ref> --to <ref>`.

7. If the run cannot proceed, close it as `skipped` **with its reason**. A
   skipped run is a real, recorded state; an abandoned one is indistinguishable
   from a crash.

## What a run records

Every run appends rows to `RUNS/<year>.md`, covering:

- the interval it covered, `from -> to` (a commit or tag at each end) —
  never a mutable "last run" pointer, so a gap between runs stays detectable;
- the outcome, including `clean`, which is recorded as distinctly as a run
  that found something and is NOT the same as never having run;
- for any check it did not perform, which one and why. A full run that skipped
  a check is a delta run wearing the wrong label, and recording it as a full
  run would retire the compensating control without anyone deciding to.

## Non-Goals

- **Not a vulnerability scanner.** Tooling that runs on every commit belongs
  in `scripts/qa/`, not here. This routine exists for the judgements a tool
  cannot make.
- **Not a release gate.** Releases stay human-gated and this routine never
  blocks one; a finding produces a Defence and a fix, on their own schedule.
- **Not a place to record findings.** Findings live in the living security
  documentation, by category. `RUNS/` records that a run happened and what it
  covered.
