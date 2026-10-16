# N460 / GitHub #120: list-venvs and prune-venvs name the current venv

## Assumptions

- The header wording changed to `Current venv (the one the resolver selects): <fp>`, and a second line names the
  fingerprint a new venv would get when it differs. The owner may prefer other wording.
- N460 has no task row in PLAN.md, so no checkbox was flipped; the ledger entry and STATUS-INDEX carry the status.

## Root cause (both symptoms)

`cmd_list_venvs`, `cmd_prune_venvs` and the fingerprint half of `_enumerate_venvs` called
`python_venv_fingerprint(project_root)`. Venvs are keyed on the daemon dir. Client install: the project-root slug
never matches any venv (#120). Self-install (N460): root equals daemon dir, but the resolver can select a venv by
scan whose fingerprint differs from the current interpreter's, so the hashed header named a venv that was not in use.

## Change

- `paths.current_venv_dir(daemon_dir)`: the resolver's venv directory (`resolve_existing_venv_python` parent.parent).
- `cli._current_venv_fingerprint` uses it; header, "Current venv:" and "Current venv preserved:" use it.
- `_enumerate_venvs` fingerprint half keyed on the daemon dir (was dead code in a client install); the live-realpath
  half (already resolver-based) is unchanged.
- Corrected `test_list_finds_venvs_in_normal_install_layout`, which pinned the project-root fingerprint.
- Release note 075.

## TDD

New `tests/unit/daemon/test_cli_current_venv_agreement.py` (client-install and self-install layouts, no resolver
mocking, including a client-install `prune-venvs --stale --force` that keeps the live venv and removes another).
Red against the old `cli.py`: `7 failed, 4 passed` (the 4 passes are the `current_venv_dir` and dry-run cases that do
not touch the changed lines). Green after: 64 passed across the five venv test files.

## QA

`./scripts/qa/llm_qa.py changed`: exit 1, 39/40, the one failure being `changed_tests` reporting 2 unmapped files
(123 passed, 0 failed). `--allow-unmapped`: exit 0, 40/40 PASSED.

## Commits

- e639697c0 code, tests, release note, ledger, STATUS-INDEX
- a follow-up commit records the hash in NIGGLES.md and adds this report
