# Plan 00471 Phase 2 build: implementer report

Author: p471-spend-levers (Opus 5.5). Worktree `worktree-p471-spend-levers`.
Built to the Fable rulings (owner-delegated) in `RULINGS-fable.md`; none of the
choices below is the owner's.

## 1. Assumptions and open items for the coordinator

1. **Q5 payload capture was NOT done.** The ruling's route is to flip
   `daemon.payload_capture` in `/workspace/.claude/hooks-daemon.yaml` and
   restart the shared daemon. My brief forbids writing outside the worktree,
   and a restart would interrupt five live teammates, so I did not. What I did
   verify on the live session instead: the resolver's main-transcript shape
   resolves my own agent id to
   `~/.claude/projects/-workspace/<session>/subagents/agent-ap471-spend-levers-41ce14dcc97c6698.jsonl`,
   and the tail reader reads it (547,629 tokens, running). The resolver accepts
   both shapes as ruled, so the capture confirms rather than gates. To do after
   merge: capture one subagent PreToolUse record and store it in
   `subagent-reports/` as the fixture source.
2. **Dogfood run (criterion 12) and the real-subagent acceptance check
   (criterion 3) are pending.** They need this branch merged and the daemon
   restarted; the daemon serving this session runs main's code. The baseline
   `p471_spend.json` is copied (`subagent-reports/260925-p471-spend-baseline.json`).
3. **Targeted QA (`llm_qa.py changed`) did not run.** Two attempts waited the
   full 600 s for the host-wide QA lock held by the p495 worktrees and exited 4.
   Per-file black, ruff and mypy, and pytest by path on every touched suite,
   are green (section 4). The coordinator should run `changed` or its gate.
4. **`background_tasks[]` matching.** Its `id` is a task id, not obviously the
   agent id, so the live count excludes an agent when either the task `id` or
   its `description` equals the agent's id or name. Unmatched agents are kept
   (the safe direction for an advisory). The ledger events will show whether
   the match holds; that is the evidence the ruling wants before any deny mode.
5. **Override arithmetic.** A `budget: B` override sets hard to `max(hard, B)`
   and keeps the soft-to-hard gap; with hard off it sets soft to `max(soft, B)`.
   It never lowers a band.
6. **00472 ledger fields.** Rows carry `model_param` (first `requestedModel`),
   `resolved_model`, `per_model_requests` and `subagent_type` (meta.json). A
   `source` field is not written: it is 00472 T3.2's classifier output, which
   belongs on its dispatch-registry row.
7. **Context budget at 547k.** This agent itself ran past every threshold it
   built. That is the measured problem; it is also why this report is short.

## 1a. Targeted QA result (`llm_qa.py changed`, run on 50c14d8b4): FAILED, exit 1

The rerun got the lock and finished: 35 of 40 checks passed, 4 failed, 1 was not meaningful. To fix on re-dispatch:

- error_hiding: 12 findings (silent fallback in spend_report.py:126, return-None in the aggregator and the dispatch registry, silent `continue` in session_load.py:106/117, and others). See `untracked/qa/error_hiding.json`.
- eacces_safe: 2 findings. Raw `.is_file()` at resume_guard.py:213 and `.is_dir()` at subagent_context_budget.py:166 need to use `utils.path_predicates`.
- plan_qa: one advisory, journal freshness for 00471.
- changed_tests: 11 failed. They are registration lists the new handlers are missing from: acceptance near-miss/deny coverage, bash-write-blindness verdicts, handler-scope SUB defaults, pretooluse fail-closed tagging (resume_guard, subagent_context_budget, subagent_handoff_gate), and registry option injection (resume_guard, subagent_context_budget). 13 files were reported unmapped, mostly too broad.

## 1b. Re-dispatch after the host reboot: section 1a fixed (commit 39b260884)

Nothing was uncommitted after the reboot. No QA exclusion, allowlist or suppression entry was added. The one stale error-hiding exclusion (`subagent_cache_aggregator.totals_for`) was removed, because the loop it covered no longer exists.

- **error_hiding.** Each swallow is now explicit:
  - Lines that do not parse (in `transcript_tail`, `transcript_spend` and `spend_ledger.read_events`) are logged through `log_and_continue` with a reason. An unreadable, corrupt or foreign offset sidecar is logged the same way: `_Entry.from_json` raises, and `_load` rebuilds the entry.
  - `find_agent_transcript` now uses `os.scandir` and raises `OSError`. `Path.glob` drops `PermissionError` silently. The resume guard records the failure as `unmeasured` (`agents-unlistable`) and allows the call.
  - `collect_session_spend` raises on an agent directory it cannot list, and `hooks-daemon spend` then exits 1 with an error. A missing directory still reads as no agents. Release note 066 says so.
  - `dispatch_budget` reads its record through `_read_budget_record`, which logs a WARNING when the record cannot be read. `read_five_hour` reads through `read_state`.
  - `live_agents`: a transcript written recently but unreadable now counts as live with an unknown context, where before it was dropped. This is the safe direction for an advisory.
  - The aggregator's `_store_root` checks `ProjectContext.is_initialized()`.
- **eacces_safe.** The two calls now use `path_is_file` and `path_is_dir` with `unreadable_means=False`.
- **changed_tests.** The new handlers are added to each registration list. They now have:
  - near-miss ALLOW acceptance tests: a warm resume (`resume_guard`) and an over-budget stop after the handoff was written (`subagent_handoff_gate`);
  - a DENY acceptance test for `subagent_context_budget`, harness-undrivable, which needs `hard_tokens` set for the run;
  - an OUT-OF-FRAME bash-blindness verdict;
  - two entries in `_EXPECTED_SUB`;
  - three rows in `_AUDITED_BLOCKING_ONLY_REASONS`, as workflow and cost gates;
  - valid option values in `_VALID_NON_DEFAULTS`.
- **Defect found on the way.** `spawn_rate_advisor` imported the `ResumeGuardHandler` class. Registry discovery walks each module's attributes, so `resume-guard` was registered twice in PreToolUse, which is also why the fail-closed test listed it twice. `target_transcript` is now a module function. The new tests `TestEachHandlerOnce` in `tests/unit/handlers/test_registry.py` check that each handler is walked once and registered once. Both failed red before the fix.
- **Red first.** The nine new behaviour tests failed before the code changed (`9 failed, 98 passed`). The two duplicate-registration tests failed too (`2 failed`), with `('pre_tool_use', 'resume_guard')` reported twice.
- **Verification.** The touched suites passed: `tests/unit/handlers/pre_tool_use/`, `subagent_stop/`, `status_line/`, the utils and spend tests, which is 11,969 passed plus the aggregator fix. So did the six registration-list modules and `test_registry.py`. `audit_error_hiding.py` and `check_eacces_safe_predicates.py` exit 0. black, ruff and mypy are clean on the touched files. `regenerate-docs`, run from the worktree's own code, built and initialised a controller over the full handler set.
- **Final targeted QA** (`FULL_QA_LOCK_WAIT_SECONDS=3600 llm_qa.py changed --allow-unmapped` on bf1be7d00): `QA: 37/40 PASSED, 1/40 FAILED, 2/40 NOT MEANINGFUL (detector failed: plan_qa)`, exit 1. The one failure is a plan_qa journal-freshness advisory for ANOTHER plan, `00472-subagent-model-tier-selection`, which the resume brief says is not this branch's to fix. Every other check passed: error_hiding 0, eacces_safe 0, and changed_tests 7458 passed, 0 failed, 5 skipped. changed_tests and project_handlers are marked not meaningful only because plan_qa failed. There are 13 unmapped (too-broad) files, which the coordinator's full gate must cover.
- **After merge (not doable here).** Two items wait for this branch to be merged and the shared daemon restarted: the Q5 payload capture (assumption 1) and the dogfood run with the real-subagent acceptance check (assumption 2, criteria 3 and 12).

## 1c. Review round 1 (`261016-p471-code-review.md`), fixed in commit 504701730

Red first: the new tests were run against the pre-fix head 83d0b509a in a scratch worktree, giving `35 failed, 284 passed, 17 errors`. The errors are imports of names that did not exist yet. After the fixes, the touched suites gave `20325 passed, 1 skipped`, and the five registration-list integration modules passed.

| Item   | Verdict                       | What changed                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| ------ | ----------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| B1     | fixed                         | `resume_guard` never gates a non-text `message`. It allows the message and records a `resume-structured` ledger event (target, message type, context). The test at `test_resume_guard.py:161` now asserts ALLOW under `mode: deny` for `plan_approval_response`, `shutdown_request` and `shutdown_response`.                                                                                                                                                                                                                                                                                                                                                                                                               |
| B2     | fixed                         | `read_tail` stops at `MAX_WINDOW_BYTES` (4 MiB). Growing the window reads only the new bytes and parses each line once. With no usage in a file larger than `FRESH_AGENT_MAX_BYTES` (256 KiB), it raises `NoUsageInTail`. The budget gate and the resume guard record `unmeasured` (`no-usage-in-tail`) and allow; the live count and the spawn advisor treat the agent as unknown. Tests: 1 MB and 8 MB usage-free transcripts read at most `min(size, cap)` bytes, and the gate records the verdict once over three calls.                                                                                                                                                                                               |
| S1     | fixed                         | `_handoff_target` runs only in the hard branch and at the first soft crossing. A test asserts zero `handoff_path` calls over five calls below every band.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| S2     | fixed                         | The Bash allowlist splits with `shlex` (punctuation chars; since round 2 the project's `LinearShlex`, which semgrep requires). Quoted `;`, a newline inside a quoted message, and `cd '<dir with space>'` pass. A bare newline, `;`, `&&`, `\|\|`, `\|` and a bare `&` are all separators: each side is judged on its own, so `git status & git log` is allowed and `git status & rm -rf src` is denied (round 2 pins both). A redirection (`>`, `2>&1`), a subshell, a command substitution or unbalanced quotes deny the whole command. The deny reason names `git commit -F` with a message file under `untracked/scratch/`. `git commit -F` was already allowed by the `git commit` prefix, so no new rule was needed. |
| S3     | fixed                         | A SendMessage made while the hard band is engaged sets `handoff_sent`, which `subagent_handoff_gate` accepts. Both deny texts say "if you cannot Write, SendMessage the lead the handoff itself".                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| S4     | fixed                         | `resolve_agent_transcript` now runs inside the `try`. The budget gate, the resume guard and the handoff gate each catch any failure, log it, and allow. The two PreToolUse gates also record `handler-error`; the stop gate only logs it, because the unmeasured record is PreToolUse-shaped. The raw `is_file`/`is_dir` calls in `transcript_tail` were kept: both callers now catch `OSError` and record it as `transcript-unreadable`, which is more exact than `path_predicates` turning EACCES into "missing". The handoff gate does use `path_is_file`.                                                                                                                                                              |
| S5     | fixed                         | `spawn_rate_advisor` reads `latest_usage().five_hour`, with `max_age_seconds` checked against `observed_at`. `context_sidecar`'s `five_hour_pct`/`resets_at` and `session_load.read_five_hour` are removed. The deviation from the ruling's wording is journalled (2026-10-16 decision entry). The example config, the HANDLER_REFERENCE entry, the manifest and release note 066 are updated.                                                                                                                                                                                                                                                                                                                             |
| S6     | partly fixed, partly declined | Fixed: `subagent_cache_aggregator.record` evicts the agent's entry after writing; the sidecars move to `spend-offsets/`; `cleanup_stale_session_dirs` ages out `spend-offsets/` files and `spend-ledger/<session>/` directories after `stale_file_days`. Declined: bounding `seen_ids`. A sidecar is rewritten once per stop, never per tool call. Once evicted, memory holds only running agents. Trimming the id set would double-count a replayed request.                                                                                                                                                                                                                                                              |
| N1     | fixed                         | `WEIGHT_OUTPUT` is exported from `transcript_tail` and used by the output-delta fold.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| N2     | fixed                         | The unreachable fallback is gone. A transcript with no derivable agent directory exits 2 with an error.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| N3     | not done                      | Follow-up: share one resolved reading per SendMessage, and have the advisor use the guard's `warm_seconds`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| N4, N5 | not done                      | They belong to the deferred L4 deny-mode item: the ledger evidence must account for both before any deny mode.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| N6     | fixed                         | `ToolSearch` is allowed in the hard band. `TaskStop` was left out: it stops other work, so it is not a handoff step.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| N7     | fixed                         | The `review-round-advisory` event is written in `commit_side_effects`, only for a dispatch that went ahead.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |

## 1d. Review round 2 (approved), three follow-ups

The round-1 targeted QA on 474f8f073 also surfaced one finding of mine: semgrep `stdlib-shlex-quadratic` on the new S2 tokeniser. It is fixed by using `utils.linear_shlex.LinearShlex`, which gives the same tokens at linear cost. Its other failure was the plan_qa journal-freshness advisory for plan 00472, which is not this branch's to fix.

1. **`five_hour_pct` on every per-agent row.** `subagent_cache_aggregator.record` stamps `latest_usage().five_hour.used_percentage` onto each row, and `null` when unknown. The tests cover a reading and no reading, and the test module now patches `latest_usage` to `None` by default so it never reads the host's real snapshot.
2. **Ledger retention.** The new option `daemon.spend_ledger_retention_days` follows the `stale_file_days` pattern (`Annotated[int, Field(ge=1, le=365)]`, default 90). `cleanup_stale_session_dirs(..., ledger_max_age_days=...)` ages out `spend-ledger/<session>/` and `cache-sidecar/<session>/` with it, and `_reap_stale_runtime_files` passes the config value. `spend-offsets/` is a cache, so it stays on `stale_file_days`.
   - **Judgement call:** `cache-sidecar/` was included because it holds the per-agent ledger rows (now carrying `five_hour_pct`). Pruning it at 7 days would lose the evidence the ruling wants. Before this change those directories went after `stale_file_days`, so the Plan 00452 regression test now passes `ledger_max_age_days=7` to keep exercising the directory-aware reaping.
   - **Recorded in:** the example and repo configs, the config-changes manifest, and release note 066.
3. **Bare `&`.** It is a separator, not a rejection. `git status & git log --oneline -3` is pinned as allowed (next to the existing `git status & rm -rf src` deny), and the S2 row above is corrected.

Red first: the new round-2 tests failed before the code changed, giving `4 failed, 75 passed, 39 errors` (the errors are the missing `latest_usage` name in the aggregator module). The `&` case passed straight away, because it pins the existing behaviour. After the fixes, the touched suites (subagent_stop, budget, paths cleanup, start-up cleanup, config, init config, status line) gave `1482 passed`.

## 2. What was built (one commit per lever)

| Task | Commit    | Delivered                                                                                                                                                                                    |
| ---- | --------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 2.0  | 35f174bec | `utils/transcript_tail.py` (tail reader, resolver, ite weights), `utils/transcript_spend.py` (offset cache, per-request dedup)                                                               |
| 2.1  | ea7fab202 | ledger rows in `subagent_cache_aggregator`, `utils/spend_ledger.py` (store, `note_unmeasured`, events), `verdict_log.append_handler_note`, `daemon/spend_report.py` and `hooks-daemon spend` |
| 2.2  | 2ca8a05c4 | `subagent_context_budget` (SUB), `subagent_handoff_gate` (SubagentStop), `budget: <N>k` in `agent_dispatch_recorder` and the dispatch registry                                               |
| 2.3  | e0c1d55b0 | `resume_guard`, `find_agent_transcript`                                                                                                                                                      |
| 2.4  | d50f10655 | `utils/session_load.py`, `spawn_rate_advisor`, `background_task_recorder` (Stop), SubagentStop reconciliation, `context_sidecar` `five_hour_pct`/`resets_at`                                 |
| 2.5  | d4425ac43 | `spend_meter` status segment, live snapshot refreshed at Stop, SubagentStop and spawn                                                                                                        |
| 2.6  | 05b87417c | `review_round_advisor` (count advanced in `commit_side_effects`)                                                                                                                             |
| 2.7  | (final)   | HANDLER_REFERENCE entries and quick-reference rows, config-changes manifest entries, release note 066, baseline copy, PLAN.md                                                                |

Config in this repo: budget soft 150k, hard null, override ceiling 450k;
resume guard deny at 150k; spawn advisor cap 4, five-hour 70 %; review
advisor on at 4; recorder and spend meter on. Client defaults (init template
and example): soft 300k, hard null; resume advise at 250k; cap off, five-hour
80 %; review advisor off. Rules: `R-SUBAGENT-CONTEXT-BUDGET`,
`R-SUBAGENT-HANDOFF-MISSING`, `R-RESUME-COLD-LARGE`.

## 3. TDD evidence (red first)

Every new test module was run before its code existed and failed at
collection, for example:

```
E   ModuleNotFoundError: No module named 'claude_code_hooks_daemon.utils.transcript_tail'
ERROR tests/unit/utils/test_transcript_tail.py
```

The new aggregator tests failed on the old code (`2 failed, 33 passed`)
before the ledger row existed.

## 4. Verification

- pytest by path, final runs: `tests/unit/handlers/status_line/`,
  `tests/unit/handlers/subagent_stop/`, the seven new handler test files,
  `tests/unit/utils/test_transcript_*`, `test_spend_ledger`, `test_session_load`,
  `tests/unit/daemon/test_spend_report.py`, `test_init_config`,
  `test_default_enabled_template_consistency`, `tests/unit/handlers/test_registry.py`,
  `tests/integration/test_claude_md_guidance_coverage.py`,
  `test_blocking_handler_evasion.py`: all green (largest combined run 1,352
  passed).
- black, ruff and mypy clean on every touched `src/` file.
- Live read: `hooks-daemon spend --by plan` over this session's 424 agents ran
  in 7.4 s cold (offset cache then persisted); it exposed bare-number plan keys
  from pytest temp paths, fixed in 2.1 by requiring a `p`/`plan`/`n` prefix or
  the zero-padded folder form.
- Success criteria 1, 2, 4 to 11 have tests; 3 and 12 wait for the dogfood run;
  13 waits for the coordinator's QA.
