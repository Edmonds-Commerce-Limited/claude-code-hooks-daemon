# Callout: the config check now reports when idle compaction is switched off

**Plan**: 00557
**Audience**: operators

Claude Code 2.1.290 and later compacts a long idle interactive session just before its one-hour prompt cache expires, so the next turn does not re-read the whole context uncached. `hooks-daemon check` gains an "Idle Compaction" line that fails and names the cause when `idleCompaction` or `autoCompactEnabled` is false, or when `DISABLE_AUTO_COMPACT`, `DISABLE_COMPACT` or `FORCE_PROMPT_CACHING_5M` is set, in the shell or any settings file's `env` section.

At session start the daemon now also writes `idleCompaction: true` to `~/.claude/settings.json` when the key is absent, and announces it in the `CONFIG SYNC` line. An explicit `false` is your choice: it is reported by the check and never overwritten.
