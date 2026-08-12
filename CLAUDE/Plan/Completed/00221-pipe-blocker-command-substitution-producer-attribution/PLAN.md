# Plan 00221: pipe blocker command substitution producer attribution

**Status**: Complete
**Created**: 2026-08-12
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

`pipe_blocker` decides by finding the pipe, then reading the PRODUCER — the
command whose output is being truncated — and checking that producer against
the whitelist/blacklist. Producer extraction takes everything to the left of
the pipe and keeps the last chain segment. That is correct at the top level
and wrong the moment the pipe sits inside a command substitution: the text to
the left then begins with the OUTER command, so the outer command name is
what gets classified.

The consequence is a laundering route. `echo $(pytest tests/ | head -1)` is
ALLOWED, because the producer resolves to `echo`, which is whitelisted for the
obvious reason that echoing is cheap. The expensive command is `pytest`, and
it is the one whose output is being thrown away. Any expensive command can be
wrapped this way, and nesting (`echo $(echo $(... | head -1))`) hides it
further. Verified against the live daemon through the production forwarder
before this plan was written.

This is an ATTRIBUTION defect, not a detection defect — the pipe is seen in
every case. Two of the four substitution shapes already deny, but by accident:
`FOO="$(pytest ... | head -1)"` denies because `FOO="$(pytest` happens not to
match any whitelist entry, not because anything understood the substitution.
Fixing attribution therefore also corrects those messages, which currently
name the wrong producer.

Implementing that surfaced two more bypasses with the SAME root cause — the
handler asked its questions of the command as a whole rather than of each
pipe — so the scope was widened from substitution to per-pipe evaluation:

- only the FIRST `| tail`/`| head` was ever classified, so a cheap first pipe
  shadowed an expensive second one and prefixing anything with
  `git log | head -1 &&` laundered it, no substitution required
- the `tail -f` / `head -c` exemptions were searched across the whole command,
  so an unrelated `&& tail -f /dev/null` anywhere in it disabled the handler

Splitting these into a separate plan was rejected: one root cause, one fix,
one guard. A guard that covered substitution but not shadowing would have
left the cheaper bypass open while looking complete.

## Goals

- Attribute a piped producer to the command inside the innermost command
  substitution containing the pipe, for both `$( )` and backtick forms
- Judge EVERY pipe in a command on its own producer and its own consumer, so
  neither a cheap earlier pipe nor an unrelated `tail -f` grants cover
- Keep a whitelisted INNER producer allowed, so correct attribution adds no
  gratuitous noise (`echo $(git log --format=%H | head -1)` stays allowed)
- Leave single-quoted, non-substituting text inert, since no command runs
- Add a guard that fails when a new substitution shape is left unclassified,
  so this class cannot silently reappear

## Non-Goals

- No general shell parser: this stays lexical, consistent with the existing
  quote-aware segmentation
- No change to the prose/heredoc sanity-check added in Plan 00209
- No broad whitelist review. One entry (`pgrep`) is added, because correcting
  the attribution is what made its absence observable at all — see Task 5.3.
  Any other whitelist gap this fix surfaces is a separate decision.

## Context & Background

The user's decision on the trade-off, given explicitly: fail closed. A newly
visible producer that is not whitelisted will now block, and the remedy is the
documented `extra_whitelist` entry. A silent bypass is not an acceptable price
for avoiding that friction.

DBF: the guard that should have caught this is the evasion-classification
suite, which pins command RESPELLINGS (`git -C`, path-qualified binaries) for
handlers that match a command name. `pipe_blocker` is the one handler that
does not merely match a name — it EXTRACTS one — and no guard covered the
extraction being pointed at the wrong text.

## Tasks

### Phase 1: Pin the defect

- [x] ✅ **Task 1.1**: Probe all substitution shapes through the production
  forwarder and record which are allowed
- [x] ✅ **Task 1.2**: Write failing tests for the laundering shapes and for
  the whitelisted-inner-producer case that must NOT regress

### Phase 2: Correct the attribution

- [x] ✅ **Task 2.1**: Resolve the innermost substitution span containing the
  pipe and extract the producer from within it
- [x] ✅ **Task 2.2**: Keep single-quoted (non-substituting) text inert
- [x] ✅ **Task 2.3**: Update `get_claude_md()` so the guidance states that a
  pipe inside `$( )` is attributed to the inner command

### Phase 3: Per-pipe evaluation (scope widened, same root cause)

- [x] ✅ **Task 3.1**: Judge every pipe, so a cheap earlier pipe cannot shadow
  an expensive later one
- [x] ✅ **Task 3.2**: Scope the `tail -f` / `head -c` exemptions to the
  consumer of the pipe being judged
- [x] ✅ **Task 3.3**: Report the OFFENDING producer in the block reason, not
  the first pipe's

### Phase 4: Guard the class

- [x] ✅ **Task 4.1**: Table-driven guard over every substitution shape, run
  twice — expensive producer must deny, whitelisted producer must allow
- [x] ✅ **Task 4.2**: Acceptance tests for laundering, shadowing, and the
  over-correction control

### Phase 5: Verify

- [x] ✅ **Task 5.1**: Full QA suite passes
- [x] ✅ **Task 5.2**: Daemon restarts RUNNING and the probe is re-run against
  the live daemon through the production forwarder
- [x] ✅ **Task 5.3**: Whitelist `pgrep` — correcting the attribution exposed
  that it was missing, since the canonical idiom
  `ps -o etime= -p $(pgrep -f x | head -1)` had been passing under the OUTER
  `ps` rather than on its own merits

## Success Criteria

- [x] `echo $(pytest tests/ | head -1)` is DENIED, naming `pytest` as the
  expensive producer
- [x] `echo $(git log --format=%H | head -1)` remains ALLOWED
- [x] Nested substitution resolves to the innermost producer
- [x] Single-quoted inert text is unaffected
- [x] `git log | head -2 && pytest tests/ | head -1` is DENIED on the pytest
  half; an all-cheap multi-pipe command stays ALLOWED
- [x] A genuine `| tail -f` / `| head -c` pipe remains exempt while an
  unrelated one elsewhere in the command exempts nothing
- [x] Full QA passes and the daemon restarts RUNNING

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00221-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Defect pinned by probe against the live daemon before any code change
- Delivered in f167d9fa, alongside Plans 00219 and 00220: `CLAUDE/Plan/README.md`
  and `.claude/HOOKS-DAEMON.md` are shared index/generated artifacts, so
  splitting the plans across commits would have broken `row-folder-bijection`
  or `terminal-state-atomic` in whichever landed first
