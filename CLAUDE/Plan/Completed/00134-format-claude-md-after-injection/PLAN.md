# Plan 00134: Format CLAUDE.md After Handler-Guidance Injection

**Status**: Complete
**Created**: 2026-06-22
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

On daemon startup, `ClaudeMdInjector` (`core/claude_md_injector.py`, invoked
from `daemon/controller.py`) collects each active handler's `get_claude_md()`
output and writes a `<hooksdaemon>…</hooksdaemon>` block into the project's
`CLAUDE.md`, then auto-commits it ("Auto: hooks daemon regenerated CLAUDE.md
handler guidance"). The injected content is written **raw** — it is not passed
through the markdown formatter (`mdformat` + `mdformat-gfm`) that the
`markdown_table_formatter` PostToolUse handler runs on every `.md` Write/Edit.

The result is an inconsistency: the daemon writes one representation, but the
**next time anyone edits CLAUDE.md**, the PostToolUse formatter reformats the
whole file — including the daemon-injected block — producing a spurious diff
that has nothing to do with the user's edit. This shows up as repeated "Auto:
hooks daemon regenerated…" churn and formatter-vs-injector ping-pong in git
history.

The fix is to run the same markdown-formatting pass on `CLAUDE.md`
**immediately after** the injector writes the block, so the on-disk content is
already formatter-canonical and stays consistent with what
`markdown_table_formatter` would produce. No more churn on the next edit.

## Goals

- After `ClaudeMdInjector` writes the `<hooksdaemon>` block, the resulting
  `CLAUDE.md` is byte-identical to what the project markdown formatter would
  produce (idempotent: a subsequent `format-markdown` run is a no-op).
- Eliminate the formatter-vs-injector diff churn on the next CLAUDE.md edit.
- Reuse the existing formatting code path (the one behind
  `cli format-markdown` / `markdown_table_formatter`) — single source of truth,
  no second formatter implementation.

## Non-Goals

- No change to *what guidance* is injected (content unchanged — only its
  formatting is normalised).
- No change to the auto-commit behaviour beyond it now committing
  formatter-canonical content.
- Not reformatting user content outside the `<hooksdaemon>` block beyond what
  the standard formatter already does on a normal edit (the formatter is
  whole-file; that is the convergence we want — but confirm it does not fight
  `validate_instruction_content`).

## Context & Background

- Injector: `src/claude_code_hooks_daemon/core/claude_md_injector.py`
  (`write_text(updated, …)` is where canonicalisation must happen).
- Formatter SSOT: the code behind `markdown_table_formatter` /
  `cli format-markdown` (`mdformat` + `mdformat-gfm`). Find the shared function
  and call it on the injector's output rather than re-implementing.
- Observable symptom: recent git log shows repeated
  `Auto: hooks daemon regenerated CLAUDE.md handler guidance` commits.

## Tasks

### Phase 1: Reproduce & locate the formatter SSOT

- [ ] ⬜ **Task 1.1**: Reproduce — inject into a fixture CLAUDE.md, then run the
  markdown formatter on it, and assert the bytes differ (proves the bug).
- [ ] ⬜ **Task 1.2**: Locate the shared formatting function used by
  `markdown_table_formatter` and `cli format-markdown`; confirm it is safe
  to call on a full file from inside the injector.

### Phase 2: Fix (TDD)

- [ ] ⬜ **Task 2.1**: RED — failing test: after `ClaudeMdInjector.inject()`,
  `CLAUDE.md` is idempotent under the formatter (formatting it again yields
  no change).
- [ ] ⬜ **Task 2.2**: GREEN — have the injector format the file (or the built
  block) via the shared formatter before/at `write_text`, with a fail-safe
  fallback to the raw write if formatting raises (advisory feature — must
  never crash daemon startup; mirror the existing "daemon continues without
  injection" guards).
- [ ] ⬜ **Task 2.3**: Ensure the auto-commit step sees the formatter-canonical
  content (format before the dirty-check/commit).
- [ ] ⬜ **Task 2.4**: REFACTOR; confirm no conflict with
  `validate_instruction_content` (the injected block is daemon-owned;
  formatting must not introduce blocked ephemeral patterns).

### Phase 3: Verify

- [ ] ⬜ **Task 3.1**: Full QA `./scripts/qa/run_all.sh` (or `llm_qa.py all`).
- [ ] ⬜ **Task 3.2**: Daemon restart + status RUNNING; confirm CLAUDE.md is
  stable across two consecutive restarts (second restart produces no diff).
- [ ] ⬜ **Task 3.3**: Dogfood — restart in this repo, edit CLAUDE.md trivially,
  confirm the formatter no longer rewrites the injected block.

## Success Criteria

- [ ] After injection, `cli format-markdown CLAUDE.md` is a no-op (idempotent).
- [ ] Two consecutive daemon restarts produce no CLAUDE.md diff.
- [ ] A user edit to CLAUDE.md no longer churns the daemon-injected block.
- [ ] Formatting failure never crashes daemon startup (fail-safe to raw write).
- [ ] QA passes; daemon restarts RUNNING.

## Risks & Mitigations

| Risk                                               | Impact | Probability | Mitigation                                                                                               |
| -------------------------------------------------- | ------ | ----------- | -------------------------------------------------------------------------------------------------------- |
| Formatter raises and blocks daemon startup         | High   | Low         | Wrap in fail-safe; fall back to raw write, log advisory (mirror existing injector guards)                |
| Whole-file format alters user content unexpectedly | Med    | Low         | Same transform a normal edit already applies; document and verify against `validate_instruction_content` |
| One-time large diff when first formatted           | Low    | High        | Expected and desirable — converges the file once; note in release                                        |

## Notes & Updates

### 2026-06-22

- Plan scaffolded (00134) to capture the niggle: daemon injects the
  `<hooksdaemon>` block into CLAUDE.md without running the markdown formatter,
  so the next edit triggers `markdown_table_formatter` to reformat it →
  spurious churn. Fix = format via the existing formatter SSOT right after
  injection so on-disk content is already canonical.
- Candidate for the next release alongside Plan 00133.

### Delivery

- Delivered in commit `08e25d3`. Extracted the mdformat+gfm transform into
  `utils/markdown_format.format_markdown_text` (SSoT) and pointed the
  `markdown_table_formatter` handler, the `format-markdown` CLI, and the
  `ClaudeMdInjector` at it (removed two duplicate copies). The injector now
  formats CLAUDE.md after writing the block (fail-safe; content-loss guard runs
  on the pre-format replace result). Dogfooded via daemon restart: the first
  restart applied a one-time canonical reformat of this repo's CLAUDE.md
  (commit `2643214`); subsequent restarts are stable.
