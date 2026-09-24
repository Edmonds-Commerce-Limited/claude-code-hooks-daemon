# Callout: the upgrade-guide list sees every crossed guide and the unreleased changes

**Plan**: 00376
**Audience**: operators

The "REQUIRED READING: Upgrade Guides" list that `scripts/upgrade_version.sh`
prints matched only guide directories named `v{M}.{m}-to-v{M}.{m+1}`. It
missed every patch-numbered guide, such as `v3.62.1-to-v3.63.0` and the three
after it, and every guide whose document is a `README.md`. It also never
looked in `CLAUDE/UPGRADES/UNRELEASED/`, so a breaking change staged for the
next release was invisible to a branch install. The list now covers every
guide in the range and, for a branch install, every document staged in the
holding area. The list is printed only when Layer 2 runs its full path. An
upgrade through `scripts/upgrade.sh` skips that path today (tracked in
Plan 00376), so the post-upgrade task list is the one you will see there.
