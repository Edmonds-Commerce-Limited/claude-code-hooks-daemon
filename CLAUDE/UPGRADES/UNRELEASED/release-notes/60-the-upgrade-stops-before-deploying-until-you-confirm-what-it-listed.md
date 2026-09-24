# Callout: the upgrade stops before deploying until you confirm what it listed

**Plan**: 00376
**Audience**: operators

Every upgrade now runs a pre-deploy gate once the new version is checked out
and before anything reaches your project. When the gate lists something (the
upgrade guides you cross, a pre-upgrade task that found a call site in your
project, a breaking change), the upgrade stops. It puts the daemon checkout
back on your previous version and exits `3`. Read the list, do what it says,
and re-run with `--skip-reading-confirmation`, which `scripts/upgrade.sh` and
`/hooks-daemon upgrade` now accept. It does not matter whether a terminal is
attached: an agent and a human get the same stop. An upgrade with nothing to
list continues without comment. `scripts/upgrade.sh` now also exits with the
version-specific script's own code; it used to exit `0` when that script
failed.
