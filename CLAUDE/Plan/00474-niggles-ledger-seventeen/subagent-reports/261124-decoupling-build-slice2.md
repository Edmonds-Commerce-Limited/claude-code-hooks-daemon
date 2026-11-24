# Decoupling build slice 2: partial report and handoff (context budget reached)

Spec: `261124-ccy-teams-coupling-audit-fable.md`. Slice 1:
`261124-decoupling-build-r1-r8.md`. Same branch and worktree
(`plan-00635-host-seat-lane-guard`, PR 250, still draft). Not merged.

This agent stopped at its context budget. The next agent continues from
"Left" below.

## Done

- **Ledger** (commit `1bc10433f`). New section at the end of `NIGGLES.md`,
  kept separate so it merges cleanly beside PR 249:
  - N725: injector-wide relevance gate (deferred).
  - N726: malformed-duty asymmetry (owner to confirm).
  - N727: `reset_shared_resolvers` is not called on a config reload.
  - N728: D-SEC finding on PR 249, a directory-component bracket under
    `nocaseglob`. Includes the wording correction owed to PR 249's N719 and
    N720 item 1 "Fixed" claims. Those claims exist only on PR 249's branch, so
    they are recorded as a correction rather than edited.
  - N729: D-RULE older gaps on main.
  - N730: PR 246 replacement-character decode.
- **R5 core** (commit `912d9d539`, test-first, targeted tests green):
  - `TeamSeatConfig.teams_in_use: bool = False` in `config/models.py`.
  - In `utils/teamchat_seat.py`:
    - `teams_declared(config)` is true for `teams_in_use` with detection
      `auto`, and false for `None` or `detection: off`.
    - `team_seat_relevance(declared) -> Relevance`.
  - In `core/claude_md_injector.py`, an opt-in `HasGuidanceRelevance`
    protocol (`guidance_relevant()`), skipped in `_collect_tiers` beside the
    dormancy skip. `_collect_tiers` is the only loop that renders guidance;
    `_external_handler_sources` only feeds the auto-commit wait.
  - Tests:
    - `tests/unit/config/test_team_seat_config.py`;
    - `TestTeamsDeclared` in `tests/unit/utils/test_teamchat_seat_decoupling.py`;
    - `TestGuidanceIsLeftOutWhereItDoesNotApply` in
      `tests/unit/core/test_claude_md_injector.py`.

## Left (in order)

1. **Wire R5 onto the handlers.**
   - Implement `guidance_relevant()` returning `teams_declared(self._team_seat)`
     on the handlers that emit guidance: `host_seat_lane_guard`,
     `human_approval_check`, `owner_wait_stop_guard`, `coordinator_board`
     (check that its `get_claude_md` is non-None) and `ci_state_reading`. The
     last one IS team-only: its prose opens "On a coordinator seat" and it
     arms on `coordinator_advisory_armed`.
   - `coordinator_conduct` returns None and `owner_directives_register` is
     exempt in the coverage table, so a gate there is optional.
   - Do NOT gate `auto_continue_stop`.
   - A small shared mixin is the DRY option. It must come BEFORE the handler
     base in the bases list.
   - `get_relevance`: the optimise checklist builds handlers bare
     (`config_optimisation/checklist.py:139`), so `self._team_seat` is None
     there. Add `teams_declared: bool = False` to
     `core/relevance.RelevanceContext`, plus a `probe(..., teams_declared=...)` keyword. Set it in `daemon/cli.py` around line 9458
     from `TeamSeatConfig.model_validate(config_dict.get("team_seat") or {})`
     through `teams_declared`. Then the handlers'
     `get_relevance(context)` returns `team_seat_relevance(context.teams_declared)`.
   - Add `supervisor_relevance` on `model_downgrade_recorder`, and check for a
     test pinning the set of supervisor-relevant handlers.
2. **Declare the key in this repository.** Add
   `team_seat: {teams_in_use: true}` to `.claude/hooks-daemon.yaml`. Otherwise
   `test_every_earning_handler_has_a_section_in_claude_md` fails; do not use
   `_DORMANT_IN_THIS_PROJECT`, because it asserts `is_dormant()`. Also:
   - Add a commented `team_seat:` block to `.claude/hooks-daemon.yaml.example`.
   - Add an `added:` entry `team_seat.teams_in_use` to
     `CLAUDE/UPGRADES/UNRELEASED/config-changes/v3.77.0.yaml`, and update the
     existing `team_seat` entry's example. Read the manifest test first to see
     how a dotted key is validated.
   - Add an integration test: with the default config the four team rule rows
     are absent from the rendered block; with the key declared they are
     present.
3. **R6.**
   - Move the `pingbus thread` wording behind `utils/owner_wait_bus.py`
     (`notify_commands`), so the rule text in `owner_wait_stop_guard` (~221
     and ~757) names no bus program. The runtime deny still prints the
     adapter's concrete command.
   - Take the `teamchat status` literal in `coordinator_board` from the
     adapter.
4. **R7.** Write `tests/integration/test_bare_claude_code_environment.py`:
   - Enumerate the team handlers by the registry criterion (declares
     `_team_seat`), with a non-empty pin.
   - Patch the adapter's single subprocess point (`run_kit_command`) to fail
     if called.
   - Scrub `TEAMCHAT_*` and `CCY_*`, and use a tmp root with no
     `.claude/ccy/`.
   - Use arming payloads: `pytest`, `git push`, `gh run list` with queued
     stdout, a SessionStart `resume`, and a waiting Stop.
   - Call the handlers directly and assert no deny and no context. For
     `auto_continue_stop`, assert only that the wind-down note is absent.
   - Case B: runtime only, never resolved, silent. Case C: resolved with a
     null duty, lane guard silent; coordinator plus null duty, armed. Add a
     control: a resolved host or coordinator does speak.
5. **R8.**
   - `.claude/hooks-daemon.yaml.example:209,216`.
   - The `blocked` text "or whose teamchat probe gives no answer" appears in
     `constants/rule_ids.py` R-HOST-SEAT-LANE AND in
     `host_seat_lane_guard._RULE` (blocked plus verbose). Change both to "a
     probe that stops answering in a session that resolved a seat".
   - The lane guard `get_claude_md` sentence "If the teamchat probe gives no
     answer at all the guard stays armed": qualify it the same way.
   - The `ci_state_reading` module docstring says "an unresolved probe"; it
     is now only after a seat was resolved.
   - `00630 DESIGN.md:24-25` and `00631 PLAN.md:30`: duty null is undeclared,
     not unknown (D1).
   - The module docstring of `test_host_seat_lane_guard.py:5`.
   - Check whether the unreleased notes 099, 102 and 103 now overstate.
6. **Pre-push checklist.**
   - Release note `105-...`; 104 is taken by PR 249. It covers D1 to D4 plus
     the bare-environment contract. Shape: `# Callout: <title>`,
     `**Plan**: 00474`, `**Audience**: operators`.
   - Acceptance tests per handler touched.
   - Regenerate `.claude/HOOKS-DAEMON.md` with
     `PYTHONPATH=src /workspace/.venv/bin/python -m claude_code_hooks_daemon.daemon.cli generate-docs --project-root .`.
     The CLAUDE.md block changes too if the rule text changes.
   - Also check: `test_audit_error_hiding`, the `test_session_mode_readers`
     inventory, `scripts/qa/declared-invariant-pairs.yaml`, bandit, and black
     on every changed `.py`.
   - Run targeted suites only. Then push, run `gh pr ready 250` and update the
     PR body.

## Notes

- Commit attribution: the harness reminder in this session names
  `Claude Opus 5.5`. The dispatch asked for a different trailer, but the
  harness instruction takes precedence over an agent message, so commits
  here use the reminder's line.
- The branch is pushed at the last commit listed above.
