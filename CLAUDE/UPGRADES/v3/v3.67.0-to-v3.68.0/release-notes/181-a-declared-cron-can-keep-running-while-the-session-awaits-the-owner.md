# Callout: a declared cron can keep running while the session awaits the owner

**Plan**: 00470
**Audience**: operators

A stop that declares `[awaiting-human]` used to drop every declared
`persistent_crons` tick along with the failsafe's. A job can now opt out with
`runs_while_awaiting_human: true`, and its ticks are delivered while the marker
is live. This repository sets it for `issue-sdlc`, whose work does not depend on
the pending question, and leaves `failsafe-recovery` suppressed. The option
defaults to false, so a project that adds nothing sees no change.
