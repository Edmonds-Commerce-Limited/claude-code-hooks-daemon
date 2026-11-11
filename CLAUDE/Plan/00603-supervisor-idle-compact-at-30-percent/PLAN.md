# Plan 00603: supervisor idle compact at 30 percent

**Status**: In Progress
**Created**: 2026-11-11
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The owner suspects sessions are not compacted as early as they could be. Today the ccy supervisor injects a real `/compact` only when the context reaches the RED tier and the session is idle. For a 1M-token window RED starts at 40% (400k tokens), and the supervisor waits for the turn to settle until the 50% urgent point. Claude Code's own auto-compaction sits near 480k to 567k tokens in this environment. So nothing compacts below 400k, and long busy sessions run on to 500k.

The owner asked for two things. First, make sure Claude Code's own idle compaction is enabled (`idleCompaction`). Plan 00557 already made the daemon check and set it, and this checkout has `idleCompaction: true` in the user settings, so this plan only adds a regression guard that proves it stays on. Second, add the supervisor's own idle compaction: when the session is in a TRUE idle (nothing happening, no background tasks, no running sub-agents, empty input box) and context is at or above 30%, the supervisor compacts, well before the RED tier.

## Goals

- Prove that Claude Code's `idleCompaction` is on in this project's effective settings, and that the check reports it off if a disabler appears (the Plan 00557 check; verify and pin, do not rebuild).
- A new supervisor trigger: true idle plus context at or above a configurable percentage (default 30) causes one armed `/compact`, then the existing `continue` after compaction.
- True idle means all of: the screen shows an idle prompt with an empty input box, no background task is registered, no sub-agent is running, no cron tick or injection is pending, and the state has held for a settle period (default 60 seconds, configurable).
- A cooldown after any compaction (default 30 minutes) so a session that sits at 30% after compacting is not compacted again at once; a floor on absolute tokens so a tiny window is not compacted at 30% of nothing.
- The trigger is off in dry-run mode, logs a clear `decision.log` line, and is configurable through the supervisor's existing env file.

## Non-Goals

- No change to the RED and CRITICAL tiers or to the status-line colours.
- No change to Claude Code's own compaction settings beyond verifying idle compaction.

## Tasks

### Phase 1: Facts

- [x] ✅ **Task 1.1**: Verify `idleCompaction` end to end: effective settings in this checkout, the Plan 00557 optimal-config check, and what Claude Code's idle compaction actually does and when (read the vendored or fetched Claude Code docs; record the trigger and any thresholds).
- [x] ✅ **Task 1.2**: Read the supervisor's idle model (`idle`, `work_idle`, empty input box, the focus hold) and find how background tasks and running sub-agents can be detected from the sidecar or the screen. Record which signals exist and which do not. Result: no sidecar signal reports either; per Plan 00604 the trigger combines Claude Code's own session `status`, sub-agent `finished` flags and background-task exit lines with the rendered screen footer, and fails closed on every one (recorded in `CLAUDE/development/CcySupervisor.md`, "Idle compaction at a percentage"; `idleCompaction` verified on and pinned by a test against the committed project settings).

### Phase 2: Trigger

- [x] ✅ **Task 2.1**: Tests first for the decision function: true idle at and above 30%, not idle with a background task, not idle with a sub-agent running, below 30%, inside the cooldown, inside the settle period, dry-run.
- [x] ✅ **Task 2.2**: Implement the trigger in `.claude/ccy/claude-supervise.py` and its deployed template; confirm the worker reloads (verify the new pid; never restart the session).
- [x] ✅ **Task 2.3**: Configuration (env variables and `ccy.env` comments), `CLAUDE/development/CcySupervisor.md`, release note.

### Phase 3: Proof

- [ ] 🔄 **Task 3.1**: Run it dry first and read `decision.log` for a day of real use, then arm it. Report how often it fires and the context size at each firing.

## Success Criteria

- [ ] The supervisor compacts once, at a true idle at or above 30%, and never while a background task or sub-agent is running.
- [ ] A session sitting at 30% after a compaction is not compacted again within the cooldown.
- [ ] `idleCompaction` is verified on, with a test that fails if the optimal-config check stops reporting a disabler.
- [ ] The pending-release holding area has a release note for the new trigger.

## Delivery & Milestones

- Plan filed from an owner request on 11 November 2026.
