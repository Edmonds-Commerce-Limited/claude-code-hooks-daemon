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

- [x] ✅ **Task 1.1**: Failing tests for the high-precision block signals.
  **REVISED after the whole-repo self-scan (see JOURNAL 12:20)**: only
  `Prior <semver>:`/`Previously <semver>:` and a dated entry measured with
  zero false positives and stayed BLOCKING. Two or more distinct semver
  tokens, a version-transition arrow, and a changelog verb naming a
  version all measured real false positives on this repo's own
  version-processing docstrings and rationale comments — demoted to
  advisory (still surfaced as context, never block)
  - [x] ✅ `Prior <semver>:` / `Previously <semver>:` — BLOCKING
  - [x] ✅ two or more distinct semver tokens in one comment — ADVISORY
  - [x] ✅ a version transition arrow (`2.20 -> 2.22`, `v1.2 → v1.3`) — ADVISORY
  - [x] ✅ a dated entry inside a comment — BLOCKING
  - [x] ✅ a past-tense changelog verb naming a version (`Removed in v2.1.224`) — ADVISORY
- [x] ✅ **Task 1.2**: Failing tests for what must stay ALLOWED — pin the
  proposal's `# History (Plan 00047 — do NOT re-add DISABLE_MOUSE…)` example
  and this repo's own rationale-comment style (plan-number-keyed, not
  release-number-keyed)
- [x] ✅ **Task 1.3**: Implement via Strategy Pattern over comment syntax
  (`#`, `//`, `/* */` — `<!-- -->`/`--`/`;` deliberately out of scope, see
  Non-Goals) — no if/elif on language
  - [x] ✅ Shared `strategies/comments/` groundwork: `CommentSyntax` data
    (`syntax.py`) + `CommentStrategy` Protocol (`protocol.py`) — see JOURNAL
  - [x] ✅ `extractor.py`: `CommentSpan` + `extract_comment_spans()` (100%
    coverage, 36 tests) — line-comment runs, trailing inline comments,
    block/doc delimited spans, Python docstring line-start guard
  - [x] ✅ `common.py` (shared skip-directories) + 12 per-language strategy
    files (11 canonical + Shell): Python, Shell, Ruby, JS/TS, Go, PHP,
    Java, Kotlin, C#, Rust, Swift, Dart
  - [x] ✅ `registry.py` (extension -> strategy lookup, `create_default()`).
    `strategies/comments/` groundwork: 121 tests, 100% coverage,
    mypy --strict clean.
  - [x] ✅ `handlers/pre_tool_use/comment_changelog.py`: `CommentChangelogHandler`
    (41 tests, 99.47% file coverage, mypy --strict clean). Not yet
    registered in `.claude/hooks-daemon.yaml` (Phase 3 task).
- [x] ✅ **Task 1.4**: Lower-precision signals (`Fixed:`/`Added:` runs, "used
  to", "no longer") ADVISE rather than block
- [x] ✅ **Task 1.5**: `get_claude_md()` naming the destination for the text —
  git / changelog file / plan `JOURNAL/` — since "where does this go instead" is
  exactly what the agent does not know

### Phase 2: `comment_size`

- [x] ✅ **Task 2.1**: Failing tests for line-length and block-length limits
- [x] ✅ **Task 2.2**: Tiering — only an edit that GROWS an already-over-limit
  comment blocks; shrinking silent; same-size advises. Growth is measured
  as aggregate non-doc comment character count in the touched region
  (`old_string`/`new_string` for Edit; on-disk content vs new content for
  Write), mirroring `plan-doc-size`'s whole-file byte-count philosophy
  rather than per-span matching
- [x] ✅ **Task 2.3**: Docstrings/JSDoc are API documentation — exempt from
  `comment_size`, still subject to `comment_changelog`
- [x] ✅ **Task 2.4**: `MUST_EXCEED_COMMENT_SIZE_BECAUSE` escape hatch

`handlers/pre_tool_use/comment_size.py`: `CommentSizeHandler` — 35 tests,
100% file coverage, mypy --strict / ruff / black clean. Not yet registered
in `.claude/hooks-daemon.yaml` (Phase 3 task).

### Phase 3: Integrate & verify

- [x] ✅ **Task 3.1**: Register in config with a code-quality band priority
  (31, 33); honour `daemon.exclude_paths` + per-handler `exclude_paths`
- [x] ✅ **Task 3.2**: `get_acceptance_tests()`; `HANDLER_REFERENCE.md` entry;
  changelog entry. **Not done**: `config-changes` manifest marking them
  `recommended: true` — deferred to the `/release` skill's own workflow
  (Step 6/Step 7 of RELEASING.md), not this plan; both are `enabled: true`
  by default already so the manifest is a release-time promotion, not a
  functional gap
- [ ] ⬜ **Task 3.3**: Full QA (`./scripts/qa/llm_qa.py all`), daemon restart
  RUNNING, and a LIVE socket probe of both directions — the banner case blocked,
  a rationale comment allowed
- [x] ✅ **Task 3.4**: Run the matcher over this entire repository and report the
  hit list. Any hit on a legitimate rationale comment is a design defect, not a
  tuning problem. **Done BEFORE Task 3.3** (see JOURNAL 12:20) — this measurement
  is what drove the Task 1.1 signal redesign; zero BLOCK hits outside this
  handler's own test fixtures after the fix

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

- [x] ✅ The field-report shape (six `Prior <version>:` entries) is DENIED
  (verified via unit test with the real phrasing; live pending)
- [x] ✅ The `DISABLE_MOUSE` rationale comment is ALLOWED (pinned test)
- [x] ✅ Running the matcher across this repo's `src/`+`scripts/`+`tests/`
  (~1,080 files) produced ZERO BLOCK hits on legitimate rationale
  comments — measured via a scratch scanner, NOT assumed. This measurement
  actively CHANGED the design: 3 of the originally-planned 5 blocking
  signals were demoted to advisory after finding real false positives
  (see JOURNAL 12:20 for the full account)
- [x] ✅ Tiering verified: an over-limit comment can still be edited downward
  (comment_size shrink/same-size/grow tests)
- [x] ✅ The deny message names where the text should go instead
- [ ] Full QA passes; daemon restarts RUNNING; live socket probe confirms both
  directions

## Risks & Mitigations

| Risk                                                          | Impact | Probability | Mitigation                                                                                         | Outcome                                                                                                                                                             |
| ------------------------------------------------------------- | ------ | ----------- | -------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Blocks legitimate rationale comments, including this repo's   | High   | Medium      | Whole-repo self-scan measures before shipping; allowed cases pinned as tests BEFORE implementation | Materialised for 3/5 signals — fixed by demoting them to advisory, not by weakening the scan                                                                        |
| Freezes a legacy over-commented file so it cannot be improved | Medium | Low         | Tiering: only a growing edit blocks, so refactoring downward is always possible                    | Verified by test (shrink/same-size never block)                                                                                                                     |
| Semver detection fires on genuine version constants in code   | Medium | Medium      | Only match inside COMMENT spans, never code; require a changelog-shaped phrase, not a bare tag     | Materialised anyway (version-processing docstrings, Task/Phase numbering collision) — fixed via signal demotion + a Task/Phase exclusion on the semver token itself |

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00208-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Not started. Proposal filed as `PROPOSAL.md` in this folder. A first
  implementation attempt was dispatched to a sub-agent and produced nothing
  before terminating; re-dispatch from this plan.
