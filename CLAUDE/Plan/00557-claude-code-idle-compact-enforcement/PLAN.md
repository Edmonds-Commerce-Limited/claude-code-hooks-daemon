# Plan 00557: Claude Code idle compact enforcement

**Status**: In Progress
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

- [ ] ⬜ **Task 1.1**: Research report covering mechanism, configuration,
  rollout status and hook interaction. The report goes in
  `subagent-reports/261102-idle-compact-research.md`.
- [ ] ⬜ **Task 1.2**: Decide the enforcement shape from the findings. It is
  either a hard requirement, or advisory only while the feature is still
  rolling out. Present that choice to the owner if it is not clear-cut.

### Phase 2: Enforce

- [ ] ⬜ **Task 2.1**: Write a failing test, then add the check to the
  existing Claude Code config checker or checkers. The report from Task 1.1
  names the location.
- [ ] ⬜ **Task 2.2**: Add the setting to the `optimise` checklist and to
  the docs.
- [ ] ⬜ **Task 2.3**: Add a release note in
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/`.

## Success Criteria

- [ ] The research report answers "is it fully rolled out?" with evidence.
- [ ] A session without idle compact enabled is told so, with the exact fix.
  A test proves this.
- [ ] A release note is recorded in `CLAUDE/UPGRADES/UNRELEASED/` (the
  pending-release holding area).

## Delivery & Milestones

- Plan filed at the owner's request.
