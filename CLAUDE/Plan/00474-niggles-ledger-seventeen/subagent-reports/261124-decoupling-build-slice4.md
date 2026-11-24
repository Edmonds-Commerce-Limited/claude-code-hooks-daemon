# Decoupling build slice 4: report

Spec: `261124-ccy-teams-coupling-audit-fable.md`. Previous handoff:
`261124-decoupling-build-slice3.md`. Same branch and worktree
(`plan-00635-host-seat-lane-guard`, PR 250). Not merged.

## Done

- **R7** (test-first, no behaviour change):
  `tests/integration/test_bare_claude_code_environment.py`.

  - The eight team handlers are enumerated by the registry criterion (their
    `__init__` sets `_team_seat`) and pinned by name.
  - The bare pass: `TEAMCHAT_*`/`CCY_*` scrubbed, a tmp project root with no
    `.claude/ccy/`, shared resolvers reset. `run_kit_command` (both import
    sites) and `subprocess.Popen` are patched to RECORD calls, not raise,
    because several handlers swallow probe exceptions. Arming payloads:
    `pytest`, `git push origin main`, a queued `gh run list`, SessionStart
    `resume`, a prompt (with a configured directive register), and a waiting
    plus a no-reason Stop with a running background task. No deny, reason or
    context, and nothing spawned; `auto_continue_stop` is checked only for the
    absence of the wind-down note.
  - Controls: the same payloads speak for a resolved seat (host for the lane
    guard, coordinator for the rest) through a real `SeatContextResolver`, so
    the bare pass is not silent by construction.
  - Case B (runtime and kit set, `NOT_FOUND`/`TIMEOUT`, never resolved):
    silent. Case C: resolved worker with null duty leaves the lane guard
    silent; coordinator with null duty arms `human_approval_check`.
  - It passed first time: R1 to R3 hold.

  Commit `998db547f`.

- **R8** (commit `1d5f26902`, test-first): R-HOST-SEAT-LANE `blocked` and
  `verbose` text and the lane guard's `get_claude_md` sentence now say "a
  probe that stops answering in a session that resolved a seat". The
  `rule_ids.py` comment, the `ci_state_reading` docstring,
  `.example:209,216`, the module docstring of `test_host_seat_lane_guard.py`,
  `00630 DESIGN.md:24` and `00631 PLAN.md:30` (null duty is undeclared, D1)
  were updated to match. Pinned by
  `test_rule_text_scopes_the_no_answer_arming_to_a_resolved_session`. The
  runtime `_UNKNOWN_REFUSAL` text was left as it is: it only fires for a
  confirmed session, and line 424 of the test pins it.

- Targeted suites green: lane guard, ci_state_reading, R7, and
  team_guidance_declared (195 passed).

## Left (this agent stopped at its context soft budget)

1. **R8 remainder.** Check whether the unreleased notes 099, 102 and 103
   overstate. They are not under `CLAUDE/UPGRADES/UNRELEASED/`; find their
   directory first.
2. **CLAUDE.md block.** `generate-docs` rewrote `.claude/HOOKS-DAEMON.md` with
   no diff, because that file does not carry rule `blocked` text. The CLAUDE.md
   R-HOST-SEAT-LANE row (worktree `CLAUDE.md:609`) still has the old wording.
   Regenerate it the way the daemon does on restart, and do not hand-edit it.
   Then run the CLAUDE.md block pin and guidance coverage tests.
3. **Pre-push checklist**, unchanged from the slice-3 handoff:
   - release note `105-...`; check main and `gh pr list` for a clash;
   - `test_audit_error_hiding` and `scripts/qa/error_hiding_exclusions.json`;
   - the `test_session_mode_readers` inventory;
   - `scripts/qa/declared-invariant-pairs.yaml`;
   - acceptance tests per touched handler, updating stale `== []`
     assertions;
   - bandit;
   - black.
4. Run `gh pr ready 250` and update the PR body. Say that the branch name is
   historical, and end the body with the Claude Code line.

## Notes

- Commit trailer: as on the earlier slices, the harness attribution
  reminder (`Claude Opus 5.5`) takes precedence over the dispatch's Sonnet
  line.
- ruff flags B010 and I001 in the new integration test. Existing team tests
  have the same patterns (for example `test_host_seat_lane_guard.py`), and the
  QA lint does not gate `tests/`. Left as is.
