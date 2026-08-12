# Plan 00212: generic command hint handler

**Status**: In Progress
**Created**: 2026-08-12
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

Build ONE generic, config-driven PostToolUse advisory handler — `command_hints`
— that injects a rate-limited HINT when a configured command is detected in a
Bash tool call. The whole point is a single handler driven by a config object
mapping command patterns to hint text, not a handler per command. The first
and only default-shipped hint: running `agent-browser` reminds the agent to
close the browser session when finished.

The handler must never block (advisory only, `terminal=False`), must not
hand-roll command detection (reuse `utils/shell_segmentation.py` and
`utils/command_evasion.py`), and must rate-limit each hint via a TTL tracked
per `(session_id, hint_id)` so it does not fire on every matching command.
Project config can extend (`mode: additive`, default) or fully replace
(`mode: replace`) the built-in hint set, mirroring the paradigm already
established by `idle_housekeeping_advisor.py`.

## Goals

- A single `command_hints` handler (PostToolUse, Bash) driven entirely by
  config — not one handler per hinted command.
- Ship exactly one default hint (`agent-browser` -> close-session reminder).
- TTL-based rate limiting per `(session_id, hint_id)`, bounded in-memory state.
- Command matching via the shared segmentation/evasion grammar — fires on
  path-qualified and `env`-prefixed spellings, never on the word appearing as
  an unrelated argument (e.g. `grep agent-browser notes.md`).
- `additive`/`replace` config paradigm identical in shape to
  `idle_housekeeping_advisor`'s `custom_guidance_mode`.
- 95%+ coverage, full type annotations, `get_claude_md()`,
  `get_acceptance_tests()`.

## Non-Goals

- No handler-per-command design.
- No persistence layer for TTL state (in-memory only; a restart resets it —
  acceptable for a hint).
- No support for arbitrary hint-pattern regexes — `pattern` is a literal
  command name (see Technical Decisions).

## Tasks

### Phase 1: TDD Implementation

- [x] ✅ Write failing unit tests: init, matching (segmentation + evasion,
  both directions), TTL gating, config merge (additive/replace/override),
  malformed-entry handling, `get_claude_md()`, `get_acceptance_tests()`
- [x] ✅ Implement `CommandHintsHandler` to pass tests
- [x] ✅ Add `HandlerID.COMMAND_HINTS` / `Priority.COMMAND_HINTS` constants
- [x] ✅ Verify 95%+ coverage on the new module (100% reached)

### Phase 2: Integration & Registration

- [x] ✅ Register in `.claude/hooks-daemon.yaml` (dogfood config)
- [x] ✅ Add to `daemon/init_config.py` `generate_full()` template (also
  fixed a pre-existing gap: `comment_changelog`/`comment_size` were missing)
- [x] ✅ `docs/guides/HANDLER_REFERENCE.md` entry
- [x] ✅ `CHANGELOG.md` `[Unreleased]` entry
- [x] ✅ `config-changes` manifest (`recommended: true`,
  `CLAUDE/UPGRADES/UNRELEASED/config-changes/v3.53.0.yaml`)

### Phase 3: Verification

- [x] ✅ `./scripts/qa/llm_qa.py all` — 18/20 (the 2 non-passing checks are
  pre-existing/environmental, not caused by `command_hints`; see Success
  Criteria for the itemised breakdown)
- [ ] 🚫 Daemon restart + live socket probe — **cannot be done from a
  worktree** (documented as outstanding for the post-merge tree)

## Technical Decisions

### Decision 1: `pattern` is a literal command name, not an arbitrary regex

**Context**: the config field is named `pattern`, which could imply full
regex support.
**Decision**: treat it as a literal command name. It is `re.escape()`d and
wrapped with the shared `OPTIONAL_PATH` / `env` prefix / segment-anchor
machinery. This satisfies every bypass class named in the brief (bare name,
path-qualified, `env`-prefixed, line-continuation-split) without asking
project authors to write correct regexes for a config file. Full regex
support is not requested by the brief and can be added later without a
breaking change (YAGNI).

### Decision 2: anchor lookahead is `(?=\s|$)`, not `\b`

**Context**: `agent-browser` contains an internal hyphen, which is a
non-word character to Python `re`. A trailing `\b` after the literal would
therefore also match `agent-browser-extra-tool` (boundary between `r` and
`-`), a false positive the shared `command_evasion` fragments do not need to
guard against for their un-hyphenated targets (`sed`, `pip`, `bash`).
**Decision**: use a lookahead requiring whitespace or end-of-segment instead
of `\b`. Regression-tested explicitly.

## Success Criteria

- [x] `command_hints` fires the `agent-browser` hint on bare, path-qualified,
  `env`-prefixed, and line-continuation-split invocations.
- [x] `command_hints` does NOT fire when the word appears as an argument to
  an unrelated command or inside a commit message.
- [x] TTL + optional `min_calls_between` gate re-firing; state is bounded.
- [x] `additive` mode overrides a built-in hint by matching `id`; `replace`
  mode discards the built-in set entirely.
- [x] `./scripts/qa/llm_qa.py all` reports 18/20. The 2 non-passing checks:
  - `tests` (3 pre-existing failures, all pre-dating this plan and unrelated
    to `command_hints`: `test_every_deny_capable_handler_has_a_near_miss_allow_case`
    and `TestEveryHandlerIsClassified::test_no_handler_is_unclassified` both
    concern `CommentChangelogHandler`/`CommentSizeHandler` from Plan 00208;
    `test_no_index_row_is_a_paragraph` concerns a pre-existing 695-char Plan
    00206 row in `CLAUDE/Plan/README.md` predating this branch)
  - `smoke_test` (needs a live daemon socket — see the next line)
- [ ] Daemon restart verification — OUTSTANDING (cannot run in a worktree).

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00212-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Plan created at `20014fbd`
- Handler implemented (65 tests, 100% coverage on the new module) at `3158a28c`
- Docs/changelog/config-changes manifest at `64888e61`
- Black auto-format checkpoint at `34bd8615`
- Full-suite QA gaps found and fixed (example config, README row length) at
  `3c8a0026`
- Still open: daemon restart + live socket probe against the merged tree
  (cannot be performed from this isolated worktree)
