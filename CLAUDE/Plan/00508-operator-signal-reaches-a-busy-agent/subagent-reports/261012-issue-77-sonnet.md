# Plan 00508 Phase 1 report (Sonnet)

Tasks 1.1-1.3 are done on branch `worktree-plan-00508` (GitHub #77).

## What changed

- `src/claude_code_hooks_daemon/utils/operator_signal.py`: added `SIGNAL_TTL_SECONDS` (1800, equal to the supervisor's TTL), `render_operator_message` (a copy of the supervisor's wording), and `read_signal_notice(untracked_dir, session_id, now=...)`, which reads one known path and returns `(notice, reject_reason)`. It mirrors the supervisor's checks (closed kind, positive-int minutes, session, TTL) and never writes. The module docstring is updated: the module now renders, from the same fixed templates.
- `src/claude_code_hooks_daemon/handlers/post_tool_use/operator_signal_notice.py`: new `OperatorSignalNoticeHandler` (`PostToolUseHandlerBase`, priority 38, enabled by default). It surfaces the rendered text as context once per (session, ts, kind), held in a `BoundedFifoMap` (256). A rejection reason is logged once per (session, reason). It never raises, and never deletes or modifies the file.
- Constants: `HandlerID.OPERATOR_SIGNAL_NOTICE`, `Priority.OPERATOR_SIGNAL_NOTICE = 38` (the next free PostToolUse slot after 37).
- Registered in `daemon/init_config.py` (the config template) and the dogfood `.claude/hooks-daemon.yaml`. `get_claude_md` guidance and an acceptance test (`harness_cannot_produce`, because a real signal file would also arm the supervisor's injection into the tester's terminal) are on the handler. `docs/guides/HANDLER_REFERENCE.md` has the entry. `tests/integration/test_claude_md_guidance_coverage.py` has the T3 verdict. `.claude/HOOKS-DAEMON.md` was regenerated with `regenerate-docs`.
- Release note `CLAUDE/UPGRADES/UNRELEASED/release-notes/030-a-pending-operator-signal-reaches-a-busy-agent.md` (`# Callout: `).
- The supervisor is unchanged and not imported. `tests/unit/supervise/test_operator_signal.py` gained `TestRendererAgreesWithTheDaemonCopy`, which loads the supervisor through the existing `load_supervisor_module` and asserts identical wording for every kind and an identical TTL.

## Tests (targeted only)

- New: `tests/unit/handlers/post_tool_use/test_operator_signal_notice.py` and `tests/unit/utils/test_operator_signal_notice.py`, written first.
- Ran with the new tests: the operator-signal utils and supervise tests (117 passed), and the integration/unit set for acceptance contract, negative-case requirement, acceptance coverage, tool-payload prose, claude_md guidance coverage, handler reference check, priority bands, priority collisions, template priorities, default-enabled template consistency, init_config, constants and effective_handlers (696 passed).
- black (py311), ruff and mypy are clean on the touched files.

## Notes for review

- A non-numeric `ts` counts as expired, as in the supervisor (`_coerce_float` gives 0.0).
- The file body's `session_id` must equal the hook's session; a mismatch is ignored and logged. The supervisor does the equivalent via `own_sessions`.
- Because the file is left in place, the supervisor may still type the same warning when the session goes idle. The guidance and release note say so.
- Task 2.1 (review, merge, close #77) is untouched.
