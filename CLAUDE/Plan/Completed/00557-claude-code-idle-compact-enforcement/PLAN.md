# Plan 00557: Claude Code idle compact enforcement

**Status**: Complete
**Created**: 2026-11-02
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The owner reports that Claude Code now supports **idle compact**: it compacts a
conversation while the session is idle. The owner wants it enabled wherever the
daemon runs. Enforcement goes through the daemon's usual Claude Code config
checks, at session start and in the `optimise` review.

Before anything is built, this plan establishes how the feature works, how it
is configured, and whether it is fully rolled out or still gated. A check that
demands a setting nobody can turn on would be noise. A check that misses the
real switch would be false comfort.

Related plans, not merged:

- Plan 00428 audits `CLAUDE_CODE_AUTO_COMPACT_WINDOW` (issue #46). That is a
  different setting: it controls when compaction triggers, not idle
  behaviour.
- Plan 00452 Tasks 4.5 and 4.6 ask whether an idle session should compact
  before its prompt cache goes cold (issue #109). This feature may answer that
  question.
- Plan 00486 Task 1.4 asked whether Claude Code had idle compaction at the
  time.

## Goals

- Record how idle compact triggers, what it compacts, and how it interacts with
  the other compaction settings and the PreCompact/PostCompact hooks. Each
  point is backed by evidence from the changelog, the docs or the installed
  binary.
- Record every way to configure it (settings key, environment variable,
  `/config`), with defaults and scopes.
- Record whether it is fully rolled out, and from which version.
- Add a config check that reports when idle compact is not enabled. It goes
  wherever the daemon already checks Claude Code config, with an exact fix.

## Non-Goals

- Changing the auto-compact window or percentage settings (Plan 00428).
- Prompt-cache observability (Plan 00452).

## Tasks

### Phase 1: Understand the feature

- [x] ✅ **Task 1.1**: Research report:
  [261102-idle-compact-research.md](subagent-reports/261102-idle-compact-research.md).
  - The `idleCompaction` setting defaults to `true`. It compacts at about 0.9
    of the one-hour cache TTL (about 54 minutes idle) in interactive sessions,
    when context is at least `CLAUDE_CODE_IDLE_COMPACT_MIN_TOKENS` (default
    200000).
  - These switch it off: `autoCompactEnabled: false`, `DISABLE_AUTO_COMPACT`
    and `DISABLE_COMPACT`. The evidence for `DISABLE_COMPACT` is the binary
    only. `FORCE_PROMPT_CACHING_5M` also switches it off, indirectly, because
    idle compaction needs the one-hour cache.
  - **Rollout:** it works from 2.1.290 and was announced in 2.1.299. 2.1.314
    took it to VS Code, Desktop and subscribers with telemetry off. It also
    reached Bedrock/Vertex/Foundry and LLM gateways, but only where the
    one-hour cache is on. The live env-var docs still say it depends on
    feature-flag fetching, and the flag name is unverified. It is broadly
    rolled out but not proven universal.
  - PreCompact fires with `trigger: "auto"`, so an idle compaction cannot be
    told apart from a normal auto-compact.
- [x] ✅ **Task 1.2**: Enforcement shape. The owner asked for the setting to be
  enforced as enabled, which settles whether it may be auto-written. Writing
  only an absent key matches the default and respects the Plan 00466 N47
  policy of never overriding an owner's explicit setting:
  - a new `_check_idle_compaction` in `optimal_config_checker` reports
    whether idle compaction is in effect and names any disabler;
  - `_enforce_settings_sync` writes `idleCompaction: true` only when the key
    is absent, following the existing `alwaysThinkingEnabled` pattern;
  - an explicit `false` is the user's choice, so it is reported and never
    overwritten.

### Phase 2: Enforce

- [x] ✅ **Task 2.1**: Wrote a failing test, then added the check
  `_check_idle_compaction` to `optimal_config_checker` as the seventh check,
  "Idle Compaction". It is merged in 5577aee1d. An unreadable project settings
  file is reported as a cause that cannot be ruled out, as
  `_check_effort_source` does. Report:
  [261102-task-2-build.md](subagent-reports/261102-task-2-build.md).
- [x] ✅ **Task 2.2**: The checklist of `check` (`skills/hooks-daemon/check.md`)
  now lists the check, in the source copy and the tracked deployed copy
  (`.claude/skills/hooks-daemon/check.md`, synced after the completion
  fact-check). The handler guidance text is unchanged, so no regeneration was
  needed.
- [x] ✅ **Task 2.3**: Release note
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/011-idle-compaction-config-check.md`.

## Success Criteria

- [x] The research report answers "is it fully rolled out?" with evidence.
- [x] A session without idle compact enabled is told so, with the exact fix.
  A test proves this (`TestIdleCompactionCheck`). On this host,
  `hooks-daemon check` reports `[OK] Idle Compaction: In effect`.
- [x] A release note is recorded in `CLAUDE/UPGRADES/UNRELEASED/` (the
  pending-release holding area): `011-idle-compaction-config-check.md`.

## Delivery & Milestones

- Plan filed at the owner's request.
