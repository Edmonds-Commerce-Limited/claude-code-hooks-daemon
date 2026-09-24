# Plan 00458: skip lists match path segments relative to the project

**Status**: In Progress
**Created**: 2026-09-24
**Owner**: dev
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration (worktree, TDD)

## Overview

Several blocking guards skip vendored and generated trees (`venv/`,
`vendor/`, `build/`, `node_modules/` and so on) by testing
`skip_dir in file_path`, a bare substring match on the ABSOLUTE path. So a
directory that only ENDS in one of those names switches the guard off for
everything under it: `myvenv/`, `rebuild/`, `notvendor/`, or a worktree
named `worktree-issue-53-venv/`. The guard fails open, silently: no
decision, no advisory, no log line a user would see. This was found when
14 acceptance DENY probes returned no decision inside that worktree and
passed everywhere else (00422 N20, whose first diagnosis was wrong and is
corrected in the ledger).

The fix already exists for one sibling. `strategies/lint/common.py`
`matches_skip_path` is segment-bounded, and its docstring names this exact
failure. Six other sites never moved onto it:

- `handlers/pre_tool_use/qa_suppression.py:162`
- `handlers/pre_tool_use/comment_changelog.py:316`
- `handlers/pre_tool_use/comment_size.py:280`
- `strategies/security/common.py:23` (security_antipattern)
- `strategies/tdd/common.py:14` (test-directory detection; here the
  mistake is classifying a file as a test when it is not)
- `handlers/pre_tool_use/british_english.py:108` (check directories)

Being segment-bounded is not enough on its own. Matched against the
ABSOLUTE path, a segment-bounded `venv/` still skips every file of a
project that happens to live under a directory named exactly `venv` or
`build`. The match must be made on the path RELATIVE to the project root,
and a file outside the project needs a decision stated per guard.

This is the defect class `CLAUDE/Security/AsymmetricSiblingProtection.md`
describes: one sibling was fixed, and nothing stopped the others from
keeping the defect.

## Goals

- One shared matcher (segment-bounded, applied to the project-relative path)
  used by every skip-list and directory-classification site. There is no
  local substring test left.
- A detector that fails QA if a new substring path test on a skip list
  appears. The detector comes first, per the project's
  defence-before-fix rule.
- Each guard's behaviour on a file OUTSIDE the project root is decided
  explicitly, tested, and recorded.

## Non-Goals

- Changing WHAT is skipped (the lists themselves), unless a list entry
  turns out to need a change for the new matcher.
- The user-configurable `exclude_paths` globs, which are a separate
  mechanism, unless the audit finds the same flaw there.

## Tasks

### Phase 1: TDD in a worktree

- [x] ✅ **Task 1.1**: Audit. Confirm the six sites and search for more:
  any `in file_path`, `in path`, `startswith` or `endswith` test on a
  path against a directory list in handlers, strategies, core and utils.
  List each with the direction in which it fails. See JOURNAL 11:22 and
  the subagent report for the full table.
- [x] ✅ **Task 1.2**: Detector first. Add a QA check (or a semgrep rule, if
  the project routes this class that way) that flags a substring
  membership test between a path variable and a skip/exclude/directory
  list. Show that it fires on the current tree, RED.
  `scripts/qa/check_skip_list_substring.py`; RED on exactly the six sites
  (`d693e13c`).
- [x] ✅ **Task 1.3**: Move the shared matcher to a neutral home (not
  `strategies/lint/`), make it match on the path relative to the project
  root, and put every site on it. Tests per site: `myvenv/`, `rebuild/`
  and `worktree-x-venv/` are NOT skipped; `venv/` and `vendor/` directly
  under the project ARE skipped; a project that lives under a directory
  named `venv` is still guarded. Where the handler has an acceptance
  probe, reproduce the original worktree case.
  `utils/path_segments.py::matches_path_segment` (`25c4573e`); all six
  sites moved (`ebb31e61`); detector green.
- [x] ✅ **Task 1.4**: Record the instance in
  `CLAUDE/Security/AsymmetricSiblingProtection.md` (or the matching
  class doc), naming the detector as the defence. Release note. Full QA
  green.

### Phase 2: Deliver

- [ ] ⬜ **Task 2.1**: Merge `--no-ff`, verify ancestry and CI, and restart
  the daemon.
- [ ] ⬜ **Task 2.2**: Mark 00422 N20 remedied.

## Success Criteria

- [ ] In a worktree whose name ends in `-venv`, the 14 acceptance DENY
  probes produce their declared decisions.
- [ ] The detector fails on the pre-fix tree and passes after.
- [ ] Full QA passes and CI is green.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00458-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Not yet delivered.
