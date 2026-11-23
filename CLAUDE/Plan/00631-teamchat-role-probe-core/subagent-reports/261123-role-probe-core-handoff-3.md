# Plan 00631 handoff 3: stamp and config done; CLI, holding area, PR left

Supersedes handoff 2. Branch `plan-00631-teamchat-role-probe-core`, head
`40e4147fb`, pushed; origin/main had not moved (no merge needed at
`c40aadf48`). Worktree
`/workspace/.claude/worktrees/agent-a4fed6cbe399e3308-e6f56464`.

## Done

- `8954d7eb3` Task 2.2: `HookInputField.TEAMCHAT_RUNTIME` / `TEAMCHAT_KIT`;
  init.sh stamps non-empty values, never overwriting; server.py
  `_stamp_teamchat_signals(hook_input, peer)` reads `cron_hosts.process_environ`
  (a SECOND small `/proc` read beside the hostname one: the hostname seams were
  left alone on purpose, since the full suite cannot be run here; merging the
  two reads is deferred). No read when both fields present or pid unknown.
  `SessionSignals.from_hook_input` (never raises). INPUT-ALLOWLIST entries;
  `scripts/qa/check_input_contract.py` clean. Test isolation: forwarder
  `_run_wrapper` pops both vars; enrichment test autouse fixture patches
  `server.process_environ`. Verified with both vars exported.
- `40e4147fb` Task 2.3 config: `TeamSeatConfig` (`detection` auto|off,
  `resolve_ttl_seconds` 60, 1..3600, extra forbid, `detection_enabled`
  property), `Config.team_seat`; `SeatContextResolver.from_config`;
  `resolve(detection_enabled=None)` uses the instance default. Manifest entry
  in `UNRELEASED/config-changes/v3.77.0.yaml`. The example YAML carries no
  top-level blocks of this kind, so none was added.

Targeted runs: test_teamchat_seat, test_team_seat_config,
test_event_socket_teamchat_signals, test_event_socket_session_hostname,
enrichment, status_raw_text, listeners, test_check_input_contract,
test_config_changes_manifest_examples, test_example_config: green. ruff,
black --target-version py311, mypy clean on touched files.

Known pre-existing local failures (not this branch): 6 status-line tests in
`tests/integration/test_forwarder_jq_free.py` fail with "hooks-relay missing"
because this worktree has no built relay binary.

Light-run helper: `untracked/q.sh "<tests>" "<lint files>" "<mypy files>"`
(venv `/workspace/untracked/venv-workspace-py313-0d6d49c6`, PYTHONPATH=src).

## Left

1. Task 2.3 CLI: own module (precedent `daemon/issue_validity_cli.py`), test
   at the mirror path FIRST (TDD gate); `cli.py` only registers the parser.
   Reads its own environment (`SessionSignals.from_environ(os.environ)`),
   loads `team_seat` config, calls `probe_seat_context` directly (no cache),
   prints state, reason category and validated fields only (never raw output).
   Pick and test exit codes.
2. Holding area: release-notes callout. Take max+1 over every `origin/*`
   branch's `CLAUDE/UPGRADES/UNRELEASED/release-notes/` (main tops out at 024;
   do not fill gaps). Read `UNRELEASED/truth-changes/README.md` to decide
   whether the CLI and payload fields also go in truth-changes (`find-plan`
   was recorded there; the staged file is v3.76.0, do not rename). Add a
   Success Criteria line in PLAN.md citing these artefacts; tick 2.2 and 2.3.
3. Task 1.1: exit 65, F44 hash and the namespace proof stay open unless a
   teamchat source is readable here; record them as explicit open items.
4. PR: `gh pr create --body-file` from scratch, no merge. Body: what it does,
   per-team roles, v2 only, degrade rules (absent vs unresolved, guards armed),
   deferred items, and a security note: `process_environ` loads the peer's
   whole environment in memory (existing hostname behaviour), only the two
   names are kept, nothing logged; `teamchat_kit` selects the binary executed
   and an existing payload value is honoured (trust boundary: the per-user
   event socket; absolute-path check); fixed argv, no shell, 2 s timeout
   (`Timeout.TEAMCHAT_WHOAMI`), output regex-bounded and never logged; worst
   case one timeout per TTL. No private paths, hostnames or seat names.
