# Callout: an upgrade keeps running the opt-in handlers that were running before it

**Plan**: 00474
**Audience**: everyone

When a rule change would stop opt-in handlers that your project was running, the upgrade now writes `enabled: true` for each of them into `.claude/hooks-daemon.yaml` (comments and layout are kept), so your real configuration carries across the upgrade. The upgrade summary names each handler, says what it wrote and why, and how to change it: set the handler's `enabled: false`, or delete its block. If the config's layout cannot be edited safely, nothing is written and the summary prints the YAML to add by hand, as before.

Also: `.claude/fake-values.yaml` is pre-filled with visibly fake examples for the kinds docs are likely to need, and the docs QA check `unlisted-fake-value` reports any registry entry that does not look obviously fake.

Nothing to do on upgrade beyond reading the summary; review the handlers it kept and disable any you did not want.
