# Plan 00498: autonomy only where allowed

**Status**: Not Started
**Created**: 2026-10-06
**Owner**: dev
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Owner request (2026-10-06): "I would like to be able to fully prevent crons by containerisation/env. This project,
when running at desktop level, should never have any kind of goal setting, crons etc that can derail it onto doing
general work that was not explicitly requested." And: the status bar already tells desktop, LXC, Podman and Docker
apart; "this is what I mean about env".

The trigger: a desktop agent the owner started for one task (Plan 00487's live test) drifted into other work. In a
desktop session today, the daemon's own machinery pushes it towards general work:

- **Global crons**: `persistent_crons` declares `failsafe-recovery` and the background watchdog with no `hosts:`
  limit, so `persistent_cron_assertor` asks EVERY session to create them. The failsafe tick says "resume ... the active
  plan/task". Only `issue-sdlc` is limited, to the `cchd-sdlc-runner` alias.
- **Goal ledger**: the Stop hook challenges a stop on behalf of every ledgered plan still In Progress ("Continue that
  work, or stop ... naming why each listed plan cannot proceed").
- **Plan edits**: the plan workflow tells the session to create a failsafe recovery cron when it creates or edits a
  plan.
- **Other drivers**: the `[awaiting-human]` stand-in cron, goal injection for the ccy supervisor, and the
  recovery-cron advisors.

The environment is already detected:

- `utils/container_detection.py: detect_container_runtime()` returns `docker`, `podman`, `lxc`, `generic` or `None`
  (the bare host, which is a desktop session), and the status line uses the same detection.
- The role alias `HOOKS_DAEMON_HOSTNAME` (Plan 00470 Task 6.1) gives a second, finer key.

## Goals

- One config switch decides, per environment, whether ANY autonomy runs: declared crons, the failsafe cron and its
  advice, goal ledger challenges, the stand-in cron, goal injection, and recovery-cron advice on plan edits.
- In an environment where autonomy is off, a session does only what it was asked: nothing is scheduled, nothing
  challenges a stop on behalf of other plans, and nothing tells it to resume other work.
- This repository turns autonomy off on the bare host (desktop) and keeps it in its containers.

## Non-Goals

- Changing any guard. Protection runs everywhere; only the work-driving machinery is gated.
- Removing the stop-reason rule (`STOPPING BECAUSE:`). It asks for an explanation, not for more work.

## Proposed shape (Task 1.1 settles it)

```yaml
autonomy:
  environments: [docker, podman, lxc, generic]   # bare host ("host") left out: no autonomy on a desktop
  hosts: []                                       # optional: role aliases that may run autonomy anywhere
```

- **Values:** `host`, `docker`, `podman`, `lxc` and `generic`, matching `detect_container_runtime()`, where `host`
  means `None`.
- **Default for clients:** every environment, so behaviour is unchanged until a project opts in.
- **Visibility:** the status line and SessionStart say plainly when autonomy is off, and why.

## Tasks

### Phase 1: Design

- [x] ✅ **Task 1.1**: List every handler and advisory that drives work rather than protects (start from the list
  above; search for cron, goal, stand-in, resume and recovery wording). Settle the config shape, the default, and how
  `hosts:` aliases combine with environments. Inventory:
  [subagent-reports/261006-autonomy-inventory-sonnet.md](subagent-reports/261006-autonomy-inventory-sonnet.md).

### Phase 2: Build (TDD)

- [x] ✅ **Task 2.1**: An `autonomy_allowed()` helper over `detect_container_runtime()` and the role alias, and the
  `autonomy:` config model with validation and a config-changes manifest entry.
- [x] ✅ **Task 2.2**: Gate every item from Task 1.1 on it, each with a test that it is silent where autonomy is off
  and unchanged where it is on.
- [x] ✅ **Task 2.3**: Status line and SessionStart wording when autonomy is off.
- [x] ✅ **Task 2.4**: This repository's config: autonomy in containers only.

### Phase 3: Prove

- [ ] ⬜ **Task 3.1**: Live: a desktop (host) session of this repository creates no crons, receives no failsafe or goal
  pressure, and stops when its one task is done. A container session is unchanged.

## Success Criteria

- [ ] On a desktop session of this repository, `CronList` stays empty and no stop is challenged on behalf of other
  plans.
- [ ] A ccy container session keeps all of today's autonomy.
- [ ] A client project with no `autonomy:` block behaves exactly as before.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00498-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Plan filed from the owner's request, after a desktop agent drifted off its one task.
