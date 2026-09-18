# Plan 00438: kill suggestion can name the protected group

**Status**: Not Started
**Created**: 2026-09-18
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single Agent

## Overview

From ledger [00422](../00422-niggles-ledger-fifteen/NIGGLES.md) N5 row (i), the
last of the three rows the v3.65.0 reviewers flagged as having teeth.

`find_breaches` takes `exclude_pgids` — "process groups to never flag (e.g. the
harvester's own)" — and honours it when deciding whether a record breaches:

```python
if record.pgid in excluded:
    continue
```

It then builds the breach's `tree_pgids` from the descendant tree with no such
filter, and `Breach.kill_command` renders one `-<pgid>` per entry. So a group
the caller declared off-limits can still appear in the command the report tells
an agent to run. The harvester never kills anything — it prints a command for a
human or an agent to run — which is exactly why the printed command is the
thing that has to be right.

**The exclusion's whole purpose is self-protection**: `cmd_harvest_background`
passes `os.getpgrp()`, the harvester's own group. A report that can name that
group in a `kill --` is a report that can tell the caller to kill the thing
producing it.

Reachability depends on process-group layout, and this plan does not overclaim
it: the tracked process would have to have a descendant sitting in the excluded
group. What is not conditional is the contract — a group the caller excluded
should never appear in the output, and today that holds for the flagging half
and not the reaping half.

## Goals

- No excluded pgid can appear in a breach's `tree_pgids`, and therefore none
  can appear in `kill_command`.
- The fallback stays safe: a tree whose every group is excluded falls back to
  the breaching record's own group, which cannot itself be excluded because
  such a record never becomes a breach.

## Non-Goals

- **Killing anything.** The harvester surfaces and never reaps; that is
  deliberate and unchanged.
- **Widening what is excluded.** The caller decides; this plan makes the
  existing declaration hold everywhere.

## Tasks

### Phase 1

- [ ] ⬜ **Task 1.1**: RED — a test building a breach whose descendant tree
  spans an excluded group, asserting that group appears neither in
  `tree_pgids` nor in `kill_command`.

- [ ] ⬜ **Task 1.2**: GREEN — filter `tree_pgids` against the same excluded
  set the flagging half uses.

- [ ] ⬜ **Task 1.3**: A test for the all-excluded tree, so the fallback to the
  record's own group is asserted rather than assumed.

## Success Criteria

- [ ] ⬜ Both new tests observed RED before the fix and GREEN after.
- [ ] ⬜ `llm_qa.py all` passes.
- [ ] ⬜ N5 row (i) is marked done in ledger 00422, with the reachability
  stated as the conditional thing it is.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00438-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- <!-- milestone or delivery commit hash -->
