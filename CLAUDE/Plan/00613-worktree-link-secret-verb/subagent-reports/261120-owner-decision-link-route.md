# Plan 00613: the owner-approved link route (Phase 3), handoff

Branch `agent-a4419afc45dbc6663-82565567`. Not merged.

The last code commit is `9d5c85138`. The commit that adds this report holds only plan documents; its sha is in the reply to the coordinator.

## Commits (after Phase 2)

- `8f9bab55c`: merge of origin/main
- `1d519fd6c`, `53b0e5fd1`: Task 3.1, the group C pin for reads through a seeded link. It includes the discriminating project-glob cases and one known gap, marked strict-xfail.
- `67385bacc` RED, then `0438789c1` GREEN: `utils/worktree_seed_apply.py`, the `seed-worktree` CLI, and `LinkAudit.verb`
- `64575032f` RED, then `c6b8d90ce` GREEN: `.yml` config support, a disabled-handler refusal, a refusal when a parent of the destination is a symlink, and doc wording that names the gap
- `ad9c0cee0`: a pin showing that an added seed entry is visible as config drift
- `2868ed7bd`: Task 3.2 docs, the copy-refusal text, callout 009, task 01, and release note 016
- `9d5c85138`: a gate-era report test reversed, so the refusal now names `mode: symlink`
- `4ea5fbd17` and the final commit: PLAN, DESIGN, the README row, the journal, and this report

## What changed

- **Owner decision recorded.** DESIGN.md "Owner decision" holds the owner's words, quoted as relayed by the coordinator's brief. They answer Q0 to Q3.
- **Builder's settlement, kept separate.** Q2's mechanism, Q4, Q5 and the small points are the builder's settlement, not the owner's; DESIGN labels them that way.
- **New command.** `hooks-daemon seed-worktree <worktree>` re-applies the configured `worktree_create` seed list to a hand-made worktree. It takes one positional argument and no options.
- **Copy refusal.** The copy-refusal text and the report now point to `mode: symlink`. Callout 009 and task 01 say to move to symlink mode.
- **Docs.** HANDLER_REFERENCE, the example config, and the handler's `get_claude_md` guidance are updated. Release note 016 is added.

## Security surfaces touched

1. **Seeding executor** (`utils/worktree_seeding.py`).
   - `LinkAudit` gains `verb`. Its default, `worktree-seed`, keeps the hook path unchanged.
   - Only the wording of the copy-refusal text changed.
   - The refusal logic and the audit-before-link order are unchanged.
2. **New route** (`utils/worktree_seed_apply.py`, plus `daemon/cli.py` `cmd_seed_worktree`). Any agent can run it. Its checks, in order:
   - The path holds no control character, and is a directory.
   - Its realpath equals a non-main, non-prunable record in `git worktree list --porcelain`, run from the target. The main checkout is the first record.
   - The config is `<main>/.claude/hooks-daemon.yaml`, else `.yml`, loaded strictly and fresh from disk.
   - `worktree_create` is not `enabled: false`.
   - No existing parent of a destination inside the worktree is a symlink (lstat).
   - `validate_seed_sources` passes: a protected copy is refused.
   - `seed_worktree` places the entries: an audit line is written before each protected link, and an existing destination is never touched.
   - The protected set comes from that config's `secret_file_guard` options, read strictly.
3. **Audit log** `worktree-seed-protected-links.jsonl`. It keeps the same keys. The verb is `seed-worktree` for this route.
4. **Secret guard.** No code change. New pin: `test_secret_file_guard_seeded_link_reads.py`, with 32 passing cases and 2 strict-xfail.
5. **Config-edit route.** No code change. An agent may Edit or Write the seed list; a probe confirmed `secret_file_guard` allows an Edit that adds a protected seed entry. The pin shows the session-start drift report counts it as an unnamed difference. The commit gate does not report it.

## Residual risks (for the security review)

- **KNOWN READ GAP, a merge gate.**
  - What is allowed: `grep -R <pattern> .`, run from a worktree, descends a seeded directory link. A file inside it that only a project `protected_paths` glob covers is not caught.
  - Where: allowed on this branch and on the Plan 00623 branch alike; I probed that branch's source.
  - Pinned strict-xfail in `test_secret_file_guard_seeded_link_reads.py`.
  - Scope: default-named protected files are denied by spelling.
  - The fix belongs to the secret-guard link work. This branch does not touch the guard.
- **Agent edits the seed list, then runs `seed-worktree`.**
  - The command reads the on-disk config fresh, so an uncommitted Edit plus one command places a link to any protected path, with no daemon restart.
  - The only safeguards are visibility (the drift report) and the guard's read judgement, which has the gap above.
  - A config-write deny was not added: it is circular, which is the existing project model.
- **Live-daemon verification not done.** Group C ran through the handler only.
- **Write-through.** A write through the link mutates the canonical file. An agent's Edit and `>` are pinned denied, but a human or a trusted consumer can still write through it.
- **Links outlive revocation.** No reporting verb lists live links (DESIGN section 7). Only the audit log finds them.
- **`linked-unclassified` on the hook path.** When the protected set is unreadable at placement, the link is still placed and logged as `linked-unclassified`. In the command, an unreadable config refuses earlier.
- **Porcelain is parsed line by line**, not with `-z`. Control characters in the argument are refused, but the paths git lists are trusted.
- **No ownership check.** Any registered worktree of the repository can be seeded with the configured list.

## QA (targeted, final HEAD code)

- **Tests.** 424 tests ran across the seeding, apply, CLI, handler, guard pins, report, strict-load, upgrade-task and release-note files.
  - Result: all pass, plus 2 strict-xfail (the known gap).
  - One failure is pre-existing on main: `015-idle-compaction-threshold-advisory.md` lacks the `# Callout:` title that `test_pending_release_notes_holding_area.py` requires.
- **Static checks.** ruff, black and mypy are clean on the touched sources.
- **Not run.** The full gate, which is the coordinator's.

## Open

- The known read gap, which needs a plan or a niggle, and its fix.
- The live-socket check.
- Task 3.4: reply to the peer project.
- Optional: a `worktree-secret-links` report.
