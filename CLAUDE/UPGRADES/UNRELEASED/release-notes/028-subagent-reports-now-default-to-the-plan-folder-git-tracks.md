# Callout: subagent reports now default to the plan folder git tracks

**Plan**: 00422
**Audience**: client projects

`dispatch_declaration` now recommends the dispatching plan's
`subagent-reports/` folder as the default place for a subagent's report. That
folder is tracked, so commit the reports with the plan.
`untracked/agent-reports/` is gitignored and is lost when the container
goes. It is now the fallback only for work with no plan. A dispatch that names
a plan folder but sends its report to the gitignored fallback gets an
advisory. The advisory names the plan's `subagent-reports/` path, and it
never blocks the dispatch. Update any agent briefs that send plan work's
reports to `untracked/agent-reports/`. This comes from the v3.65.0 release
reviews: twenty findings were written there and came within one restart of
being lost.
