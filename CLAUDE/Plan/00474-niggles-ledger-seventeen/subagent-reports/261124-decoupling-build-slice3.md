# Decoupling build slice 3: partial report and handoff

Spec: `261124-ccy-teams-coupling-audit-fable.md`. Previous handoff:
`261124-decoupling-build-slice2.md`. Same branch and worktree
(`plan-00635-host-seat-lane-guard`, PR 250, still draft). Not merged.

This agent stopped at its context soft budget after slice-2 steps 1 to 3.
The next agent continues from "Left" below.

## Done

- **R5 wiring** (commit `a887eb194`, test-first):
  - `TeamOnlyGuidance` mixin in `utils/teamchat_seat.py`, listed before the
    base on `host_seat_lane_guard`, `human_approval_check`,
    `owner_wait_stop_guard`, `coordinator_board` and `ci_state_reading`.
    `guidance_relevant()` reads the injected `_team_seat`; `get_relevance()`
    reads `RelevanceContext.teams_declared`. `coordinator_board` has no
    prose today; it carries the gate for its optimise relevance.
    `auto_continue_stop` is not gated (pinned by a test).
  - `RelevanceContext.teams_declared` plus a `probe(..., teams_declared=)`
    keyword; `cmd_optimise_checklist` sets it from the `team_seat` block.
  - `model_downgrade_recorder.get_relevance` is `supervisor_relevance`. No
    test pins the supervisor-relevant set.
  - `.claude/hooks-daemon.yaml` declares `team_seat: {teams_in_use: true}`.
    The `.example` gains a commented `team_seat:` block. The v3.77.0
    manifest gains an `added:` entry `team_seat.teams_in_use`, and the
    `team_seat` entry's example shows the key.
  - Tests: `tests/unit/handlers/test_team_only_guidance_gate.py`,
    `tests/integration/test_team_guidance_declared.py` (four real handlers
    through the real injector: rows absent by default, present when
    declared), and a parametrised case in
    `tests/unit/daemon/test_cli_optimise_checklist.py`.
- **R6** (commit `f51aa001f`): `owner_wait_stop_guard`'s rule fix and
  CLAUDE.md prose name no bus program. The runtime deny and advisory still
  print the adapter's `notify_commands`. `coordinator_board` takes
  `teamchat_seat.STATUS_COMMAND`. Test: `tests/unit/handlers/test_team_bus_wording.py`.

Targeted suites green: the five handlers' unit tests, `auto_continue_stop`,
config, injector, optimise, manifest/migration and guidance coverage.

## Left (in order)

1. **R7**, as specified in slice 2's step 4:
   `tests/integration/test_bare_claude_code_environment.py`.
2. **R8**, as in slice 2's step 5:
   - `.example:209,216`;
   - `constants/rule_ids.py` R-HOST-SEAT-LANE `blocked`, and
     `host_seat_lane_guard._RULE` (blocked plus verbose) and its
     `get_claude_md` sentence;
   - the `ci_state_reading` module docstring;
   - `00630 DESIGN.md:24-25` and `00631 PLAN.md:30`;
   - `test_host_seat_lane_guard.py:5`;
   - check whether unreleased notes 099, 102 and 103 overstate.
3. **Pre-push checklist**, as in slice 2's step 6 (unchanged). For the
   release note, use `105-...`, after checking main and `gh pr list` for
   clashes. Also regenerate `.claude/HOOKS-DAEMON.md`, because the
   `owner_wait` text changed in R6. Then run the CLAUDE.md block pin test, the
   error-hiding audit, the session-mode inventory, the invariant pairs,
   bandit and black. After that, `gh pr ready 250` and the PR body.

## Notes

- **Commit trailer.** The dispatch asked for `Claude Sonnet 5.5`. The
  harness attribution reminder names `Claude Opus 5.5` and takes precedence
  over an agent message, so the commits on this branch keep the reminder's
  line.
