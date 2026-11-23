# Plan 00634 build handoff 1

Branch `plan-00634-human-approval-check` (pushed). The worktree was
`.claude/worktrees/agent-a6328547e60968275-2a1ab764`. I stopped at the context
budget, partway through the first build unit.

## Done

- `c?` commit 1: public seams in `utils/teamchat_seat.py`, so `verify` reuses
  the 00631 code instead of copying it: `decode_json_document` (strict JSON:
  cap, depth, duplicate keys), `kit_argv`, and `run_kit_command(signals, args, runner=, timeout=)` (checks the kit and the plain absolute paths, sets only
  `TEAMCHAT_RUNTIME`). `parse_whoami` and `_probe` now use them. Tests are in
  `tests/unit/utils/test_teamchat_seat.py` (TestDecodeJsonDocument,
  TestRunKitCommand). The seat, role gate and CLI tests pass: 184.
- Commit 2 (RED, deliberately failing): `tests/unit/utils/test_human_approval.py`
  and a provisional `verify` fixture in `tests/support/teamchat.py`
  (`HUMAN_ID`, `verify_answer(...)`).

## Next: Unit 1, GREEN

Make `src/claude_code_hooks_daemon/utils/human_approval.py` satisfy the red
test. The test file is the spec. In outline:

- `ActClass` (push, delete, permission, merge_main).
- `ApprovalCite(team, event_id)`. `parse_cite` normalises the team with
  `normalise_name`. The event id must match `\$[A-Za-z0-9._~+/=-]{1,255}`; a
  leading `$` rules out option injection. Anything else is refused.
- `VerifiedLine(team, event_id, room, declared_human, question)`. The line
  text is never kept.
- `VerifyFailure(refusal)`.
- `Refusal` categories: NO_CITE, ROLE_UNKNOWN, NOT_COORDINATOR,
  CONTRACT_UNCONFIRMED, VERIFY_UNAVAILABLE, VERIFY_REFUSED, ANSWER_UNREADABLE,
  ANSWER_MISMATCH, NOT_QUESTIONS_ROOM, NOT_HUMAN.
- `parse_verify_answer(text, cite)` uses `decode_json_document`. It requires
  `v` to be exactly the int 1. `id` must equal the cited id, and `team` must
  normalise-equal the cited team. `room` and `kind` must be strings, and
  `declared_human = kind == "human"`. Any other shape is a VerifyFailure:
  ANSWER_UNREADABLE, or ANSWER_MISMATCH for a team or id mismatch.
- `contract_unconfirmed_verifier` always answers `VerifyFailure(CONTRACT_UNCONFIRMED)`.
  `DEFAULT_VERIFIER` points at it (fail closed until issue 369 is confirmed).
  Its reason text must contain "unverified here".
- `TeamchatVerifyCli(runner=default_command_runner, timeout=...)`. Its argv is
  `verify --json --team <T> <id>` through `run_kit_command`. The `--json` flag
  is UNVERIFIED HERE. The outcome mapping is pinned by the test table:
  - NOT_FOUND, TIMEOUT, UNTRUSTED and any ProbeReason map to VERIFY_UNAVAILABLE.
  - TOO_LARGE maps to ANSWER_UNREADABLE.
  - Every non-zero exit maps to VERIFY_REFUSED.
- `ApprovalRecords(clock=, ttl_seconds=300)` lives in daemon memory only, so a
  Bash write cannot mint one. It is keyed by (signals, cite, act). Only passes
  are recorded.
- `GoGrant(team, classes, window_end)`.
- `is_armed(hook_input, context)` holds Q5 provisionally, pending an owner
  ruling. It arms on the main thread only, when not ABSENT and some team's
  role is coordinator or unknown (UNRESOLVED, a null role, conflicting rows).
  A worker seat or a sub-agent is not armed.
- `check_approval(hook_input, context, signals, *, acts, cite, verifier, go, records, clock)` runs in this order:
  1. ABSENT, or a sub-agent, never passes, and the verifier is never called.
  2. Acts covered by the GO pass if `role_gate(go.team, coordinator)` is
     APPLIES, the act is in `classes`, and `now < window_end`.
  3. For the remaining acts, a missing cite is NO_CITE.
  4. `role_gate(cite.team)` must be APPLIES. ROLE_UNKNOWN gives ROLE_UNKNOWN;
     anything else gives NOT_COORDINATOR. The verifier is not called in either
     case.
  5. A live record per act skips the verifier.
  6. Otherwise the verifier runs. The answer must match the cited team and id
     (else ANSWER_MISMATCH), the room must be `questions`, and `declared_human`
     must be true. Every act is then recorded.
- Add `Timeout.TEAMCHAT_VERIFY` to `constants/timeout.py`.
- The module source must not contain the words pingbus, history or password
  (a test checks this).

## Then: Unit 2, the guard (Task 2.2)

- A PreToolUse handler `human_approval_check`, advisory first, with the mode
  off | advise | block (advise by default).
- It classifies destructive acts by reusing the existing detectors:
  `merge_to_main_approval.merge_target`, the `destructive_git` and
  `dangerous_permissions` classifiers, and `strip_inert_spans`. Do not write
  new regexes.
- The silent path: `is_armed` is false, or the team is absent.
- Q4 is provisional, pending an owner ruling: the cite is a trailing shell
  comment `# human-approval team=<T> id=<$id>`. A comment is never expanded,
  which matters because the id starts with `$`.
- It resolves the seat with `SeatContextResolver.from_config` and
  `SessionSignals.from_hook_input`.
- A pass must never relax another handler (invariant 1). In advise mode it
  must never say "verified" for a failed cite.
- Plumbing follows commit fb583a8233:
  - code: HandlerID, Priority, RuleID;
  - config: `.claude/hooks-daemon.yaml(.example)`, and a config-changes entry
    under `CLAUDE/UPGRADES/UNRELEASED/`;
  - docs: `docs/guides/HANDLER_REFERENCE.md` and CONFIGURATION.md;
  - tests: the claude-md coverage and scope-default tests.

## Open (owner) and unverified

- Q4 (how the cite is passed) and Q5 (workers) are builder choices, not
  settled. Journal them with `mkplan.bash --journal` as owner ruling pending.
- The issue 369 `verify` answer shape and flags are unverified here; the
  fedora-desktop repository has issues disabled, so `gh` cannot read 369. The
  default verifier denies.
- Gap to raise: under Q5-provisional, a coordinator's sub-agent is not armed,
  so a sub-agent push escapes the guard.
- Replay: one verified human line can authorise any act of the cited classes
  within the TTL. Nothing binds the line's text to the act.

## How to run

`PYTHONPATH=src` is needed, because the shared venv imports `/workspace/src`
otherwise. Run tests with:

`PYTHONPATH=src nice -n 19 /workspace/untracked/venv-workspace-py313-0d6d49c6/bin/python -m pytest <files> -q -p no:cacheprovider --no-cov`
