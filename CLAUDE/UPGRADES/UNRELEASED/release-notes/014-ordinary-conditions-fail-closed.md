# Callout: Four ordinary conditions no longer let a scan pass without reading

**Plan**: 00483
**Audience**: everyone

A QA walker that cannot list a directory now fails with a `WalkError` naming it, instead of reporting its files clean. The history and sensitive-content sweeps fail with a configuration error when run by an interpreter that cannot import the daemon package, instead of checking no term. `scripts/debug_info.py` now resolves the project's secret word list from its own config, so a report is redacted without a running daemon. `remote-docs add` and `refresh` refuse, writing nothing, when the sensitive-content scanner cannot be built (for example a config that does not parse), instead of capturing the page unscanned.
