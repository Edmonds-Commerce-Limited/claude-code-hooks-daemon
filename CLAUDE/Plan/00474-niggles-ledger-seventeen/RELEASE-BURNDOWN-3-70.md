# Release burndown: next release after v3.69.0

The work standing between `main` and the next release (UNRELEASED notes 001-051; `config-changes/v3.70.0.yaml` already
names it 3.70.0). Evidence: the coordinator's CI and venv checks of 2026-10-13 and the
[burndown audit](subagent-reports/261013-burndown-audit-sonnet.md). A release starts only when the owner types
`/release`; this list says when that would be sound, not when it is wanted.

Tick an item here when it lands, with the commit.

## Must land before `/release`

- [x] **N453**: the source `check.md` skill page catches up with N439, which turns main's full CI run green again (red
  on every full run since 2026-10-12). Merged 190af5059.
- [ ] **One green full CI run on main** after N453. N455's two CI-load failures can still redden it: a Swift lint
  timeout scored as an allow (probe #214), and a timing bound (N376 class). Fix N455's scoring if it recurs; never
  loosen a bound.
- [ ] **Plan 00450**: `.claude/skills/release/invoke.sh` (lines 170-176) still tells the agent the acceptance gate spawns
  parallel Haiku agents, which `acceptance-test/invoke.sh` forbids. The next `/release` reads it.
- [ ] **Plan 00451**: `.claude/agents/release-agent.md` lists 3 of the 6 version-carrying files (missing
  `.claude/HOOKS-DAEMON.md`, `.claude/ccy/claude-supervise.py`, `uv.lock`; `RELEASING.md` has all six), which costs up
  to three red QA cycles mid-release.
- [ ] **Plan 00517 Task 3.0 (N456)**: `prune-venvs --all-except-current --force` would delete the live daemon's venv.
  Ships a destructive command in a release otherwise.

## Owner-directed for this release (2026-10-13)

- [ ] **Plan 00517 Phase 2**: the installed daemon version comes only from the installed `version.py`.
- [ ] **Plan 00517 Phases 3-4**: one staleness rule; venvs with missing or unreadable metadata surfaced to the running
  agent with evidence and removed once confirmed safe; cleanup on restart, provision and session start.
- [ ] **Plan 00517 Phase 5**: release note and post-upgrade task.

## Already in good order

- Plan 00503 (no upgrade approval) is complete and archived; note 022 matches main.
- Plans 00495, 00472, 00471: nothing landed since v3.69.0 beyond journal entries, so nothing half-done ships.
- Plan 00477: what landed (Task 5.2a, notes 025 and 031) is coherent alone; its remaining tasks can follow.
- The 19 🔄/🟡 ledger rows leave no contradictory state on main.
- UNRELEASED notes 001-051 are contiguous.
- No open worktree but the N453 one; 38 merged remote branches deleted and the leftover review worktree removed on
  2026-10-13. Two unmerged remote branches (`agent-a388f9611b6f8f3d1-1f7c8c8f`, a parked alternative N350 fix;
  `feature/00135-tmux-send-keys-injection`, Plan 00135 superseded) need a human to delete.

## Not blocking, worth taking if time allows

- Open ledger rows: N424, N427, N430, N435, N443, N447, N451, N454, N457.
- Untriaged issues #109 to #115 (#113, #114 and #115 read as defects).

## Owner decisions open (none blocks the release)

#91/#106 (Plan 00501), #87 (00513), #92 (00514), #93 (00515), #104 (00479), #107 (00476), #108 (00516, including the
N389 host-name redaction), the N442 release-gate question, the N448 suppress question, and N457's one-at-a-time lock.
