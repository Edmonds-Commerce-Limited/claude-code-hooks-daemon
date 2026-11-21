# Phase 5 handoff 3 (Tasks 5.1 and 5.2 done)

## Done

- `utils/scratch_dir_creation.py`: `directory_creating_targets(command, cwd)` and `creates_directory_under(command, cwd, roots)`. Recognises `mkdir`, `git clone` (incl. `git -C`), `git init`, `git worktree add`, recursive `cp` (`-r`/`-R`/`-a`), `tar` extraction (`-C`/`--directory`, else cwd), `mktemp -d` (`-p`/`--tmpdir`/a template with a slash). Heredoc bodies are stripped; redirects and plain `cp` never count; `cd` is NOT followed (paths resolve against the hook `cwd`). Tests: `tests/unit/utils/test_scratch_dir_creation.py`.
- PostToolUse `scratch_inventory_refresher` (priority 42, enabled by default, silent): calls `cli.start_scratch_inventory_refresh` when a Bash command creates a directory under `<project>/untracked/scratch`. Registered in `constants/handlers.py`, `constants/priority.py`, `init_config.py`, both yaml files. Tests: `tests/unit/handlers/post_tool_use/test_scratch_inventory_refresher.py`.
- Priority tie verified: chain sort is (slow sweep, priority, name); `branch_sweep` < `scratch_sweep`, and `git_upstream_checker` (56) is `SLOW_SWEEP`. Test: `tests/unit/handlers/session_start/test_scratch_sweep_order.py`.
- PLAN.md 5.1 and 5.2 ticked.

## Not done / next

- The refresher watches the default `untracked/scratch` only, not a configured `resolve_sweep_root` root; Task 5.4 should resolve the root the same way `start_scratch_inventory_refresh` does and the refresher can adopt it.
- HOOKS-DAEMON.md / generated handler docs not regenerated (the refresher has no `get_claude_md`, so likely only a listing line).
- Task 5.4 `R-SCRATCH-CAP`: PreToolUse handler, reuse `creates_directory_under`; read `scratch_inventory.read_inventory(untracked/scratch-inventory.json)`, deny only when `cap_level == BLOCK`; never a Write/redirect; never-stranded downgrade per DESIGN.md section 8 (lines ~275-290). Rule ID + explain-rule entry + acceptance test.
- Task 5.6: must-do item through `session_actions_directive` (DESIGN.md table line ~305).
