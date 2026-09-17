# Plan 00432: scoped qa scan overwrites repo artefact

**Status**: Complete
**Created**: 2026-09-17
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Thread

## Overview

`llm_qa` publishes each check's JSON artefact as that check's evidence surface —
it prints the path and a `jq` hint for a reader to query. Three checkers write
that artefact to a module-level absolute path inside this checkout whenever
`--json` is passed, regardless of whether the scan was pointed somewhere else.
Their own unit tests run them against a temp fixture directory, so a full QA run
leaves `git_history.json`, `skill_references.json` and
`python_var_guidance.json` describing a pytest fixture rather than this
repository. The tests do not merely tolerate that clobber, they READ the
repository artefact to get their result, so they depend on it.

Both directions are wrong, and only one of them is visible. A check that PASSED
can be left holding a fixture FAILURE — that is what happened, and it cost a
mid-run diagnosis. A check that FAILED can be left holding a fixture PASS, which
masks a real defect and is the direction nobody would notice. Which one you get
depends on the order the checks and the tests happen to run in.

`check_sensitive_content.py` already solved exactly this, with the reasoning
written down at its write site: a `--path` scan answers "is this DIRECTORY
clean", which is not the question the repository artefact answers, so a scoped
run reports beside what it scanned and never overwrites the repository's. This
plan applies that established shape to the three checkers that still lack it,
rather than inventing a second convention for the same problem (Plan 00422 N10).

## Goals

- A run of any checker given an override — a scan target or an input file it is
  graded against — leaves the repository artefact byte-identical.
- A scoped run still writes its verdict somewhere the caller can read — beside
  what was scanned, as `check_sensitive_content.py` does.
- Each of the three carries the guard test that would catch the regression, so
  the fix cannot rot back silently.
- The inventory is taken by measurement, not assumed: every
  `scripts/qa/check_*.py` with a module-level artefact constant is examined for
  the same shape, and the result recorded.

## Non-Goals

- Reordering `llm_qa` so the checks run after the tests. That makes the
  corruption deterministic in the MASKING direction, which is worse than the
  bug.
- Converting the three checkers' hand-rolled `sys.argv` loops to `argparse` —
  a separate change, and one that would obscure this diff.
- Changing what any check MEASURES, or its schema.

## Known property of the chosen shape

Reporting beside what was scanned means a scan scoped at a TRACKED directory
drops an untracked JSON file into it. That is inherited from the precedent, not
introduced here, and it surfaced immediately: one existing test scanned
`scripts/qa/` in place, which left `scripts/qa/skill_references.json` behind.
The test now scans a COPY in `tmp_path` — the exclusion it asserts is by
basename, so a copy tests the same rule and no longer depends on the real tree
being clean.

The alternative — writing every scoped verdict into `untracked/qa/` under some
derived name — was rejected: it keeps a repository-wide filename holding a
directory-scoped answer, which is the confusion this plan exists to end.

## Tasks

### Phase 1: Inventory

- [x] ✅ **Task 1.1**: Examine every `scripts/qa/check_*.py` with a module-level
  artefact constant; record which accept a scan-target override and which write
  unconditionally. Name the affected set in this plan.

  19 checkers carry a module-level artefact constant. **Seven** are affected —
  four more than the report named, which is why the inventory was a task rather
  than an assumption:

  | checker                             | override |
  | ----------------------------------- | -------- |
  | `check_git_history.py`              | `--repo` |
  | `check_skill_references.py`         | `--path` |
  | `check_python_var_guidance.py`      | `--path` |
  | `check_github_urls.py`              | `--path` |
  | `check_security_downgrade_flags.py` | `--root` |
  | `check_eacces_safe_predicates.py`   | `--path` |
  | `check_authored_path_stat.py`       | `--path` |

  Not affected: eight already resolve an `output_dir` from their `--root`
  (`repo_hygiene`, `input_contract`, `project_handler_tests`, `hook_contract`,
  `handler_reference`, `doc_truth`, `doc_snippets`, `british_english`), and
  `sensitive_content` is the precedent this plan follows.

- [x] ✅ **Task 1.2**: The three input-file overrides, first excluded and then
  covered.

  `check_fail_open_inventory.py` (`--inventory`),
  `check_dangerous_invocation_corpus.py` (`--corpus`) and
  `check_declared_invariant_pairs.py` (`--registry`) were first set aside as
  "no scanned directory to report beside". That was a statement about the FIX
  shape, not about the defect, and it was wrong to stop there: all three wrote
  the repository artefact unconditionally, and two of them still sweep this
  repository — so the override changes the DECLARATIONS the sweep is graded
  against, and "clean against our registry" is not the fact "clean against a
  substitute" establishes. The third grades only the corpus it was handed, so
  its verdict is not about this repository at all.

  All three now report beside the file they were pointed at. RED confirmed the
  same way as the other seven: the pre-fix versions were restored in place and
  the three behaviour tests failed against them, with their three controls
  passing.

### Phase 2: RED

- [x] ✅ **Task 2.1**: For each affected checker, a test that a scoped scan
  leaves the repository artefact untouched and writes its verdict beside the
  scanned target. Must fail before the fix.
  `tests/unit/qa/test_scoped_scan_leaves_repo_artefact.py` — one parametrised
  guard over all seven, 14 failed / 2 controls passed before the fix.

### Phase 3: GREEN

- [x] ✅ **Task 3.1**: Apply the `check_sensitive_content.py` shape to each
  affected checker.
- [x] ✅ **Task 3.2**: Update the existing tests that read the repository
  artefact to read the scoped one instead. 45 tests across four modules
  depended on the clobber; all now read the scoped artefact.

### Phase 4: Close

- [x] ✅ **Task 4.1**: Release note, if the change is user-visible.
- [x] ✅ **Task 4.2**: Mark N10 remedied in the Plan 00422 ledger.

## Success Criteria

- [x] `untracked/qa/*.json` after a full `llm_qa all` describes this repository
  for every check, with no fixture-scoped verdicts among them.
- [x] Each affected checker has a guard test pinning the boundary.
- [x] `llm_qa all` is green.
- [x] Every release-bound consequence is in the pending-release holding area:
  `UNRELEASED/release-notes/10-a-scoped-qa-scan-reports-beside-what-it-scanned.md`

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00432-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Plan filed from Plan 00422 niggle N10.
- Delivered and archived in a single commit; the work was one unit and the plan
  never outlived it.
