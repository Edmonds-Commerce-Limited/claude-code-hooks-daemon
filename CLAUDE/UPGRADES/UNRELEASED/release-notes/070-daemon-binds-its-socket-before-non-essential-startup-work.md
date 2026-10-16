# Callout: the daemon binds its socket before the non-essential start-up work

**Plan**: 00495
**Audience**: client projects

The daemon start used to finish everything before it bound its socket: the `<hooksdaemon>` block regeneration in `CLAUDE.md`, the agent-asset and directory-role-rules syncs, and the guard-index pre-warm all ran first, so the status line and the first hook waited on work that has no bearing on how a request is judged. The socket is now bound as soon as the handlers are registered and the config is validated, and those four steps run in a worker thread behind it.

On this repository's own config, in a throwaway project, the first request was answered after a median of 1.94 s before and 1.51 s after (8 interleaved starts each), and the `start` command returned after 2.12 s and 1.68 s. The deferred work finished about 0.5 s after the first answer.

A request that arrives while the deferred work runs is answered exactly as it would be afterwards: the config validation that decides degraded mode, and the handler registration, are not deferred. A deferred step that fails is logged at ERROR and the remaining steps still run. For about half a second after a start, `CLAUDE.md`, `.claude/agents/` and `.claude/rules/` may therefore still show the previous start's content. Nothing needs to change in your config.
