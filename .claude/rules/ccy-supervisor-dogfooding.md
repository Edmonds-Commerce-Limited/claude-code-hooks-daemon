---
paths:
  - ".claude/ccy/claude-supervise.py"
  - ".claude/ccy/**"
description: Editing the ccy supervisor is inert until its --worker subprocess reloads — verify (or force) the reload before dogfooding
---

# Dogfooding a change to the ccy supervisor

You touched `.claude/ccy/claude-supervise.py` (or another ccy file). An edit to
the supervisor does NOT take effect until its `--worker` subprocess hot-reloads
the new code. Verify the reload actually happened (or force it) before testing
behaviour — never assume it did, and never restart the whole ccy session just
to reload the worker.

The hot-reload contract and verification procedure live in
[.claude/ccy/CLAUDE.md](../ccy/CLAUDE.md).
