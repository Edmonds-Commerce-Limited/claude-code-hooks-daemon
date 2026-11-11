# Plan 00596: destructive git printed text captured or formatted

**Status**: Complete (2026-11-11)
**Created**: 2026-11-10
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #197

## Overview

`destructive_git` denies commands that only PRINT the words of a destructive git command,
when the printing command's output is captured by a substitution or piped to a text
formatter (GitHub #197). Reported shapes, none of which runs git:

- **(a) A capture.** `msg=$(printf '%s\n' 'then git push origin --delete b'); echo "$msg"`,
  and `echo "$(printf …)"`, are denied with "a command or process substitution can run a
  delete this reading misses". The substitution's output becomes a variable's value or an
  `echo` argument; nothing executes it.
- **(b) A formatter.** `printf '…git push origin --delete b' | fold -w 40` is denied with "no
  git push --delete could be read". `fold`, `fmt`, `tr` and similar only reformat text,
  yet they are missing from the inert pipeline-stage allowlist
  (`utils/command_position.py`, `is_inert_pipeline_stage`). The same happens for
  `printf '…git reset --hard' | fold`, so it is the shared scan, not one rule.

This is the Plan 00478 Phase 0 (#170) family: git text that provably stays data is no git
command. Text that may be executed keeps its verdict: `| sh`, `| bash`, `| xargs`,
`eval "$(…)"`, a substitution in command position (`$(printf 'git …')`), and a pipe into a
program the guard cannot classify.

## Goals

- (a) A substitution whose output is only assigned to a variable, or passed as an
  argument to a printing command, and whose body only prints, is data.
- (b) Pure text formatters join the inert pipeline-stage allowlist.
- Every executing twin still denies, each pinned by a test.

## Non-Goals

- **(c) A pipe into an arbitrary program**, such as the project messaging CLI in #197. The
  guard cannot tell whether an unknown receiver executes its input. Plan 00478's
  stand-in ruling (Q1) keeps "text that may be executed" denied, so (c) is not changed.

## Tasks

### Phase 1: Fix (TDD)

- [x] ✅ **Task 1.1**: (a) a print-only substitution captured into an assignment value or a
  printing command's argument is data; RED tests both ways (the executing twins deny).
  As shipped, this is a fail-closed allowlist: the capture is data only when every
  segment of the command is an assignment from a print-only substitution, an
  `echo`/`printf` (not `-v`) with no redirect, or a pure-formatter pipe stage.
- [x] ✅ **Task 1.2**: (b) text formatters (`fold`, `fmt`, `nl`, `expand`, `unexpand`,
  `paste`, `rev`, `tac`) join `DATA_SINKS`; `tr`, `cut` and `column` were already there
- [x] ✅ **Task 1.3**: release note 052

### Phase 2: Delivery

- [x] ✅ **Task 2.1**: independent adversarial review, merge, main CI green, close #197.
  Round 1 approved with two suggestions. Round 2 found the fix for them over-blocking
  ordinary commands. Round 3 found 18 commands that ran written text getting through:
  the relaxation removed a deny whenever a check that can only CONFIRM a run returned
  false. The fail-closed redesign then passed an independent check over 362 probes.

## Success Criteria

- [x] Reproductions 1, 2 and 4 in #197 are allowed; the `| sh`, `| bash`, `eval`,
  command-position and unknown-receiver twins still deny
- [x] No existing destructive_git deny test changes verdict. Against main, 8 commands go
  from deny to allow (all #197 shapes) and 29 go from allow to deny (all run written text)
- [x] Release-bound consequences in the holding area: release note
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/052-destructive-git-printed-text-captured-or-formatted.md`

## Follow-ups (not done here)

From the final verification (`subagent-reports/`); none lets a destructive command run:

- `echo "$m" | tee 40`, `| uniq -c 5` and `| less -o` write a file but count as
  print-only (`_FORMATTER_OPTION` accepts a bare number and clustered options). Fix: add
  `tee`, `uniq`, `less` and `more` to `_UNSAFE_PRINTED_SINKS`.
- Already wrong on main and unchanged here:
  - `n='git reset --hard'; echo "$n"` denies, a false positive.
  - `n=git; echo "$n"; $n reset --hard` allows, a missed deny.
  - `echo 'git reset --hard' > s.sh; sh "$x" < s.sh` allows, a missed deny.

## Delivery & Milestones

- Merged at `5638615ac`; main CI run 42936949523 green; GitHub #197 closed.
