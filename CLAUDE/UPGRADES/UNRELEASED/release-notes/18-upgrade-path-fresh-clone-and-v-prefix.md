# Callout: the fresh-clone upgrade completes, and every version check accepts the tag form

**Plan**: 00362
**Audience**: client projects

A client upgrading from a fresh clone (config and forwarders present, no venv
yet) no longer rolls back at the daemon-stop step: with no venv there is no
daemon to stop, and the upgrade now says so and moves on. The truth-changes,
config-migrations and release-notes checks accept `v3.62.0` as well as
`3.62.0`, so the argument every RELEASES page and `git describe` produces
works everywhere. A re-install that keeps an existing config now prints the
config-migration advisory for it instead of retaining it silently.
