# Callout: a breaking upgrade needs the owner's one-shot approval

**Plan**: 00376
**Audience**: operators

Confirming what you read is not enough when an upgrade breaks your project.
That covers a MAJOR version, a crossed config-changes manifest that declares
`breaking: true`, and a `critical` pre-upgrade task with hits. The gate then
stops with exit `4` until the project owner runs
`hooks-daemon approve-upgrade <version>`. That records one approval, and the
next upgrade to that version run with `--skip-reading-confirmation` consumes
it. Agents are told to report and stop, never to record it themselves. The
same idiom already covers `approve-merge` and `approve-plan-close`.
