# Callout: `settings_repair` no longer clobbers a concurrent settings.json writer

**Plan**: 00468
**Audience**: operators

`settings_repair` (the SessionStart self-heal that adds missing hook registrations) used to read `settings.json` once and write its merged result unconditionally, so a write landing in between — including Claude Code's own `/plugin` or `claude plugin install|enable|disable` commands — could be silently lost. It now re-reads the file immediately before replacing it: if the content changed since the first read, it recomputes the reconciliation against the fresh content and folds its addition onto it; if the fresh content cannot be parsed, it aborts without writing rather than overwriting the concurrent writer's change. `run_settings_merge`'s existing docstrings, which already used this pattern, are corrected to count this as the fifth unlocked writer of `settings.json`, not four.
