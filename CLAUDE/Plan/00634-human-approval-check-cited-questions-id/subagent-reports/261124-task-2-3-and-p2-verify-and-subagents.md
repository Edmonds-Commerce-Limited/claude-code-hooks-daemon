# Plan 00634 builder report: Task 2.3 (live verify call) and P2 (coordinator sub-agents armed)

Branch `plan-00634-human-approval-check`. The handler stays `mode: advise`, per the owner's ruling. That ruling arrived mid-build and says:

- the check stays advise-only;
- the P1 switches stay OFF, built to a minimal tested size, and are never made the default;
- nothing assumes a team, role or duty exists;
- sub-agent arming applies only to a seat that is positively declared coordinator.

## (A) Task 2.3: the verify call

### What the verifier does

`utils/human_approval.py`: `DEFAULT_VERIFIER` is now `TeamchatVerifyCli()`. The placeholder `contract_unconfirmed_verifier` and `Refusal.CONTRACT_UNCONFIRMED` are removed.

- **argv**: `$TEAMCHAT_KIT/bin/teamchat verify <id> --room questions`. There is no `--json` and no `--team`. The team is bound by the answer's `team` field. The id comes before the flag, as the contract writes it.
- **Runner**: the command runs only through `run_kit_command` and the injected runner. Output size is capped at 64 KiB and the timeout is `Timeout.TEAMCHAT_VERIFY`. The runner call catches `OSError`, `TimeoutExpired`, `ValueError`, `RecursionError` and `UnicodeDecodeError`, and so does the parse. Each becomes a refusal, and only the exception type is logged (invariant 4).
- **Parse**: the answer must be exactly one line, with `kind == "verified"` and the exact 13-key set. Types are checked by exact type:
  - `v` is int 1;
  - `sent_ms` is a non-negative int, not a bool;
  - `human` is a bool;
  - `question` is `Q<n>`, `"none"` or null;
  - `headline` is a string or null;
  - every other key is a string.
- **Acceptance**: the id must match exactly and the team must match after normalisation. A line with `human` other than True is refused by the verifier, and `check_approval` still re-checks room, team, id and human. `text` and `headline` are type-checked and then discarded.
- **Exits**: 23 maps to `LINE_NOT_FOUND`, 22 to `VERIFY_UNTRUSTED`, 20 to `VERIFY_UNREACHABLE` and 14 to `VERIFY_RATE_LIMITED`. Any other non-zero exit, or an OK status with a non-zero code, is refused.
- **Event id**: `\$[A-Za-z0-9_-]{43}`, replacing the provisional `[A-Za-z0-9_+=-]{1,255}`.

### The P1 switches (owner question O4, all OFF)

`BindingPolicy` holds the three switches. The handler reads them from the options `require_question`, `max_line_age_seconds` and `single_use_cites`:

- **`require_question`**: a `question` of `none` or null refuses.
- **`max_line_age_seconds`**: compared against the wall clock. A line more than 60 s in the future is refused.
- **`single_use_cites`**: uses `CiteLedger`, a JSON file holding (team, id, act) triples. It lives at `<daemon untracked dir>/human-approval-used-cites.json` and stores no text. The ledger works as follows:
  - it is resolved lazily, and never while the switch is off;
  - check-and-record happens under a lock;
  - writes are atomic (temp file, then replace);
  - an unreadable, oversized (over 256 KiB) or unwritable file refuses.

While any switch is on, the 300 s in-memory approval record is bypassed, so it cannot reopen a used or aged cite.

## (B) P2: coordinator sub-agents

- `role_gate` and `duty_gate` take `include_subagents` (default False, so advisories and the lane guard are unchanged).
- When it is True, a sub-agent is judged on a DECLARED role or duty only. An unreadable role, team or duty answers NOT_APPLICABLE for a sub-agent, never ROLE_UNKNOWN.
- `is_armed` and `check_approval` take the same flag. Only `human_approval_check` passes True.
- A sub-agent is armed only when a held seat is declared coordinator. That holds even with `coordinator_seats_only: false`.
- Sub-agents of a worker seat, an unresolved or role-null seat, or a session with no team are silent.
- Main-thread behaviour is unchanged.
- `host_seat_lane_guard` was not touched.

**Known collision for a later block flip.** R-BRANCH-SUBAGENT-STOP-GUARD refuses a sub-agent stop that leaves unpushed commits. In block mode, a coordinator seat's sub-agent could therefore be unable either to push without a cite or to stop. A hand-over route is needed, for example letting sub-agents push only their own agent branch, and the owner has not decided. Advise mode creates no conflict. That guard was not changed.

## Surfaces updated

- The handler's docstring, rule text and guidance text.
- `.claude/hooks-daemon.yaml`, `init_config.py` and `docs/guides/HANDLER_REFERENCE.md`.
- The v3.77.0 config-changes manifest: three new `options.*` entries, and a corrected migration note.
- Release note 087 (stale "refuses every cite" text corrected) and the new note 103.
- PLAN.md.

## Tests

- `tests/unit/utils/test_human_approval.py`: rewritten to cover the contract, exits, raising runner and parse, the id grammar, sub-agents, the three switches on and off, the ledger, and the invariants.
- `test_team_role_gate.py`: `include_subagents` cases added.
- `test_human_approval_check.py`: the default verifier is a `TeamchatVerifyCli` over a fake runner, and the cases cover sub-agent arming, options and policy wiring.
- `tests/support/teamchat.py`: the contract fixture, a 43-character `HUMAN_ID` and `SENT_MS`.

## Open items

1. **Live check from a v2 seat (Task 2.4).** These facts are unstated in the relayed contract and were set to the strictest reading:

   - the argv order (id before `--room`);
   - the value of `v` (1 assumed);
   - the types of `item`, `from` and `body_sha256` (string assumed).

   If the real answers differ, every cite refuses. That fails closed.

2. **Ledger lifetime.** The ledger is never pruned. Past 256 KiB (roughly 3,000 entries) it refuses every cite while single use is on, and deleting the file re-allows every recorded cite. This is acceptable only while the switch is off by default.

3. **Unchanged by design.** The approval record is shared by the seat's main thread and its sub-agents, because they carry the same session signals. With the switches off, replay stays unbounded and a human "NO" still verifies (finding 1). Advise mode is annotation only.
