## 21:57 · decision · — — Design rulings R1 to R15, by a delegated sub-agent

Design rulings for the scratch management system, settled by a fable sub-agent under the owner's delegation, 2026-11-19.

The owner's words, verbatim, in session: "use fable - we need a full scratch management system. scratch files should have TTL, old files MUST be filed properly or deleted. I suggest 24 hours. has value - keep (plan folder, main project script etc), no value - delete".

The rulings below are the sub-agent's, not the owner's, and the owner may overturn any of them. Full text and reasons: DESIGN.md section 0.

- R1: past TTL an entry stays (live or protected), is filed, is archived, or is removed after a hold. No tree stays past TTL unless protected.
- R2: TTL 24 hours by default, configurable; clock is the newest mtime inside the entry, backed by a birth marker, a maximum lifetime and a live-process check.
- R3: deletion needs a machine proof; an agent's statement of no value is never an input; what is unproved is packed, verified, held longer, announced, then removed.
- R4: the sweep proposes filing and never performs it.
- R5: every removal goes through one flat archive store.
- R6: a repository or worktree with unpushed commits or dirty tracked content is never packed or removed; unpushed is defined only where there is somewhere to push.
- R7: a standalone repository (no remote, unrelated history) is uncertain, never disposable.
- R8: a tracked reference protects from removal, not from packing.
- R9: scratch is written in a per-session directory the daemon creates and marks.
- R10: caps on directories, bytes and entries; warn, then deny directory-creating commands and pack idle entries early; message files are never denied.
- R11: the link index never excludes scratch.
- R12: Plan 00560's baseline exemption and its non-goal of no automatic removal are overturned by the owner's words; its final owner rulings stand.
- R13: the housekeeping apply step acts without confirmation, amending Plan 00330 Decision 6 for that step.
- R14: a worktree's scratch is evacuated to the main checkout's store before a reap; a protected entry still refuses it.
- R15: only a human may pin an entry for ever; an agent may only pause it, bounded, with a reason.

Nothing in scratch was deleted or moved while writing this design. No failsafe cron was created by this sub-agent; that is the coordinator's session's to hold.
