# Plan 00635: host-seat lane guard

**Status**: In Progress
**Created**: 2026-11-23
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Child (e) of umbrella [Plan 00630](../00630-coordinator-level-skills-ccy-teams-aware/PLAN.md);
design in its [DESIGN.md](../00630-coordinator-level-skills-ccy-teams-aware/DESIGN.md)
section 15 (fedora-desktop Plan 00263 D3). Owner ruling (lts-infra Q62): host
sessions should not run tests; host seats are for deployments or triage at
desktop level, and they are not workers.

This plan owns ONE layer: the dynamic, by-duty check. A PreToolUse handler
refuses QA, test and build commands when any held team of the session has duty
`host` (from `teamchat whoami --json`), reusing the existing command
classification. The static layer is fedora-desktop's: `cc-run` writes
`cc-deny.json` from the seat's duty and passes it on a host launch. This plan
builds no deny rules.

## Decision (owner, lts-infra Q64 D3, settled; 00630 Q14)

Build the handler. On a seat whose duty (per team, from `teamchat whoami --json`) is host, the guard refuses test, build, lint and QA commands. The
static deny rule is fedora-desktop's `cc-deny.json` (the coordinator is having
fedora-desktop.1 add the host-seat entries); this plan adds no deny-rule task.
An unreadable `whoami` means role unknown and the guards stay armed.

**Decision (owner, 2026-11-24)**: only an explicit `host` duty arms the guard.
A seat whose duty is null, missing or unreadable is silent (duty is an optional
teams field); a host duty in one team is not disarmed by a null duty in
another. A probe that gives no answer at all (UNRESOLVED) keeps the guard
armed. Finding 2 is re-scoped: the lane list moves to a per-language strategy
domain (`strategies/lane_commands/`); `npm t` and `pre-commit run` are closed;
`docker exec` and `ssh` stay an owner question; the other finding-2 spellings
are accepted as won't-chase (the guard advises, it is not a sandbox).

## Goals

- In a session holding a team with duty `host`, a QA/test/build command
  (including via `sh -c` and scripts) is refused with a message naming the
  lane; deployment and triage commands are untouched; advisory first.

## Non-Goals

- Deny rules (fedora-desktop's `cc-deny.json`). A host `cc` session with no
  team (it has no duty; fedora-desktop's static layer covers it). Any session
  with no `host` duty.

## Tasks

### Phase 1: Decision and RED

- [x] ✅ **Task 1.1**: Record the Q64 ruling in the umbrella DESIGN.md
  (Q14 and section 15, settled).
- [x] ✅ **Task 1.2** (test-first, red before the handler; tests in
  `tests/unit/handlers/pre_tool_use/test_host_seat_lane_guard.py`): duty `host` in any
  held team denies pytest, npm test, build, lint and QA commands incl. `sh -c`
  and scripts; deploy and triage allowed; worker and coordinator unaffected;
  unreadable `whoami` = role unknown, guards armed; absent team unchanged;
  probe with no answer reports once (Q9).

### Phase 2: Handler

- [ ] 🔄 **Task 2.1** (built, advise mode, targeted QA green; live verification
  in a host-duty seat and the promote-to-block ruling remain): Handler reusing the slow-command
  classifier, with its lane list held per language in `strategies/lane_commands/`
  (`classify` and `FindingKind` in
  `src/claude_code_hooks_daemon/utils/long_running_command.py`, as used by
  `handlers/pre_tool_use/long_running_command_guard.py`), advisory first. Name
  it distinctly from the existing `host_command_guard.py` (docker root mount,
  gh auth token, pip index, `crontab -r`; Plan 00483), e.g.
  `host_seat_lane_guard.py`. The fedora-desktop `cc-deny.json` half is
  unverified here;
  live verification in a host-duty seat; promote to block when ruled.
  Targeted QA green.
  **Preconditions for switching to `mode: block`** (independent review of
  PR #233, `subagent-reports/261123-opus-independent-review-pr233.md`; fixed
  in advise: findings 1, 4, 6, 7; OPEN: 3, and 2 only for `docker exec`/`ssh`):
  - Finding 2 (re-scoped 2026-11-24, see Decision): CLOSED `npm t` and
    `pre-commit run`; OWNER QUESTION `docker exec` and `ssh`; WON'T-CHASE the
    rest. The original list, about 40 wrapper and launcher bypasses the classifier misses:
    `xargs`, `eval`, `$(...)` and backticks in argument position,
    `echo pytest | bash`, `python -I/-X ... -m pytest`, `python -c`,
    `coverage run -m`, `uv run -p/--python`, value options of `stdbuf`,
    `exec`, `env -C`, `sudo -h/-T`, unpeeled wrappers (`taskset`, `flock`,
    `chronic`, `unbuffer`, `script -qc`), `make -C/-f`, `gmake`/`just`/
    `task`/`hatch`, package-manager spellings (`npm t`, `run-script`,
    `pnpm vitest`, `yarn jest`, `bunx`), `cargo +nightly test`,
    `pre-commit run`, `run_autofix.sh`, and container or remote execution
    (`docker exec`, `ssh`; owner to rule).
  - Finding 3, sub-agents of a host seat are never judged (`duty_gate`
    returns NOT_APPLICABLE off the main thread): needs an owner ruling to
    accept (and document) or to arm sub-agents.
  - Also check the teamchat kit emits `duty` (finding 10) before promoting.

## Dependencies

- Plan 00631 (`any_duty`); the Q64 ruling. Related fedora-desktop Plan 00263
  (static layer).

## Success Criteria

- [x] Fixtures above pass; absent-team fixture passes.
- [x] Release-bound items recorded in the pending-release holding area
  (`CLAUDE/UPGRADES/UNRELEASED/release-notes/091-host-seat-lane-guard.md`
  and the `host_seat_lane_guard` entry in `config-changes/v3.77.0.yaml`).

## Delivery & Milestones

- Plan filed; revised for the fedora-desktop vet (duty, layer ownership).
