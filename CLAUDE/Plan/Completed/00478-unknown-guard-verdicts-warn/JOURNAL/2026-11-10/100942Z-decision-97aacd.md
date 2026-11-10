## 10:09 · decision · —   — STAND-IN ruling on Q1-Q4 (not the owner's): rows 16 non-literal and 26 warn, rest deny

# Plan 00478: stand-in ruling on owner questions Q1-Q4

This is the STAND-IN's ruling, not the owner's. The owner may overturn any line.
Test applied to every row: is the dangerous action itself positively recognised,
or is the guard merely unable to decide? Source: PLAN.md, INVENTORY.md rows 1-26.

## Q1 (rows 1, 2, 3)

Q1: DENY (unchanged)

`git branch -D`, `git worktree remove` and `git push --delete` are positively
recognised verbs (INVENTORY rows 1 and 3: "the action is recognised; whether it
loses work is not"). The guard's design is deny-by-default with an allow earned by
a proof that nothing is lost; a failed proof is a missing exemption, not an unknown
command. The loss is irreversible (an unpushed tip, a remote branch), and a
stand-in may not authorise remote-branch deletes, so row 3 could not convert here
in any case. Row 2 is the same shape: the forced delete matched, only its target
is hidden.

Consequence: Task 2.2b converts nothing. Row 2 stays deny; add the missing pinning
test for the local-delete substitution deny (INVENTORY: "no test found by name").
Rows 1 and 3 stay deny in all sub-cases, including "no delete could be read" where
the delete text may be executed (Phase 0 already released the provable-data case).
Narrowing row 2's command-wide substitution test to substitutions that can reach
the delete would be a misreading fix in the Phase 0 style; it is not ruled here.

## Q2 (row 5)

Q2: DENY (unchanged)

Both the evacuating step and the destroying step are positively present in one
command (row 5: "both shapes are positively present"), and `core/evacuation.py`
notes that inside one command the evacuation "is certain to be this command's
own". The destroying verb is recognised and irreversible; what is missing is proof
that it targets different work, which is the Q1 shape. The cost of the deny is
small: the cross-command twin already allows (`test_evacuation_turns.py:188`).

Consequence: Task 2.2e leaves `_same_work(unplaced_matches=True)` and
`test_unplaceable_evacuation_fails_closed` as they are.

## Q3 (rows 16, 23)

Q3: DENY where the path is literally named; WARN where it is not

This is the line `secret_file_guard` already holds (`_literal_finding_or_advisory`):
a protected path literally in the input is a positive mention and denies. Row 16's
unknown-verb route (`_unknown_command_violation`) and its `_text_naming` fallbacks
(depth bound, brace cap, unreadable text) deny on a visibly named path, so they
stay. Row 16's deny on a glob with no literal part ("named by any text") and any
"could reach it" verdict with no literal appearance rest on no mention at all, so
those are could-not-decide. Row 23 names the plan directory literally beside a
recognised `mkdir`, so it stays.

Consequence: Task 2.2e converts only row 16's non-literal sub-branches to
`unknown_verdict_allow` (the `**`-only glob case pinned by
`test_a_glob_with_no_literal_directory_stays_fail_closed`, which flips to an
advisory). Every literally-named deny in row 16, and row 23, stays as-is.

## Q4 (rows 21, 25, 26)

Q4 row 21 (public-issue body check): OUT OF SCOPE, stays deny
Q4 row 25 (plan-sync config check): OUT OF SCOPE, stays deny
Q4 row 26 (pipe-to-tail unknown tier): IN SCOPE, converts to WARN

Row 21: `gh issue create` against the public tracker is positively recognised and
cannot be retracted; an unreadable, oversize or stdin body is a missing required
proof, the Q1 shape. Row 25: an absent or unparseable settings file, or an unset
`plansDirectory`, is a positively found configuration fault, not an undecided
command. Row 26 is the most literal instance of the question the owner answered
("whether guards deny unknown commands"): the producer is on neither list, the
guard cannot tell whether truncation costs anything, and the loss is fully
reversible by rerunning.

Consequence: Task 2.2e converts row 26 only. An unknown producer piped to
`tail`/`head` allows with the shared advisory (name `bin/echd-capture` and
`extra_whitelist`) plus the `UNKNOWN-VERDICT` log line; blacklisted producers
still deny. Rows 21 and 25 are recorded as not could-not-decide routes.

## Scope of Task 2.2b and 2.2e under this ruling

- Row 1 (forced branch delete / worktree removal, unproven): stays deny
- Row 2 (substitution beside a forced delete, Task 2.2b): stays deny; add a test
- Row 3 (remote delete, unproven): stays deny
- Row 5 (evacuate-then-destroy, unplaced link): stays deny
- Row 16 (write-protected paths): literal naming stays deny; non-literal
  sub-branches convert to warn
- Row 23 (plan-folder mkdir, brace cap): stays deny
- Row 21 (public-issue body): out of scope, stays deny
- Row 25 (plan-sync config): out of scope, stays deny
- Row 26 (pipe-to-tail unknown tier): converts to warn
- Task 2.3 follows: rule texts, generated guidance and a release note for rows 16
  and 26; Success Criterion 1 should name rows 1-3, 5, 21, 23, 25 as positive denies.
