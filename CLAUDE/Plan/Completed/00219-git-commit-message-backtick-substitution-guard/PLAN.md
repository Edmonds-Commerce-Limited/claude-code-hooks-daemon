# Plan 00219: git commit message backtick substitution guard

**Status**: Complete
**Created**: 2026-08-12
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Backticks inside a **double-quoted** `git commit -m "..."` are not quoted —
bash performs command substitution. The backticked span is **executed**, and
its stdout replaces the text in the message.

This is not theoretical. It happened in this repo while writing a commit
message that described a handler interaction in backticks. Bash ran the
command, it printed a `fatal:` line to stderr and nothing to stdout, and the
commit landed with the phrase silently deleted from its body. The `fatal:`
read as git rejecting the commit; it was bash running a command nobody asked
it to run. The commit itself succeeded.

Two distinct failure modes, and they need separating because their severity
and their existing coverage differ:

1. **Message corruption** (what happened). Silent, and there is currently
   nothing that detects it — no handler, no QA check, no test.
2. **Unintended execution**. A message describing a destructive command in
   backticks would run it. This is **already covered** for the dangerous
   cases: the blocking handlers match the FULL Bash command string, so
   `destructive_git` / `sed_blocker` / the rest deny it before bash sees it.
   That is the same string-matching that produces the documented
   commit-message false positives, and it is real defence rather than luck.

So the gap worth closing is (1). Treating this plan as a security fix would
overstate it and would risk duplicating protection that already works.

## Context & Background

The corrupting commit is on `main`; its body reads "pipe_blocker now allows ,
so the force-delete form" where a backticked command used to be. It was not
amended, because `git commit --amend` is blocked in this repo — which is
itself part of the argument for a write-time guard: there is no cheap
after-the-fact repair, so the only effective place to catch this is before
the commit runs.

The lesson is recorded in `CLAUDE/development/LESSONS.md` ("Backticks in a
double-quoted `-m` message are executed, not quoted").

## Goals

- Detect an unescaped backtick inside a double-quoted `-m` message and warn
  before the commit runs, naming the substitution that is about to happen.
- Keep single-quoted `-m '...'` completely unaffected — no substitution
  happens there, and backticks are legitimate markdown in that form.

## Non-Goals

- **Re-solving the execution risk.** Already covered by full-command-string
  matching in the existing blocking handlers. Verify that claim rather than
  assume it, but do not build a second layer.
- Blocking. A false positive here denies a commit, which is expensive and
  will get the handler switched off. Advisory unless measurement justifies
  otherwise.
- Parsing shell exhaustively. `$(...)` substitution has the same effect and
  should be considered, but a full shell parser is not warranted.

## Tasks

### Phase 1: Establish the real shape before writing a rule

- [x] ✅ **Task 1.1**: Confirmed against the live daemon through the production
  forwarder: a destructive command inside backticks is DENIED in both quoting
  forms. The execution half is genuinely covered and is not rebuilt here
- [x] ✅ **Task 1.2**: Measured — 120 of 1,736 commit messages contain
  backticks. The inversion matters: a stored message CONTAINING backticks is
  proof of SAFE authoring, because a double-quoted one would have had the span
  consumed by bash. cc7dddc0 contains none for exactly that reason
- [x] ✅ **Task 1.3**: BLOCKING, justified by that measurement — see Decision 1

### Phase 2: Implement

- [x] ✅ **Task 2.1**: TDD'd as `GitMessageBacktickHandler`. Scope narrowed to
  the unescaped BACKTICK form only; `$(...)` is deliberately left alone,
  because unlike a backtick it has a legitimate use in a message
  (`-m "Release $(cat VERSION)"`) and is written deliberately rather than
  by accident. Covers `git tag -m` as well as `git commit -m`, since
  `RELEASING.md` mandates exactly that form for every release
- [x] ✅ **Task 2.2**: Deny reason names both remedies (single quotes, `-F`)
  and states that the commit would otherwise SUCCEED, which is what makes the
  loss silent
- [x] ✅ **Task 2.3**: `get_claude_md()` guidance and two acceptance tests
  (one each direction). The DENY case is deliberately NOT `echo`-wrapped the
  way most blocking tests are — `echo` would itself perform the substitution
  being demonstrated; it is safe unwrapped because the handler denies before
  bash runs

### Phase 3: Verify

- [x] ✅ **Task 3.1**: Full QA, daemon restart RUNNING, and a five-case live
  probe through the production forwarder — double-quoted DENY, single-quoted
  ALLOW, escaped-backtick ALLOW, `git tag -a -m` DENY, plain message ALLOW
- [x] ✅ **Task 3.2**: `config-changes` entry staged for v3.53.0 — the handler
  ships enabled by default, so upgrading projects gain a new block

## Dependencies

- Related: Plan 00209, whose merge is the commit that got corrupted.

## Technical Decisions

### Decision 1: Blocking, not advisory — and the history says so

**Context**: This plan's own Non-Goals argued for advisory, on the grounds
that a false positive denies a commit and an over-eager handler gets switched
off. That caution was right in general and wrong here, and the measurement is
what settled it rather than a preference.

**The measurement**: 120 of 1,736 commit messages in this repo contain
backticks. The naive reading is "7% of commits would have been blocked" — the
opposite of the truth. A stored message containing backticks is *proof it was
authored safely*: had it been double-quoted, bash would have consumed the
backticked span before git ever saw it. The corrupted commit cc7dddc0 contains
no backticks for precisely that reason. So all 120 were single-quoted, `-F`,
or escaped — every one of which this rule permits. It would have fired on
none of them.

**Decision**: Block. The construct it matches — an unescaped backtick inside a
double-quoted git message — has no legitimate use whatsoever: nobody wants
their commit message replaced by a command's stdout. The measured
false-positive rate on real history is zero, and unlike an advisory, a block
prevents the loss rather than narrating it afterwards.

**Scope limit from the same reasoning**: `$(...)` is NOT matched, even though
it substitutes identically. `git commit -m "Release $(cat VERSION)"` is a
legitimate, deliberate use. Backticks in a message are essentially always
markdown that someone forgot to single-quote; `$(...)` is essentially always
intentional. Blocking both would trade a zero false-positive rule for a
non-zero one.

**Date**: 2026-08-12

## Success Criteria

- [x] A double-quoted `-m` containing an unescaped backtick is flagged before
  the commit runs
- [x] Single-quoted `-m` and escaped backticks never fire
- [x] The false-positive rate is measured against this repo's real commit
  history, not asserted
- [x] The execution half is confirmed already-covered, with evidence

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00219-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Defect hit live while committing Plan 00209 follow-up work; lesson recorded
