# Plan 00222: pipe blocker message redaction overbreadth

**Status**: Complete
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

### Decision 1: SUBSTITUTION presence decides inertness, not quote class

**Context**: the redaction treats any `-m` value as prose.

**Rejected first attempt — "blank only single-quoted values".** Writing the
tests before the fix killed this immediately. Plan 00200 has two deliberate
tests asserting that a DOUBLE-quoted message containing literal `| tail -20`
prose is not blocked, and they are right: without a `$(` or a backtick, the
shell executes nothing and the pipe really is text. A quote-class rule would
have re-broken the exact false positive Plan 00200 was written to fix.

**Decision**: a message value is inert unless it contains a COMMAND
SUBSTITUTION — `$(`, `` ` ``, or `<(`. Single-quoted values never do (the
shell suppresses substitution inside them), so they stay inert unconditionally.
A double-quoted value carrying a substitution is left visible to the scanner,
where Plan 00221's substitution attribution already resolves the inner producer
correctly.

**Why this is the right line**: it is the same fact `git_message_backtick`
encodes — the danger is substitution, not quoting.

### Decision 1a: the heredoc idiom is inert because its DELIMITER is quoted

**Context**: I predicted the repo's own `"$(cat <<'EOF' … EOF)"` message idiom
would survive Decision 1 because its inner producer resolves to the
whitelisted `cat`. **That prediction was wrong**, and the tests caught it —
two of them, before any of this shipped.

Newlines are chain separators, so scanning that value resolves the "command"
before a pipe in the heredoc BODY to a line of English prose, not to `cat`.
That is exactly the Plan 00200 false positive, reintroduced.

**Decision**: recognise the quoted-heredoc value explicitly and treat it as
inert. What makes it safe is not the producer but the QUOTED delimiter — bash
performs no expansion at all inside `<<'EOF'`, so the body is literal text and
only `cat` runs. An unquoted `<<EOF` does expand and is deliberately excluded.

### Decision 2: scope the flag to commands that take a message

**Context**: `-m` means "module" to python and "message" to git.

**Decision**: treat `-m`/`--message` as a message flag only for the commands
that have one. `-F`/`--file` likewise. This is what makes `python -m pytest`
name its real producer again.

## Tasks

### Phase 1: Pin the current behaviour

- [x] ✅ **Task 1.1**: Failing test for the double-quoted substitution bypass
- [x] ✅ **Task 1.2**: Failing test for `python -m <module>` producer naming
- [x] ✅ **Task 1.3**: Passing tests locking the behaviour that must NOT change —
  single-quoted prose stays inert, and the Plan 00200 heredoc case

### Phase 2: Fix

- [x] ✅ **Task 2.1**: Blank only values that cannot execute
- [x] ✅ **Task 2.2**: Scope message-flag interpretation to message-taking commands

### Phase 3: DBF — why did nothing catch this?

- [x] ✅ **Task 3.1**: The fact now lives once, in
  `utils.shell_segmentation.value_can_substitute`. `pipe_blocker` consumes it
  and `git_message_backtick` points at it, so a third handler asks rather than
  re-derives. That module already existed for the identical failure — two
  handlers growing their own scanner and each getting half the rule right
- [x] ✅ **Task 3.2**: Two acceptance tests added — the substituting message and
  the `python -m` naming — so both are exercised against the live daemon

### Phase 4: Verify

- [x] ✅ **Task 4.1**: Full QA suite passes — 20/20
- [x] ✅ **Task 4.2**: Probed the live daemon through the production forwarder:
  5/5, covering both defects and all three must-not-change controls
- [x] ✅ **Task 4.3**: `get_claude_md()` now states where the exemption ends

## Success Criteria

- [x] `git commit -m "$(pytest … | tail -1)"` is blocked
- [x] `git commit -m 'prose with | tail'` is still allowed
- [x] `python -m pytest … | tail` names `pytest` as the producer
- [x] The Plan 00200 heredoc false-positive case still does not fire
- [x] Full QA passes and the daemon restarts RUNNING

All five verified through the production bash forwarder against the live
daemon, not only in unit tests.

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
- Delivered at `75c23bf8` — bypass closed, producer naming fixed, and the
  "double quotes execute" fact given one home in
  `utils.shell_segmentation.value_can_substitute`
