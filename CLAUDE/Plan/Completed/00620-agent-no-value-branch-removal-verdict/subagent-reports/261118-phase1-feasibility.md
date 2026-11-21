# Plan 00620 Phase 1 feasibility: sub-agent report

Scope: Phase 1 only. No guard code and no feature code was changed.

Deliverables:

- [FEASIBILITY.md](../FEASIBILITY.md): the Task 1.1 answer, a binding table (what is machine-verified, what the daemon observes live but a same-user process could forge, what is trusted), the failure modes, the archive-ref analysis, a draft design for Task 1.2, and owner questions Q1-Q8.
- PLAN.md Task 1.1 now links to it. Task statuses are unchanged; Task 1.2 waits on the owner.
- Journal entry `JOURNAL/2026-11-18/131104Z-finding-de364d.md`.

Main findings:

1. The task's model and independence checks cannot be proven against the agent asking for the delete. The daemon socket accepts any same-user process, and an unmarked payload counts as real. SubagentStop carries no model field; the model is only in the agent transcript, at a path the payload names. Transcripts, the branch records in git config and `untracked/` can all be written by the same user. Per Task 1.1, this goes to the owner as Q1 (threat model) before DESIGN.md is written.
2. If the agent is assumed motivated but not forging, every easy route can be closed by a machine check:
   - tip binding plus the existing `tip_moved_since_proof` check
   - a recomputed unique-commit and unique-path inventory that the verdict must match line for line
   - single-use verdict ids
   - a review prompt the daemon writes, enforced at the Agent dispatch
   - transcript model and downgrade checks
   - no fork and no resume
   - the unlock limited to the explicit `delete-branch` (never the sweep or merge-cleanup paths)
3. Archive refs already accumulate through two existing exits: `recovery_copy_advisory` (pointing to `refs/archive`) and the `remote-held` tier. This is raised as Q6. The recommended verdict route uses no ref at all. Recovery after a delete then depends on git's unreachable-object retention, which the design records and checks, and which is not a guarantee. A "condemn, then delete" variant (Q4) removes that risk without adding a ref.

Two points still need a live dispatch in Phase 2. They are inferred here from the contracts and existing handlers, not observed:

- that a background dispatch's PostToolUse carries `agentId`
- that the agent `meta.json` `tool_use_id` matches the parent's call

Commit trailer: the brief asked for a Sonnet co-author line, but the session's attribution instruction names Opus 5.5 and gives way only to the user's own instructions. The commit therefore carries the Opus line.
