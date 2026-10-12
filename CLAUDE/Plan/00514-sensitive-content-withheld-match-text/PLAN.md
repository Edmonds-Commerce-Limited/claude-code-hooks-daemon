# Plan 00514: sensitive content withheld match text

**Status**: Not Started
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

Changing what a safety control discloses is an owner call, so this plan records the options and waits.

## Owner Decisions Needed

The coordinator has not ruled on these.

1. **Shape of the change.** There are three options:

   - (a) A per-pattern option such as `disclose_match: false`. Existing patterns keep naming what they match.
   - (b) A separate pattern class, for example `withheld_patterns`, whose deny reason never shows the match.
   - (c) Withhold the match for every public pattern by default.

   Options (a) and (b) are additive. Option (c) reverses Plan 00201's decision for every existing user.

2. **What a withheld reason names.** #92 asks for the path, the pattern name and the line number. The Write/Edit
   reason has no line number today. Should it gain one, and should a withheld reason keep the pattern's description,
   which an owner might also write too specifically?

3. **Other surfaces.** Should the commit-time scan, the git metadata checks and the `gh` body checks follow the same
   per-pattern setting, or stay as they are?

## Goals

- An owner can declare a structural pattern whose match never appears in a deny reason, log or transcript.
- A withheld deny still tells the agent where to look, so the content stays fixable.

## Non-Goals

- Changing the secret word list.
- Weakening any existing deny: every pattern that blocks today still blocks.

## Tasks

### Phase 0: Owner decisions

- [ ] ⬜ **Task 0.1**: The owner answers the questions under Owner Decisions Needed.

### Phase 1: Implement per the decisions

- [ ] ⬜ **Task 1.1**: Write the tests red first, covering a withheld Write deny, a withheld Edit deny, and an unchanged named deny.
- [ ] ⬜ **Task 1.2**: Implement the chosen shape, including its config validation.
- [ ] ⬜ **Task 1.3**: Update the handler guidance and `docs/guides/HANDLER_REFERENCE.md`.

## Success Criteria

- [ ] The owner's decisions are recorded in this plan's JOURNAL/.
- [ ] With the #92 reproduction, a withheld pattern's deny reason does not contain the matched text.
- [ ] Release-bound consequences are in the UNRELEASED holding area (a release note), or this plan records that it has
  none because the owner declined it.

## Delivery & Milestones

- Filed from GitHub #92 by the coordinator; awaiting owner decisions.
