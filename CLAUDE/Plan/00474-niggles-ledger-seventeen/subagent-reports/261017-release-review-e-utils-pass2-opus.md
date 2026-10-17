STOPPING BECAUSE: the review of all 22 assigned modules is complete. I'm sending the report as this reply.

# Release review pass 2: remaining `src/claude_code_hooks_daemon/utils/` modules (v3.69.0..9513c3d45)

## Scope covered
I read all 22 assigned modules in the priority order you gave, and traced their callers:

- **`agent_dispatch_registry.py`**: traced into `full_qa_exemption.exempting_entry`, `subagent_context_budget.matches` and the `agent_dispatch_recorder` writer.
- **`session_thread_group.py`**: traced into `initial_thread_exemption`.
- **`spend_ledger.py`**, **`dispatch_tier.py`**: traced the recorder's tier row through `subagent_tool_resolution._find_agent_file`.
- **`workflow_fanout.py`**, **`workable_issues.py`**, **`model_tiers.py`**, **`goal_ledger.py`**, **`deliberate_swallow.py`** (and `escape_hatch.is_acceptable_reason`), **`fake_values.py`**, **`deployed_version.py`**, **`markdown_format.py`**, **`retention.py`**, **`container_detection.py`**, **`subagent_report_paths.py`**, **`stop_hook_helpers.py`**, **`usage_pause.py`**: read in full or as diff hunks.
- **`plan_fact_check.py`**: traced into `plan_fact_check_feed.handle`.
- **`stale_litter.py`**: traced into `idle_housekeeping_advisor._build_guidance`.
- **`session_load.py`**, **`operator_signal.py`**: traced into the `operator_signal_notice` handler.
- **`ccy_supervisor.py`**: checked against `install_layout.get_untracked_dir`.

I also checked how `core/chain.py` handles a handler exception (lines 1159-1224): a non-safety handler that raises is logged and the chain continues.

## DEFECTS (2 confirmed, 0 plausible)

**D1. `plan_fact_check.py:574-583` (`deliver_pending`) gives the same fact-check instruction twice in one event and uses up an extra offer.**
- **Cause:** `batches` builds both folder lists before anything is processed. A folder that has a new pending record and also an offer older than 300 s gets handled in the pending batch, which overwrites `.offered.json` with `offers=1`. The offered batch then claims that fresh record and hands it over again.
- **Failing input:** the session ignores an offer for more than 5 minutes, the plan is edited again, and the debounce stores a new pending record. Then `PlanFactCheckState.offer(stale)` + `store_pending(new)` + `deliver_pending(st, now=1000)` returns **2 messages**, and `read_offered().offers == 2`.
- **What the user sees:** `plan_fact_check_feed` puts two identical "Dispatch the hooks-daemon-plan-fact-checker agent now" lines into one PostToolUse context. That invites two checker dispatches, and the `MAX_OFFERS=3` cap is reached one offer early.
- **Why tests miss it:** `tests/unit/utils/test_plan_fact_check.py` never sets up a pending record and a stale offered record for the same folder.
- **Fix:** compute `offered_due` after the pending batch has run, or skip folders already handed over in this call.
- **Evidence:** reproduced with an inline `python -I -c` probe (state under `untracked/scratch/review-utils-probe/`).

**D2. `stale_litter.py:155` and `:240-247` print a false "SCAN INCOMPLETE: the time budget ran out before git answered" on the gone-branch-refs report.**
- **Cause:** `collect_scratch_report` sets `shared.exhausted = True` whenever its walk is incomplete. That includes the entry cap, an unreadable subdirectory, or a file whose stat fails mid-scan, not only a spent budget. `idle_housekeeping_advisor._build_guidance` (lines 288-293) passes that same `ScanDeadline` to `collect_gone_branch_ref_report`. The flag doesn't stop `deadline.run`, so git answers in full, but the report still claims it didn't.
- **Failing input:** a scratch walk that hits `max_entries`. It then prints the "SCAN INCOMPLETE" line above a complete list of 70 refs (reproduced against `/workspace`).
- **What the user sees:** whenever no ref is gone, the housekeeping advisory gets a header-plus-"SCAN INCOMPLETE" block with no content, on every pass while scratch has an unreadable entry.
- **Why tests miss it:** the shared-budget tests (`test_stale_litter.py:110` and `:256`) only cover a budget that really is spent.
- **Fix:** have the scratch scan record its own incompleteness without setting `shared.exhausted` (only `expired()` should set it). Alternatively, the ref report could judge incompleteness from its own `deadline.run` results.

## NON-DEFECTS
- **`agent_dispatch_registry.py:117-149`**: the full-QA exemption fails closed in every path I traced:
  - A missing record for a named id gives `""`.
  - An unreadable record gives `""`.
  - A name mismatch gives `""`.
  - An unrecognised id shape is looked up as a name.
  - The blocker is `scope=SUB`, so the empty-`agent_id` branch can't be reached from it.

  One residual risk: two agents with the same name live at once, but different `subagent_type`, would both resolve to whichever dispatch was recorded last. The record stores no `agent_id` to tell them apart. This needs concurrent name reuse; noted as a design limit.
- **`dispatch_tier.py` / `agent_dispatch_recorder._record_tier`**: it catches only `(OSError, RuntimeError)`. `_find_agent_file` calls `path.read_text()` without an encoding, so a non-UTF-8 `.claude/agents/*.md` raises `UnicodeDecodeError`. The chain catches it (the handler isn't SAFETY/BLOCKING), so the cost is one lost tier row plus "Handler exception" text in context. The name record was already written before this point. Fix: add `ValueError`.
- **`operator_signal.py` `read_signal_notice`**:
  - A `kind` that is a list or dict raises `TypeError` at `kind not in KINDS`, and a huge integer `ts` raises `OverflowError`. The docstring promises `(None, reason)` instead. The caller catches `Exception`, so nothing is shown, but it logs an ERROR on every PostToolUse while the file is there.
  - A `ts` of NaN or Infinity never expires.
  - Both need a corrupted or forged file that names this session.
- **`workflow_fanout.py`**: it's advisory only.
  - `for (i=0;i<N;i+=k)` is counted as N and labelled EXACT.
  - A brace-less outer loop around an inner counted `for` ends at the inner header's `;`, so it undercounts.
  - Both are rare shapes.
- **`session_load.py:154-157`**: the "finished" set includes task `description` values and is matched against agent names. A reused name is therefore left out of the live count until the next Stop rewrites the record. This only feeds an advisory.
- **`session_thread_group.py`**:
  - `_save` drops groups in insertion order, not least-recently-used.
  - Each candidate walk in the scan gets its own fresh 0.25 s budget.

  Both are bounded. All failure paths keep the crons held, as the module promises.
- **`ccy_supervisor.daemon_untracked_dir`**: it now uses `install_layout`, which tests `is_dir()` where the old code tested `exists()`. The behaviour is equivalent.
- **`deliberate_swallow.log_and_continue`**: now attaches `exc_info` to the log record, so WARNING-level swallows in hot paths (`goal_ledger`, `retention`) log full tracebacks. That's noise only.
- **`model_tiers.py`, `workable_issues.py`, `spend_ledger.py`, `usage_pause.py`, `fake_values.py`, `deployed_version.py`, `markdown_format.py`, `retention.py`, `container_detection.py`, `subagent_report_paths.py`, `stop_hook_helpers.py`**: no issues found. Most of the diff in these is the `log_and_continue` conversion.

## Not reviewed
- Test files for these modules: I only checked them for D1 and D2.
- `subagent_tool_resolution.py`: out of scope, beyond the one exception path above.
- The consuming handlers' own new logic, beyond the call sites I traced.