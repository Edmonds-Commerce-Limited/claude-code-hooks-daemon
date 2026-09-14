# Plan 00406: newline is a command boundary in handler patterns

**Status**: In Progress
**Created**: 2026-09-14
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Direct

## Overview

Four blocking handlers match a RAW multi-line Bash command with a negated
separator class that omits `\n` (`SUBCOMMAND_SEPARATOR_CHARS` is `";&|"`), or
with a `\s+` sitting in front of one. Both let a pattern step past the end of
its own command and judge the NEXT line, so an unrelated command is denied.

Every case has the same control: joining the two lines with `&&` instead of a
newline reverses the verdict. Two spellings of one shell structure disagreeing
is a fact about the implementation, never about the policy, which is what makes
each of these a defect rather than a tuning preference.

Graduated from [Plan 00405](../Completed/00405-niggles-ledger-eleven/PLAN.md) N8. Its N6
fixed the first instance found (`plan_number_helper`) and its N7 fixed the
opposite-direction defect the survey turned up — a mid-token line continuation
that evaded every guard. This plan is the remaining false positives.

## The four sites (verified against each handler's own `matches()`)

| site                         | a denial nobody should get                                                         |
| ---------------------------- | ---------------------------------------------------------------------------------- |
| `destructive_git` push-force | `git push origin main` ⏎ `grep -f patterns.txt notes.txt` → denied as a force push |
| `destructive_git` update-ref | `git update-ref refs/heads/backup HEAD` ⏎ `git branch -d refs/heads/old` → denied  |
| `ancestry_preserving_merge`  | `git merge origin/main` ⏎ `echo --squash is what we avoid` → denied                |
| `daemon_location_guard`      | bare `cd` ⏎ `.claude/hooks-daemon/bin/hooks-daemon status` → denied                |

The push-force row is the most reachable: a `git push` on one line and any later
line carrying a `-f` flag is enough, and the `-f` there is `grep`'s. The
update-ref row denies `git branch -d`, the SAFE delete this project's own rules
table prescribes instead of `-D`. The `cd` row denies precisely what its own
deny message tells the reader to do instead.

## Goals

- A pattern in a blocking handler cannot judge text belonging to a different
  command, whichever separator spells the boundary.
- The fix does not open the one newline that is NOT a boundary: a `\<newline>`
  line continuation, which genuinely joins two lines into one command.
- The comments that assert the boundary holds say something true afterwards.

## Non-Goals

- Rewriting these handlers onto a shell parser. The boundary set is the defect;
  the matching approach is not in question here.
- `compile_command_name_pattern`. It crosses newlines, but its contract is a
  caller-supplied single segment and a newline is itself a segment separator,
  so a correct caller never presents one. Verified, and recorded so the next
  person who greps for this shape does not re-derive it.
- `merge_to_main_approval`. Uses the same class and is unaffected — verified
  rather than assumed.

## The ordering constraint

`daemon_location_guard` reads `tool_input` directly in `matches()`, so it never
receives the line-continuation normalisation `get_bash_command` performs. It
must be routed through that reader BEFORE its whitespace gap is tightened.
Tightening first converts its false positive into a hole — the same trap Plan
00405 N6 hit, where a naive fix would have stopped
`cd \<newline>.claude/hooks-daemon` matching at all.

`destructive_git` and `ancestry_preserving_merge` already read through
`get_bash_command`, so excluding `\n` from their classes is safe as it stands.

## Tasks

### Phase 1: The shared boundary

- [x] ✅ **Task 1.1**: `SUBCOMMAND_SEPARATOR_CHARS` gains the newline — one
  constant, not a second beside it. **Decided**, with the reason stated: all
  three consumers want the newline excluded, and a newline genuinely IS a
  sub-command separator in shell, so the name stays accurate.

  One detail settled the spelling, and it is not obvious: the constant is
  iterated character by character by its own parametrised test as well as
  interpolated into regex classes. The escape form `r";&|\n\r"` is equivalent
  inside a class but would hand that test a `\` and an `n` as two bogus
  separators, so the constant holds REAL characters. Both properties are now
  asserted, so the boundary set is learnable from a test rather than inferred.

### Phase 2: The sites

- [x] ✅ **Task 2.1**: `destructive_git` — push-force and update-ref. Both read
  through `get_bash_command` already, so the shared constant fixed them as it
  stood. `update-ref` needed a second edit the class alone could not make: its
  `\s+` gap matches a newline, so `git update-ref` ⏎ `-d refs/heads/x` would
  still have read as one call; the gap is now `[ \t]+`.

  **One deliberate behaviour change, found by a failing test rather than
  predicted.** `test_an_unquoted_heredoc_body_is_still_scanned` asserted that
  `git commit -F - <<EOF && git push origin main` with `--force` in the BODY is
  a force push. It is not: bash feeds that `--force` to `git commit -F -` as
  the message, so the push beside it never carried it — a cross-line
  attribution, which is this plan's whole subject. The guard it exists to
  protect is untouched: an unquoted body is still scanned rather than blanked,
  so a force push written inside it still matches, including the `$(...)`
  spelling that genuinely executes. Both are now asserted.

- [x] ✅ **Task 2.2**: `ancestry_preserving_merge`. Fixed by the shared
  constant. Its `_SEGMENT` comment claimed a segment "cannot leak a match
  across commands" while naming only `;`/`&&`/`|` — a claim that was false for
  the commonest spelling of all — and now records what was wrong and the `&&`
  control that proved it.

- [x] ✅ **Task 2.3**: `daemon_location_guard`, in the order above: reader
  first, then the gap, and its comment given the same treatment.

  **The ordering constraint was not theoretical — the reproduction proved it
  before any fix landed.** `cd \<newline>.claude/hooks-daemon` was ALREADY
  unmatched on the unfixed tree, because this handler read `tool_input`
  directly and so never saw the line-continuation normalisation. It carried
  both defects at once: a false positive across a real newline and an open hole
  on a continuation. Tightening the gap first would have made the hole
  permanent and looked like a clean fix.

  Verified against the live daemon, both directions: the two-line form now runs
  (exit 127 from the shell, no hook denial), and `cd .claude/hooks-daemon` is
  still denied by R-DAEMON-DIR-CD.

### Phase 3: Stopping the class recurring

- [x] ✅ **Task 3.1**: `tests/unit/handlers/pre_tool_use/test_newline_is_a_command_boundary.py`
  encodes the class, not the four instances. Each row supplies two innocent
  lines and the genuine one-line violation, and the file asserts three things
  per row: the newline pair is not judged as one command, the `&&` spelling
  returns the SAME verdict, and the genuine form is still denied. A separate
  class pins the continuation direction shut so a future "stop matching
  newlines" fix cannot reopen Plan 00405 N7.

  The `&&` control is the part worth keeping: it turns "this block feels wrong"
  into an implementation fact, and it is what a fifth site will fail on.

## Success Criteria

- [x] ✅ Each of the four denials above is gone, asserted by a test naming the
  real command that should never have been denied, plus the `&&` control that
  must agree with it.
- [x] ✅ Each handler still denies the genuine one-line form, and still denies
  the line-continuation spelling — the direction Plan 00405 N7 closed, which
  this work must not reopen. `daemon_location_guard` did not satisfy the second
  half BEFORE this plan and does now, which is the ordering constraint paying
  off rather than a bonus.
- [x] ✅ No comment in the tree still claims a boundary holds while naming only
  `;`, `&` and `|`. Four were found and corrected — the two site comments, the
  push-force pattern's, and `_scan_target`'s docstring, which stated the
  opposite of the truth once the class changed. `merge_to_main_approval`'s was
  updated too: it is unaffected in OUTCOME (it captures a target rather than
  denying on a flag) but shares the constant.
- [ ] ⬜ Full QA passes and CI is green.
- [x] ✅ Release-bound consequences are in `CLAUDE/UPGRADES/UNRELEASED/` before
  the status flips: `release-notes/47-a-newline-ends-the-command-being-judged.md`,
  which names all four denials and the one deliberate heredoc behaviour change.

## Delivery & Milestones

- Graduated from Plan 00405 N8 rather than fixed in the ledger: four blocking
  handlers, patterns whose loosening has evasion consequences, and an ordering
  constraint between the two halves of one fix.
- Dedupe scout checked 23 live plans and found no overlap. Prior art it named:
  Plan 00382 fixed a DIFFERENT flag-boundary defect in `destructive_git`'s `-f`
  alternative; Plan 00227 fixed `plan_number_helper` matching text rather than
  commands; Plan 00207 built `ancestry_preserving_merge`. The scout reported
  00207 used the `command_evasion` grammar "to avoid this class" — half right,
  and worth knowing: the handler uses that grammar for the `git` invocation
  prefix only and hand-rolls `_SEGMENT` for the boundary, which is where the
  defect is.
- Every verdict here was taken from the handler's own `matches()`, not from a
  regex re-typed into a probe. The first `cd`-guard check did re-type it, which
  proves only what the pattern does; the handler was then checked separately
  and agreed.
