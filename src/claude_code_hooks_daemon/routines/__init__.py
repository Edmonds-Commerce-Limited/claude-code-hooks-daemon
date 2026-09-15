"""Routines — recurring work that never completes (Plan 00412).

A Plan is numbered, one-shot and archived on completion. That shape fits
everything this project has been asked to do, and fits recurring work badly: a
plan that is never finished sits in the Active list forever, which is how a
recurring obligation becomes indistinguishable from a stalled one.

A Routine is the second concept — a definition, plus a separate record per RUN
rather than a completion. The first consumer is a security review, but the
core is deliberately generic: this repository already has six recurring sweeps
implemented as bespoke SessionStart handlers, each independently reinventing
"run periodically, report findings, stay quiet when clean".

**This package is NOT a scheduler and must not become one.** The daemon cannot
guarantee that anything ran: Claude Code crons live in session memory and the
daemon cannot read them. "Runs every hour" is unsupportable; "declared, plus
every run that recorded itself" is supportable. Any design that treats a
declared cron as evidence of execution is recording an intention and calling
it a fact.
"""
