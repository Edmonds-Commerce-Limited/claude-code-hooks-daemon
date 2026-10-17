# Callout: four fixes found by CI after the subagent-tier release work

**Plan**: 00474
**Audience**: client projects

- **A deeply nested config no longer kills the daemon.** libyaml composes nested collections by C recursion with no depth limit, so a flow document nested tens of thousands deep overflowed the C stack. A document with more than 1000 opening brackets is now parsed by the pure-Python loader, which raises `RecursionError`, reported by `Config.load` as a `ValueError`. Real configs are far below the threshold and keep the fast loader.
- **The installer emits the SessionStart background-sync block.** `install.py` generated a `session-start` forwarder without the block that syncs in the background, so a fresh install differed from the tracked hook. Re-run the installer (or an upgrade) to get it.
- **Protected files are left out of the sweep fingerprint.** `tree_fingerprint` stated every tracked path, including ones the project marks as protected, so editing a protected file moved the fingerprint. Protected paths are now skipped.
- **Go 1.20+ `declared and not used: x` is allowed mid-edit.** `lint_on_edit` for Go treated the newer message, which appends the variable name, as a genuine finding and denied; it now shows it as an advisory like the older spelling.
