# Plan 00613 Phase 2: Tasks 2.2 to 2.5

Branch `agent-a4419afc45dbc6663-82565567`. Not merged.

## Commits

- `d53f3f31d`: Task 2.2 RED (audit tests, failing at import)
- `bb55b1f61`: Task 2.2 GREEN (`LinkAudit`, the audit log, handler wiring)
- `2f6d2e6d6`: Task 2.3 pin (hand-typed `ln -s` / `ln` / `cp` still denied)
- `cacb88a18`: `check-worktree-seed` RED (11 failing)
- `f9ea6da53`: `check-worktree-seed` GREEN (`refused_copies`)
- The final commit holds the example fix, release callout 009, and the PLAN and journal updates.

## Decisions

These are recorded in full in the journal entry `JOURNAL/2026-11-20/063718Z-action-6afc35.md`.

- **When links are classified.** Links are classified at placement, never at validation, so a link-only config still reads no protected set.
- **Unreadable protected set.** The link is still placed and is logged as `linked-unclassified`.
- **When the audit line is written.** It is written before the link. If the log cannot be written, the link is refused and seeding raises after `git worktree add`, so the worktree remains.
- **Linked directories.** A linked directory is judged by walking every path reachable through it.

## Open for the coordinator

- **Suggested seed candidates.** `worktree_seed_suggestions` still proposes names that look protected (the `*.secret*` shapes). The report renders those in symlink mode. Changing this is a policy choice, and it relates to the Q5 gate.
- **Phase 3.** Phase 3 is still gated on Plan 00614, Plan 00623, live verification, and the owner's own confirmation of Q1.
