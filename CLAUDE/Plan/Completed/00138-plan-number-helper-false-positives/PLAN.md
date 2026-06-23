# Plan 00138: Fix Plan-Number Handler False Positives

**Status**: Complete
**Type**: Bug Fix
**Severity**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Bug Description

TWO plan-number handlers share the same false-positive disease — they conflate
"operating on a SPECIFIC, already-known plan folder" with "creating/discovering
a NEW plan number":

### Handler A — `plan_number_helper` (priority 33, Bash path)

(`src/claude_code_hooks_daemon/handlers/pre_tool_use/plan_number_helper.py`)

Blocks Bash commands that merely reference a SPECIFIC numbered plan folder/file,
mistaking them for "scan the plan dir to discover the next number." It should
only fire on genuine *discovery* (enumerating the plan directory's contents to
find the highest number), never on a command operating on a specific,
already-known plan folder.

### Handler B — `validate_plan_number` (priority 41, Write/Edit + mkdir path)

(`src/claude_code_hooks_daemon/handlers/pre_tool_use/validate_plan_number.py`)

Two field bugs:

1. It treats an EDIT/rewrite of an EXISTING plan's files as if a NEW plan is
   being created — rewriting `CLAUDE/Plan/00135-…/PLAN.md` triggered
   "PLAN NUMBER INCORRECT". It must only validate genuinely-new plan folders
   (target folder not yet on disk).
2. It stripped the zero-padding when rendering the folder name in the message
   (`00135-…` → `135-…`) because `int()` dropped leading zeros.

See `context.md` for the exact real-session evidence that motivated this plan.

## Root Causes

### Handler A — `plan_number_helper` (verified against the live `matches()`)

1. **Pattern #2 (find)** — `rf"find\s+{re.escape(plan_dir)}"` matches
   `find CLAUDE/Plan/<ANY-subpath>`, including a find scoped to ONE specific
   plan folder (e.g. `find CLAUDE/Plan/00135-feature ...`). It must only match a
   find on the plan dir ITSELF, not a find inside a specific numbered folder.

2. **Pattern #3 (glob_echo / glob_printf)** —
   `rf"echo\s+[^;&|]*{re.escape(plan_dir)}/[0-9\*\[]"` (and the `printf` twin):
   the char class `[0-9\*\[]` matches a BARE DIGIT, so any `echo`/`printf`
   mentioning `CLAUDE/Plan/0...` (i.e. any numbered folder like `00135`) falsely
   matches. It must require an actual glob metacharacter (`*`, `[`, `?`), not a
   digit.

### Handler B — `validate_plan_number`

3. **`matches()` ignores existence** — it fired on ANY Write/mkdir whose path
   matched `CLAUDE/Plan/(\d+)-name`, regardless of whether the folder already
   existed. Editing an existing plan's PLAN.md is therefore mis-flagged as a new
   creation. Fix: skip when the target plan folder already exists on disk.

4. **`handle()` zero-strips the folder name** — it displayed `{int(number)}`,
   so `00135` rendered as `135`. Fix: echo the ORIGINAL captured digit string
   verbatim and use the zero-padded convention in the corrected example.

The shared root cause across both handlers: conflating "a reference to a
specific, already-known numbered folder (e.g. `00135-name`)" with "a discovery
glob / a new-plan creation."

## Goals

- Stop blocking commands that operate on a specific numbered plan folder/file.
- Keep blocking genuine discovery commands (glob enumeration, `find` on the plan
  dir itself, `ls | sort | tail`, `ls | grep numbers`).
- Maintain 95%+ coverage; black/ruff/mypy clean; no magic values.

## Non-Goals

- No change to the always-on `get_claude_md()` guidance.
- No change to either handler's decision type (both still advisory/non-blocking
  as configured) or to the shared `plan_numbering` util's numbering logic.

## Tasks

### Handler A — `plan_number_helper`

- [x] Reproduce the bug locally (RED tests proving false positives match)
- [x] Add failing regression tests for each confirmed false positive
- [x] Audit patterns #1, #4, #5 for the same digit-conflation; add documenting tests
- [x] Fix `matches()` patterns #2 and #3 (make GREEN)
- [x] Keep every existing TRUE-positive test green

### Handler B — `validate_plan_number`

- [x] RED test: writing to an EXISTING plan folder must not match
- [x] RED test: zero-padded folder name preserved in the message
- [x] RED test: genuinely-new mis-numbered plan still warns (true positive kept)
- [x] Fix `matches()` to skip when the target plan folder already exists on disk
- [x] Fix `handle()` to echo the original digit string + zero-padded example
- [x] Update the two pre-existing tests that encoded the zero-strip bug

### Shared

- [x] Promote `_PLAN_NUMBER_WIDTH` → public `PLAN_NUMBER_WIDTH` in the
  `plan_numbering` util so the warning shares the single source of truth
- [x] Run full test files for both handlers
- [x] Run full QA: `./scripts/qa/llm_qa.py all` (13/13)
- [x] Verify no import break

## Technical Decisions

### Decision 1: Anchor the `find` pattern to the plan dir itself

**Context**: `find CLAUDE/Plan/00135-x` must NOT match; `find CLAUDE/Plan`,
`find CLAUDE/Plan/ -name ...`, `find CLAUDE/Plan -maxdepth 1` must match.

**Decision**: Use `rf"find\s+{re.escape(plan_dir)}/?(\s|$)"`. The optional
trailing slash plus a whitespace/end-of-string anchor means the path token must
END at the plan dir (optionally with a slash) — a deeper path like
`CLAUDE/Plan/00135-x` has more non-space characters after the slash and so does
not match.

### Decision 2: Require a real glob metacharacter for echo/printf

**Context**: `echo CLAUDE/Plan/00135-feature/PLAN.md` must NOT match;
`echo CLAUDE/Plan/0*`, `printf ... CLAUDE/Plan/[0-9]*` must match.

**Decision**: Use
`rf"{cmd}\s+[^;&|]*{re.escape(plan_dir)}/[^\s;&|]*[\*\[?]"` for `echo` and
`printf`. The referenced path segment must contain an actual glob metacharacter
(`*`, `[`, `?`), not merely a digit.

### Decision 3: Patterns #1, #4, #5 are already narrow

**Context**: Audit for the same digit-conflation.

**Decision**: Confirmed safe and documented by regression tests:

- #1 (ls_glob) requires a literal `*` or `[0-9]` glob segment after the plan dir.
- #4 (sort+tail) requires both `sort` AND `tail -N` present alongside the plan
  dir — a specific-folder reference alone does not satisfy this.
- #5 (ls|grep-numbers) requires `ls ...plan_dir`, a `grep`, AND a numeric grep
  pattern. A bare `ls CLAUDE/Plan/00135-x` does not match.

### Decision 4: `validate_plan_number` skips existing plan folders

**Context**: Editing an existing plan's PLAN.md fired "PLAN NUMBER INCORRECT".

**Decision**: In `matches()`, resolve the target plan folder to an absolute path
and return `False` when it already exists on disk. A Write/Edit to a file inside
an existing plan folder (and an `mkdir` of an existing folder) is an
edit/rewrite, not a creation. This also subsumes the prior TOCTOU handling: the
mkdir-already-ran case now short-circuits at `matches()`.

### Decision 5: `validate_plan_number` preserves zero-padding

**Context**: The message rendered `00135-x` as `135-x` (`int()` stripped zeros).

**Decision**: Capture the original digit string and echo it verbatim in
"You are creating: …"; render the corrected `mkdir` example with the expected
number zero-padded via the shared `PLAN_NUMBER_WIDTH` constant (single source of
truth, promoted from the previously-private `_PLAN_NUMBER_WIDTH`).

## Success Criteria

- [x] Each `plan_number_helper` false-positive command no longer matches.
- [x] All pre-existing `plan_number_helper` true-positive tests still match.
- [x] `validate_plan_number` does not warn when editing an existing plan folder.
- [x] `validate_plan_number` preserves zero-padding in its message.
- [x] `validate_plan_number` still warns on a genuinely-new mis-numbered plan.
- [x] Both test files pass.
- [x] QA 13/13.
- [x] No import break.

## Notes & Updates

- Delivery commit: see git log on branch `worktree-agent-aff49a38441fb4860`
  (commit message prefix `Plan 00138:`).
