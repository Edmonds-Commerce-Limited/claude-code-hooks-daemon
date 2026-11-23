# Plan 00631 — independent-review fixes: handoff (context budget reached)

Review being fixed: `untracked/agent-reports/261123-00631-independent-review.md`
(main checkout). Branch `plan-00631-teamchat-role-probe-core`, PR #222. Do NOT merge.
CI at start had no red (only pending). origin/main had not moved.

## Done (each red test commit, then fix commit; pushed)

- F1: `parse_whoami` size cap (`MAX_OUTPUT_BYTES` 64 KiB -> `output_too_large`),
  depth pre-scan (`MAX_JSON_DEPTH` 32 -> `not_json`), catches RecursionError and
  MemoryError. CLI test: hostile output exits 3.
- F2/F9: `normalise_name` (strip + casefold + grammar, else unknown) for team,
  role, duty; team key normalised before grouping and in `_seat`; `_merge` order
  `host > unknown > worker > coordinator` (any host row -> host; disagreement ->
  unknown; coordinator only beside a readable non-host duty). `role_gate`
  normalises the action team (blank -> ROLE_UNKNOWN). Decision: coordinator +
  worker rows stay UNKNOWN (a conflict is an unknown reading, which outranks worker).
- F3: `probe_environment` / `PROBE_ENV_ALLOWLIST` (PATH, HOME, USER, LOGNAME,
  LANG, LC_ALL, LC_CTYPE, TMPDIR, XDG_RUNTIME_DIR) + overlay.

## Red tests committed, fix NOT yet written

- F4 (in `test_bad_document_is_unknown`): duplicate keys -> SHAPE_MISMATCH
  (`object_pairs_hook` raising a private exception, caught before ValueError);
  `v: 1.0` -> VERSION_MISMATCH (`type(version) is int`).
- F6 lexical (in `test_relative_signal_is_unknown`): kit/runtime must be absolute,
  `os.path.normpath(p.rstrip('/')) == p.rstrip('/')`, no control chars/NUL ->
  SIGNAL_NOT_A_PATH, in `_probe`.

## Left

- F5: `default_command_runner` -> Popen(start_new_session=True, stdin=DEVNULL,
  stderr=DEVNULL), deadline-bounded selector/os.read loop up to cap+1, on timeout
  or over-cap `os.killpg(SIGKILL)` (tolerate ProcessLookupError) then wait. Add a
  new CommandStatus for over-cap -> ProbeReason.OUTPUT_TOO_LARGE. Tests: grandchild
  dies on timeout (`sh -c 'sleep 30 & echo $!; wait'`), stdin is /dev/null,
  oversized output.
- F6 filesystem: in the real runner, realpath of argv[0] must stay under realpath
  of its kit (argv[0] grandparent); refuse world-writable binary/dir. Runner tests
  using bare `sh`/`sleep` must switch to absolute paths. Keep the Invariant 5
  test (fake runner) as is.
- F7: one source, pair-atomic: peer environ readable -> it supplies both fields
  (replacing/popping payload values); unreadable -> payload pair stands.
  `server._stamp_teamchat_signals`, `init.sh` ~4363, tests in
  `tests/unit/daemon/test_event_socket_teamchat_signals.py` (overwrite test) and
  `tests/integration/test_forwarder_jq_free.py` param row 4; INPUT-ALLOWLIST text;
  umbrella 00630 DESIGN section 5 ("never overwritten" sentence).
- F8: bound `SeatContextResolver._cache` (max entries; evict expired, then oldest).
- Docs: 00631 DESIGN/PLAN mention of the merge order, env allowlist, precedence.
- PR comment listing fixes (no private paths).

Test command (worktree root): `PYTHONPATH=src nice -n 19 /workspace/untracked/venv-workspace-py313-0d6d49c6/bin/python -m pytest -q tests/unit/utils/test_teamchat_seat.py tests/unit/utils/test_team_role_gate.py tests/unit/daemon/test_team_seat_cli.py tests/unit/daemon/test_event_socket_teamchat_signals.py`
