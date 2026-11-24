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

## Left

R8, then the pre-push checklist, then `gh pr ready 250` and the PR body.
