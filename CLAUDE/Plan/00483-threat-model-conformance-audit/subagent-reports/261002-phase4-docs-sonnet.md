# Phase 4 docs fixes (Tasks 4.1, 4.2)

## Applied

Task 4.1: CHECKS.md (scope note with both clauses, prompt-injection statement, dismissal
record; D-SEC "ordinary route"; F-BYPS "in-scope route"; F-GAP careless-agent bound);
Routine 00002 ROUTINE.md (pointer sentence); Routine 00001 ROUTINE.md step 4 (dismissal
branch); security-reviewer.md (two-clause test, skip `UNCOVERED-accepted`, "Threat-model
test" finding item); code-reviewer.md (security qualifier); test_blocking_handler_evasion.py
docstring bounded.

Task 4.2: BUG_REPORTING.md (new first check, "Four checks"); 1-defect.yml (intro section,
optional checkbox, absolute GitHub URL); TROUBLESHOOTING.md (bypass subsection at end of
section 5). config.yml skipped by instruction.

## Skipped

- Findings 10 and 11 (optional wording in the evasion test messages): not requested.
- No source template exists for `.claude/agents/*.md`; the deployed files were edited directly.

## Verification

- 1677 tests passed: evasion test file, test_claude_md_guidance_coverage.py, tests/unit/docs_qa,
  and every test file referencing the touched docs.
- check_generated_doc_drift.py: no drift. docs-qa --sweep: 0 findings. ruff and black clean.
