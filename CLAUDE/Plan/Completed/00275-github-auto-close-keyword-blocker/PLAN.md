# Plan 00275: github auto close keyword blocker

**Status**: Complete
**Created**: 2026-08-26
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

A new PreToolUse safety handler, `github_auto_close_keywords`, that denies
`git commit` (and `git merge -m` / `git tag -m`) commands whose message
contains a GitHub auto-closing keyword reference such as "Fixes #123".
These keywords auto-close issues/PRs when the commit reaches the default
branch, the behaviour cannot be disabled repository-side, and agents write
them accidentally. Blocking at source is the only reliable guard.

The handler scans the full Bash command string (destructive_git precedent),
and additionally reads the file referenced by `-F`/`--file=` so the scratch
file route is covered. The deny message quotes the matched span and shows
non-closing rewrites ("Addresses #123", "Refs #123", "See #123"). A
`MUST_AUTO_CLOSE_BECAUSE="reason"` escape hatch keeps a genuinely-wanted
auto-close expressible.

## Goals

- Deny commit messages carrying keyword+reference forms, case-insensitively,
  across all GitHub-documented keywords and reference syntaxes
- Cover inline `-m`/`--message` (all quoting) AND `-F`/`--file` scratch files
- Ship enabled by default with `mode: warn|block` (default block)

## Non-Goals

- No matching of the keyword alone ("fixes the race" must not match)
- No coverage of `gh issue close` (a deliberate, different act)
- No PR-body scanning (`gh pr create --body`) — commits are the accident path

## Context & Background

Keyword grammar verified against docs.github.com "Linking a pull request to
an issue" (fetched 2026-08-26): keywords close/closes/closed/fix/fixes/fixed/
resolve/resolves/resolved, optionally followed by a colon, case-insensitive,
followed by `#N`, `owner/repo#N`, `GH-N`, or a full issue URL.

## Tasks

### Phase 1: TDD Implementation

- [x] ✅ **Task 1.1**: Test file first — keyword×reference matrix, negatives,
  -F file reading, escape hatch, warn mode, multi -m, case-insensitivity
- [x] ✅ **Task 1.2**: Implement handler (PreToolUseHandlerBase, priority 18
  safety band, non-terminal like git_stash so warn mode cannot shadow chain)
- [x] ✅ **Task 1.3**: get_claude_md() guidance + get_acceptance_tests()

### Phase 2: Registration & Docs

- [x] ✅ **Task 2.1**: HandlerID + Priority constants, pre_tool_use import
- [x] ✅ **Task 2.2**: Config wiring — init_config.py default (enabled: true),
  .claude/hooks-daemon.yaml, .claude/hooks-daemon.yaml.example
- [x] ✅ **Task 2.3**: docs/guides/HANDLER_REFERENCE.md entry
- [x] ✅ **Task 2.4**: config-changes UNRELEASED manifest entry
  (recommended: true, notes the unusual enabled-by-default choice)

### Phase 3: Verification

- [x] ✅ **Task 3.1**: Integration suites pass (response validation, guidance
  coverage, evasion classification, dogfooding config)
- [x] ✅ **Task 3.2**: Full QA green: `./scripts/qa/llm_qa.py all` (24/24)

### Phase 4: Landing (main session)

- [x] ✅ **Task 4.1**: Merged `--no-ff` at `2bdafe05`, dogfood daemon
  restarted RUNNING, QA 24/24 on main, live socket probe confirmed the deny
  (the handler blocked the probe command itself); archive move + README
  update in this commit

## Technical Decisions

### Decision 1: merge/tag message scope

`git merge -m` and `git tag -m` ARE covered: a merge commit lands on the
default branch directly and closes referenced issues; annotated tag messages
are cheap to cover with the same subcommand alternation and the identical
rewrite applies. `-t`/`--template` is ignored (not a message source).

### Decision 2: escape hatch

`MUST_AUTO_CLOSE_BECAUSE="reason"; git commit ...` follows the established
git_stash/ancestry_preserving_merge convention — consequences stay inside
the repository/GitHub project, so an agent-typed justification is acceptable.

### Decision 3: -F file handling

The file path is resolved as given (absolute) or against the hook input
`cwd`, falling back to the project root. Missing/unreadable file = allow
(the commit will fail on its own; FAIL FAST belongs to git here).

## Success Criteria

- [x] Every keyword×reference form denied; keyword-alone and bare `#N` allowed
- [x] `-F` scratch-file route covered, missing file allowed
- [x] Warn mode allows with advisory context; escape hatch allows
- [x] All QA checks passing in the worktree (24/24)

## Delivery & Milestones

- Handler + tests + registration delivered on worktree branch (see JOURNAL
  for commit hashes)
