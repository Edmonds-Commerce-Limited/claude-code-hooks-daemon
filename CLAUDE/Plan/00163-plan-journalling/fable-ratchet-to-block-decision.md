# Ratchet decision for Task 3.2: `journal-dayfile-naming` → BLOCK

The full decision record, with the measurements and file:line citations,
lives with the sibling question in Plan 00144:
`CLAUDE/Plan/00144-plan-qa-system/fable-ratchet-to-block-decision.md`
(section "Question 2"). This file exists so a reader of 00163 does not have
to know that.

## Decision

**Yes: set `plan_workflow.qa.journal.mode: block` in this repository's
`.claude/hooks-daemon.yaml` (`:1190`).** The shipped model default
(`src/claude_code_hooks_daemon/config/models.py:532-535`) stays `advise`,
mirroring how `commit_gate_mode` was dogfooded to `block` here (Plan 00343)
while its default stayed `warn`.

## The evidence in one paragraph

The check has never fired: `plan-qa --sweep` reports 0 findings across 407
plan folders (the check runs at SWEEP as well as EDIT since Plan 00230); the
tree holds 306 day-files in 256 `JOURNAL/` directories with 0 grammar or
number mismatches; git history shows 325 day-file paths ever added, 0
non-conformant, and no corrective rename ever. So `block` has a
false-positive ceiling of zero on this tree. The benefit is that a malformed
name is otherwise silent — `_scan_journal` (`plan_qa/model.py:405-410`) and
`journal-dayfile-is-today` (`checks/journal_dayfile_is_today.py:78-80`) both
skip it, so this is the only check that can see one, and an advisory is a
nudge an agent can scroll past (Plan 00341's lesson). The subordination rule
(`models.py:499-506`) makes the ratchet real here because `edit_mode` is
`block` (`.claude/hooks-daemon.yaml:1165`), and self-limiting for any client
on `edit_mode: warn`.

## Human gate

None remains. Every input is in the repository and no shipped default moves.
Task 3.2's "decide with the user" was a fair deferral with no evidence in
v3.40.0; the evidence is now unanimous.

## What the closer does

Flip the key, restart and verify the daemon, run the sweep (expect 0),
record the above as a Technical Decision in `PLAN.md`, tick Task 3.2, and
archive with the README row and stats in the same commit. Also reconcile
`PLAN.md:408-410` ("Plan stays In Progress") with the Dormant header.
Nothing here has been implemented.
