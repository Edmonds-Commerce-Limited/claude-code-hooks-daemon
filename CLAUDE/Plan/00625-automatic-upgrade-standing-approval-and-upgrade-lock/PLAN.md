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

All design decisions are in [DESIGN.md](DESIGN.md). Its section 11a holds the
six rulings settled under the owner's delegation, section 12 the threat model
and section 13 the tests that must exist. An unattended upgrade installs only
a release whose tag signature verifies against a key a human added to the
project, so every install fails closed until that key exists.

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

- Shipping a release-signing key, or taking one from a tag, a release or the
  repository host: a human adds it per project (DESIGN.md ruling 2).
- Changing the attended upgrade route.
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

- [x] ✅ **Task 8.1**: independent review of the branch (verdict FAIL; `subagent-reports/261119-p625-adversarial-review.md`)
- [x] ✅ **Task 8.1a**: review fixes F1 (takeover generations) and F2 (Layer 2 holds the lock as writer) `d7acda90a`; M10 (example config leaves the entry unlisted) `b4ea0fe4a`; F3 to F5 by the reviewer
- [x] ✅ **Task 8.1b**: the six open points settled by a fable sub-agent under the owner's delegation, with a threat model (DESIGN.md sections 11a, 12, 13; `subagent-reports/261119-fable-settle-and-threat-model.md`)
- [ ] ⬜ **Task 8.2**: fresh independent re-review of the finished branch against DESIGN.md sections 11a to 13; full QA gate; the owner shown rulings 1 and 5 (they loosen guards, and the delegation reached the settling seat only through the coordinator); merge

### Phase 9: Build the rulings (requirement ids and test ids are DESIGN.md's)

Already built and kept: `scripts/lib/release_tag_verify.sh`, the owned-path
dirty check, the skill's ask-stop text.

- [ ] ⬜ **Task 9.1**: harden the verify lib before its first release: `command -p` ssh-keygen, git 2.34 minimum, replace objects off and git location variables unset, tag points at a commit whose `version.py` names it, no `cert-authority` line (R2.2; V3, V8, V9)
- [ ] ⬜ **Task 9.2**: signers file usable only when tracked and identical to `HEAD`; add it to the owned paths (R2.1, R5.1; V1, V2)
- [ ] ⬜ **Task 9.3**: `scripts/upgrade_unattended.sh`, the shim branch and Layer 1: verify, extract by commit id, byte comparison, verification repeated under the lock, target by commit id, refuse the redirecting variables, skip self-bootstrap, explicit VERSION (R3.1 to R3.3; V4, V5, V6, V10, V11)
- [ ] ⬜ **Task 9.4**: Layer 2 receives the verified commit id, refuses a mismatch and deploys by id (R3.4; V7)
- [ ] ⬜ **Task 9.5**: the entry enforces the opt-out, `disable_tags` and self-install through the installed Python pre-check, failing closed (R1.5; V12)
- [ ] ⬜ **Task 9.6**: soak period from a first-sighting record (R1.6; V13)
- [ ] ⬜ **Task 9.7**: `started` attempt record written by Layer 1 under the lock, after its last refusal (a dirty path or a held lock leaves none); `needs-human` record for a signature mismatch; halt file when the rollback fails (R1.7, R2.5, R6t.3; V14, V27)
- [ ] ⬜ **Task 9.8**: never-unattended fixes: release-state as a dangling symlink, MAJOR baseline from the clone and a stamp above it, strictly newer only (R1.3; V15, V16)
- [ ] ⬜ **Task 9.9**: `hooks-daemon release-signers add|list|remove` (R2.3; V23)
- [ ] ⬜ **Task 9.10**: built-in write guard on the signers path and denial of the key command to an agent's Bash (R2.4; V24)
- [ ] ⬜ **Task 9.11**: `Requires human` field on post-upgrade tasks and guides, read by the gate, required by the release checks; pending-human file reported by `version_check` (R4.1, R4.2; V17, V18)
- [ ] ⬜ **Task 9.12**: a commit script the skill calls, so the unattended commit takes only the owned paths, says it was automatic, never pushes; one owned-path list held equal by a test (R5.2, R5.3, R1.2; V19, V20)
- [ ] ⬜ **Task 9.13**: `check_eligibility` mirrors every refusal it can judge offline (no key, dirty owned path, soak, records, halt) so no doomed run is invited (R1.1, R5.4; V1, V21)
- [ ] ⬜ **Task 9.14**: once-only notice in both wordings; nothing injected without a key; the one-line injected text (R1.1, R1.2, ruling 6; V21)
- [ ] ⬜ **Task 9.15**: Plan 00223 amendment in the handler docstring, tests, handler reference and example config; only one default-on id (R1.4; V22)
- [ ] ⬜ **Task 9.16**: unattended reads upgrade material only from the verified commit; dependencies only from the lock file (R6t.1, R3.5; V30)
- [ ] ⬜ **Task 9.17**: lock paths must be regular files (R6t.2; V26); run `test_upgrade_lock.py` in full after the last `upgrade.sh` edit
- [ ] ⬜ **Task 9.18**: release procedure verifies the new tag against the owner's own allowed-signers file before publishing (R2.7; V29)
- [ ] ⬜ **Task 9.19**: end-to-end tests with both real layers, a `breaking: true` manifest and a real rollback (V28); the `valid-before` probe (V25)
- [ ] ⬜ **Task 9.20**: docs: `CLAUDE/LLM-UPDATE.md` unattended section, release note `003`, `config-changes/v3.76.0.yaml`, the owner's key step and the rotation and revocation rules

## Success Criteria

- [ ] Every refusal in DESIGN.md section 4 has a test that fails without it
- [ ] Two concurrent lock takers in a test: exactly one wins; a foreign-namespace holder with a fresh heartbeat is never taken over; an expired one is
- [ ] Every test in DESIGN.md section 13 exists and was seen failing first
- [ ] With no key in the project, no unattended run changes anything, in every test fixture that omits the key
- [ ] Targeted tests and the full QA gate pass (the gate is run by the coordinator)
- [x] Release note and `v3.76.0` config-changes entry in `CLAUDE/UPGRADES/UNRELEASED/` (the release-bound consequences of this plan)

## Delivery & Milestones

- Design: DESIGN.md (`81b2c3f5e`)
- Authorisation and trigger: `705575c82`, `012061950`, `ea3c4799c`, `f9459d11d`
- Gate and Layer 2: `853e87009`, `adeb815c9`
- Lock and Layer 1: `ff8431cfd`, `b30fcc757`; provision lock and takeover fix: `e8f2bb710`
- Docs and release: `bd6a05d27`, `7fe5b9645`, `825c7d135`
- Phase reports: `subagent-reports/261119-p625-*.md`
