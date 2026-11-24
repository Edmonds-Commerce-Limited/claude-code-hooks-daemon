# Decoupling build (audit R1-R8): slice 1 report and handoff

Spec: `261124-ccy-teams-coupling-audit-fable.md` (this folder), owner rulings
2026-11-24. Branch `plan-00635-host-seat-lane-guard` (historical name; reused
because the merged-branch pool refused a new branch), fast-forwarded to
`origin/main` at `fc4014267` and built in
`/workspace/untracked/worktrees/plan-00635-host-seat-lane-guard`.

## Done (commit `e5fcd12c9`)

- **R1 / D1.** `SeatContext.duty_unknown()` is now True only for an
  UNRESOLVED probe. A null, absent or unreadable duty in a resolved seat is
  undeclared, so `duty_gate` gives NOT_APPLICABLE for it. The local
  workaround in `host_seat_lane_guard._verdict` is gone.
- **R2 / D2.** `_merge` makes a coordinator unknown only beside a `host`
  duty, or beside a **malformed non-null duty** (`"Host!"`, `["host"]`). The
  second case keeps review F2's caution: a garbled value might be a host. A
  null or absent duty leaves a declared coordinator. Disagreeing non-host
  duties (coordinator plus worker rows) leave it declared too, because they
  can never be host. Reading taken on coordinator plus `host` duty: it stays
  role UNKNOWN, as before. So the coordinator advisories and
  `human_approval_check` stay armed there (D5, nothing loosened).
- **R3 / D3.** `SeatContextResolver` remembers, keyed on the runtime alone
  (not the kit), which sessions resolved a seat. That memory sits outside
  the TTL cache, is bounded by `max_entries` and is read under the lock.
  - An UNRESOLVED probe for a session that never resolved a seat now reads
    ABSENT (`ProbeReason.TEAM_UNCONFIRMED`) and logs one INFO line.
  - A session that did resolve a seat stays UNRESOLVED, so it stays armed.
  - Exit 69 or an empty `teams` list clears the memory.
  - New seams: `team_confirmed(signals)` and `confirmed_count()`.
  - `probe_seat_context` and the `team-seat` CLI are unchanged; the CLI still
    shows the raw state for diagnosis.
  - Every UNRESOLVED-based arming path (`human_approval.is_armed`,
    `coordinator_advisory_armed`, `owner_wait_stop_guard._armed_teams`) now
    receives UNRESOLVED only in case D.
- **R4.**
  - `shared_resolver(config)` and `reset_shared_resolvers()` in
    `utils/teamchat_seat.py` give one resolver per `(ttl, detection)`.
  - All eight holders use it, keeping the `_resolver` seam:
    `host_seat_lane_guard`, `human_approval_check`, `ci_state_reading`,
    `coordinator_board`, `coordinator_conduct` (new since the audit),
    `auto_continue_stop`, `owner_wait_stop_guard` and
    `owner_directives_register`.
  - The last two take the registry-injected `_team_seat` instead of their own
    config load. `owner_wait_stop_guard` keeps `_config_loader` for the
    stand-in requirement only.
  - `daemon/server.py` imports `RUNTIME_ENV_VAR` and `KIT_ENV_VAR`.
  - An autouse fixture in `tests/conftest.py` resets the shared resolvers
    around every test.
- **Sub-agent arming (owner Q1).** `host_seat_lane_guard` calls
  `duty_gate(..., include_subagents=True)`. A host seat's sub-agent is armed
  on the DECLARED duty only, never on an unresolved probe or an undeclared
  duty. Reading taken: a sub-agent is **only ever advised**, never denied,
  whatever the mode, and the main thread keeps the configured mode. No mode
  default changed.
- **Tests.** New file `tests/unit/utils/test_teamchat_seat_decoupling.py`.
  Pinned tests in `test_teamchat_seat.py` and `test_team_role_gate.py` were
  flipped or split to the new rulings. New sub-agent cases were added to
  `test_host_seat_lane_guard.py`. The targeted suites pass: 2059 passed,
  1 xfailed. The run covered the team handlers, team-seat CLI, event-socket
  signals, registry, `human_approval`, `team_role_gate` and stop/UPS
  handlers. ruff, black and mypy are clean on the changed files.

## Left (next agent)

1. **R5 / D4.**
   - Add a separate config key. Do NOT extend `detection`, because
     `detection_enabled` is `== "auto"`. Suggested:
     `team_seat.teams_in_use: bool = False`. It needs the manifest entry under
     `added:` in `CLAUDE/UPGRADES/UNRELEASED/config-changes/v3.77.0.yaml`, the
     `.claude/hooks-daemon.yaml.example` and `init_config`.
   - Add a narrow injector protocol (for example
     `guidance_relevant() -> bool`) in `core/claude_md_injector.py`, beside
     the `is_dormant` skip. Implement it only on the team-only handlers:
     `host_seat_lane_guard`, `human_approval_check`, `owner_wait_stop_guard`,
     `coordinator_board`, `coordinator_conduct` and
     `owner_directives_register`. Check whether `ci_state_reading` is
     team-only. Do NOT gate `auto_continue_stop`.
   - Do NOT make the injector honour every handler's `get_relevance`. Doing
     so drops npm, LSP and supervisor guidance and breaks the coverage test;
     the wider option belongs in the niggles ledger.
   - Add `get_relevance` on the same handlers using the same predicate, and
     `supervisor_relevance` on `model_downgrade_recorder`.
   - Decide whether this repository's own `.claude/hooks-daemon.yaml`
     declares the key. It does hold team seats, so most likely yes. Then
     regenerate `.claude/HOOKS-DAEMON.md` with `generate-docs` and check that
     generate-docs and restart injection both see the injected `_team_seat`.
2. **R6.** Move the `pingbus thread` wording behind
   `utils/owner_wait_bus.py` (`notify_commands`) so the
   `owner_wait_stop_guard` rule text names no bus program. Take the
   `teamchat status` literal in `coordinator_board` from the adapter.
3. **R7.** Write `tests/integration/test_bare_claude_code_environment.py`.
   Build the registry from default config. Case A uses a fail-if-called
   teamchat runner and expects no deny and no context from team or supervisor
   handlers; git subprocesses elsewhere are fine. Cases B (runtime only,
   never resolved: silent) and C (resolved, null duty: lane guard silent;
   coordinator plus null duty: armed) need a fake runner that answers.
4. **R8.** Fix the comments at `.claude/hooks-daemon.yaml.example:209,216`,
   `constants/rule_ids.py` (the R-HOST-SEAT-LANE `blocked` text still says
   "or whose teamchat probe gives no answer") and the handler's `_RULE`
   wording. Reword `00630 DESIGN.md:24-25` and `00631 PLAN.md:30` for D1.
   The test module docstring of `test_host_seat_lane_guard.py:5` still says
   "An unreadable whoami means the duty is unknown".
5. **Pre-push checklist.**
   - A release note: take the next free number after 104, checking main and
     open PRs.
   - Acceptance tests per handler touched.
   - `test_audit_error_hiding`, `test_session_mode_readers` inventory,
     `declared-invariant-pairs.yaml` and the guidance coverage test.
   - black on every changed `.py`.

## Deferred / niggles (to record in the ledger)

- The injector-wide relevance gate, which would also quiet the ccy-only
  guidance rows (`R-USAGE-PAUSE-*`, `ccy_supervisor_integrity`,
  `model_downgrade_recorder`) in clients with no ccy. This is out of scope
  for D4 (teams only).
- A malformed non-null duty arms nothing for the lane guard but still makes a
  coordinator unknown. That is deliberate, but it is asymmetric, so the owner
  should confirm.
- `reset_shared_resolvers()` is not yet called on a daemon config reload. A
  `team_seat` change keys a new resolver anyway (the key is ttl plus
  detection), so this is only stale-memory hygiene.
