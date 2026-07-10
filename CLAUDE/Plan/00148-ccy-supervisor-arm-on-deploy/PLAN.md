# Plan 00148: ccy supervisor arm on deploy

**Status**: In Progress
**Created**: 2026-07-10
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

v3.33.0 (Plan 00147) auto-deploys the standalone PTY supervisor
(`claude-supervise.py`) into a project's `.claude/ccy/` on install/upgrade, but
it only **copies the script** — it never **arms** it. Arming requires
`.claude/ccy/ccy.env` to export `CCY_CLAUDE_WRAPPER=".../claude-supervise.py --arm --"`; the launcher (podman `entrypoint.sh` / LXC `ccy()` alias) sources
that file and prepends `$CCY_CLAUDE_WRAPPER` to the `claude` invocation. Because
the deploy never writes `ccy.env`, a client project's `${CCY_CLAUDE_WRAPPER:-}`
stays empty, the launcher runs plain `claude`, and the freshly-deployed
supervisor is inert — a complete no-op. This is a field-reported bug.

This hotfix makes the deploy **deploy + arm** by default. After copying the
script it ensures `.claude/ccy/ccy.env` exports an armed, path-independent
`CCY_CLAUDE_WRAPPER`, idempotently and respecting any pre-existing user setting.
It ships as a patch release (v3.33.1).

## Goals

- The ccy deploy arms the supervisor: it writes/ensures an armed
  `CCY_CLAUDE_WRAPPER` export in the target `.claude/ccy/ccy.env`.
- Arming is idempotent and respects the user: an existing `ccy.env` that already
  sets (or explicitly comments out) `CCY_CLAUDE_WRAPPER` is left untouched.
- The armed wrapper path is launcher-independent (self-locating via
  `${BASH_SOURCE[0]}`) so it works for podman (`/workspace` mount) AND LXC
  (arbitrary project dir) — closing LXC-SUPPORT.md open question #2.
- Tri-state semantics: `true` and absent(`None`) both deploy **and** arm; absent
  still recommends making it explicit. `false` deploys nothing and arms nothing.
- Self-install (dogfood) stays a no-op: the tracked `ccy.env` already sets the
  wrapper, so arming detects it and leaves it untouched.

## Non-Goals

- No changes to the launcher (`entrypoint.sh` / LXC alias) — the source+prepend
  contract already exists; arming only populates the file it sources.
- No changes to the supervisor state machine (`claude-supervise.py` logic).

## Tasks

### Phase 1: TDD the arm-on-deploy behaviour

- [ ] ⬜ **Task 1.1**: RED — add failing tests to
  `tests/unit/install/test_ccy_supervisor.py`: arms fresh `ccy.env`; appends to
  an existing `ccy.env` lacking the wrapper; leaves an existing wrapper (armed
  OR commented) untouched; `false` arms nothing; absent + `true` both arm; the
  generated line sources in bash to an absolute `claude-supervise.py --arm --`.
- [ ] ⬜ **Task 1.2**: GREEN — extend `install/ccy_supervisor.py` with an arm
  step (`armed` field on the result; idempotent `ccy.env` writer).
- [ ] ⬜ **Task 1.3**: REFACTOR + 95%+ coverage on the module.

### Phase 2: Consistency + docs

- [ ] ⬜ **Task 2.1**: Update the tracked dogfood `.claude/ccy/ccy.env` to the
  self-locating wrapper form (resolves identically here; fixes LXC fragility).
- [ ] ⬜ **Task 2.2**: Update `CcyConfig` docstring/field text and
  `docs/guides/CONFIGURATION.md` — deploy now arms by default.
- [ ] ⬜ **Task 2.3**: Add `CLAUDE/UPGRADES/UNRELEASED/truth-changes/v3.33.1.yaml`
  (the "deploy does not arm" statement became false).

### Phase 3: Verify + release

- [ ] ⬜ **Task 3.1**: `./scripts/qa/llm_qa.py all` → 13/13; daemon restart RUNNING.
- [ ] ⬜ **Task 3.2**: `/release` patch → v3.33.1.

## Success Criteria

- [ ] Deploy result reports `armed=True` for a fresh/unconfigured ccy project.
- [ ] Existing user `CCY_CLAUDE_WRAPPER` (set or commented) is never clobbered.
- [ ] Generated `ccy.env` sources to an absolute armed wrapper path in bash.
- [ ] QA 13/13, daemon RUNNING, patch released.

## Notes & Updates

### 2026-07-10

- Plan scaffolded. Recovery cron `26b41693` (hourly :37, non-durable) armed.
- Root cause confirmed: `deploy_ccy_supervisor_if_enabled` copies the script but
  never writes `ccy.env`, so `CCY_CLAUDE_WRAPPER` is unset in clients → launcher
  runs plain `claude` → supervisor never wraps the PTY (no-op).
