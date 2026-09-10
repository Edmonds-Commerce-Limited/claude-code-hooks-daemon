# UNRELEASED — Truth-Changes Staging

Stage per-version truth-changes files here during the release cycle. At release time
the `/release` skill moves every `v{X.Y.Z}.yaml` in this directory into the flat
`CLAUDE/UPGRADES/truth-changes/` directory (keeping the version-named filename).

A truth-change records a statement that **was true** about working in a project but
became false in a release — replaced by a **new truth** or retired. See
`CLAUDE/UPGRADES/truth-changes/README.md` for the `was`/`now` schema (plus the
optional `id` that names a truth) and how the `upgrade.md` flow and
`check-truth-changes` CLI consume it.

**When to add a file here**: a release changes something a project's own docs are
likely to assert (a workflow, a command, a convention). One `{was, now}` entry is two
sentences plus a `topic:` naming the document area it lives in (reuse an existing
slug — `grep topic:` across the live directory — so the entry joins that chunk).
If a release changes no documented truth, add nothing.

**When the truth you are revising already has an entry** in the live directory (your
`was` is roughly its `now`), give both entries the same `id` — back-fill the older
file. The report then surfaces only your entry, so an upgrading agent is never told
to assert the older truth and then contradict it.

This `README.md` stays; only `v*.yaml` files are moved at release.
