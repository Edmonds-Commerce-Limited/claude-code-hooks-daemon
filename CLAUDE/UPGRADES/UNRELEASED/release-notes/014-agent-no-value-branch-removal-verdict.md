# Callout: an agent can remove a branch whose work has no value, through a reviewed verdict

**Plan**: 00620
**Audience**: client projects

A branch whose work the delete proof cannot clear used to be removable only by a human. `delete-branch` now has a `rejected-bundled` tier: an agent runs `branch-reject request <branch>`, which prints a reviewer prompt, and a separate `hooks-daemon-branch-reject-reviewer` sub-agent of at least Opus judges the work. The delete proceeds only when the guard finds that verdict valid, fresh and bound to the branch's exact tip, and has itself written and verified a recovery bundle holding the work. A verdict alone, or a bundle alone, unlocks nothing, and doubt means keep. Three handlers carry the gate: `branch_reject_dispatch_gate` (PreToolUse), `branch_reject_agent_binder` (PostToolUse) and `branch_reject_verdict_recorder` (SubagentStop). A verdict is single use: its id, nonce and file name must match, and it is also keyed on the reviewer agent, so a used verdict cannot be re-filed or copied under a fresh nonce to delete a restored branch again.

Every removal is a tracked ledger line. `branch-reject digest [--mark-read] [--format text|json]` lists the removals for the owner, and a session-start line counts the undigested ones; many no-value verdicts in a row ask for a stronger review. Restore lines still print after a removal. Nothing is on by default beyond the shipped `branches.reject` settings; see `CLAUDE/UPGRADES/UNRELEASED/config-changes/v3.77.0.yaml`.

Known limits: a forger who also writes a new agent id is not caught (accepted), and the used-verdict ledger is per checkout, so a second worktree can re-delete a restored branch on a verdict already used elsewhere (an open question, recorded in the plan).
