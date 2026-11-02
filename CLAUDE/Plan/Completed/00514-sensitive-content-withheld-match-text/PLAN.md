# Plan 00514: sensitive content withheld match text

**Status**: Complete
**Created**: 2026-10-12
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #92

## Overview

When `sensitive_content` denies a Write or Edit on a public pattern, the reason ends with `Matched: <matched text>`
(`_deny_public_pattern` in `src/claude_code_hooks_daemon/handlers/pre_tool_use/sensitive_content.py`). That is
deliberate. Plan 00201 defined public patterns as safe to name, so the reason says what matched, and the handler's own
guidance says the same.

Issue #92 reports the cost of that choice. A pattern written to catch a secret by its shape, such as a labelled sort
code or a reference number, cannot be used safely, because the deny reason repeats the value into the transcript. The
secret word list never discloses a term, but it matches exact terms only and cannot express a format. The commit-time
scan already withholds the line and names only the path and the pattern.

Changing what a safety control discloses is an owner call, and the owner has ruled.

## Owner Ruling

The owner's own words, 2 November 2026: "why would we ever want to disclose the matched text ... disclose WHERE we found
it but not WHAT IT IS - that puts sensitive stuff directly into transcript which is absolutely wrong. disclose the
pattern sure, dont disclose the match."

So option (c) applies, with no per-pattern switch: no public pattern ever echoes its match, on any surface. The deny
reason may name the pattern, the path, the line, the git field (commit message, tag name, branch name, author identity,
merge message) and the `gh` body (inline, or the body-file path). It never names the matched characters, a snippet of
them, or a recoverable redaction. This reverses Plan 00201's "public patterns are safe to name".

## Goals

- No public pattern's match appears in a deny reason, log or transcript.
- A withheld deny still tells the agent where to look, so the content stays fixable.

## Non-Goals

- Changing the secret word list.
- Weakening any existing deny: every pattern that blocks today still blocks.

## Tasks

### Phase 0: Owner decisions

- [x] ✅ **Task 0.1**: The owner ruled (see Owner Ruling).

### Phase 1: Implement per the decisions

- [x] ✅ **Task 1.1**: Tests written red first for Write, Edit, git metadata, `gh` body and log records.
- [x] ✅ **Task 1.2**: Withhold the match on every surface and add the line number to the Write/Edit reason.
- [x] ✅ **Task 1.3**: Handler guidance, rules table, `docs/guides/HANDLER_REFERENCE.md` and the release note updated.

### Phase 2: Merge

- [x] ✅ **Task 2.1**: The coordinator merges the branch, runs the full QA gate and closes this plan. Merged at `17184f376`; targeted QA 6275 passed, 0 failed; the full QA gate runs as part of the imminent release's CI gate, by the owner's release authorisation of 2 November 2026.

## Success Criteria

- [x] The owner's ruling is recorded in this plan (Owner Ruling).
- [x] With the #92 reproduction, the deny reason does not contain the matched text.
- [x] Release-bound consequences are in the UNRELEASED holding area: release note 017.

## Delivery & Milestones

- Filed from GitHub #92 by the coordinator; owner ruled 2 November 2026; implemented.
