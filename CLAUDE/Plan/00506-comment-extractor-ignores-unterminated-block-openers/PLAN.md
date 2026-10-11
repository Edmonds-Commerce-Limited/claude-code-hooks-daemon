# Plan 00506: comment extractor ignores unterminated block openers

**Status**: In Progress
**Created**: 2026-10-11
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #75

## Overview

`strategies/comments/extractor.py` `_consume_delimited` closes an unterminated
block or doc comment at end of file. A `/*` inside a string literal (a glob such
as `"src/*/x.rs"`) therefore opens a "comment" that swallows every following
line. `comment_size` then denies a file that contains no comment at all
(R-COMMENT-SIZE). The extractor's docstring accepts that a marker inside a string
can be misread. That limitation is not visible to users, and the
run-to-end-of-file effect turns a one-token misread into a hard deny of ordinary
code.

Coordinator ruling: an opener with no closing delimiter after it is not a comment
span. An unterminated block comment cannot occur in valid code for the languages
that have block delimiters, so this removes the defect without a per-language
tokenizer. The docstring rules a tokenizer out deliberately.

## Goals

- A block or doc opener with no closer later in the content yields no span. Scanning
  resumes on the next line as ordinary code.
- A terminated block comment is extracted exactly as today.
- The remaining limitation is documented where users read the handler's
  guidance: a marker inside a string can still be misread, bounded by its closer
  or by its line.

## Non-Goals

- A string-literal-aware tokenizer per language.

## Tasks

### Phase 1: Fix

- [ ] ⬜ **Task 1.1**: RED. Tests: the reported Rust reproduction (a `/*` in a
  string, then 40 one-line functions) yields no span over the code and is allowed
  by `comment_size`; a terminated block comment is unchanged; an opener with no
  closer yields no span. Also check every consumer of `extract_comment_spans`
  (`comment_size`, `comment_changelog` and any other), and decide whether the Edit
  path, which judges a fragment, can see a legitimate opener whose closer is outside
  the fragment. State the result in a test or in the report.
- [ ] ⬜ **Task 1.2**: GREEN. Implement the rule in `_consume_delimited`, and
  update the extractor's docstring.
- [ ] ⬜ **Task 1.3**: Document the limitation in the user-facing guidance:
  `comment_size`'s `get_claude_md`/explain text and its handler reference entry,
  wherever the canonical home is. Add a release note in
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/`.

### Phase 2: Land

- [ ] ⬜ **Task 2.1**: Review, coordinator checks, merge; comment on and close
  #75.

## Success Criteria

- [ ] The reported reproduction is allowed, and a genuine over-limit block
  comment is still denied.
- [ ] The limitation is stated in user-facing guidance.
- [ ] The release-bound consequence, a behaviour change in comment extraction,
  is in the pending-release holding area as a release note.

## Delivery & Milestones

- Issue #75 triaged and claimed.
