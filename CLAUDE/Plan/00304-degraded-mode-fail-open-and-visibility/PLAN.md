# Plan 00304: degraded mode fail open and visibility

**Status**: Complete
**Created**: 2026-09-01
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

A real-repo canary upgrade of `LongTermSupport/php-qa-ci` onto v3.58.0
surfaced a v3.58.0 RELEASE BLOCKER: a config value written by an OLDER
daemon's own default template (`markdown_organization.options. monorepo_subproject_patterns: null`) hard-fails Plan 00300's removed-option
validator, putting the daemon into DEGRADED MODE. Degraded mode's existing
design is blanket fail-open — every PreToolUse request, including
`git reset --hard`, gets an ALLOW with only an advisory `additionalContext`
warning — so a routine config drift silently disabled ALL enforcement on a
real client, with no denial anywhere on the wire.

Compounding the danger, degraded mode was also nearly invisible: `status`
reported RUNNING, `check` was byte-identical to a healthy run, and
`config-validate` reported `{"valid": true}` for the very file the daemon
degraded on at startup (a divergence between two different validator code
paths). This plan closes both gaps — tolerating the null/empty config shape
that should never have degraded the daemon in the first place, and making
any REMAINING degraded state both safer (a config-independent
destructive-command safety net still runs) and visible on every surface that
previously claimed health.

## Goals

- A null or empty `monorepo_subproject_patterns` never degrades the daemon;
  only a non-empty (real) pattern list keeps the Plan 00300 hard error.
- A comments-only handler `options:` block (parses to YAML `null`) loads
  cleanly instead of hard-failing startup with a misleading error path.
- Degraded mode is never silently all-enforcement-off: the destructive-git
  guard family runs even while degraded, independent of the config that
  failed to validate.
- `status`, `check`, and `config-validate` all surface the SAME degraded
  verdict the running daemon itself reaches — no surface may report healthy
  for a daemon that is actually degraded.
- `LLM-UPDATE.md`'s `config-validate` example uses the real (positional)
  CLI invocation.
- The v3.58.0 upgrade manifests describe the corrected null-tolerant
  migration story.

## Non-Goals

- Redesigning degraded mode wholesale (e.g. a general per-handler
  config-independent allowlist beyond the destructive-command guard family).
- Making config validation fail-closed (refuse to start) — the owner-ruling
  choice recorded below keeps the daemon running so a session is never
  bricked by a config typo.
- Auditing every handler for a "config-independent" flag; only the
  destructive-git guard is wired into the degraded-mode safety net here.

## Tasks

### Phase 1: Reproduce and fix the false-positive validation

- [x] ✅ **Task 1.1**: TDD reproduction — `monorepo_subproject_patterns: null`
  / `[]` must not error (`tests/unit/config/test_validator.py`); fix in
  `config/validator.py::_validate_removed_monorepo_patterns_option`.
- [x] ✅ **Task 1.2**: TDD reproduction — a comments-only handler `options:`
  block (`options: None`) must not fail Pydantic validation
  (`tests/config/test_models.py`); fix via a `field_validator` on
  `HandlerConfig.options` normalising `None` → `{}`.

### Phase 2: Close the fail-open enforcement gap

- [x] ✅ **Task 2.1**: TDD reproduction — degraded mode must still deny
  `git reset --hard` (`tests/unit/daemon/test_controller_degraded_mode.py`);
  fix via `DaemonController._degraded_mode_safety_net` running
  `DestructiveGitHandler` config-independently before the fail-open
  configuration-error advisory.

### Phase 3: Visibility on every surface

- [x] ✅ **Task 3.1**: TDD reproduction — `status` and `check` must surface
  a degraded daemon's own `health` verdict
  (`tests/unit/daemon/test_cli_degraded_mode_visibility.py`); fix via a
  shared `_query_daemon_config_degraded` helper querying the live
  daemon, wired into both `cmd_status` and `cmd_check`.
- [x] ✅ **Task 3.2**: TDD reproduction — `config-validate` must agree with
  the daemon's own startup validation path
  (`tests/unit/install/test_config_validator.py`); fix via
  `config.validator.ConfigValidator.validate_business_rules()`, a shared
  business-rule pass reused by both the startup path and
  `install.config_validator.ConfigValidator` (the CLI).

### Phase 4: Docs and upgrade manifests

- [x] ✅ **Task 4.1**: Fix `LLM-UPDATE.md`'s `config-validate --config PATH`
  example to the real positional invocation.
- [x] ✅ **Task 4.2**: Update `CLAUDE/UPGRADES/UNRELEASED/config-changes/v3.58.0.yaml`
  and `post-upgrade-tasks/03-migrate-monorepo-subproject-patterns.md` for
  the null-tolerant migration story.

## Design Decision: fail-open safety net, not fail-closed (Task 2.1)

**Decision**: keep degraded mode's existing "daemon keeps running" design
(do not make config-validation failure refuse to start), but no longer let
that mean *all* enforcement is off. A small, explicitly config-independent
safety net (currently: the destructive-git guard family) runs directly
against every `PreToolUse` event while degraded, ahead of the fail-open
configuration-error advisory. Everything else keeps today's fail-open
behaviour — an advisory `additionalContext` warning, no denial.

**Rationale**:

- Fail-closed (refuse to start on any config error) was rejected: a daemon
  that cannot start on a client's real repo bricks the session harder than a
  degraded one — no hooks at all is worse than "destructive commands are
  still blocked, everything else is advisory". This is exactly the failure
  mode the fail-open design was chosen to avoid, and Task 1.1/1.2 remove the
  false-positive triggers that made this instance of degraded mode
  unnecessary in the first place.
- A general "run every config-independent handler while degraded" design was
  rejected as out of scope (see Non-Goals): most handlers legitimately read
  their own `options:`, so "config-independent" is not a property the
  existing architecture tracks per-handler. `DestructiveGitHandler` hard-
  codes its own patterns and takes no config, so it is safe to run directly
  without threading a wider capability through the handler registry.
- The safety net is scoped to `PreToolUse` only — it is the only tier that
  can carry a `deny` on the wire (Plan 00271's result-type tiering), so
  nothing is gained by running it for other events.

## Success Criteria

- [x] `tests/unit/config/test_validator.py::TestRemovedMonorepoSubprojectPatternsOption`
  passes, including the two new null/empty tests.
- [x] `tests/config/test_models.py::TestHandlerConfig::test_null_options_normalised_to_empty_dict`
  and the `TestConfig` comments-only-options regression test pass.
- [x] `tests/unit/daemon/test_controller_degraded_mode.py` passes, including
  `test_degraded_mode_still_blocks_destructive_git`.
- [x] `tests/unit/daemon/test_cli_degraded_mode_visibility.py` passes.
- [x] `tests/unit/install/test_config_validator.py` passes, including
  `test_agrees_with_daemon_startup_on_business_rule_errors`.
- [x] Full `tests/unit` + touched acceptance/config suites green; `mypy --strict`, `black -l 100`, `ruff` clean (3 pre-existing semgrep setup errors are environmental, not from this change).

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00304-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Implementation commit: see JOURNAL for the working session; this repo's
  existing failsafe recovery cron (`2494b387`) was reused for this session,
  not re-created.
