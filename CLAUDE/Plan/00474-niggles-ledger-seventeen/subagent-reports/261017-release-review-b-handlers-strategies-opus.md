# v3.70.0 Code Review Gate (Step 10), reviewer B: handlers (not pre_tool_use) and strategies

Range: `git diff v3.69.0..HEAD` (HEAD 9513c3d45), 84 files, +3912/-615.
Probe scripts (kept as evidence): `/workspace/untracked/scratch/revb/probes/`.

## Scope covered (files read)

New files, read completely:
- handlers/stop/idle_workable_issue_stop_gate.py, handlers/stop/background_task_recorder.py
- handlers/subagent_stop/subagent_handoff_gate.py
- handlers/post_tool_use/dispatch_model_recorder.py, handlers/post_tool_use/operator_signal_notice.py
- handlers/session_start/unproven_venv_advisor.py, handlers/status_line/spend_meter.py
- handlers/utils/initial_thread_exemption.py, strategies/lint/module_context.py

Modified files, every diff hunk read, with surrounding code where logic changed:
- nitpick/dismissive_language, permission_request/auto_approve_reads, post_tool_use/{budget_exhaustion_detector, daemon_sync_after_merge, goal_injection, lint_on_edit, markdown_table_formatter, merge_qa_report, model_downgrade_recorder, plan_fact_check_feed, validate_eslint_on_write}, pre_compact/compaction_signal, project_loader, registry
- session_start/{branch_count_advisor, ccy_supervisor_integrity, contract_staleness, docs_qa_sweep, gitignore_safety_checker, hook_registration_checker, lsp_noise_checker, model_fallback_detector, monorepo_detector, optimal_config_checker, persistent_cron_assertor, plan_qa_sweep, session_actions_directive, suggest_statusline, tool_disable_advisor, version_check}
- status_line/{supervisor_indicator, thread_registry, upgrade_notifier, usage_indicator}
- stop/{auto_continue_stop, cron_stop_enforcer, usage_pause_stop_gate}; subagent_stop/{cron_subagent_stop_enforcer, subagent_cache_aggregator, subagent_report_path_verifier, subagent_report_size_blocker}
- user_prompt_submit/{daemon_upgrade_detector, failsafe_cron_blockage_suppressor, idle_housekeeping_advisor, standing_authorisations, usage_pause_gate}; utils/plan_numbering; worktree_create/worktree_create_handler
- strategies: comments/{extractor, go_strategy, syntax}, error_hiding/{go_strategy, protocol, python_strategy}, lint/{ansible_strategy, common, go_strategy, protocol, rust_strategy}, qa_suppression/{go_strategy, python_strategy}, tdd/{common, go_strategy}

Supporting code read to trace the paths: core/chain.py (handler exception handling), utils/spend_ledger.py, utils/session_load.py, utils/workable_issues.py, config PersistentCronsConfig.active_jobs, core/worktree_paths.enclosing_checkout, install/expected_version.read_expected_version, .claude/hooks/session-start, comment_changelog's scan target.

Priorities checked against constants/priority.py: the new ones (IDLE_WORKABLE_ISSUE_STOP_GATE 4, BACKGROUND_TASK_RECORDER 9, SUBAGENT_HANDOFF_GATE 11, DISPATCH_MODEL_RECORDER 33, OPERATOR_SIGNAL_NOTICE 38, UNPROVEN_VENV_ADVISOR 72, SPEND_METER 17) each carry a comment explaining the ordering. The stop-event slots below 10 are an existing, documented convention, so they are not findings. Every new handler has a unit test file.

## DEFECTS

### D1. A Rust file with a crate-context error is ALLOWED even when it also has a real compiler error (CONFIRMED)

- Location: `src/claude_code_hooks_daemon/strategies/lint/rust_strategy.py:258-276` (`is_tool_unavailable_output`), used at `handlers/post_tool_use/lint_on_edit.py:475-490`.
- Contract: the lint_on_edit guidance added in this release says the crate-context codes (E0432/E0433/E0463/E0583) are not findings, and "Syntax errors and other compiler errors still DENY."
- The defect: the regex is matched with `search`, so a single crate-context code anywhere in the output makes the whole run "tool unavailable", and the write is ALLOWED unlinted. Real errors reported in the same run are thrown away. rustc does not stop after a resolve error; it keeps going and type-checks. Nearly every module of a real crate has a `use crate::...` line, and compiled on its own that line always produces E0432 or E0433. So in practice no compiler error in a crate module is denied any more.
- Failing input: `src/lib_mod.rs` in a crate:
  `use crate::other::Thing;` plus `let x: u32 = "not a number";`. rustc reports E0432 and E0308. `is_tool_unavailable_output` returns True, so the write is ALLOWED. Reproduced: `probes/probe_rust_mixed_errors.py`, with the crate at `untracked/scratch/revb/rustprobe/`.
- Why tests miss it: `tests/unit/strategies/lint/test_rust_crate_context.py` only uses output with one error class (E0432 alone gives True, E0308 alone gives False). No test mixes them.
- Fix: do what Go's `is_mid_edit_output` does and excuse the run only when EVERY `error[...]` / `error:` finding is a crate-context code. For example, collect every `^error(\[E\d+\])?:` line except the trailing `aborting due to` summary, and return True only when all of them match `_CRATE_CONTEXT_ERROR` (or the clippy shim marker is present). Add a mixed-output test (E0432 + E0308 must give False).

### D2. comment_changelog (and comment_size) now miss a comment opened in an Edit fragment whose closer is outside it (CONFIRMED, regression from v3.69.0)

- Location: `src/claude_code_hooks_daemon/strategies/comments/extractor.py:183-215` (`_consume_delimited` now returns `None, start_index + 1` for an opener with no closer), consumed by `handlers/pre_tool_use/comment_changelog.py:280,298`. The handler scans only `new_string` on Edit.
- Contract: comment_changelog blocks "Prior/Previously <version>:" and dated entries in comments. Only the added text (`new_string`) is checked on Edit.
- The defect: the new rule is "valid code never has an opener with no closer, so it must be inside a string". That holds for a whole file. It does not hold for an Edit `new_string`, which is a fragment: an Edit that rewrites the top of an existing `/* ... */` block, JSDoc block or Python docstring routinely carries the opener and leaves the closer in the untouched file. That opener is now dropped, and scanning resumes as code, so the comment's lines (` * Previously 3.69.0: ...`) are never scanned.
- Failing input (Edit on `x.go`): `new_string = "/*\n * Previously 3.69.0: retried twice\n"`. v3.69.0 extractor: matches = True (denied). HEAD: matches = False (allowed). The same holds for `x.ts` with `"/**\n * 2026-08-12: switched to retry loop\n"`. With the closer present, HEAD still matches. Reproduced: `probes/probe_unterminated_block.py` (HEAD) and `probes/probe_unterminated_block_old.py probes/old_extractor.py` (v3.69.0 extractor).
- The same root cause lets an Edit that opens a large block comment slip past `comment_size`, which scans with the same extractor. I did not probe that.
- Why tests miss it: `tests/unit/strategies/comments/test_extractor.py:133-171` asserts the new behaviour on whole-content inputs only. No comment_changelog or comment_size test feeds an Edit fragment whose opener is unclosed.
- Fix: keep the #75 fix for whole-file content, but let the caller choose. Either (a) add an `unterminated_is_comment: bool` parameter (True for Edit `new_string`, False for Write and full-file scans), or (b) in comment_changelog and comment_size, extract the spans from the post-edit file (old content with old_string replaced) and keep only the spans that overlap the inserted range. Add an Edit-fragment regression test to both handlers.

## NON-DEFECTS

- N1 `handlers/post_tool_use/daemon_sync_after_merge.py:209-211,241-243`: the sync advisory fires when the pull touched the config file AND `expected_version != running`. It does not check that the pull changed `expected_version`. A pull that edits some other config key in a clone that was already behind still says "this pull changed daemon.expected_version to vX". The advice (`provision.sh`) is still right; only the wording overclaims. Fix: compare against `git show ORIG_HEAD:<config>` or reword to "daemon.expected_version is vX".
- N2 `handlers/session_start/version_check.py:3126-3134` (`_background_sync_lines`): with no sync record it says "this session start launched provision". That is true only when the deployed session-start forwarder carries the Plan 00477 launcher. A client whose forwarder predates it but who has `.claude/provision.sh` would be told a sync started when none did. Consider "should have launched" or detect the forwarder version.
- N3 `handlers/stop/idle_workable_issue_stop_gate.py:158-169`: the gate ignores a `hooks-daemon cron-pause issue-sdlc` pause. A session whose owner paused the job is still refused one idle stop. Design question: consider standing aside on a live pause like `cron_stop_enforcer` does.
- N4 `handlers/post_tool_use/plan_fact_check_feed.py:1440-1443` (`_in_main_checkout`): this uses `enclosing_checkout`, which depends on the worktree naming convention. A nested checkout elsewhere (e.g. `untracked/scratch/wt`) still feeds the debouncer. `core/worktree_paths.nested_git_checkout_root` is convention-independent and fits the stated intent better.
- N5 `handlers/session_start/optimal_config_checker.py:261-269`: the project settings files are re-read and re-parsed with no try. This is safe only because the first loop already proved them readable dicts; a TOCTOU change in between would raise out of the handler (fail-open, logged). DRY fix: keep the parsed dicts from the first loop.
- N6 `handlers/subagent_stop/subagent_handoff_gate.py:76`: `terminal=False` but no `HandlerTag.NON_TERMINAL`. Its siblings (idle gate, background recorder) carry the tag. Tag consistency only.
- N7 `strategies/tdd/common.py:1` imports `strategies.lint.module_context.find_module_root`, so the TDD strategies now depend on the lint package. Consider moving `find_module_root` to `utils/` (it is a path walk, not lint logic).
- N8 `handlers/user_prompt_submit/idle_housekeeping_advisor.py:5854-5873` `_DayCountOption.__get__`: class-level access (`instance is None`) raises AttributeError instead of returning the descriptor, so `hasattr(cls, "_stale_worktree_days")` reads False. Not reached by the registry today (it injects on instances). Return `self` when `instance is None`.
- N9 `handlers/status_line/usage_indicator.py:4125-4146`: `read_usage_override` and `current_breaches` run on every render without an mtime gate, which goes against the package's no-ungated-reads rule (cited in spend_meter's docstring). This is one stat of a usually absent file, so the cost is negligible; noted for consistency.
- N10 `handlers/registry.py:1659-1729` `_DISCOVERY_CACHE`: one submodule that fails to import is cached as absent for the life of the process (only a whole-package import failure is retried). That is fine for a daemon process, but the docstring promise ("an import failure is retried") is broader than the behaviour.
- N11 `strategies/error_hiding/go_strategy.py:6496-6500`: the blank-last regex does not see a generic call head (`v, _ := pkg.New[T]()`) or an underscore-led name (`_x, _ := f()`). Accepted precision limit for a regex guard.

## Not reviewed (honestly)

- Status-line diffs only skimmed, not traced: account_display, context_sidecar, daemon_stats, downgrade_indicator, downgrade_state, git_branch, host_hostname, model_context, multithread_indicator, startup_cleanup. They are mostly log_and_continue conversions, but I did not check every changed conditional in daemon_stats, host_hostname and git_branch.
- The bulk `logger.* -> log_and_continue` conversions were read for changed control flow only (none found), not for log-level policy.
- utils/ modules the handlers call (sweep_cache, stale_litter, background_sync, session_thread_group, spend_ledger.merge_dispatch_row, operator_signal) were treated as their callers' contracts and not reviewed in their own right. They are outside these paths.
- Ansible wrapper behaviour (`import_tasks` of a role task file that uses role-relative includes) was not run against a real ansible-playbook. ansible is not installed here.
- No test suite was run (brief: read-only, coordinator's gate is running).
