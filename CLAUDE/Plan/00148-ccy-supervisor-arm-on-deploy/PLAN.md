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

This fix makes the deploy **deploy + arm** by default. After copying the script
it ensures `.claude/ccy/ccy.env` exports an armed, path-independent
`CCY_CLAUDE_WRAPPER`, idempotently and respecting any pre-existing user setting.

**Scope grew during review (field feedback):** projects were also leaving the
supervisor files git-ignored (the common ccy `.gitignore` is a blanket `*`), so
even an armed supervisor never reached teammates. And an armed-but-broken setup
(script missing / not executable / ignored) can brick `ccy` launches. So the fix
also (a) makes the deploy append whitelist exceptions for our files to an
existing `.claude/ccy/.gitignore` — without owning the rest of the project's
ignore policy — and (b) adds a daemon SessionStart advisory handler
(`ccy_supervisor_integrity`) that detects and warns on the brick-risk states.
The new handler makes this a **MINOR** release (**v3.34.0**), not a patch.

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

- [x] ✅ **Task 1.1**: RED — added failing tests to
  `tests/unit/install/test_ccy_supervisor.py`: arms fresh `ccy.env`; appends to
  an existing `ccy.env` lacking the wrapper; leaves an existing wrapper (armed
  OR commented) untouched; `false` arms nothing; absent + `true` both arm; the
  generated line sources in bash to an absolute `claude-supervise.py --arm --`.
- [x] ✅ **Task 1.2**: GREEN — extended `install/ccy_supervisor.py` with an arm
  step (`armed` field on the result; idempotent `ccy.env` writer).
- [x] ✅ **Task 1.3**: REFACTOR + 100% coverage on the module (20 tests).

### Phase 2: Consistency + docs

- [x] ✅ **Task 2.1**: Updated the tracked dogfood `.claude/ccy/ccy.env` to the
  self-locating wrapper form (resolves identically here; fixes LXC fragility).
- [x] ✅ **Task 2.2**: Updated `CcyConfig` docstring/field text and
  `docs/guides/CONFIGURATION.md` — deploy now arms by default.
- [x] ✅ **Task 2.3**: Added the truth-change manifest (the "deploy does not arm"
  statement became false); renamed to `v3.34.0.yaml` when the bump became MINOR.

### Phase 3: Ensure files are tracked (field feedback)

- [x] ✅ **Task 3.1**: TDD — deploy appends whitelist exceptions for our files
  (`claude-supervise.py`, `ccy.env`, `.gitignore`, `Dockerfile`) to an EXISTING
  `.claude/ccy/.gitignore`; absent `.gitignore` left alone (not our policy to
  own). Real-git-repo test proves `git check-ignore` no longer ignores them.

### Phase 4: Daemon enforcement (field feedback)

- [x] ✅ **Task 4.1**: TDD new SessionStart advisory handler
  `ccy_supervisor_integrity` — when armed, warns if the script is missing, not
  executable, or git-ignored (brick risk). Silent for non-ccy / un-armed. 100%
  covered; registered (HandlerID + Priority 58 + config); daemon RUNNING; no
  false alarm in this dogfood repo.

### Phase 5: Verify + release (MINOR — v3.34.0)

- [ ] 🔄 **Task 5.1**: `./scripts/qa/llm_qa.py all` → 13/13; daemon restart RUNNING.
- [ ] ⬜ **Task 5.2**: `/release` MINOR → v3.34.0.

## Success Criteria

- [x] Deploy result reports `armed=True` for a fresh/unconfigured ccy project.
- [x] Existing user `CCY_CLAUDE_WRAPPER` (set or commented) is never clobbered.
- [x] Generated `ccy.env` sources to an absolute armed wrapper path in bash.
- [x] Deploy un-ignores our files in an existing blanket-`*` `.claude/ccy/.gitignore`.
- [x] `ccy_supervisor_integrity` warns on armed-but-broken; silent when healthy.
- [ ] QA 13/13, daemon RUNNING, v3.34.0 released.

## Notes & Updates

### 2026-07-10

- Plan scaffolded. Recovery cron `26b41693` (hourly :37, non-durable) armed.
- Root cause confirmed: `deploy_ccy_supervisor_if_enabled` copies the script but
  never writes `ccy.env`, so `CCY_CLAUDE_WRAPPER` is unset in clients → launcher
  runs plain `claude` → supervisor never wraps the PTY (no-op).
- Scope grew on field feedback: (1) projects leave the supervisor files
  git-ignored (blanket `*`) so they never reach teammates → deploy now appends
  whitelist exceptions to an existing `.claude/ccy/.gitignore`; (2) an
  armed-but-broken setup can brick `ccy` → new SessionStart handler
  `ccy_supervisor_integrity` warns. New handler ⇒ MINOR bump v3.34.0.
- Delivered so far: arm-on-deploy `78164b1`; docs/self-locating env `8bf12f5`;
  gitignore-tracking + integrity handler `663fe75`. QA green per phase; daemon
  RUNNING; no dogfood false alarm.
