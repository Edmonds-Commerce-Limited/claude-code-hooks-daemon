# Callout: a session on a Claude Code version newer than the last changelog review is told once

**Plan**: 00486
**Audience**: everyone

The `contract_staleness` SessionStart handler now has a second check beside its hook-contract one. It compares the running Claude Code version with the newest version whose changelog this daemon release was reviewed against, and advises once per newer version. The record is `CLAUDE/development/claude-code-versions.yaml`: each daemon release lists the Claude Code version it was built and tested against and how far the changelog was reviewed. A corrupt record is reported, never read as "no record". Nothing blocks and no configuration is needed; the advisory only says that Claude Code may have added or changed behaviour the daemon has not yet been checked against.
