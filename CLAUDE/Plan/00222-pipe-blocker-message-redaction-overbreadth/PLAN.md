# Plan 00222: pipe blocker message redaction overbreadth

**Status**: In Progress
**Created**: 2026-08-12
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

`pipe_blocker` blanks the VALUE of `-m` / `--message` / `-F` / `--file` before
it scans for pipes, so prose in a commit message that happens to contain the
literal characters of a pipe-to-pager is not mistaken for a real pipe. The
intent is right. The implementation is too broad in two independent ways, one
cosmetic and one a genuine bypass.

**Bypass.** The pattern blanks DOUBLE-quoted values. The shell performs command
substitution inside double quotes, so `git commit -m "$(pytest tests/ | tail -1)"`
runs pytest, pipes it, and is **not blocked** — measured against the live
handler, not inferred. Single quotes suppress substitution and are correctly
inert. The daemon already knows this exact fact elsewhere:
`git_message_backtick` exists *because* double quotes execute. Two handlers in
one codebase currently disagree about the shell.

**Misattribution.** The flag is matched anywhere, with no requirement that the
command takes a message at all. `python -m pytest tests/ | tail -5` is correctly
blocked, but the producer is reported as a redaction placeholder instead of
`pytest`, so the remediation the block prints is not runnable. `python -m pytest`
is one of the most common invocations in this repository — it was hit while
working on Plan 00216, which is how this was found.

This is the same root-cause shape as Plan 00221, closed hours earlier: there, a
pipe was detected but its producer was read from the wrong text. Here, a value
is discarded as inert prose when the shell will in fact execute it. Both are
"the guard reasoned about the wrong span".

## Goals

- Blank only values that genuinely **cannot** execute, so a real pipe inside an
  executing substitution is never hidden
- Interpret a message flag only for commands that actually take a message, so
  `python -m <module>` keeps naming its real producer
- Keep the Plan 00209 false-positive fix intact: heredoc/quoted PROSE describing
  a pipe must still not trip detection

## Non-Goals

- No change to the block MESSAGE templating — that is Plan 00209's scope, and
  the dedupe scout confirmed the two are orthogonal (00209 is the advisory
  text; this is the scanning that precedes it).
- No new whitelist entries.

## Context & Background

Measured against the live handler:

| command                                  | decision        | reality                           |
| ---------------------------------------- | --------------- | --------------------------------- |
| `python -m pytest tests/ \| tail -5`     | blocked         | correct, but producer is redacted |
| `git commit -m "$(pytest … \| tail -1)"` | **not blocked** | substitutes and executes          |
| `git commit -m 'prose with \| tail'`     | not blocked     | correct — cannot substitute       |

## Technical Decisions

### Decision 1: quote class decides inertness, not flag presence

**Context**: the redaction treats any `-m` value as prose.

**Decision**: only a SINGLE-quoted value (and the quoted-heredoc form, which is
also literal) may be blanked. A double-quoted or bare value can substitute, so
it must be left visible to the scanner — where Plan 00221's substitution
attribution already resolves the inner producer correctly.

**Consequence accepted**: a double-quoted commit message containing literal
`| tail` prose will now be scanned. That is the correct trade: such a message
is *already* dangerous for the reason `git_message_backtick` documents, and the
project's own guidance tells authors to use single quotes or `-F`.

### Decision 2: scope the flag to commands that take a message

**Context**: `-m` means "module" to python and "message" to git.

**Decision**: treat `-m`/`--message` as a message flag only for the commands
that have one. `-F`/`--file` likewise. This is what makes `python -m pytest`
name its real producer again.

## Tasks

### Phase 1: Pin the current behaviour

- [ ] 🔄 **Task 1.1**: Failing test for the double-quoted substitution bypass
- [ ] ⬜ **Task 1.2**: Failing test for `python -m <module>` producer naming
- [ ] ⬜ **Task 1.3**: Passing tests locking the behaviour that must NOT change —
  single-quoted prose stays inert, and the Plan 00209 heredoc case

### Phase 2: Fix

- [ ] ⬜ **Task 2.1**: Restrict blanking to non-substituting quote classes
- [ ] ⬜ **Task 2.2**: Scope message-flag interpretation to message-taking commands

### Phase 3: DBF — why did nothing catch this?

- [ ] ⬜ **Task 3.1**: `git_message_backtick` already encodes "double quotes
  execute". Establish whether that fact can be shared rather than restated, so a
  third handler cannot disagree with it again
- [ ] ⬜ **Task 3.2**: Add the bypass shape to the handler's
  `get_acceptance_tests()` so it is exercised against the live daemon

### Phase 4: Verify

- [ ] ⬜ **Task 4.1**: Full QA suite passes
- [ ] ⬜ **Task 4.2**: Probe the live daemon through the production forwarder
- [ ] ⬜ **Task 4.3**: `get_claude_md()` states the quote-class rule, since the
  guidance currently implies any `-m` prose is safe

## Success Criteria

- [ ] `git commit -m "$(pytest … | tail -1)"` is blocked
- [ ] `git commit -m 'prose with | tail'` is still allowed
- [ ] `python -m pytest … | tail` names `pytest` as the producer
- [ ] The Plan 00209 heredoc false-positive case still does not fire
- [ ] Full QA passes and the daemon restarts RUNNING

## Dependencies

- Related: Plan 00221 — same root-cause shape (guard reasoned about the wrong
  span), and its substitution attribution is what makes Decision 1 safe.
- Related: Plan 00209 — owns the block-message templating; explicitly not
  touched here.

## Risks & Mitigations

| Risk                                                     | Impact | Probability | Mitigation                                                                   |
| -------------------------------------------------------- | ------ | ----------- | ---------------------------------------------------------------------------- |
| Scanning double-quoted messages reintroduces 00209 noise | Medium | Medium      | Task 1.3 locks the heredoc case before any change; prose-shape guard remains |
| Message-flag scoping misses a command that takes `-m`    | Low    | Medium      | Failing open here only costs a redacted label, never a bypass                |

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00222-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Found by dogfooding while running `python -m pytest … | tail` during Plan 00216
