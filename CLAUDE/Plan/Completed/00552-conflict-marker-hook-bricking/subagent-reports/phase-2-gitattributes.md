# Plan 00552 Phase 2 report

Branch: agent-a05abb6da40c5f0ec-4ec991b3. Task 2.1 commit is the first of the two on the branch tip (message "Plan 00552 Task 2.1"); Task 2.2 is the commit after it.

## Done

- `src/claude_code_hooks_daemon/install/git_attributes.py`: `ensure_managed_block(project_root) -> bool` plus a CLI (`--project-root`). The block is delimited by `# BEGIN/# END claude-code-hooks-daemon managed block` comment lines and sets `-merge` for `.claude/hooks/**` and `.claude/init.sh`. It creates, updates in place, is idempotent, and preserves lines before and after. A lone begin or end marker raises `ValueError` (the CLI exits 1).
- Wiring: `deploy_gitattributes_block` in `scripts/install/hooks_deploy.sh`, called from `deploy_all_hooks` (shared by install_version.sh and upgrade_version.sh, advisory on failure, needs the venv python), and a direct call in `install.py`. Both skip self-install mode.
- Decisions (journal decision entry): settings.json is NOT covered (project-owned entries would be dropped silently by `-merge`; `reconcile-settings` repairs daemon entries). Self-install is skipped and this repo carries no `.gitattributes`, because developers here edit tracked hooks on branches.
- Tests: `tests/unit/install/test_git_attributes.py` (unit) and `tests/integration/test_gitattributes_merge_conflict.py` (real temp git repo: with the block the file keeps "ours", has no markers, passes `bash -n`, and `git status` / `ls-files --unmerged` still report the conflict; a control without the block shows markers and a `bash -n` failure; `git check-attr` confirms init.sh; the shell deploy step is exercised and idempotent). Run red first (module missing), then green: 39 passed including test_hooks_deploy_relay_guard and test_hooks_deploy_permissions. ruff, black (py311) and mypy clean.
- Release note `CLAUDE/UPGRADES/UNRELEASED/release-notes/003-conflict-marker-hook-bricking.md` covers Phase 1 and Phase 2.

## Notes for the merge

- The sibling Phase 1 branch also has an untracked 003 release-note file; on merge, keep this one (it covers both phases) or reconcile the two.
- Phase 1's PLAN.md tick edits are on the sibling branch, not here; expect a trivial PLAN.md conflict.
- The upgrade path was only tested through the shell function, not a full upgrade run.
