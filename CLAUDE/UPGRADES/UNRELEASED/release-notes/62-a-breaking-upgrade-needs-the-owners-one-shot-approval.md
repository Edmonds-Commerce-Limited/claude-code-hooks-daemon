# Callout: a breaking upgrade needs the owner's one-shot approval

**Plan**: 00376
**Audience**: operators

Confirming what you read is not enough when an upgrade breaks your project.
That covers a MAJOR version, a crossed config-changes manifest that declares
`breaking: true`, a `critical` pre-upgrade task with hits, and an installed
version the gate cannot read. The gate then stops with exit `4` until the
project owner approves that one upgrade, in their own terminal: the approval
asks them to type a phrase naming both versions, and its marker is bound to
those versions and to this install, so an agent cannot record it and a marker
made by hand does not count. The stop prints two commands for it:
`hooks-daemon approve-upgrade <target> --from <installed>`, and one that runs
the approval from the new release's own code in the daemon clone. Use the
second while the installed daemon predates `approve-upgrade`, which it does on
every project's first gated upgrade. Then re-run with the same
`--skip-reading-confirmation=<digest>`; the approval is removed once that
upgrade completes, so a failure after the gate does not spend it.

Which upgrades stop here: only those that cross a manifest declaring
`breaking: true` (today, v3.58.0's), a MAJOR version, or a detected
`critical` task. An upgrade from v3.64.x or later to this release crosses
none of them. See "the first gated upgrade and what it asks of the owner".
