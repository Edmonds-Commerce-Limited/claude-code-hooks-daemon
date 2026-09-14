# Callout: the upgrade route works from a fresh clone of a client repository

**Plan**: 00291
**Audience**: everyone

A teammate who clones an existing client repository gets its committed
config and hook forwarders but no `.claude/hooks-daemon/` checkout and no
venv, because both are gitignored. The documented upgrade route failed in
that state: Layer 1 refused because the daemon directory was not a git
repository, and Layer 2, when run by hand, stopped a daemon that did not
exist and rolled back. The only way through was the fresh installer, which
treats the project as new and reports no migration advisories for the
versions the config predates.

`scripts/upgrade.sh` now clones the daemon for a project that already
carries a config, reads the previous version from the committed
`.claude/HOOKS-DAEMON.md` so the migration advisories cover the right range,
hands that version to Layer 2 (which used to print "Current version:
unknown" with no venv to ask), and skips the daemon stop when there is
nothing to stop. LLM-UPDATE.md says in one place which guide applies to
that state.

A daemon checkout that is not on a release tag is now visible. Such an
install carries a version stamp that names the commit, `status` prints an
`Install:` line for it every time, the session-start version check flags it
on every new session instead of ever calling it up to date, and the
migration advisories for it include the manifests staged for the next
release. `check-config-migrations` and `check-truth-changes` also take
`--include-unreleased` to read those staged manifests from any install. The
mechanism that produces such an install is first-party only and is not
documented for clients.
