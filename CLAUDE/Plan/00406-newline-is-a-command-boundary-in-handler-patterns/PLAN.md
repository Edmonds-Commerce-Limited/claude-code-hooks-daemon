# Plan 00406: newline is a command boundary in handler patterns

**Status**: Not Started
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

- [ ] ⬜ **Task 1.1**: Decide whether `SUBCOMMAND_SEPARATOR_CHARS` gains `\n`
  or whether a second constant is introduced beside it. Every current consumer
  wants the newline excluded, which argues for changing the one constant — but
  it is public and named for SUBCOMMAND separators, so the choice needs stating
  rather than assuming. Whichever wins, a test asserts the constant's contents,
  so the next reader learns the boundary set from a test.

### Phase 2: The sites

- [ ] ⬜ **Task 2.1**: `destructive_git` — push-force and update-ref. Both
  already read through `get_bash_command`. `_scan_target`'s docstring already
  diagnoses this class for the heredoc route and answers it with
  `strip_inert_spans`; it needs to say that a plain multi-line command is a
  third route that blanking does not reach.
- [ ] ⬜ **Task 2.2**: `ancestry_preserving_merge`. Its `_SEGMENT` comment
  claims a segment "cannot leak a match across commands" and names only
  `;`/`&&`/`|`; it has to change with the fix.
- [ ] ⬜ **Task 2.3**: `daemon_location_guard`, in the order above: reader
  first, then the gap. Its comment makes the same claim and gets the same
  treatment.

### Phase 3: Stopping the class recurring

- [ ] ⬜ **Task 3.1**: A test that FAILS if a new handler pattern can judge
  across a newline — the generic form of the four cases, so the fifth site is
  caught when it is written rather than when someone trips over it. The `&&`
  control is the shape to encode: the same two commands, two spellings, one
  verdict.

## Success Criteria

- [ ] ⬜ Each of the four denials above is gone, asserted by a test naming the
  real command that should never have been denied.
- [ ] ⬜ Each handler still denies the genuine one-line form, and still denies
  the line-continuation spelling — the direction Plan 00405 N7 closed, which
  this work must not reopen.
- [ ] ⬜ No comment in the tree still claims a boundary holds while naming only
  `;`, `&` and `|`.
- [ ] ⬜ Full QA passes and CI is green.
- [ ] ⬜ Release-bound consequences are in `CLAUDE/UPGRADES/UNRELEASED/` before
  the status flips.

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
