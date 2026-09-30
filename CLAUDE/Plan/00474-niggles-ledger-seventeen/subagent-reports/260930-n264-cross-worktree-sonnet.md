# N264 report: a sub-agent writes only in its own worktree

**Branch**: `worktree-n264-cross-worktree-write`. **Ledger**: 00474 N264.

## What was built

- `src/claude_code_hooks_daemon/utils/git_checkouts.py`: `enclosing_checkout(path)` returns the innermost git checkout a path sits in (`root`, `common_dir`, `linked`), or `None` when the path is in no repository. It raises `CheckoutUndecidableError` when a `.git` marker exists but cannot be read or parsed, or the path cannot be resolved.
- `src/claude_code_hooks_daemon/handlers/pre_tool_use/subagent_worktree_write_guard.py`: `SubagentWorktreeWriteGuardHandler`, rule `R-SUBAGENT-CROSS-WORKTREE-WRITE`, priority 14, terminal, `scope=SUB`, default enabled.
- Registration: `constants/handlers.py`, `constants/priority.py`, `constants/rule_ids.py`, `daemon/init_config.py` template, `.claude/hooks-daemon.yaml`, `.claude/hooks-daemon.yaml.example`, `docs/guides/HANDLER_REFERENCE.md` (section and summary row), `.claude/HOOKS-DAEMON.md` and the `CLAUDE.md` block (both regenerated with `regenerate-docs`), `CLAUDE/UPGRADES/UNRELEASED/config-changes/v3.68.0.yaml`, release note 198.
- Test registries edited: `test_claude_md_guidance_coverage.py` (T1 verdict), `test_blocking_handler_evasion.py` (`_NOT_COMMAND_ANCHORED` with a reason), `test_handler_scope_defaults.py` (the exact SUB set).

## Design choices

- **No subprocess and no worktree list.** Git marks each checkout root with a `.git` entry. The nearest one above the symlink-resolved path is the innermost checkout, which attributes a nested worktree (`untracked/worktrees/X`, `.claude/worktrees/X`) to itself rather than to the main tree. A `.git` directory is a main tree; a `.git` file with a gitdir holding `commondir` is a linked worktree; a gitdir without `commondir` (submodule, separate git dir) is a main checkout. Two paths are in the same repository when their `common_dir` (resolved) is equal. This is git's own on-disk fact and needs only a few `stat` calls, so there is nothing to cache and no stale-list problem when worktrees are added or removed.
- **Role test is the chain's `scope=SUB`**, as in `subagent_cron_delete_blocker`; the handler never reads `agent_id`. A chain-level test shows the same crossing write is denied for a sub-agent and untouched on the main thread.
- **Not judged**: cwd is the main tree (not linked), cwd in no repository, target outside any repository, target in a different repository (including a repository nested inside a worktree).
- **Fails open.** An unreadable or unparseable marker on either side, a NUL-byte path, or a missing cwd allows, with a debug log naming why. The util raises rather than returning `None` on error because `scripts/qa/audit_error_hiding.py` (rightly) rejects `return None` in an `except`; the handler's `matches`/`handle` catch it, log and allow.
- Deny text names both checkouts (`YOUR WORKTREE:` and `WRITE TARGET IN:`, each marked linked worktree or main working tree) and tells the agent to write only in its own worktree and report cross-branch needs to the coordinator.
- Tools covered: `Write`, `Edit` (`file_path`), `NotebookEdit` (`notebook_path`). Relative targets are read against `cwd`.

## Measured cost

`matches()` per call, 2000 iterations, from this worktree (about 10 path components, real sibling worktrees in this repository): own worktree (allow) 1160 us; main tree (deny) 598 us; sibling worktree (deny) 525 us; outside the repository (allow) 533 us. A deny costs one more lookup in `handle()`. Roughly 0.5 to 1.2 ms against a hook round trip. A per-cwd cache was not added: the saving is under 0.5 ms and it would introduce staleness the stat-based design does not have.

## Tests

- New: `tests/unit/utils/test_git_checkouts.py` (real `git worktree add` repositories plus hand-built markers), `tests/unit/handlers/pre_tool_use/test_subagent_worktree_write_guard.py` (deny sibling, deny main tree, nested worktrees, symlink, relative path, NotebookEdit, not-yet-existing file, allow own worktree, main-tree sub-agent, outside repo, other repo, nested repo, other tools, fail-open cases, chain-level role test).
- Red first: both new test files failed at import before the modules existed.
- Coverage of the two new modules: 96.7 percent (uncovered: the unreadable-file branches; the permission-based test skips when run as root).
- Targeted run (by path), all green: the two new files, `test_claude_md_guidance_coverage`, `test_blocking_handler_evasion`, `test_hook_probe`, `test_default_enabled_template_consistency`, `test_registry_option_injection`, `test_pretooluse_fail_closed_tagging`, the four acceptance contract tests, `test_config_changes_manifest_examples`, `test_doc_truth_check`, `test_dogfooding_config`, `test_example_config`, `test_handler_reference_check`, `test_handler_scope_defaults`, `test_handlers_do_not_match_prose`, `test_priority_bands_match_the_code`, `test_template_priorities_match_the_constants`, `test_generated_docs_are_path_agnostic`, `test_handler_instantiation`, both all-handlers response validation tests, `test_handler_config_blocking`, `test_chain_handler_scope`, `test_upgrade_regenerates_handler_docs`, `test_repo_hygiene_check`, `test_fingerprint_parity` (2432 passed, 1 skipped, 2 failures fixed afterwards in `test_handler_scope_defaults`, then rerun green).
- ruff, black `--target-version py311`, mypy, pyright (0 errors), `audit_error_hiding.py`, `check_input_contract.py`: clean on touched files.

## Not verified

- `./scripts/qa/llm_qa.py changed --base main --allow-unmapped` was run once and produced no output before my 580 s timeout killed it (exit 124), most likely waiting for the host-wide lock. It was not re-queued; the coordinator's gate covers it.
- The deny has not been observed in a live sub-agent session. The playbook harness marks probes synthetic and a SUB handler declines those, so both acceptance tests declare `harness_cannot_produce`. Behaviour is covered by unit tests over real worktrees and the chain-level test.
- The Bash route is not covered: `>`, `tee`, `cp`, `mv` into another worktree from a sub-agent still get through. Only the three file-writing tools are judged.
- A bare repository with no main working tree, and `git worktree move`/`repair` states, were not exercised.
- The permission-denied branches of the util ran only in the skipped test (root).
