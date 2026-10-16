# Plan 00472 build: implementer report

Author: p472 build implementer (Opus 5.5). Worktree `worktree-p472-tier-advisor`.
Built to `RULINGS-fable.md` section 4 (Fable rulings under the owner's
delegation, recorded as Fable's, never the owner's).

## 1. Assumptions and open items for the coordinator

1. **Main-model source for the advisories.** `spawner_model` reads the
   spawner's own transcript tail first (a subagent's when the payload has
   `agent_id`), then the context sidecar's `model_id` for the main thread only.
   A subagent never takes main's sidecar: it names main's model, not the
   subagent's. Unknown means silent, as ruled.
2. **"Top tier" with no ceiling configured** (the client default) is read as
   Opus or above, so an inherited Opus or Fable dispatch is advised, naming the
   next tier down. A Sonnet main with an empty table draws nothing.
3. **Review is a top-tier role.** The advisory is silent on security,
   adversarial, decide and review roles (472-B section 3.2 and T3: reviews
   "stay on Opus"). Role floors in this repo are the three the ruling names;
   reviewer types get floors through `types`.
4. **The type wins over free text** in the role label (`code-reviewer`,
   `qa-runner`, `Explore`), then fix/resume before review. `implement` does not
   match "developer", so a `python-developer` "fix review findings" dispatch is
   `fix` (criterion 02).
5. **A `tier:` line silences the floor advisory too** (a reason was given).
6. **Downgraded agents in `hooks-daemon tiers`** are agents whose per-request
   models hold more than one model id (a mid-run swap, which can stay inside
   one family: Opus 5.5 to Opus 4.8). The aggregator row's `downgraded` flag
   comes from the `model_fallback_records` parser, as ruled.
7. **Not done here, waiting for the merge and a daemon restart:** the dogfood
   run (criterion 09), the acceptance run through a real dispatch (criterion
   04), and the issue #58 comment and close (criterion 10). The daemon serving
   this session runs main's code. Closing the issue is outward-facing and the
   plan is not complete, so it is left to the coordinator.
8. **Recovery cron.** `mkplan.bash` advised creating one; a subagent's cron
   belongs to the coordinator's session, so none was created.
9. **Push.** The common handover says do not push; the lead's message asks for
   `git push -u origin worktree-p472-tier-advisor`. The lead's direct
   instruction was followed.

## 2. What was built

| Task | Commit    | Delivered                                                                                                                                                                                                                                                                                         |
| ---- | --------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 3.1  | 59cbd6a4f | `utils/model_tiers.py` (rank table, alias and full-id resolution, `family_below`, Explore cap); downgrade indicator, recorder and `downgrade_state` use it                                                                                                                                        |
| 3.7  | 59cbd6a4f | `session_load.model_family` (the spend segment's per-family live counts) reads the shared table, so `mythos` counts as fable                                                                                                                                                                      |
| 3.2  | 3d959a9e5 | `utils/dispatch_tier.py`: source classifier, predicted family, role label, `tier:` reason, settings.json env reader, spawner model; `context_sidecar.sidecar_path`                                                                                                                                |
| 3.3  | 59c01ac0f | `spend-ledger/<session>/dispatches/<digest>.json` rows keyed by `tool_use_id` (`spend_ledger.write/merge/read_dispatch_rows`); `agent_dispatch_recorder` writes one per dispatch; new `dispatch_model_recorder` (PostToolUse); aggregator row gains `tool_use_id`, `downgraded`, `fallback_model` |
| 3.5  | 317c7bac2 | `subagent_tier_advisor` (PreToolUse Agent/Task, MAIN and SUB)                                                                                                                                                                                                                                     |
| 3.6  | 234bffa3f | `utils/workflow_fanout.py` static reader; `workflow_fanout_advisor` (PreToolUse Workflow) with the shape probe; `ToolName.WORKFLOW`                                                                                                                                                               |
| 3.4  | ee5299367 | `daemon/tier_report.py`, `hooks-daemon tiers`; `cmd_spend`'s session resolution shared as `_resolve_ledger_session`                                                                                                                                                                               |
| reg  | 44b717ff5 | HandlerID/Priority constants, repo config (this repo's table), example and init template (empty tables), guidance-coverage and command-anchoring lists, regenerated `.claude/HOOKS-DAEMON.md`                                                                                                     |
| 3.8  | 05404fd2b | `docs/guides/SUBAGENT_MODEL_TIERS.md`, HANDLER_REFERENCE entries, manifest entries, release note 079, 00280 cross-reference, baseline copy, PLAN.md, follow-up Plan 00530 with its README row                                                                                                     |

No RuleID was added: nothing here denies. No QA exclusion, allowlist or
suppression entry was added.

## 3. TDD evidence (red first)

Each new test module failed at collection before its code existed, for example:

```
E   ModuleNotFoundError: No module named 'claude_code_hooks_daemon.utils.model_tiers'
E   ModuleNotFoundError: No module named 'claude_code_hooks_daemon.utils.dispatch_tier'
E   ImportError: cannot import name 'merge_dispatch_row' from 'claude_code_hooks_daemon.utils.spend_ledger'
E   ModuleNotFoundError: No module named 'claude_code_hooks_daemon.handlers.post_tool_use.dispatch_model_recorder'
E   ModuleNotFoundError: No module named 'claude_code_hooks_daemon.handlers.pre_tool_use.subagent_tier_advisor'
E   ModuleNotFoundError: No module named 'claude_code_hooks_daemon.utils.workflow_fanout'
E   ModuleNotFoundError: No module named 'claude_code_hooks_daemon.daemon.tier_report'
```

Gap: the `workflow_fanout_advisor` handler tests were written before the
handler but not run red before it was created; its parser tests were.

## 4. Verification

- pytest by path, green: the new modules (`test_model_tiers`,
  `test_dispatch_tier`, `test_workflow_fanout`, `test_tier_report`,
  `test_subagent_tier_advisor`, `test_workflow_fanout_advisor`,
  `test_dispatch_model_recorder`), the touched ones (`test_spend_ledger`,
  `test_agent_dispatch_recorder`, `test_subagent_cache_aggregator`,
  `test_session_load`, `test_spend_report`, all of `tests/unit/handlers/status_line/`
  and `post_tool_use/`).
- Registration lists, run by path: `test_claude_md_guidance_coverage`,
  `test_handler_scope_defaults`, `test_bash_write_blindness_coverage`,
  `test_acceptance_test_coverage`, `test_config_changes_manifest_examples`,
  `test_handler_reference_check`, `test_skill_surface_coherence`, the
  `test_registry*` modules, `test_pretooluse_fail_closed_tagging`,
  `test_blocking_handler_evasion`, `test_default_enabled_template_consistency`,
  both `test_init_config`, `test_cli_commands`, `test_registry_config`,
  `test_explain_segment_completeness`. Two lists failed first (guidance
  coverage, command anchoring) and pass after the entries were added.
- `bin/hooks-daemon generate-docs` run from the worktree regenerated
  `.claude/HOOKS-DAEMON.md` (81 PreToolUse, 16 PostToolUse handlers).
- Targeted QA: section 5.

## 5. Targeted QA (`llm_qa.py changed`)

See the final section appended after the run.
