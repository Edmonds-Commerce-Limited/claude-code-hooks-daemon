# UNRELEASED — Config-Changes Staging

Stage the per-version config-changes manifest for the in-flight release here. At
release time the `/release` skill moves every `v{X.Y.Z}.yaml` in this directory
into the flat `CLAUDE/UPGRADES/config-changes/` directory (keeping the
version-named filename) **and sets its `date:` to the release date**.

Draft the file here with `date: "UNRELEASED"` — the release date genuinely does
not exist yet. That placeholder is correct only while the file is in THIS
directory; once moved it asserts a false fact about when the version shipped,
which the `unreleased-manifest-date` repo-hygiene rule fails the QA gate on.

A config-changes manifest documents `added` / `renamed` / `removed` / `changed`
config keys for a version. The advisory (`check-config-migrations`) diffs it
against a client's config and surfaces what is new or recommended on upgrade.
See `CLAUDE/UPGRADES/config-changes/SCHEMA.md` for the full schema, including the
`recommended` / `dormant` / `recommended_value` promotion fields.

**When to add/extend the file here**: a release adds a config option, renames or
removes one, or flips a default. If a release adds an **opt-in** feature or
**flips a default** (so a feature would otherwise ship dormant), mark it
`recommended: true` (and `recommended_value:` for a flip) so the upgrade advisory
actively promotes enabling it instead of letting it sit silently inert.

This `README.md` stays; only `v*.yaml` files are moved at release.
