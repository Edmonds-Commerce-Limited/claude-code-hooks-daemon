# Callout: branch guard notices state intent and action

**Plan**: 00583
**Audience**: client projects

The surfaces that name idle branches read as a status report, so unfinished work branches were left in place across
many stops. The main-thread Stop context line for idle branches and the `branch-sweep` "Dormant:" section now state the
branch-limit principle (work must finish, not disappear), tell the session to take that work on, and give each branch
its next step: finish and merge it, `branch-park <name> --reason ...`, or `delete-branch <name>` when the guard proves
nothing is lost. The `R-BRANCH-WIP-CAP` deny no longer offers "continue in one of them" as a way past the cap; it
demands finishing (merging), parking or proven-safe deletion first. Thresholds, caps and which branches are judged are
unchanged. GitHub #192.
