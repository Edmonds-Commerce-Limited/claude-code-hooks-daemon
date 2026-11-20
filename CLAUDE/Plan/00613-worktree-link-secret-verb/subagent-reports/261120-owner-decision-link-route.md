# Plan 00613: the owner-approved link route (Phase 3), handoff

Branch `agent-a4419afc45dbc6663-82565567`. Not merged. The head sha is the commit that adds this report. Run `git log -1` on the branch for it; the coordinator's reply carries it too.

## Commits (after Phase 2)

- `8f9bab55c`: merge of origin/main
- `1d519fd6c`: Task 3.1, a group C pin covering reads through a seeded link
- `67385bacc`: Task 3.3 RED, `seed_existing_worktree` tests
- `0438789c1`: Task 3.3 GREEN, `utils/worktree_seed_apply.py`, `seed-worktree` CLI, and `LinkAudit.verb`
- `ad9c0cee0`: pin showing that an added seed entry is visible as config drift
- `2868ed7bd`: Task 3.2 docs, the copy refusal text, callout 009, task 01, and release note 016
- the last commit: PLAN, DESIGN (Owner decision), the README row, two journal entries, and this report

## What changed

- **Owner decision recorded.** The owner's words are quoted in DESIGN.md "Owner decision" and in the decision journal entry. The quote reached this agent through the coordinator's brief, and the provenance note says so.
- **`hooks-daemon seed-worktree <worktree>`** re-applies the configured `worktree_create` seed list to a hand-made worktree. It takes one positional argument and no options.
- **Copy refusal text** now advises `mode: symlink`. Callout 009 and task 01 now say to move a protected copy entry to symlink mode.
- **Docs:** HANDLER_REFERENCE, `.claude/hooks-daemon.yaml.example`, and the handler's `get_claude_md` seeding guidance.

## Security surfaces touched

1. **Seeding executor** (`utils/worktree_seeding.py`). `LinkAudit` gains `verb`, which is recorded in the audit line; the default `worktree-seed` keeps the hook path unchanged. The copy-refusal text changed, but its logic did not. The copy refusal and the audit-before-link order are unchanged.
2. **New route** (`utils/worktree_seed_apply.py`, `daemon/cli.py` `cmd_seed_worktree`). It is agent-runnable by design: the authority is the config, not the invoker. Checks:
   - The path contains no control character.
   - The target is a directory and its realpath equals a non-main, non-prunable record in `git worktree list --porcelain`, run from the target.
   - The main checkout is the first record.
   - The config `<main>/.claude/hooks-daemon.yaml` is loaded strictly; any failure refuses.
   - Seeding then runs `validate_seed_sources` (protected copy refused) followed by `seed_worktree` (an audit line before each protected link, an existing dest never touched).
   - The protected set comes from that config's `secret_file_guard` options, via `protected_patterns_from_options`, read strictly.
3. **Audit log** `worktree-seed-protected-links.jsonl`. It has the same keys as before. Lines now carry the verb `seed-worktree` when written by the command.
4. **Secret guard: no change in code.** New pin: `test_secret_file_guard_seeded_link_reads.py`, covering 18 cases. They are run through the handler with the hook cwd in the worktree, not through a live daemon socket.
5. **Config-edit route: no change in code.** An agent can still `Edit`/`Write` the seed list. A probe confirmed that `secret_file_guard` allows an Edit adding a protected seed entry. The new pin shows that the session-start drift report counts such an entry, as an unnamed difference. The commit gate stays silent on it, because it reports weakenings only.

## Residual risks (for the security review)

- **Agent edits the seed list.** This is the top residual. An agent can add any protected path to the config and then run `seed-worktree`, or create a worktree, to link it. The safeguards are only visibility (the drift report) and the reads staying denied. A deny on config writes was not added, because it is circular; this follows the existing project model.
- **Write-through.** A write or truncation through the link mutates the canonical file. Group C pins that `> <P>` and `Edit` are denied to an agent, but a trusted consumer or a human can still write through it.
- **Links outlive revocation.** The audit log is what finds them. No reporting verb lists live links yet (DESIGN section 7).
- **`linked-unclassified`.** If the protected set is unreadable at placement, the link is still made and only logged. In the command, an unreadable config refuses earlier, so this case arises only on the hook path.
- **Live-daemon verification not done.** Group C ran through the handler only. Plans 00614 and 00623 are still In Progress. Every group C case passed on the main-merged guard, but the live-socket check from the old gate has not been run.
- **Porcelain parsing is line-based** (not `-z`). A registered worktree path containing a newline could mis-parse. Control characters in the argument are refused, but a path git lists is trusted as listed.
- **No seed-entry ownership check.** `seed-worktree` does not check that the worktree's branch or session belongs to the caller. Any registered worktree of the repository can be seeded. That is the same list the hook would have placed.

## QA (targeted)

- 249 + 191 + 76 tests across the seeding, handler, CLI, guard pin, upgrade-task and release-note files. All pass except one pre-existing failure from main: callout `015-idle-compaction-threshold-advisory.md` lacks the `# Callout:` title that `test_pending_release_notes_holding_area.py` requires.
- ruff, black and mypy are clean on the touched sources.
- The full gate has not been run; it is the coordinator's.

## Open

- Task 3.4: reply to the peer project with the route.
- Optional: a read-only `worktree-secret-links` report (DESIGN section 7).
