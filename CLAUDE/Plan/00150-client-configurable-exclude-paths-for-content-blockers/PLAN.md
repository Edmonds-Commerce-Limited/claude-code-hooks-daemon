# Plan 00150: Client-configurable exclude_paths for content-scanning blockers

**Status**: In Progress
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

- [ ] ⬜ **Task 2.1**: `error_hiding_blocker` — add `exclude_paths` option + a
  built-in default skip set; RED tests (fixture path skipped, non-fixture blocked,
  client glob skipped) then GREEN.
- [ ] ⬜ **Task 2.2**: `security_antipattern` — add `exclude_paths` option layered
  on top of the existing `should_skip()` built-ins; RED then GREEN.
- [ ] ⬜ **Task 2.3**: `qa_suppression` — add `exclude_paths` option layered on top
  of `strategy.skip_directories`; RED then GREEN.
- [ ] ⬜ **Task 2.4**: Project-level `exclude_paths` default inheritance — all
  three read a shared project default when their own option is unset.

### Phase 3: Config, manifest, docs

- [ ] ⬜ **Task 3.1**: Register the option in config loading / schema and the
  dogfood `.claude/hooks-daemon.yaml` + `.yaml.example`.
- [ ] ⬜ **Task 3.2**: Add `CLAUDE/UPGRADES/UNRELEASED/config-changes/v3.35.0.yaml`
  (`added`, `recommended: true`).
- [ ] ⬜ **Task 3.3**: Document the option in `docs/guides/HANDLER_REFERENCE.md`
  and each handler's `get_claude_md()`.

### Phase 4: Verify

- [ ] ⬜ **Task 4.1**: Full QA (`./scripts/qa/llm_qa.py all`) 13/13.
- [ ] ⬜ **Task 4.2**: Daemon restart RUNNING; probe a fixture-path Write is
  allowed and a real-source Write is still blocked.
- [ ] ⬜ **Task 4.3**: Hand off to the user for the v3.35.0 release decision
  (this plan does NOT ship a release autonomously).

## Success Criteria

- [ ] A project can add `exclude_paths` globs (per-handler and/or project-level)
  and have all three content blockers honour them.
- [ ] `error_hiding_blocker` no longer scans vendor/node_modules/test-fixtures by
  default.
- [ ] No config ⇒ no behaviour change beyond the error_hiding default skips.
- [ ] QA 13/13, daemon restarts clean, 95%+ coverage maintained.

## Notes & Updates

### 2026-07-10

- Plan scaffolded (mkplan → 00150) after the v3.34.2 release.
- Failsafe recovery cron: `733c0f4e` (hourly at :23, non-durable, session-only).
- Motivation from a live user question: QA libraries need to exempt fixtures of
  deliberately-broken code and code that legitimately suppresses errors.
