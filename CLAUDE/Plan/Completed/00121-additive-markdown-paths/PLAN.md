# Plan 00121: Additive `extra_allowed_markdown_paths` for markdown_organization

**Status**: Complete
**Created**: 2026-06-11
**Owner**: Claude (Opus)
**Priority**: Medium
**Recommended Executor**: Opus
**Execution Strategy**: Single-Threaded (TDD)

## Overview

The `markdown_organization` handler's `allowed_markdown_paths` option **replaces**
the built-in allowed-location logic. Any client project that wants to allow ONE
extra markdown location must redeclare the entire default set, then maintain that
copy forever — it drifts out of sync with upstream defaults on every release.

This plan introduces `extra_allowed_markdown_paths`: an **additive** list of regex
patterns layered on top of whatever base applies (built-in defaults, or the legacy
override). This mirrors the existing `extra_whitelist` pattern in `pipe_blocker`.
It also closes the `.claude/skills/` gap (non-`SKILL.md` markdown inside a skill
directory is currently blocked) and dogfoods the new option by migrating this
repo's own config from the 17-pattern override to a 1-line additive entry.

## Goals

- Add `extra_allowed_markdown_paths` — additive over built-ins AND the legacy override.
- Keep `allowed_markdown_paths` working (backward-compatible) but document it as legacy/discouraged.
- Allow all `.md` inside `.claude/skills/` (not just `SKILL.md`).
- Dogfood: migrate `.claude/hooks-daemon.yaml` to the additive style.
- Update `get_claude_md()` and `docs/guides/HANDLER_REFERENCE.md`.
- Stage upgrade guidance (post-upgrade-task + truth-change) so upgrading projects
  migrate override → additive.

## Non-Goals

- Removing or deprecating `allowed_markdown_paths` (kept for backward compat).
- Adding `.github/` as a new silent global default (kept as a project-level extra).
- Editing the external gist (outside the repo — flagged to the user as a follow-up).

## Context & Background

Flow in `matches()` (markdown_organization.py): standard-root files →
`is_adhoc_instruction_file()` → `is_page_colocated_file()` → `_is_invalid_location()`.
`_is_invalid_location()` calls `_check_custom_paths()` when `allowed_markdown_paths`
is set, else `_check_builtin_paths()`. Adhoc check already allows `.claude/rules/`,
`.claude/commands/`, `.claude/agents/`, and `SKILL.md` everywhere.

`pipe_blocker` precedent: `extra_whitelist` / `extra_blacklist` options merge
additively with the universal lists (`src/.../handlers/pre_tool_use/pipe_blocker.py`).

## Tasks

### Phase 1: Core feature — `extra_allowed_markdown_paths` (TDD)

- [x] ✅ **1.1** RED: tests for additive rescue over built-ins (blocked path matching extra → allowed)
- [x] ✅ **1.2** RED: tests for additive rescue over legacy override
- [x] ✅ **1.3** RED: tests for unset (unchanged behaviour) and non-matching extra (still blocked)
- [x] ✅ **1.4** GREEN: add `_extra_allowed_markdown_paths`, `_matches_extra_allowed()`, rescue in `_is_invalid_location()`
- [x] ✅ **1.5** REFACTOR + docstrings

### Phase 2: Allow all `.md` inside `.claude/skills/` (TDD)

- [x] ✅ **2.1** RED: `.claude/skills/foo/reference.md` allowed; `SKILL.md` still allowed
- [x] ✅ **2.2** GREEN: generalize `is_adhoc_instruction_file()` skills check
- [x] ✅ **2.3** Negative test: markdown outside `.claude/skills/` unaffected

### Phase 3: Guidance docs

- [x] ✅ **3.1** Update `get_claude_md()` — additive (preferred) vs override (legacy)
- [x] ✅ **3.2** Update `docs/guides/HANDLER_REFERENCE.md` markdown_organization section

### Phase 4: Dogfood config migration

- [x] ✅ **4.1** Verify all repo `*.md` locations are covered by built-ins/adhoc/standard-root
- [x] ✅ **4.2** Replace `allowed_markdown_paths` override with `extra_allowed_markdown_paths: ["^\\.github/.*\\.md$"]`
- [x] ✅ **4.3** Restart daemon, verify RUNNING, probe handler against sample paths

### Phase 5: Upgrade guidance

- [x] ✅ **5.1** Stage post-upgrade-task: check for `allowed_markdown_paths` override, recommend additive migration
- [x] ✅ **5.2** Stage truth-change entry (override-only → additive available)

### Phase 6: QA + close-out

- [x] ✅ **6.1** `./scripts/qa/llm_qa.py all` green (95%+ coverage)
- [x] ✅ **6.2** Daemon restart RUNNING
- [x] ✅ **6.3** Flag external gist update to user
- [x] ✅ **6.4** Complete plan, move to Completed/

## Technical Decisions

### Decision 1: Additive over BOTH base modes

`extra_allowed_markdown_paths` rescues a path the base check blocked, whether the
base is built-ins or the legacy override. This makes it useful regardless of which
mode a project is in, and keeps semantics simple: "extra = always-allow on top".

### Decision 2: `.github/` stays a project extra, not a global default

`.github/*.md` is common but making it a silent default changes behaviour for every
client. Keeping it in this repo's `extra_allowed_markdown_paths` both dogfoods the
feature and demonstrates the migration without altering global defaults.

## Success Criteria

- [x] `extra_allowed_markdown_paths` additive over built-ins and override
- [x] `.claude/skills/**/*.md` allowed
- [x] This repo's config uses the additive style; daemon RUNNING
- [x] HANDLER_REFERENCE + get_claude_md document the option
- [x] post-upgrade-task + truth-change staged
- [x] All QA passes (95%+ coverage)

## Notes & Updates

### 2026-06-11

- Plan created. Counter at 120 → this is plan 00121.
- Delivered across Phase 1-2 (feature + skills + tests), Phase 3-4 (docs +
  dogfood config migration + init_config), Phase 5 (post-upgrade-task +
  truth-change), plus a black-format follow-up.
- Final QA: 13/13 PASSED (8508 tests, 95.1% coverage). Daemon restart RUNNING.
  Live probe confirmed built-ins + `.github`/`BUG_REPORTING.md` extras +
  `.claude/skills/**/*.md` allow; `src/`/`lib/` markdown still deny.
- Truth-change staged as anticipated v3.19.0 (MINOR bump); release agent should
  rename if the actual version differs.
- Follow-up (out of repo): the external project-docs gist still describes the
  override-only style — flagged to the user; cannot be edited from here.
