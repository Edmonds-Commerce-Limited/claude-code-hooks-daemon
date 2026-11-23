# Plan 00631 — independent-review fixes: handoff 2 (context budget reached)

Continues `261123-review-fixes-handoff.md`. Review:
`untracked/agent-reports/261123-00631-independent-review.md` (main checkout).
Branch `plan-00631-teamchat-role-probe-core`, PR #222. Do NOT merge.
origin/main had not moved at `2c67c64d0`.

## Done since handoff 1 (red then green, all pushed)

- F4/F6 lexical green `5ed204309`: `object_pairs_hook` duplicate keys ->
  SHAPE_MISMATCH; `type(v) is int`; `_is_plain_absolute` for kit/runtime.
- F5 `b1c3d33c5`/`91cbd072c`: runner is Popen(start_new_session, stdin and
  stderr DEVNULL), selector read capped at `MAX_OUTPUT_BYTES`; timeout or
  over-cap -> `os.killpg(SIGKILL)` then wait. New `CommandStatus.TOO_LARGE`
  -> `ProbeReason.OUTPUT_TOO_LARGE`.
- F6 filesystem `5e2328d09`/`dfb44ab96`: `_binary_trust` in the real runner:
  argv[0] absolute, resolved binary inside resolved kit (argv[0] grandparent),
  binary, its dir and kit not world-writable. New `CommandStatus.UNTRUSTED` ->
  `ProbeReason.KIT_UNTRUSTED`. Runner tests use `/bin/sh`, `/bin/sleep`.
- F7 `aa7dac926`/`2c67c64d0`: pair from one source. `server._stamp_teamchat_signals`
  reads the peer every time; readable env sets non-blank / pops blank; unreadable
  or unknown peer leaves the payload pair. `init.sh` forwarder: same rule from its
  own env. Protocol comment and INPUT-ALLOWLIST text updated.

## Left

- F8: bound `SeatContextResolver._cache` (max entries; evict expired, then
  oldest). Optional: shorter TTL for ABSENT/no_session answers (review F8 bullet 1).
- Docs: 00631 DESIGN/PLAN mention of merge order, env allowlist, runner limits
  (cap, group kill, binary trust), signal-pair precedence; umbrella
  `CLAUDE/Plan/00630-coordinator-level-skills-ccy-teams-aware/DESIGN.md:156`
  still says "value already on the payload is never overwritten" — fix.
- PR #222 comment listing F1-F8 fixes (no private paths), then `gh pr checks 222`.

## Notes

- `tests/integration/test_forwarder_jq_free.py` has 6 `test_status_line_*`
  failures locally: "hooks-relay missing or not executable" (no relay binary in
  this worktree). Unrelated to this work.
- Targeted QA script: `untracked/scratch/qa631.sh [extra test files]` (worktree
  root; writes `untracked/scratch/qa631.out`).
