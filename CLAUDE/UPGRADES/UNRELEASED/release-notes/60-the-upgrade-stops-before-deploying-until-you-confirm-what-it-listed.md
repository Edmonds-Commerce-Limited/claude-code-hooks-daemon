# Callout: the upgrade stops before deploying until you confirm what it listed

**Plan**: 00376
**Audience**: operators

Every upgrade that runs this release's upgrade script now runs a pre-deploy
gate once the new version is checked out and before anything reaches your
project. When the gate lists something (the upgrade guides you cross, a
pre-upgrade task that found a call site in your project, a breaking change),
the upgrade stops, deploys nothing and exits `3`. Read the list, do what it
says, and re-run with `--skip-reading-confirmation=<digest>`, using the digest
the stop printed. The digest belongs to that listing: a bare flag, or one from
an earlier listing, stops again. It does not matter whether a terminal is
attached: an agent and a human get the same stop. An upgrade with nothing to
list continues without comment.

The gate compares the target with the version you have INSTALLED, not with
whatever the daemon checkout holds: the venv's version stamp, else the version
in your committed `.claude/HOOKS-DAEMON.md`. So a fresh clone of your project,
a checkout moved by hand and a re-run all see the real range. On a stop it
puts the checkout back on that installed version. If neither source names a
version, the gate cannot rule anything out and asks for the owner (see "a
breaking upgrade needs the owner's one-shot approval").

An upgrade script older than the gate (an installed daemon's own
`scripts/upgrade.sh`, or a pinned `HOOKS_DAEMON_UPGRADE_REF` older than this
release) cannot pass the flag and still reports a stop as success. The new
version's own script restores the checkout anyway and prints
`THE UPGRADE DID NOT COMPLETE` with the command that runs the new release's
`upgrade.sh` from your clone. `scripts/upgrade.sh` now also exits with the
version-specific script's own code; it used to exit `0` when that script
failed.
