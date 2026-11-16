# Plan 00616: secret guard regex token in interpreter code

**Status**: Blocked
**Created**: 2026-11-16
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #205

## Overview

GitHub #205 (and ledger entry N626 in Plan 00474, the same class reported on
`R-SECRET-SCRIPT-AUTHOR`) report a false deny. A Bash command ran `python3`
with a quoted-delimiter heredoc whose body held the regex `.*?\n`, and
`secret_file_guard` denied it (R-SECRET-BASH-MENTION). Only one thing reached
a protected file: the token's single literal character, a leading dot, read as
a glob against the protected-file index, where `.*` names every dotfile.
`.vault-pass*` is a default protected glob.

The report was reconstructed by the reporter and has not been reproduced here
yet.

This is a coverage trade-off on a safety guard, so it waits for the owner.

- Bash expands nothing inside a quoted heredoc body.
- The interpreter could glob with the same text: `glob.glob('.*')` in Python
  reads a dotfile.
- The guard cannot tell a regex from an interpreter-side glob by shape alone.
- The guard's documented promise ("a glob of only wildcards names no place")
  does not cover `.*?\n`, which carries a literal dot.

## Question for the owner

How should a glob-shaped token from INTERPRETER CODE (a heredoc body or `-c`
string handed to python, node, ruby and so on, or an `Edit` payload judged by
the script-author rule) be judged against the protected-file index?

- **A, status quo:** keep denying. Any glob-shaped token that the index can
  match is a possible interpreter-side read. There are no false allows, but
  regexes with a leading dot keep getting denied.
- **B, recommended:** apply the existing `_MIN_GLOB_OVERLAP_CHARS` rule to
  index matches of interpreter-code tokens, and only those. A token must share
  at least two literal characters with the protected name before the index can
  match it. That is the rule the text checks already follow, as the reporter
  notes.
  - Shell words that bash really expands (`cat .*`) keep today's verdict.
  - `glob.glob('.*')` inside interpreter code would then be allowed, which is
    a narrow false allow.
- **C, advisory:** for interpreter-code tokens that meet only the index rule,
  give an advisory instead of a deny. This is noisier than B, but nothing goes
  unreported.

## Goals

- Reproduce #205 and N626 with synthetic fixtures. Build protected names in
  code, never spell them.
- Implement the owner's choice test-first.

## Non-Goals

- Changing how shell words bash expands are judged.

## Tasks

### Phase 1: decision and fix

- [ ] ⬜ **Task 1.1**: Owner (or stand-in) chooses A, B or C.
- [ ] ⬜ **Task 1.2**: Reproduce #205 and N626 as failing tests on main.
- [ ] ⬜ **Task 1.3**: Implement the choice, and add a release note under
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/`.

## Success Criteria

- [ ] The choice is recorded in JOURNAL/.
- [ ] Both reports are covered by tests that fail on main, and targeted QA
  passes.
- [ ] The release-bound consequence is recorded in the holding area: a release
  note in `CLAUDE/UPGRADES/UNRELEASED/release-notes/`.

## Delivery & Milestones

- <!-- merge commit hash -->
