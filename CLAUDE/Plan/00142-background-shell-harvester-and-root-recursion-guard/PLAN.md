# Plan 00142: Background-Shell Harvester & Root-Recursion Guard

**Status**: In Progress
**Created**: 2026-06-24
**Owner**: Claude (Opus)
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Implements the two-layer defence proposed in
`untracked/hooks-daemon-runaway-background-shell-harvester.md`, written after an
orphaned `ugrep -rl … /` ran unreaped at >1000% CPU for ~115 minutes, surviving
a context compaction. Nothing tracked, time-boxed, or surfaced the runaway.

Two complementary layers:

- **Layer A — root_recursion_guard** (PreToolUse, blocking): block a recursive
  scanner (`grep -r/-R/-rl`, `ugrep -r`, `find`, `fd`, `rg`) whose path argument
  resolves OUTSIDE the project root — most dangerously `/`, `/proc`, `/sys`,
  `$HOME`, `~`. Escape hatch `MUST_SCAN_ROOT_BECAUSE="…"` mirrors `git_stash`'s
  `MUST_STASH_BECAUSE=`. This alone would have prevented the incident.
- **Layer B — background-shell harvester** (PostToolUse tracker + watchdog-cron
  advisory): track every backgrounded / long-lived child process a tool call
  spawns; on breach (wall-time / CPU / orphaned-past-session) SURFACE it to the
  agent via a non-durable watchdog cron (same `CronCreate` mechanism as
  `recovery_cron_advisor`). **The daemon never kills** — it detects and
  escalates; the agent decides and acts; the cron persists until resolved.

## Goals

- Block obviously-catastrophic root-rooted recursive scans before they run, with
  scoped-search guidance and a `| head`-does-not-bound-`-l` note.
- Provide an explicit env escape hatch for the rare legitimate root scan.
- Track backgrounded/long-lived processes to a daemon-managed state file.
- Advise the agent to create a watchdog cron that re-surfaces a runaway during
  idle and keeps nagging until the agent resolves it; daemon performs no `kill`.
- 95%+ coverage; full QA green; daemon restarts RUNNING; dogfooded in this repo.

## Non-Goals

- The daemon will NOT kill any process autonomously (owner steer — every kill
  decision belongs to the agent's reasoning loop).
- No replacement of `pipe_blocker` allowlisting behaviour.
- Not building a generic process supervisor; scope is detect → surface → resolve.

## Context & Background

See the incident report at
`untracked/hooks-daemon-runaway-background-shell-harvester.md` for the full
timeline, root cause (unscoped recursion; `| head` does not stop a `-l`
producer; no lifecycle ownership), and the acceptance criteria.

Reference handlers:

- `git_stash` — PreToolUse blocking handler with `MUST_*_BECAUSE=` escape hatch.
- `pipe_blocker` — allowlists `grep`/`find` (explains why this class passed).
- `recovery_cron_advisor` — PostToolUse advisory that drives a non-durable cron
  via injected guidance (the daemon cannot create crons itself; it tells the
  agent to). Layer B's watchdog reuses this exact pattern.

## Tasks

### Phase 1: Layer A — root_recursion_guard (PreToolUse blocking)

- [x] ✅ **Task 1.1**: RED — `tests/unit/handlers/pre_tool_use/test_root_recursion_guard.py` (46 tests)
- [x] ✅ **Task 1.2**: GREEN — implemented `root_recursion_guard.py`
- [x] ✅ **Task 1.3**: Wired constants (HandlerID + HandlerKey Literal, Priority=16), `__init__.py`, `hooks/pre_tool_use.py`
- [x] ✅ **Task 1.4**: Dogfood config `.claude/hooks-daemon.yaml` + template `init_config.py` + `.yaml.example`
- [x] ✅ **Task 1.5**: get_claude_md() + get_acceptance_tests()
- [x] ✅ **Task 1.6**: QA green, daemon restart RUNNING, dogfooded live (block + scoped-allow + escape-hatch), docs regenerated

### Phase 2: Layer B — background process tracker + watchdog advisory (PostToolUse)

- [ ] ⬜ **Task 2.1**: RED — tests for `background_process_tracker`
  - registration: detects `run_in_background: true`, trailing `&`, records PGID/command/session/start to state file
  - watchdog advisory: injects CronCreate guidance on first registration
- [ ] ⬜ **Task 2.2**: GREEN — implement tracker + state-file writer (use daemon untracked dir, never /tmp)
- [ ] ⬜ **Task 2.3**: CLI subcommand `harvest-background` evaluating tracked PGIDs vs budgets, emitting breaches + `kill -- -<pgid>` (NO kill performed)
- [ ] ⬜ **Task 2.4**: Wire constants, registration, dogfood config + template
- [ ] ⬜ **Task 2.5**: get_claude_md() + get_acceptance_tests()
- [ ] ⬜ **Task 2.6**: QA green, daemon restart RUNNING, commit

### Phase 3: Integration & docs

- [ ] ⬜ **Task 3.1**: regenerate `.claude/HOOKS-DAEMON.md` (generate-docs)
- [ ] ⬜ **Task 3.2**: full QA + acceptance playbook spot-check
- [ ] ⬜ **Task 3.3**: complete plan, move to Completed/, update README, delete recovery cron

## Technical Decisions

### Decision 1: Daemon never kills — detect & escalate only

**Context**: Autonomous killing could reap a legitimate long build/server.
**Decision**: Layer B surfaces breaches to the agent and re-nags via a watchdog
cron until resolved; the agent issues any `kill`. Matches owner steer in the
proposal.
**Date**: 2026-06-24

### Decision 2: root_recursion_guard priority = 16

**Context**: Safety range is 10-20; 16 is currently unused and sits among the
Bash safety blockers (security_antipattern 14, pipe_blocker 15, git_stash 20).
**Decision**: Use Priority.ROOT_RECURSION_GUARD = 16.
**Date**: 2026-06-24

### Decision 3: Skip get_rules() (follow git_stash precedent)

**Context**: `get_rules()` is optional (base returns []); peer blocker git_stash
does not override it.
**Decision**: Implement get_claude_md + get_acceptance_tests (both required by
enumeration tests); skip get_rules to avoid public-contract scope creep.
**Date**: 2026-06-24

## Success Criteria

- [ ] `grep -rl "x" /` / `find / …` blocked unless `MUST_SCAN_ROOT_BECAUSE=` set
- [ ] Scoped searches under project root pass untouched
- [ ] Backgrounded command registered; watchdog advisory surfaces a breach with
  PID/PGID, command, runtime, reason, ready-to-run `kill -- -<pgid>`
- [ ] Daemon performs no kill
- [ ] All QA checks pass; daemon restarts RUNNING; 95%+ coverage

## Notes & Updates

### 2026-06-24

- Plan created. Failsafe recovery cron `0cd40325` (hourly :37, non-durable).
- Reference patterns mapped via Explore agent; full file-touch checklist captured.
