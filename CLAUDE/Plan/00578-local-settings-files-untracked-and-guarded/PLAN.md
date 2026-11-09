# Plan 00578: local settings files untracked and guarded

**Status**: Blocked on the owner (the questions below)
**Created**: 2026-11-09
**Owner**: dev
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #189

## Overview

`.claude/settings.local.json` is Claude Code's per-user, per-machine settings file. Claude Code writes each "don't ask
again" approval into its `permissions.allow` word for word, so a command approved with an inline password or token is
stored in it. `CLAUDE.local.md` is the per-user memory file. Claude Code keeps the settings file out of git only through
the user's GLOBAL git excludes, and only on a machine where it wrote the file itself. That rule is absent in a fresh
container, a CI runner or under another `HOME`, and it never covers `CLAUDE.local.md`.

Verified on `main` at triage:

- This repository TRACKS `.claude/settings.local.json` (`git ls-files`), and has done since January 2026.
- Neither `.gitignore` nor `.claude/.gitignore` has a rule for either file.
- `scripts/install/gitignore.sh`, which install and upgrade both run, adds no rule for either file in client projects.
- No handler refuses staging or committing either path.

The tracked file is a DELIBERATE design: Plan 00468 (Complete) moved the dogfood-only plugin keys into the tracked
`.claude/settings.local.json`, so that the shipped `.claude/settings.json` template carries none of them.
`tests/unit/install/test_shipped_settings_carry_no_dogfood_keys.py` and
`tests/integration/test_worktree_claudemd_excludes.py` read it, and Plan 00467 enables a plugin through it. Reversing
that, and adding a new safety control, are owner decisions, so issue #189 is parked on the questions below.

## Owner questions

- **Q1. This repository's tracked file.** Untrack `.claude/settings.local.json` (`git rm --cached`) and ignore both
  files? If yes, where do the dogfood-only keys from Plan 00468 live instead? The issue suggests a committed example
  file that the self-install setup copies into place. The two tests above, and Plan 00467's plugin enablement, move
  with it.
- **Q2. Client projects.** Should install and upgrade add `**/.claude/settings.local.json` and `**/CLAUDE.local.md` to
  the project's root `.gitignore`, as they already add the daemon's own entries? This edits a file the client owns,
  on every upgrade.
- **Q3. A new guard.** Should a handler refuse staging or committing either path in any form (`git add <path>`,
  `git add -A`, `git add .`, `git commit -a`, `git add -f`), whatever the file holds? Q3a: on by default for clients,
  or opt-in? Q3b: deny, or advise?
- **Q4. Optional advisory.** Should an advisory point project-relevant settings at the tracked `.claude/settings.json`?

## Goals

- To be set from the owner's answers to Q1-Q4.

## Non-Goals

- No change before the owner answers. The issue's suggested design is a hypothesis, not a spec.

## Tasks

### Phase 0: Owner decision

- [ ] ⬜ **Task 0.1**: owner answers Q1-Q4; this plan is then re-planned into implementation phases

## Success Criteria

- [ ] The owner has answered Q1-Q4, and the plan carries implementation phases that follow those answers

## Delivery & Milestones

- (pending the owner)
