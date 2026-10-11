# Phase 4 review findings (read-only review, copied for the record)

Source: untracked/agent-reports/auto/261002-172358-p483-phase4-ap483-phase4-b4e500ba5bef8ea6.md

Test: CLAUDE/ARCHITECTURE.md threat model. A shape is out of scope when the operative text is
not visible to the daemon at call time, or when it has no working purpose except defeating a
parser. README statement: "Guardrails, not armour".

## Task 4.1 passages to change

01. CHECKS.md F-BYPS: bound "every route" to every in-scope route; dismissals recorded.
02. CHECKS.md F-GAP: constructs a careless agent plausibly types.
03. CHECKS.md scope note: add prompt-injection statement, both clauses, in-scope list, how a
    dismissal is recorded (`Dismissed (threat model)`, `UNCOVERED-accepted` corpus row).
04. security-reviewer.md: replace judgement words with the two-clause test.
05. security-reviewer.md: skip residue already `UNCOVERED-accepted`.
06. security-reviewer.md finding list: add a required "Threat-model test" item.
07. Routine 00002 ROUTINE.md: one sentence pointing at the threat model; CHECKS.md D-SEC
    "any route" becomes "any ordinary route". Leave D-PATH.
08. Routine 00001 ROUTINE.md step 4: branch for dismissals.
09. test_blocking_handler_evasion.py docstring: bound "a silent bypass is not acceptable" to
    ordinary respellings.
    10-11. Optional message wording in the evasion test (not applied).
10. code-reviewer.md security item: threat-model qualifier.

Already correct: README :63-82; code-reviewer "not theoretical ones"; the evasion test table
limit at :346-348.

## Task 4.2 insertions

A. BUG_REPORTING.md: new first check "Is it in scope?", "Three checks" becomes "Four".
B. 1-defect.yml: "Is it in scope?" intro paragraph (absolute GitHub URL) and an optional
third checkbox.
C. TROUBLESHOOTING.md: "a command got past a handler" subsection at the end of section 5.
D. config.yml: optional contact link (skipped by instruction).
E. 2-other.yml: no change.
