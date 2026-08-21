# Plan 00263: An escaped quote makes the bash tokeniser hallucinate a write target

**Status**: Complete
**Created**: 2026-08-20
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

`get_bash_write_targets` tokenised a Bash command with
`shlex.shlex(text, posix=False, punctuation_chars=True)`. In non-POSIX mode
shlex does **not** process backslash escapes, so a `\"` inside a double-quoted
argument *terminates* the quote instead of escaping it. Everything after it was
then treated as live shell — including a redirect that was only ever data
inside a quoted string.

The result was a **phantom write target**: a path the accessor reported as
written by a command that never wrote it.

**Fixed by switching the lexer to `posix=True`**, which is what bash itself
does with an escaped quote. The past tense above is deliberate — this document
describes the defect as it was, and the code no longer behaves this way.

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

- No write verb or operator appearing inside a quoted argument — a redirect,
  `tee`, or a copy verb — is ever reported as a write target, regardless of
  escaped quotes in that argument.
- A path whose name contains a backslash-escaped space is reported as the single
  file bash writes, not split into fragments.
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
- **Conditional execution** — found while verifying this fix, and confirmed
  PRE-EXISTING against both tokenisers rather than caused by it.
  `cp a b || echo x > f` names `f` even when `cp` succeeds and the branch never
  runs; `false && echo x > f` is the mirror. The reason it is not fixed here is
  not that it belongs to another plan: learning the exit code means EXECUTING
  the command, which an accessor running inside a PreToolUse dispatch must never
  do. Dropping conditional branches instead would trade this overclaim for a
  MISS on every legitimate `&& >` write, which is a common deliberate shape.
  Documenting the limit is the better trade, so it sits with the accessor's
  other conservatism limits (the `$VAR` and glob declines). Both denying linters
  check `Path.exists()` first, which is the same thin protection the
  escaped-quote phantom had — so this is recorded, not dismissed.

## Context & Background

The first diagnosis of this defect, written from two hand-built examples, was
**wrong on both counts** and is corrected here. It claimed the damaging shape
needed a line break inside the quoted argument, and that only redirects were
affected. Running candidate shapes through a real shell and diffing against the
accessor showed neither holds. Recording the correction rather than quietly
replacing it: the original reasoning was an inference from two data points, and
the measurement is what settled it.

Measured against the shipped accessor, with a real `bash` as the authority:

| command shape                                        | reported target             | bash writes  |
| ---------------------------------------------------- | --------------------------- | ------------ |
| escaped quote, then a redirect, path then a space    | `.../phantom.py`            | nothing      |
| escaped quote, then a redirect, path at end of value | `.../phantom.py\"}` — inert | nothing      |
| escaped quote, then `tee`                            | `.../phantom.py\`, `loudly` | nothing      |
| escaped quote, then `cp`                             | `next`                      | nothing      |
| `> sp\ ace.txt` (backslash-escaped space)            | `sp\` — and MISSES the file | `sp ace.txt` |
| multi-line double-quoted arg mentioning a redirect   | none                        | nothing      |
| single-quoted / plain double-quoted prose            | none                        | nothing      |

Three corrections to the original account:

1. **Line breaks are irrelevant.** Both multi-line shapes came back clean. What
   decides whether a phantom is *clean* or *malformed* is only whether the path
   token happens to be followed by whitespace.
2. **The blast radius is wider than redirects.** Once the quote breaks, `tee`
   and the copy verbs consume trailing operands, so a run of ordinary prose
   words becomes a list of "written files" — `loudly` is an adverb, and `next`
   is a preposition. A phantom that is a bare plausible word is *worse* than a
   malformed one: a malformed path fails `Path.exists()` and a plausible one
   need not.
3. **It also causes the opposite failure.** `sp\ ace.txt` is one path to bash;
   unprocessed escapes split it, so the accessor named a fragment nothing writes
   **and missed the file that was written**. One defect, both failure directions.

## Tasks

### Phase 1: Pin the defect

- [x] ✅ **Task 1.1**: Add failing tests for the phantom shapes, in
  `tests/unit/core/test_bash_write_targets.py::TestAnEscapedQuoteDoesNotExposeProse`
  - [x] ✅ Escaped quote exposing a redirect, `tee`, and a copy verb
  - [x] ✅ Backslash-escaped space in a genuine path (the MISS direction)
  - [x] ✅ Assert the SAFE shapes stay safe (single quotes, plain double quotes)
- [x] ✅ **Task 1.2**: Extend the differential harness with these cases and
  confirm the real shell writes nothing, so the expectation is measured rather
  than asserted from belief. All four failed as OVERCLAIM before the fix

### Phase 2: Fix

- [x] ✅ **Task 2.1**: Correct quote tracking so an escaped quote does not
  terminate a double-quoted region. `posix=True` chosen over pre-processing —
  measured, not assumed: it is what bash itself does, and the alternative meant
  hand-rolling escape rules the lexer already implements correctly
- [x] ✅ **Task 2.2**: Re-run the full differential harness; it stayed exact
- [x] ✅ **Task 2.3**: Remove the now-redundant `strip("'\"")` in
  `_resolve_write_target`. POSIX mode strips quotes that are SYNTAX; stripping
  again would corrupt a path whose name genuinely contains a quote character

### Phase 3: Verify

- [x] ✅ **Task 3.1**: Full QA (12,876 passed, coverage 95.14% against a 95.00
  gate), daemon restarted RUNNING with zero load errors
- [x] ✅ **Task 3.2**: Live probe over the production socket, BOTH halves. The
  original false-denial shape now returns `{}` (allow); the control — a genuine
  `cat >` authoring the same broken file — still returns `decision: block` with
  the real `SyntaxError`. The control is the half that matters: an allow alone
  would be equally consistent with a disabled or broken handler
- [x] ✅ **Task 3.3**: Regression-probed the OTHER consumers live —
  `markdown_organization` still denies a memory-path write (tilde expansion
  intact), and the Decision 5f split still holds: `cp` INTO the broken file is
  allowed while `tee` INTO the same file is denied

## Dependencies

- Follows: Plan 00260 (Completed), which introduced the denying consumers that
  make this consequential and recorded Decision 5f, the principle it violates.

## Success Criteria

- [x] No write verb inside a quoted argument yields a write target — pinned by
  unit tests for the escaped-quote redirect, `tee` and copy-verb shapes, and by
  a generated differential matrix crossing five quoting styles with all seven
  write mechanisms.
- [x] The differential harness passes exactly, with the new cases included, and
  is proven able to FAIL: reverting the one-flag fix produces 12 failures.
- [x] A backslash-escaped space names the single file bash writes, closing the
  mirror-image miss.
- [x] Authoring routes still detected and relocation routes still excluded,
  confirmed live as well as in tests.
- [x] Full QA passes (95.14% coverage against the 95.00 gate) and the daemon
  restarts RUNNING.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00263-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Found live during Plan 00260's closing client-mode verification.
- Fix, regression tests and the class-covering differential matrix delivered at
  `0e99b260`.
- Verified live over the production socket after a deliberate daemon restart:
  the phantom shape allows, the genuine-authoring control still denies, and
  both other consumers of the accessor were regression-probed.
