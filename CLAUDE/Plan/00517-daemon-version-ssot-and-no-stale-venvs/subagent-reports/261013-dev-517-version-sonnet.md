# Report: Plan 00517 Phase 1 Task 1.1 and Phase 2 Tasks 2.1-2.2

Branch `worktree-plan-517-version-ssot`. Inventory: `INVENTORY.md` in the plan folder.

## What changed

- `utils/deployed_version.py`: new `read_installed_source_version(daemon_root)` and `INSTALLED_SOURCE_VERSION_REL_PATH`.
  No Python reader of an installed `version.py` existed (only awk and regex in shell scripts), so this is the single
  Python one. It parses text and never imports; unreadable, undecodable, missing or literal-less files give `None`.
- `daemon_upgrade_detector`: `_resolve_installed_daemon_version` uses it; no venv resolution, no metadata read.
  Docstring, `get_claude_md` and acceptance-test text updated. `daemon/paths.py` docstring no longer says the detector
  reads metadata.
- Tests: detector tests rewritten (metadata naming another version reports nothing; version.py rewritten under a
  running handler reports; missing, literal-less and undecodable version.py fail open); reader tests in
  `tests/unit/utils/test_deployed_version.py`; guard `tests/unit/daemon/test_installed_version_single_source.py`
  (AST scan: only `daemon/metadata.py` may use `read_daemon_metadata`).
- Task 2.2 finding: the detector was the only reader taking the installed version from venv metadata. The shell
  `_read_installed_version` (upgrade_version.sh) and cli.py `_read_venv_stamp` read the `.daemon-version` build stamp
  on purpose (at upgrade time version.py already names the target), documented as build-record readers in INVENTORY.md.
- Release note `054-...` used (053 left free for another branch).
- Plan Tasks 1.1, 2.1, 2.2 ticked; journal entry added.

## QA

`./scripts/qa/llm_qa.py changed`: `QA: 39/40 PASSED, 1/40 FAILED`. The one failure is
`changed_tests: 1896 passed, 0 failed, 5 skipped | 34 test files from 10 changed files (1 unmapped)` with
`src/claude_code_hooks_daemon/daemon/paths.py [too-broad]` unmapped (a docstring-only edit to a very broad file). The
earlier run's error_hiding finding (return-none-on-error in the new reader) was fixed.
