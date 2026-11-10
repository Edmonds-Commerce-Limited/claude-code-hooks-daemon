# Plan 00596: destructive git printed text captured or formatted

**Status**: In Progress
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

- [ ] ⬜ **Task 1.1**: (a) a print-only substitution captured into an assignment value or a
  printing command's argument is data; RED tests both ways (the executing twins deny)
- [ ] ⬜ **Task 1.2**: (b) text formatters (`fold`, `fmt`, `tr`, `cut`, `column`, `nl`,
  `expand`, `unexpand`, `paste`, `rev`, `tac`) join the inert stage allowlist; RED tests
- [ ] ⬜ **Task 1.3**: release note

### Phase 2: Delivery

- [ ] ⬜ **Task 2.1**: independent adversarial review, merge, main CI green, close #197

## Success Criteria

- [ ] Reproductions 1, 2 and 4 in #197 are allowed; the `| sh`, `| bash`, `eval`,
  command-position and unknown-receiver twins still deny
- [ ] No existing destructive_git deny test changes verdict
- [ ] Release-bound consequences in the holding area: a release note in
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/`

## Delivery & Milestones

- <!-- delivery commit hash -->
