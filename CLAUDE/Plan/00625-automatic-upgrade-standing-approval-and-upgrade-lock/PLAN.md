# Plan 00625: automatic upgrade standing approval and upgrade lock

**Status**: In Progress
**Created**: 2026-11-19
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The owner asked for a standing approval that lets an agent upgrade the hooks
daemon to the latest published release without a human trigger, on by
default, and for an upgrade lock so that when one checkout is mounted by
several agents (containers sharing the folder but not a PID namespace, plus
the host) exactly one upgrades.

This extends the existing route rather than adding one: a new built-in
standing authorisation, the SessionStart `version_check` advisory as the
trigger, and an `--unattended` mode of `scripts/upgrade.sh` that only adds
refusals (lock, release in progress, dirty tree, MAJOR bump, `READ THIS FIRST`, a previously failed version) and rolls back on a failed health
check. One lock file on the shared filesystem is taken by every route that
moves the daemon clone (`upgrade.sh` and `provision.sh`).

All design decisions, and the ones that need the owner, are in
[DESIGN.md](DESIGN.md).

## Goals

- `daemon-auto-upgrade` standing authorisation, on by default, switched off
  by one config line, honest that it is a shipped default.
- `version_check` invites an unattended upgrade only when it is authorised and
  the local pre-check passes, and reports a recorded failure instead.
- `upgrade.sh --unattended` enforces every "never" in DESIGN.md section 4.
- One cross-namespace-safe upgrade lock (owner identity, heartbeat, takeover
  only when provably dead or expired) shared by `upgrade.sh` and
  `provision.sh`.
- Unattended rollback when the daemon does not start or validation fails.
- A failed or needs-human attempt is recorded and not retried until a newer
  release appears.

## Non-Goals

- Tag signature verification (owner decision, DESIGN.md section 5).
- Any new schedule, cron or hook that runs an upgrade by itself.
- Auto-upgrade of the daemon's own repository (self-install).
- Running a real upgrade against any checkout: tests use scratch repos and
  fake releases only.

## Tasks

### Phase 1: Design

- [x] ✅ **Task 1.1**: DESIGN.md: trigger, nevers, supply chain, lock, rollback, loop, self-install

### Phase 2: Standing authorisation

- [x] ✅ **Task 2.1**: tests then code: `daemon-auto-upgrade` id, per-entry default, shipped-default wording, opt-out
- [x] ✅ **Task 2.2**: this repo's config lists it `enabled: false`; example config and handler reference

### Phase 3: The upgrade lock and `--unattended` in Layer 1

- [x] ✅ **Task 3.1**: tests then code: lock acquire, heartbeat, stale rule, takeover, release in `upgrade.sh`
- [x] ✅ **Task 3.2**: tests then code: `--unattended` refusals, attempt record, `--lock-wait`

### Phase 4: Layer 2 and the gate

- [x] ✅ **Task 4.1**: gate verdict file carries `escalations=<n>`; unattended Layer 2 stops on it (exit 5)
- [x] ✅ **Task 4.2**: unattended rollback at Steps 15 and 16

### Phase 5: provision.sh takes the same lock

- [x] ✅ **Task 5.1**: replace the pid-only `lock.d` with the shared lock; lockstep test with `upgrade.sh`

### Phase 6: The trigger

- [x] ✅ **Task 6.1**: `install/auto_upgrade.py`: authorisation read, eligibility pre-check, attempt records
- [x] ✅ **Task 6.2**: `version_check` advisory wording for authorised, refused and recorded-failure cases

### Phase 7: Docs and release

- [x] ✅ **Task 7.1**: LLM-UPDATE.md section, skill `upgrade.md` pointer, `standing_authorisations` claude-md
- [x] ✅ **Task 7.2**: config-changes `v3.76.0.yaml` entry and release note `003`

### Phase 8: Review and gate (coordinator)

- [ ] ⬜ **Task 8.1**: independent review of the branch
- [ ] ⬜ **Task 8.2**: full QA gate; owner rulings on the DESIGN.md OWNER DECISION items; merge

## Success Criteria

- [ ] Every refusal in DESIGN.md section 4 has a test that fails without it
- [ ] Two concurrent lock takers in a test: exactly one wins; a foreign-namespace holder with a fresh heartbeat is never taken over; an expired one is
- [ ] Targeted tests and the full QA gate pass (the gate is run by the coordinator)
- [x] Release note and `v3.76.0` config-changes entry in `CLAUDE/UPGRADES/UNRELEASED/` (the release-bound consequences of this plan)

## Delivery & Milestones

- Design: DESIGN.md (`81b2c3f5e`)
- Authorisation and trigger: `705575c82`, `012061950`, `ea3c4799c`, `f9459d11d`
- Gate and Layer 2: `853e87009`, `adeb815c9`
- Lock and Layer 1: `ff8431cfd`, `b30fcc757`; provision lock and takeover fix: `e8f2bb710`
- Docs and release: `bd6a05d27`, `7fe5b9645`, `825c7d135`
- Phase reports: `subagent-reports/261119-p625-*.md`
