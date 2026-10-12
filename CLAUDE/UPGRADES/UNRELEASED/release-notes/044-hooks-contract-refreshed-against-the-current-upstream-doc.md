# Callout: the vendored hooks contract matches the current upstream hooks doc again

**Plan**: 00474
**Audience**: handler authors

`contracts/claude-code-hooks/META.json` now records the upstream hooks page as fetched on 2026-10-12 (268811 bytes), still audited at Claude Code 2.1.296, so `bin/hooks-daemon contract-status` reports `unchanged` again. The refresh changed what the contract says about: the `agent_id` input field, which upstream now describes as identifying the subagent or in-process teammate the hook fires in and no longer states is absent from a main-thread call; the `Elicitation` and `ElicitationResult` exit-2 and output behaviour (an exit-2 decline shows no dialog, an `Elicitation` answer skips `ElicitationResult` hooks) and the `ElicitationResult` example, which no longer carries `elicitation_id`; the extra triggers of `WorktreeCreate` and `WorktreeRemove` (`EnterWorktree`, `ExitWorktree`, `claude remote-control`); the `PreToolUse` `allow` exception for reads from network paths; and the `SessionStart` PowerShell and plugin caveats. The vendored copy of the page under `remote-docs/` was refreshed with it. The daemon's own behaviour is unchanged.
