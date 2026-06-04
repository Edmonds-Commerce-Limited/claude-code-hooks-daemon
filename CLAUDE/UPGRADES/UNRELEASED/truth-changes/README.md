# UNRELEASED — Truth-Changes Staging

Stage per-version truth-changes files here during the release cycle. At release time
the `/release` skill moves every `v{X.Y.Z}.yaml` in this directory into the flat
`CLAUDE/UPGRADES/truth-changes/` directory (keeping the version-named filename).

A truth-change records a statement that **was true** about working in a project but
became false in a release — replaced by a **new truth** or retired. See
`CLAUDE/UPGRADES/truth-changes/README.md` for the two-key (`was`/`now`) schema and how
the `upgrade.md` flow and `check-truth-changes` CLI consume it.

**When to add a file here**: a release changes something a project's own docs are
likely to assert (a workflow, a command, a convention). One `{was, now}` entry is two
sentences. If a release changes no documented truth, add nothing.

This `README.md` stays; only `v*.yaml` files are moved at release.
