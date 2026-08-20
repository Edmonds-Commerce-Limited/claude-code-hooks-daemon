# Plan 00263: An escaped quote makes the bash tokeniser hallucinate a write target

**Status**: Not Started
**Created**: 2026-08-20
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

`get_bash_write_targets` tokenises a Bash command with
`shlex.shlex(text, posix=False, punctuation_chars=True)`. In non-POSIX mode
shlex does **not** process backslash escapes, so a `\"` inside a double-quoted
argument *terminates* the quote instead of escaping it. Everything after it is
then treated as live shell — including a redirect that was only ever data
inside a quoted string.

The result is a **phantom write target**: a path the accessor reports as
written by a command that never wrote it.

This was found live, not by inspection. Immediately after Plan 00260 Task 3.5
wired the two linters to Bash-authored files, a command was DENIED for a file
it had not authored. The command built a JSON probe payload whose body
contained the text `cat > untracked/cmp-broken.py <<'EOF'`; that file happened
to exist and happened to contain deliberately-invalid Python, so `lint_on_edit`
reported a real `SyntaxError` about a real file — while attributing it to a
command that had only *mentioned* the path.

## Why this matters more than it did last week

The phantom behaviour is **pre-existing** in the accessor. What changed is its
consequence. Before Task 3.5 the only consumer was `markdown_organization`, a
LOCATION guard that denies solely for memory-directory paths — a phantom had to
land inside the memory directory to matter. Two DENYING linters now consume the
same accessor, so a phantom in *any* lintable path can produce a false denial.

That is precisely the hazard Decision 5f of Plan 00260 names: **a DENYING
handler must never act on a file the command did not write.** The decision is
sound; this is a gap in the accessor beneath it.

## Severity, stated honestly

A false denial here is **recoverable and non-destructive**. The write has
already landed when a PostToolUse handler runs, so the denial is a failure
report rather than a rollback, and the agent reads a genuine lint error about a
genuine file. Nothing is lost or corrupted.

It also needs a coincidence to bite: the command must mention a redirect inside
a quoted argument, the named path must **exist**, it must carry a lintable
extension, and it must fail lint. The `Path.exists()` check in both handlers is
what keeps the common case harmless.

Against that: it was hit within an hour of shipping, by ordinary work.

## Goals

- A redirect appearing inside a quoted argument is never reported as a write
  target, regardless of escaped quotes or line breaks in that argument.
- The differential harness still passes exactly, and gains cases for this shape
  so the fix is measured against a real shell rather than belief.
- No regression for the routes Plan 00260 established: authoring routes still
  detected, relocation routes still excluded.

## Non-Goals

- Rewriting the accessor, or moving to a full shell parser.
- Revisiting Decision 5f's authoring/relocation split, which is unaffected.
- The heredoc-body phantom of Decision 5e, which is a DIFFERENT and deliberate
  superset: `include_heredoc_bodies=True` is documented as inherently
  over-broad and is not used by the denying handlers.

## Context & Background

Measured against the shipped accessor:

| command shape                                        | reported target                        |
| ---------------------------------------------------- | -------------------------------------- |
| multi-line quoted arg containing an escaped redirect | `/workspace/untracked/phantom.py`      |
| single-line equivalent                               | `.../phantom.py\"}` — malformed, inert |
| single-quoted `echo` containing a redirect           | none                                   |
| plain double-quoted `echo`, single line              | none                                   |
| a genuine `cat > real.py`                            | `/workspace/real.py`                   |

Only the first is dangerous: it yields a **clean, plausible path** that can
exist on disk. The single-line variant produces a malformed path that no
`exists()` check will match, which is why this went unnoticed — the damaging
shape needs a line break inside the quoted argument.

## Tasks

### Phase 1: Pin the defect

- [ ] ⬜ **Task 1.1**: Add failing tests for the phantom shapes
  - [ ] ⬜ Multi-line double-quoted argument containing a redirect
  - [ ] ⬜ Escaped-quote sequence inside a double-quoted argument
  - [ ] ⬜ Assert the SAFE shapes stay safe (single quotes, plain double quotes)
- [ ] ⬜ **Task 1.2**: Extend the differential harness with these cases and
  confirm the real shell writes nothing, so the expectation is measured rather
  than asserted from belief

### Phase 2: Fix

- [ ] ⬜ **Task 2.1**: Correct quote tracking so an escaped quote does not
  terminate a double-quoted region. Evaluate `posix=True` versus targeted
  pre-processing; `posix=True` changes token content (strips quotes, processes
  escapes) and so ripples into `_write_target_tokens` — measure before choosing
- [ ] ⬜ **Task 2.2**: Re-run the full differential harness; it must stay exact

### Phase 3: Verify

- [ ] ⬜ **Task 3.1**: Full QA, daemon restart RUNNING
- [ ] ⬜ **Task 3.2**: Live probe — reproduce the original false denial and
  confirm it no longer fires, and that genuine denials still do

## Dependencies

- Follows: Plan 00260 (Completed), which introduced the denying consumers that
  make this consequential and recorded Decision 5f, the principle it violates.

## Success Criteria

- [ ] A redirect inside a quoted argument yields no write target, pinned by
  tests for both the multi-line and escaped-quote shapes.
- [ ] The differential harness passes exactly, with the new cases included.
- [ ] Authoring routes still detected and relocation routes still excluded.
- [ ] Full QA passes and the daemon restarts RUNNING.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00263-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Found live during Plan 00260's closing client-mode verification.
