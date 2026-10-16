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
