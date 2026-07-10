# Plan 00150: Client-configurable exclude_paths for content-scanning blockers

**Status**: Complete
**Created**: 2026-07-10
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

The three content-scanning PreToolUse blocking handlers — `security_antipattern`,
`qa_suppression`, and `error_hiding_blocker` — decide whether to scan a
Write/Edit by inconsistent, hardcoded, non-client-configurable rules.
`security_antipattern` skips a hardcoded `SKIP_PATTERNS` tuple (`/vendor/`,
`/tests/fixtures/`, …); `qa_suppression` skips per-language
`strategy.skip_directories`; `error_hiding_blocker` skips **nothing**. None of
them accept a project-supplied path list.

This is hostile to exactly the projects that most need an escape hatch: a
QA/linting library whose job is to contain deliberately-"bad" code samples
(fixtures with `# noqa`, `except: pass`, SQL built by concatenation), or code
that legitimately must suppress an error for a documented reason. Today the only
levers are disabling a whole handler project-wide or renaming fixtures into the
two paths `security_antipattern` happens to hardcode (which does nothing for the
other two handlers).

This plan adds a uniform, client-configurable `exclude_paths` glob option to all
three handlers, backed by one shared utility, plus an optional project-level
default that all three inherit. Absent config preserves today's behaviour (with
`error_hiding_blocker` additionally gaining the same sane built-in default skips
as its siblings, for consistency).

## Goals

- One shared glob-based path-exclusion utility (gitignore-style `**` support),
  stdlib-only unless `pathspec` is already a dependency.
- An `exclude_paths: [glob, …]` option on `security_antipattern`,
  `qa_suppression`, and `error_hiding_blocker`.
- An optional project-level `exclude_paths` default that all three inherit
  (single source of truth for "exempt these paths everywhere").
- `error_hiding_blocker` gains a built-in default skip set (vendor, node_modules,
  test fixtures) matching the siblings, so it stops being the odd one out.
- Fully backwards compatible: no config ⇒ current behaviour (plus the
  error_hiding default skips).
- A `config-changes/v3.35.0.yaml` manifest entry (`recommended: true`) so the
  upgrade advisory actively surfaces the new option.
- Docs: `docs/guides/HANDLER_REFERENCE.md` per-handler option reference.

## Non-Goals

- Not wiring `lint_on_edit` / `tdd_enforcement` this plan (follow-up if wanted).
- Not rewriting the existing hardcoded substring skips into globs — they remain
  as built-in defaults to guarantee zero behaviour change; client `exclude_paths`
  are the new glob-matched layer on top.
- Not a security downgrade: excludes are opt-in per project; defaults only ever
  ADD the fixture/vendor skips that reduce false positives.

## Tasks

### Phase 1: Shared exclusion utility (TDD)

- [x] ✅ **Task 1.1**: Decide glob engine — `pathspec` is a **dev-only** transitive
  dep (via black), not runtime, so a small stdlib `glob → regex` translator is
  used instead (no runtime dependency added).
- [x] ✅ **Task 1.2**: RED — `tests/unit/utils/test_path_exclusion.py` (23 tests:
  `**`/segment globs, anchored patterns, project-relative vs absolute, empty/None,
  non-match).
- [x] ✅ **Task 1.3**: GREEN — `src/claude_code_hooks_daemon/utils/path_exclusion.py`
  (`is_path_excluded(file_path, patterns, *, project_root=None)`), compiled-pattern
  cache, correct zero-or-more-segment `**`.

### Phase 2: Wire into the three handlers

- [x] ✅ **Task 2.1**: `error_hiding_blocker` — `exclude_paths` option +
  `_DEFAULT_EXCLUDE_GLOBS` built-in skip set; tests (fixture/vendor skipped,
  real source blocked, client + project globs skipped). Live-probe verified.
- [x] ✅ **Task 2.2**: `security_antipattern` — `exclude_paths` layered onto
  `should_skip()` inside the single `_find_all_violations` scan path; tests.
- [x] ✅ **Task 2.3**: `qa_suppression` — `exclude_paths` layered onto
  `strategy.skip_directories` in `matches()`; tests.
- [x] ✅ **Task 2.4**: Project-level default `daemon.exclude_paths` → injected as
  `_project_exclude_paths` (mirrors `daemon.languages` through config model →
  cli → controller → registry → Handler slots); merged as a union with the
  per-handler option via `merge_exclude_patterns`.

### Phase 3: Config, manifest, docs

- [x] ✅ **Task 3.1**: Schema field `daemon.exclude_paths` in `config/models.py`
  (default `[]`) + commented example in `.claude/hooks-daemon.yaml.example`. The
  dogfood `.claude/hooks-daemon.yaml` is intentionally left unset (this repo needs
  no exclusions).
- [x] ✅ **Task 3.2**: `CLAUDE/UPGRADES/UNRELEASED/config-changes/v3.35.0.yaml`
  (`daemon.exclude_paths` recommended + per-handler option); validated via
  `check-config-migrations`.
- [x] ✅ **Task 3.3**: `docs/guides/HANDLER_REFERENCE.md` "Content-Blocker Path
  Exclusion" section (SSOT) + `get_claude_md()` note on all three handlers.

### Phase 4: Verify

- [x] ✅ **Task 4.1**: Full QA `./scripts/qa/llm_qa.py all` — 13/13 (9902 tests,
  95.5% coverage).
- [x] ✅ **Task 4.2**: Daemon restart RUNNING; live socket probe — fixture-path
  Write allowed (`{}`), real-source Write still denied by error_hiding_blocker.
- [x] ✅ **Task 4.3**: User authorised the release; shipped as v3.35.0 (release
  commit `1c00123`), tagged and published to GitHub.

## Success Criteria

- [x] A project can add `exclude_paths` globs (per-handler and/or project-level)
  and have all three content blockers honour them.
- [x] `error_hiding_blocker` no longer scans vendor/node_modules/test-fixtures by
  default.
- [x] No config ⇒ no behaviour change beyond the error_hiding default skips.
- [x] QA 13/13, daemon restarts clean, 95%+ coverage maintained.

## Notes & Updates

### 2026-07-10

- Plan scaffolded (mkplan → 00150) after the v3.34.2 release.
- Failsafe recovery cron: `733c0f4e` (hourly at :23, non-durable, session-only).
- Motivation from a live user question: QA libraries need to exempt fixtures of
  deliberately-broken code and code that legitimately suppresses errors.
- Feature delivered across commits `c66d446` (scaffold), `3b74579` (Phase 1 util),
  `2517288` (Phase 2 handlers/plumbing), `d76ed09` (Phase 3 docs/manifest).
- Released as **v3.35.0** (release commit `1c00123`) after explicit user
  authorisation; QA 13/13 (9902 tests, 95.5% coverage), H-1 acceptance 23 passed.
  Plan closed in the release housekeeping commit.
