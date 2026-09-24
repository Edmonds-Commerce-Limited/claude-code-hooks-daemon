# Callout: every upgrade now checks your config and lists the target's guides before deploying

**Plan**: 00376
**Audience**: operators

The config compatibility check and the "REQUIRED READING: Upgrade Guides"
list never ran on a normal upgrade. `scripts/upgrade.sh` checks the target
out before it hands over, so the version-specific script always took its
already-at-target path, which skipped both. Run directly, the script checked
the old checkout, which cannot hold a guide for the version being installed.
Both now run on every route that runs this release's upgrade script: the
fetched `scripts/upgrade.sh`, `/hooks-daemon upgrade`, a direct call of the
version-specific script, and the manual route in `CLAUDE/LLM-UPDATE.md`,
which now runs the target's own `upgrade.sh` out of the daemon clone. They run
after the target is checked out and before anything is deployed into your
project. The reading list starts from the version you have installed; the
config check compares your previous version against the target's handlers.

The list also misses fewer guides. It used to match only directories named
`v{M}.{m}-to-v{M}.{m+1}`, so it skipped every patch-numbered guide (such as
`v3.62.1-to-v3.63.0`) and every guide whose document is a `README.md`. It now
covers every guide in the range. A branch install also lists the documents
staged for the next release under `CLAUDE/UPGRADES/UNRELEASED/`.

The config check only reports. The reading list is now the first half of the
pre-deploy gate (see "the upgrade stops before deploying until you confirm
what it listed"). The interactive "have you read the guides?" prompt it
replaces read the old checkout, so it could never fire.
