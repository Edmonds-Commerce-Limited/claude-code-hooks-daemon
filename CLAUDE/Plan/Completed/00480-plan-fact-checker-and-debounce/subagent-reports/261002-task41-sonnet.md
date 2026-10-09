# Plan 00480 Task 4.1 (and the 4.2 part that does not depend on open question 1)

Branch `worktree-p480-debounce-feed`.

## What was built

- **Handler**: `src/claude_code_hooks_daemon/handlers/post_tool_use/plan_fact_check_feed.py`,
  `PlanFactCheckFeedHandler`, config key `plan_fact_check_feed`, priority 36 (next free
  PostToolUse slot). Non-terminal, never blocks, `default_enabled = False`. Option
  `quiet_seconds` (default 5.0, passed to `get_debouncer().trigger`).
- **Bash writes**: covered. `get_written_file_paths` (the accessor `lint_on_edit` uses) names
  Write, Edit and Bash-authored paths in one call, so no extra code was needed. Relocations
  (`cp`/`mv`) are not reported by that accessor, by design.
- **Scope**: tracked documents are markdown files directly in or below a plan folder
  `<plan_dir>/<digits>-<name>/`. Excluded: `Completed/`, `subagent-reports/`, `JOURNAL/`, non-markdown.
  `subagent-reports/` is excluded because the fact checker writes its reports there and would
  otherwise re-trigger itself.
- **State and diff**: `src/claude_code_hooks_daemon/utils/plan_fact_check.py`. Files under
  `<daemon untracked dir>/plan-fact-check/`: `<folder>.checked.json` (last fact-checked content
  plus hash) and `<folder>.pending.json`. Atomic writes via `unique_temp_path` + `replace`. A corrupt
  file raises `PlanFactCheckStateError` rather than being ignored.
- **Boundary (open question 1)**: the fire callback `_on_quiet` calls `process_quiet_plan`, which
  logs at info and stores the pending record. It dispatches nothing and does NOT advance the
  checked hash; `record_checked` is for delivery to call. Stated in both module docstrings and in
  the PLAN.md task notes.
- **Registration**: `HandlerID.PLAN_FACT_CHECK_FEED`, `Priority.PLAN_FACT_CHECK_FEED`, entry in the
  full template (`init_config.py`, `enabled: false`), entry in `.claude/hooks-daemon.yaml.example`.
  NOT added to `.claude/hooks-daemon.yaml`. The opt-in set in
  `test_default_enabled_template_consistency.py` and the guidance exemption list in
  `test_claude_md_guidance_coverage.py` were extended; `get_claude_md()` returns None.

## Tests (TDD, RED first)

`tests/unit/utils/test_plan_fact_check.py` and
`tests/unit/handlers/post_tool_use/test_plan_fact_check_feed.py`. The debouncer is injected with a
fake clock and an inline runner, so there are no sleeps. They cover: a burst of five edits fires once
(trigger_count 5); two plans fire independently; non-plan paths ignored; quiet period configurable;
shutdown cancels pending; hash recorded and diff computed since the checked content; unchanged plan
stores nothing; fire logs at info and writes only the pending file.

## Not done

Delivery of the pending record, and calling `record_checked` after delivery (Tasks 4.2 remainder,
4.3, 4.4). Task 4.2 is marked in progress.
