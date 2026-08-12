# Plan 00208: comment changelog and size handlers

**Status**: In Progress
**Created**: 2026-08-12
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Two new `PreToolUse` handlers on `Write`/`Edit`, from a field proposal filed in
this folder as `PROPOSAL.md`. Read that first — it is the specification, it is
detailed, and it carries the real-world evidence.

The rule being enforced separates three artifacts that an LLM conflates
constantly, because a comment is the cheapest place to put text:

| Artifact                   | Job                                            |
| -------------------------- | ---------------------------------------------- |
| git                        | tracking changes — what changed, when, by whom |
| changelog files / journals | documenting changes for humans over time       |
| code comments              | **CURRENT STATE, RELEVANT INFO ONLY**          |

The moment a comment carries "in 3.26.1 we did X, prior to that Y", it has
become a changelog living in the wrong file — unsearchable, never pruned, and
duplicating git.

## Goals

- Block writing **historical narrative** into a code comment
  (`comment_changelog`) — the valuable half; ship it first
- Block over-long comments (`comment_size`) with `plan-doc-size`-style tiering,
  so an over-commented legacy file stays editable and can be refactored down
- Do both without flagging history-as-**rationale**, which is legitimate and
  load-bearing

## Non-Goals

- No reformatting or auto-fixing of comments. These handlers refuse a write and
  name the destination; they never rewrite the author's text.
- No opinion on comment *style*, density or usefulness. Only history-in-the-
  wrong-place and runaway length.
- Markdown prose is not a comment — `.md` is skipped entirely.

## Context & Background

Reported from `LongTermSupport/fedora-desktop`, where an agent-authored comment
reached **5,645 characters on a single line**, six releases deep, and silently
broke a user-facing banner: the file's rebuild notice reads that trailing
comment and prints it, so "Rebuilding to include:" dumped the entire accumulated
history to the terminal on every base-image update.

No human wrote any of it. Each entry was appended by an agent following the
shape of the previous entry.

**Why a handler and not a style guide**: the failure mode is *monotonic*. Nobody
deletes from a comment changelog — removing someone else's note feels
destructive — so it only ever grows. A `CLAUDE.md` rule does not fire at the
moment of the append. A handler does.

### The distinction that makes or breaks this

History as **rationale** is legitimate: a comment may recount the past when the
past is *the reason the current code looks the way it does* and re-litigating it
would reintroduce a fixed bug. The proposal's separating test:

> Does this comment **grow** when the code changes, or get **rewritten**?
> A changelog appends; a rationale is replaced.

Practical proxies: an entry keyed by a **release number** is a changelog; an
entry keyed by a **failure mode** is a rationale. Narrative about code no longer
in the file is a changelog.

**This repository is the hardest available test case and must be used as one.**
`src/` is full of legitimate rationale comments citing plan numbers (e.g. "Plan
00181: this append-only JSONL had no bound"). If the matcher blocks this
daemon's own source, the design is wrong. That must be *measured*, not assumed.

## Tasks

### Phase 1: `comment_changelog` (TDD) — the valuable half

- [ ] ⬜ **Task 1.1**: Failing tests for the high-precision block signals
  - [ ] ⬜ `Prior <semver>:` / `Previously <semver>:`
  - [ ] ⬜ two or more distinct semver tokens in one comment
  - [ ] ⬜ a version transition arrow (`2.20 -> 2.22`, `v1.2 → v1.3`)
  - [ ] ⬜ a dated entry inside a comment
  - [ ] ⬜ a past-tense changelog verb naming a version (`Removed in v2.1.224`)
- [ ] ⬜ **Task 1.2**: Failing tests for what must stay ALLOWED — pin the
  proposal's `# History (Plan 00047 — do NOT re-add DISABLE_MOUSE…)` example
  and a representative sample of this repo's own rationale comments
- [ ] ⬜ **Task 1.3**: Implement via Strategy Pattern over comment syntax
  (`#`, `//`, `/* */`, `<!-- -->`, `--`, `;`) — no if/elif on language
  - [x] ✅ Shared `strategies/comments/` groundwork: `CommentSyntax` data
    (`syntax.py`) + `CommentStrategy` Protocol (`protocol.py`) — see JOURNAL
  - [x] ✅ `extractor.py`: `CommentSpan` + `extract_comment_spans()` (100%
    coverage, 36 tests) — line-comment runs, trailing inline comments,
    block/doc delimited spans, Python docstring line-start guard
  - [x] ✅ `common.py` (shared skip-directories) + 12 per-language strategy
    files (11 canonical + Shell): Python, Shell, Ruby, JS/TS, Go, PHP,
    Java, Kotlin, C#, Rust, Swift, Dart — 110 tests passing, mypy --strict
    clean. `strategies/comments/` groundwork is COMPLETE; next is the
    registry + the two handlers themselves
- [ ] ⬜ **Task 1.4**: Lower-precision signals (`Fixed:`/`Added:` runs, "used
  to", "no longer") ADVISE rather than block
- [ ] ⬜ **Task 1.5**: `get_claude_md()` naming the destination for the text —
  git / changelog file / plan `JOURNAL/` — since "where does this go instead" is
  exactly what the agent does not know

### Phase 2: `comment_size`

- [ ] ⬜ **Task 2.1**: Failing tests for line-length and block-length limits
- [ ] ⬜ **Task 2.2**: Tiering — only an edit that GROWS an already-over-limit
  comment blocks; shrinking silent; same-size advises
- [ ] ⬜ **Task 2.3**: Docstrings/JSDoc are API documentation — exempt from
  `comment_size`, still subject to `comment_changelog`
- [ ] ⬜ **Task 2.4**: `MUST_EXCEED_COMMENT_SIZE_BECAUSE` escape hatch

### Phase 3: Integrate & verify

- [ ] ⬜ **Task 3.1**: Register in config with a code-quality band priority;
  honour `daemon.exclude_paths` + per-handler `exclude_paths`
- [ ] ⬜ **Task 3.2**: `get_acceptance_tests()`; `HANDLER_REFERENCE.md` entry;
  changelog entry; `config-changes` manifest marking them `recommended: true`
- [ ] ⬜ **Task 3.3**: Full QA (`./scripts/qa/llm_qa.py all`), daemon restart
  RUNNING, and a LIVE socket probe of both directions — the banner case blocked,
  a rationale comment allowed
- [ ] ⬜ **Task 3.4**: Run the matcher over this entire repository and report the
  hit list. Any hit on a legitimate rationale comment is a design defect, not a
  tuning problem

## Dependencies

- Related: the `plan-doc-size` tiering model, reused deliberately — same problem
  shape (a document that only ever grows), same remedy (relocate, never delete),
  same "only a growing edit blocks" rule

## Technical Decisions

### Decision 1: Ship `comment_changelog` before `comment_size`

**Context**: Size is the visible symptom; history is the defect.

**Decision**: `comment_changelog` first. A 400-char comment explaining one
genuinely intricate mechanism is fine; a 200-char comment carrying two release
notes is not. If only one handler ever ships, it should target the actual defect
rather than its proxy.

**Date**: 2026-08-12

## Success Criteria

- [ ] The 5,645-char six-release banner comment is DENIED
- [ ] The `DISABLE_MOUSE` rationale comment is ALLOWED
- [ ] Running the matcher across this repo's `src/` produces ZERO hits on
  legitimate rationale comments — measured, not assumed
- [ ] Tiering verified: an over-limit comment can still be edited downward
- [ ] The deny message names where the text should go instead
- [ ] Full QA passes; daemon restarts RUNNING; live socket probe confirms both
  directions

## Risks & Mitigations

| Risk                                                          | Impact | Probability | Mitigation                                                                                     |
| ------------------------------------------------------------- | ------ | ----------- | ---------------------------------------------------------------------------------------------- |
| Blocks legitimate rationale comments, including this repo's   | High   | Medium      | Task 3.4 measures the whole repo; allowed cases are pinned as tests BEFORE implementation      |
| Freezes a legacy over-commented file so it cannot be improved | Medium | Low         | Tiering: only a growing edit blocks, so refactoring downward is always possible                |
| Semver detection fires on genuine version constants in code   | Medium | Medium      | Only match inside COMMENT spans, never code; require a changelog-shaped phrase, not a bare tag |

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00208-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Not started. Proposal filed as `PROPOSAL.md` in this folder. A first
  implementation attempt was dispatched to a sub-agent and produced nothing
  before terminating; re-dispatch from this plan.
