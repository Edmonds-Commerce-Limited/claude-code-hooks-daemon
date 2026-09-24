# Callout: pre-upgrade tasks name your affected call sites before the new version lands

**Plan**: 00376
**Audience**: client projects

A release can now ship `pre-upgrade-tasks/`, which are post-upgrade tasks' twin
for changes your own tooling must absorb before the new version runs. Each task
carries a `**Detect**` pattern. The gate runs it over your project and names
every hit at `file:line`, and a task that finds nothing stays silent.
The first one covers v3.64.0's `plan-qa --json` rename of `level` to
`severity`, so an upgrade from v3.63 or earlier that parses that output is
stopped with the lines to rewrite. `check-post-upgrade-tasks` takes
`--project-root` and runs a post-upgrade task's pattern too, and the upgrade
script's end-of-run report now says, per task, whether it was detected and
where. Both task shapes share one schema, which CI now enforces.
