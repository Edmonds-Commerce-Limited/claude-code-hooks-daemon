# Plan 00451 Phases 1 and 2 report (python-developer, sonnet)

## Task 1.1: enumeration

`git ls-files` + fixed-string grep for 3.69.0, excluding CHANGELOG.md, RELEASES/, CLAUDE/UPGRADES/, CLAUDE/Plan/.
The plan's table of six is COMPLETE and correct: pyproject.toml, version.py, README.md, .claude/HOOKS-DAEMON.md,
.claude/ccy/claude-supervise.py, uv.lock. Other hits are not declarations: CLAUDE/LLM-UPDATE.md (prose naming versions
to avoid), CLAUDE/development/claude-code-versions.yaml (one entry per release), and fixture strings in tests/.

## Phase 1

- New `tests/unit/qa/test_version_bump_completeness.py`: `VERSION_DECLARATIONS` (path -> regex extracting the declared
  version) is the single home. Check A: every registered file declares `version.py`'s version. Check B: no other
  tracked file (outside the historical trees and `tests/`, minus a two-entry `_INCIDENTAL_MENTIONS` allowlist)
  contains the current version.
- Non-vacuity: self-tests build a throwaway git repo. Also run against a copy of the real files with pyproject.toml
  pinned at 3.41.0 and a new `new.txt` containing 3.69.0. Output:
  `['pyproject.toml: declares 3.41.0, expected 3.69.0']` and `['new.txt']`.
- `CLAUDE/development/RELEASING.md` Step 3 now names the test and its registry instead of restating the six files
  (release-agent.md already pointed at Step 3, so it needed no change).

## Phase 2

- Tests added to `tests/unit/qa/test_run_dependency_check.py` (stale lockfile via a fake `uv`, missing uv, and a
  witness fake deptry that records the verdict file as it stood mid-run). RED against the old script:
  `assert True is False` (x2) and `AssertionError: a crash here would leave a stale pass`; 3 failed.
- `scripts/qa/run_dependency_check.sh`: writes a pending (failed) verdict right after `mkdir`, before `ensure_venv`;
  new `write_failed_verdict` helper (also replaces the duplicated inline python in the deptry-error branch) records
  `uv lock --check` / `uv.lock` on a stale lock and a uv-missing verdict. deptry config and the `src/` scope are untouched.
  Result: 15 passed across both test files.

## QA

`llm_qa.py changed`: 37/40 passed; the only failure was `format` (1 file), which made 2 more checks NOT MEANINGFUL
(project_handlers, changed_tests; changed_tests itself showed 897 passed, 0 failed). Fixed with `run_autofix.sh`;
`run_format_check.sh` then exits 0 and both new/changed test files pass (15 passed). The full `changed` run was not
repeated (it queues behind the host QA lock): a coordinator re-run will confirm.

## Notes and disagreements

- Design choice: the registry lives in the test module (no new script) per YAGNI; `tests/` is excluded from the
  scan because fixtures there legitimately hardcode the current version.
- Release note: none needed. `scripts/qa/`, `tests/` and RELEASING.md are daemon-repo development tooling, not
  shipped to client installs.
- Other QA gates might share the stale-artefact shape; not audited (plan non-goal).
- Boundary: only the QA script, two test files, RELEASING.md and the plan folder were touched.
