# Plan 00098: Human-Friendly Markdown Tables

**Status**: Not Started
**Created**: 2026-04-09
**Owner**: Claude (Opus 4.6)
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**Type**: Feature Implementation

## Overview

Claude consistently writes markdown tables with unaligned pipes — the `|` characters don't line up vertically and the delimiter row (`|---|`) doesn't match cell widths. The output is valid markdown but hard to read in source form. We want to auto-fix this so every `.md` file in the repo ends up with cleanly aligned tables without Claude having to remember or think about it.

Research (see `RESEARCH.md` in this folder) evaluated six candidate tools. The clear winner is **`mdformat + mdformat-gfm`** — a pure-Python, pip-installable formatter that aligns table pipes by default, has both a CLI and a Python API, is idempotent, and slots cleanly into the existing daemon venv with no new runtime dependencies.

This plan installs `mdformat + mdformat-gfm` into the daemon venv, adds a PostToolUse handler that runs it automatically after Write/Edit of `.md` files, and exposes a CLI subcommand for ad-hoc batch fixes to existing files.

## Goals

- Every `.md` file written or edited by Claude ends up with aligned table pipes and consistent column widths
- Zero manual intervention — it just works
- No new runtime dependency beyond a `pip install` into the existing venv
- Ad-hoc CLI available for batch-fixing existing files
- Handler is idempotent and safe to re-run
- 95% test coverage, full QA passing, daemon restart verified

## Non-Goals

- Rewriting other markdown constructs (headings, lists, code blocks) beyond what `mdformat` does naturally
- Replacing existing `markdown_organization` or `validate_instruction_content` handlers
- Supporting non-GFM table dialects (MultiMarkdown grid tables etc.)
- Adding a PreToolUse block that denies unaligned tables — advisory/auto-fix is less disruptive
- Formatting markdown inside other file types (e.g. docstrings, JSON strings)

## Context & Background

### The Problem Claude Produces

```
| Field | Key | Zoho Type | Required | Visibility |
|-------|-----|-----------|----------|------------|
| Snapshot Taken At | `cf_stat_snapshot_taken_at` | DateTime | No | Stats |
| Total Orders | `cf_stat_total_orders` | Number | No | Stats |
```

### The Target Output

```
| Field             | Key                         | Zoho Type | Required | Visibility |
| ----------------- | --------------------------- | --------- | -------- | ---------- |
| Snapshot Taken At | `cf_stat_snapshot_taken_at` | DateTime  | No       | Stats      |
| Total Orders      | `cf_stat_total_orders`      | Number    | No       | Stats      |
```

### Why mdformat (Short Version)

Six tools were evaluated. Full matrix in `RESEARCH.md`. Summary:

- **mdformat + mdformat-gfm** — Python, pip-installable, aligns by default, CLI + API, idempotent. **Winner.**
- **markdown-table-prettify** — Node runtime, extra dependency
- **markdownlint-cli2** — MD060 detects but is **not auto-fixable** (confirmed upstream limitation)
- **Prettier** — Node, expands tables too wide, poor for large tables
- **tabulate / py-markdown-table** — generate tables from data, don't reformat existing markdown
- **markdown-table-formatter (npm)** — Node runtime

### Integration Choice: PostToolUse Handler + CLI Subcommand

Option D from `RESEARCH.md`: combined auto-format on write + on-demand CLI.

- **Auto**: PostToolUse handler matching `Write`/`Edit` of `.md` files runs `mdformat.file(path)` after write
- **Manual**: `$PYTHON -m claude_code_hooks_daemon.daemon.cli format-markdown <path>` for batch fixes to existing files

## Tasks

### Phase 1: Install & Smoke-Test the Tool

- [ ] ⬜ **Task 1.1**: Install `mdformat` and `mdformat-gfm` into the daemon venv
  - [ ] ⬜ `/workspace/untracked/venv/bin/pip install mdformat mdformat-gfm`
  - [ ] ⬜ Add both to `pyproject.toml` dependencies (not dev deps — the handler needs them at runtime)
  - [ ] ⬜ Verify version is pinned sensibly (e.g. `mdformat>=0.7`, `mdformat-gfm>=0.4`)
- [ ] ⬜ **Task 1.2**: Smoke-test against a deliberately malformed table
  - [ ] ⬜ Create a temp `.md` file with an unaligned table from the user's Zoho example
  - [ ] ⬜ Run `mdformat tempfile.md`
  - [ ] ⬜ Verify pipes are aligned, delimiter row matches widths, content preserved
  - [ ] ⬜ Run again — verify idempotence (no changes second time)
- [ ] ⬜ **Task 1.3**: Smoke-test the Python API
  - [ ] ⬜ `python -c "import mdformat; print(mdformat.text('| a | b |\n|-|-|\n| foo | bar |'))"`
  - [ ] ⬜ Verify output is aligned
- [ ] ⬜ **Task 1.4**: Check for unexpected reformatting side-effects
  - [ ] ⬜ Run `mdformat --check` against a few existing `.md` files in the repo
  - [ ] ⬜ Document any undesired reflows (code blocks, headings, lists)
  - [ ] ⬜ Decide if a `.mdformat.toml` config is needed to constrain behaviour

### Phase 1 Smoke Test Findings (2026-04-09)

Smoke-testing `mdformat 1.0.0 + mdformat-gfm 1.0.0` against `CLAUDE.md` revealed three side effects that must be mitigated in the handler:

1. **Tables aligned correctly** — pipes aligned, delimiter row widened to match cell widths, alignment colons preserved. This is the desired behaviour.
2. **Ordered lists renumbered** — `2. 3. 4.` → `1. 1. 1.` by default. Mitigated by passing `options={"number": True}` to preserve consecutive numbering.
3. **Thematic breaks reformatted** — `---` → `______________________________________________________________________` (70 underscores, hardcoded in `mdformat/renderer/_context.py` with no config option). Mitigated by post-processing the formatter output: replace any line matching `^_{70}$` with `---`.
4. **Asterisks in table cells escaped** — `RELEASES/*.md` → `RELEASES/\*.md`. This is a correctness fix (GFM tables require escaping) and should be kept.

**Handler contract** (locked in for Phase 3):

```python
FORMATTED = mdformat.text(
    raw_markdown,
    extensions={"gfm"},
    options={"number": True},
)
# Post-process: restore --- thematic breaks
_THEMATIC_BREAK_UNDERSCORE = "_" * 70
_THEMATIC_BREAK_DASH = "---"
FORMATTED = "\n".join(
    _THEMATIC_BREAK_DASH if line == _THEMATIC_BREAK_UNDERSCORE else line
    for line in FORMATTED.split("\n")
)
```

**Implication**: the handler must use `mdformat.text()` (not `mdformat.file()`) so the post-processing can run before writing back to disk. Read the file, format the string, post-process, write back if different.

### Phase 2: Debug Hook Events

Per CLAUDE/DEBUGGING_HOOKS.md, capture real event flow before writing the handler.

- [ ] ⬜ **Task 2.1**: Run `./scripts/debug_hooks.sh start "Writing markdown file"`
- [ ] ⬜ **Task 2.2**: In a separate Claude Code session, Write and Edit a `.md` file with a table
- [ ] ⬜ **Task 2.3**: Stop debug capture and inspect logs in `/tmp/hook_debug_*.log`
- [ ] ⬜ **Task 2.4**: Document exact PostToolUse hook_input shape for Write and Edit of `.md` files
  - [ ] ⬜ Confirm `tool_name`, `tool_input.file_path`, and any other fields
  - [ ] ⬜ Confirm Edit on `.md` file produces the same event shape

### Phase 3: TDD Handler Implementation

- [ ] ⬜ **Task 3.1**: RED — write failing tests
  - [ ] ⬜ Create `tests/unit/handlers/post_tool_use/test_markdown_table_formatter.py`
  - [ ] ⬜ Test `matches()` positive cases: Write to `.md`, Edit to `.md`, `.markdown` extension, uppercase `.MD`
  - [ ] ⬜ Test `matches()` negative cases: non-markdown extensions, non-Write/Edit tools, missing file_path
  - [ ] ⬜ Test `handle()` reformats an unaligned table into an aligned table
  - [ ] ⬜ Test `handle()` is a no-op when the file is already aligned (idempotence)
  - [ ] ⬜ Test `handle()` skips missing files (race condition safety)
  - [ ] ⬜ Test `handle()` gracefully handles mdformat exceptions (FAIL FAST with context, don't crash dispatch)
  - [ ] ⬜ Test initialisation: name, priority, terminal flag
  - [ ] ⬜ Run tests — they must FAIL
- [ ] ⬜ **Task 3.2**: GREEN — implement handler
  - [ ] ⬜ Create `src/claude_code_hooks_daemon/handlers/post_tool_use/markdown_table_formatter.py`
  - [ ] ⬜ Use `HandlerID` and `Priority` constants (no magic values)
  - [ ] ⬜ Priority range: 25-35 (code quality) — choose `26` to sit next to `lint_on_edit` at `25`
  - [ ] ⬜ `terminal=False` (non-terminal so other post-tool handlers still run)
  - [ ] ⬜ Import `mdformat` lazily inside `handle()` to avoid import cost when handler doesn't match
  - [ ] ⬜ Use `mdformat.text()` with `extensions={"gfm"}` and `options={"number": True}`
  - [ ] ⬜ Post-process output to restore `---` thematic breaks (replace 70-underscore lines)
  - [ ] ⬜ Read file, format string, post-process, write back only if changed
  - [ ] ⬜ Run tests — they must PASS
- [ ] ⬜ **Task 3.3**: REFACTOR
  - [ ] ⬜ Extract `_MARKDOWN_EXTENSIONS` and other magic values as module constants
  - [ ] ⬜ Verify 95%+ coverage on the new handler file
  - [ ] ⬜ Add `get_claude_md()` method returning guidance text for CLAUDE.md injection (per CLAUDE.md Guidance Audit gate in release process)
  - [ ] ⬜ Add `get_acceptance_tests()` method with test cases

### Phase 4: Handler Registration & Dogfooding

- [ ] ⬜ **Task 4.1**: Register handler in `constants/handler_id.py`
- [ ] ⬜ **Task 4.2**: Add handler entry to `.claude/hooks-daemon.yaml` under `post_tool_use:`
- [ ] ⬜ **Task 4.3**: Add handler to the handler registry loader if needed
- [ ] ⬜ **Task 4.4**: Regenerate `.claude/HOOKS-DAEMON.md` via `$PYTHON -m claude_code_hooks_daemon.daemon.cli generate-docs`
- [ ] ⬜ **Task 4.5**: Run dogfooding tests
  - [ ] ⬜ `pytest tests/integration/test_dogfooding_config.py -v`
  - [ ] ⬜ `pytest tests/integration/test_dogfooding_hook_scripts.py -v`

### Phase 5: CLI Subcommand for Batch Fixes

- [ ] ⬜ **Task 5.1**: Add `format-markdown` subcommand to `daemon/cli.py`
  - [ ] ⬜ Accepts a file path or directory
  - [ ] ⬜ Recursively formats all `.md` files if given a directory
  - [ ] ⬜ Prints a summary of files changed
  - [ ] ⬜ Has a `--check` mode that exits non-zero if any file would be reformatted
- [ ] ⬜ **Task 5.2**: Unit tests for the CLI subcommand
  - [ ] ⬜ Single file format
  - [ ] ⬜ Directory recursive format
  - [ ] ⬜ `--check` mode exit codes
  - [ ] ⬜ Handles non-existent paths gracefully (FAIL FAST)

### Phase 6: Daemon Load & QA

- [ ] ⬜ **Task 6.1**: Restart daemon — this is the critical check
  - [ ] ⬜ `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart`
  - [ ] ⬜ `$PYTHON -m claude_code_hooks_daemon.daemon.cli status` — must show `RUNNING`
  - [ ] ⬜ `$PYTHON -m claude_code_hooks_daemon.daemon.cli logs` — check for import errors
- [ ] ⬜ **Task 6.2**: Run full QA suite
  - [ ] ⬜ `./scripts/qa/run_all.sh`
  - [ ] ⬜ All 8 checks must pass
- [ ] ⬜ **Task 6.3**: Live test in the current session
  - [ ] ⬜ Write a deliberately malformed table into a test `.md` file
  - [ ] ⬜ Verify the file is automatically reformatted after the Write completes
  - [ ] ⬜ Verify the PostToolUse advisory context appears in the response

### Phase 7: Batch-Fix Existing Repo Markdown

- [ ] ⬜ **Task 7.1**: Dry-run the new CLI against the whole repo
  - [ ] ⬜ `$PYTHON -m claude_code_hooks_daemon.daemon.cli format-markdown --check .`
  - [ ] ⬜ Review the list of files that would change
- [ ] ⬜ **Task 7.2**: Decide scope of batch fix
  - [ ] ⬜ Only format files under `CLAUDE/`, `docs/`, `RELEASES/`? Or entire repo?
  - [ ] ⬜ Avoid reformatting files that are intentionally hand-crafted (e.g. generated output samples, test fixtures)
- [ ] ⬜ **Task 7.3**: Apply the format
  - [ ] ⬜ Commit the batch fix as a separate checkpoint commit with clear scope description
  - [ ] ⬜ Review the diff for any unexpected content changes

### Phase 8: Documentation & Completion

- [ ] ⬜ **Task 8.1**: Update `CLAUDE.md` with a mention of the new handler and CLI subcommand
- [ ] ⬜ **Task 8.2**: Update `CLAUDE/Plan/README.md` — move this plan from Active to Completed when done
- [ ] ⬜ **Task 8.3**: Add entry to changelog (via `/release` skill, not manually)

## Dependencies

- **External**: `mdformat>=0.7`, `mdformat-gfm>=0.4` (new pip deps — both pure Python)
- **Internal**: None — standalone PostToolUse handler, no handler chain dependencies
- **Depends on**: Nothing — this is a self-contained feature
- **Blocks**: Nothing

## Technical Decisions

### Decision 1: mdformat + mdformat-gfm vs alternatives

**Context**: Need a tool to reformat markdown tables with aligned pipes.

**Options Considered**:
1. `mdformat + mdformat-gfm` — Python, pip-installable, aligned-by-default
2. `markdown-table-prettify` — Node runtime
3. `markdownlint-cli2 --fix` — Node runtime, MD060 not auto-fixable
4. `prettier` — Node runtime, expands tables poorly
5. Custom Python implementation — maintenance burden, reinventing the wheel

**Decision**: `mdformat + mdformat-gfm`. Python-native matches the project's stack, no new runtime dependency, aligned pipes by default, both CLI and API, idempotent, actively maintained. See full comparison in `RESEARCH.md`.

**Date**: 2026-04-09

### Decision 2: PostToolUse auto-format vs PreToolUse block

**Context**: When should the formatter run?

**Options Considered**:
1. PostToolUse handler that runs `mdformat` after Write/Edit completes — automatic, invisible on success
2. PreToolUse handler that denies Write/Edit with unaligned tables — intrusive, burns tokens
3. Manual slash command only — unreliable, Claude might forget

**Decision**: PostToolUse auto-format (Option 1) as the primary mechanism, with a CLI subcommand (Option 3 variant) for ad-hoc batch fixes. PreToolUse blocking is too intrusive for a cosmetic concern.

**Date**: 2026-04-09

### Decision 3: Handler priority

**Context**: Where to slot this in the PostToolUse priority range?

**Options Considered**:
1. Priority 25 (alongside `lint_on_edit`)
2. Priority 26 (just after `lint_on_edit`)
3. Priority 30+ (after other quality handlers)

**Decision**: Priority 26 — sits next to `lint_on_edit` in the code-quality cluster (25-35 range). Order doesn't strictly matter because it's `terminal=False`, but 26 keeps it adjacent to related concerns.

**Date**: 2026-04-09

### Decision 4: Full-file format vs table-only

**Context**: `mdformat` reformats the entire file (headings, lists, code blocks), not just tables. This could surprise users.

**Options Considered**:
1. Let `mdformat` reformat the whole file — gives consistent output across the project
2. Parse the file, extract tables, reformat only tables, splice back in — table-only scope, custom logic
3. Constrain `mdformat` via `.mdformat.toml` config to minimise non-table changes

**Decision**: Start with Option 1 (full-file format). If side-effects prove disruptive during the smoke test in Phase 1.4, fall back to Option 3 with a `.mdformat.toml` config. Option 2 is over-engineering — reinventing a markdown AST parser.

**Date**: 2026-04-09

## Success Criteria

- [ ] `mdformat` and `mdformat-gfm` installed in venv and declared in `pyproject.toml`
- [ ] New PostToolUse handler `markdown_table_formatter` exists with 95%+ test coverage
- [ ] Handler automatically reformats unaligned tables after Write/Edit of `.md` files
- [ ] New CLI subcommand `format-markdown` works for single files and directories
- [ ] CLI `--check` mode exits non-zero on files that would be reformatted
- [ ] Daemon restarts successfully with new code (`RUNNING` status)
- [ ] Full QA suite passes (all 8 checks)
- [ ] Live test: writing an unaligned table results in an aligned table on disk
- [ ] Handler is idempotent — re-running on an aligned file produces no changes
- [ ] `.claude/HOOKS-DAEMON.md` regenerated and shows the new handler
- [ ] Handler implements `get_claude_md()` and `get_acceptance_tests()` per release-gate requirements

## Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| mdformat reformats non-table content unexpectedly | Medium | Medium | Phase 1.4 smoke test; fall back to `.mdformat.toml` config if needed |
| Handler runs on every `.md` write and slows things down | Low | Low | Lazy import of mdformat; handler only runs for matching files; skip if file unchanged |
| Batch-fix in Phase 7 introduces noise in unrelated files | Medium | Medium | Dry-run with `--check` first; scope narrowly; commit as separate checkpoint |
| mdformat exception crashes the PostToolUse handler chain | High | Low | Wrap `mdformat.file()` in try/except with explicit error context; never propagate |
| Users with hand-crafted tables lose their formatting | Low | Medium | Only runs after Write/Edit; doesn't touch files on disk otherwise |
| Adding runtime deps increases install surface | Low | Low | Both are pure Python, no C extensions; minimal transitive deps |

## Execution Strategy

**Sub-Agent Orchestration (Sonnet)**: The main agent coordinates the phases. Phase 1 (install + smoke test) can run in the main thread. Phase 3 (TDD implementation) can be delegated to a `python-developer` sub-agent with the test file as the starting point. Phase 6 (daemon restart + QA) runs in the main thread. Phase 7 (batch fix) runs in the main thread with human review of the diff.

## Notes & Updates

### 2026-04-09
- Plan created from user request ("human friendly markdown tables")
- Research completed in `RESEARCH.md` — six tools evaluated, `mdformat + mdformat-gfm` selected
- Current version: v3.0.1 (from `git log`)
