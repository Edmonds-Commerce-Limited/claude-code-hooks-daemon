# N434 / issue #84: rank the venv scan fallback by metadata lock_hash

Branch: worktree-issue-84-venv-scan-order. Ruling implemented as written; I found nothing wrong with it.

## Changes

- `src/claude_code_hooks_daemon/daemon/paths.py`: new `_best_ranked_scan_candidate`; step 3 of `resolve_existing_venv_python` calls it. Candidates must still be slug-eligible with an executable `bin/python`. Rank 0 is a metadata `lock_hash` equal to `_compute_project_lock_hash_stdlib(daemon_dir)`, rank 1 any other slugged name, rank 2 a legacy name (`_parse_venv_dir_slug` is `None`). Ties keep sorted-name order. It reuses `_compute_project_lock_hash_stdlib`, `_read_venv_metadata_stdlib` and `_parse_venv_dir_slug`, with no subprocess and no run-probe. Steps 1, 2, 4, the slug rule and the diagnostics resolver are untouched. The docstring precedence list is updated.
- `scripts/lib/resolve_venv.sh`: `_rv_pick_python`'s two scan loops (python, then python3) are replaced by `_rv_pick_ranked_scan`, which walks ranks 0, 1, 2 and keeps the existing `_rv_candidate_runs` probe and its "failed to run" message. New helpers: `_rv_current_lock_hash` (pyproject.toml plus uv.lock or the `\0no-uv-lock\0` marker through `sha256sum`, falling back to `shasum -a 256`) and `_rv_rank_scan_candidate` (a bash-regex JSON read of `lock_hash`, no fork). The header precedence comment is updated.
- Bash cost: a lock-hash match was computable without a Python spawn. The only new fork is one `sha256sum` per scan, and the scan already forks a Python probe per candidate. If neither hash tool exists, the shell side ranks slugged over legacy only.
- Bash has no slug-eligibility check (it never had one), and I did not add one. "Legacy" there means a name matching `^venv-py[0-9]+-[a-f0-9]+(-.+)?$`.
- Release note: `CLAUDE/UPGRADES/UNRELEASED/release-notes/037-the-venv-scan-prefers-the-venv-built-for-this-source.md`.

## Decision on the bash side (coordinator correction)

`_rv_pick_python` has no fingerprint step and no slug check. It only picks the interpreter that then runs `paths.py resolve-venv` (`resolve_venv.sh` lines ~488-529); it does not choose the final venv. I kept the ranking there anyway, because `python_venv_fingerprint` hashes `sys.version` of whichever interpreter runs `paths.py`. A stale legacy `venv-py311-*` interpreter picked first computes a py311 fingerprint, so `paths.py` resolves against the wrong interpreter and the upgrade gate runs under it. Ranking the interpreter choice by lock_hash match, then slugged, then legacy therefore changes the final venv. The run-probe is kept and no Python spawn is added.

## Tests (RED first)

- Python, `tests/unit/daemon/test_paths_resolve_existing_venv.py`, new class `TestScanFallbackRanking` (7 cases). On unchanged code 4 failed, 21 passed (the 3 passing new cases are guards: legacy alone, legacy-with-match beats stale slugged, slug-ineligible stays skipped). The failures were AssertionError on the returned path: the legacy `venv-py311-00000001/bin/python` came back instead of the slugged one:
  - test_lock_hash_match_beats_lexically_first_legacy_venv
  - test_lock_hash_match_beats_other_slugged_venv
  - test_slugged_venv_beats_legacy_when_no_lock_hash_matches
  - test_slugged_venv_beats_legacy_without_project_sources
- Bash, new `tests/integration/test_resolve_venv_scan_ranking.py` (7 cases, subprocess-driven like `test_resolve_venv_runnability_probe.py`). On unchanged code 6 failed, 1 passed. Failures: the issue layout with and without uv.lock, slugged beats legacy with no match, slugged beats legacy with no sources, a matching venv that cannot run falls through (`assert 'failed to run' in ''`, the legacy was returned first), and bash/Python parity. The passing one is the legacy-alone case.
- After the change: those two files plus `test_resolve_venv_runnability_probe`, `test_venv_resolver_parity_matrix`, `test_venv_resolver_hot_path_latency`, `test_resolve_venv_override_cache` and `test_paths_resolve_venv_diagnostics` give 113 passed.

## QA

black (reformatted paths.py once), ruff and mypy on the touched Python are clean; shellcheck on `resolve_venv.sh` is clean. `./scripts/qa/llm_qa.py changed`: 37 of 40 passed, 2 failed, 1 not meaningful.

- `changed_tests`: 520 passed, 0 failed, from 33 test files. It still fails the run because `scripts/lib/resolve_venv.sh` and `src/claude_code_hooks_daemon/daemon/paths.py` are "unmapped [too-broad]" (no `changed_tests_map.yaml` rule narrows them). That is a property of those two paths, not of this change; I did not add a map rule, and I did not rerun with `--allow-unmapped`.
- `docs_qa`: one advisory (0 block) `duplicate-block` in `CLAUDE/Plan/00471-subagent-token-budget-protection/JOURNAL/00471-Journal-26-10-12.md:39-41`, a file this change does not touch. It makes `project_handlers` read "not meaningful" (238 passed, 0 failed).
- pyright reported a "working tree changed during the run" warning (I was writing the report while it ran); it found 0 errors.

## Not touched

`src/claude_code_hooks_daemon/skills/hooks-daemon/scripts/install.sh:429` has its own `venv-*/bin/python` dual-layout probe (marked deliberate). It is outside the brief, so I left it; it is a possible follow-up if the same shadowing matters there. NIGGLES.md was not edited: the coordinator owns the ledger status.
