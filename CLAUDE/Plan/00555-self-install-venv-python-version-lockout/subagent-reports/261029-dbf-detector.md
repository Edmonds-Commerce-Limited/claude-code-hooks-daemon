# DBF detector: venv-interpreter-trust, reconciled with the independent search

Detector: `scripts/qa/check_venv_interpreter_trust.py` (rules `venv-exec-bit-trust`, `venv-weak-liveness-probe`). Tests: `tests/unit/qa/test_check_venv_interpreter_trust.py` (117 pass). Ruff, black and mypy (strict, per pyproject) are clean on both files. Doc: `CLAUDE/Security/UntrustedVenvInterpreter.md`.

Result on the tree: 64 findings (first run 64; after reconciliation 64: five removed by one narrowing, five added by three widenings). 54 real instances, 10 false positives. The count was not used as a target.

## Changes made by the reconciliation (tests first)

Widened (search wins; each has fixture tests in `TestWidenedToMatchTheIndependentSearch`):

1. `[[ -z "$x" || ! -f "$PYTHON_CMD" ]]`: the lexer splits on `||` inside `[[ ]]`, so the second half had no test head. Now tracked as a continuation. Hazard-free check: a compound test about a non-interpreter is not reported.
2. `venv-*/bin/"$name"` and `"${VENV_DIR}/bin/${tool}"`: a `bin/$var` path under a path naming `venv`. Added `resolve_venv.sh:324` (search item 18) and `venv-include.bash:307` (item 37). A `${PREFIX}/bin/${tool}` is not reported.
3. Python `meta["python_path"]` / `meta.get("python_path")` is an interpreter path. Added `paths.py:1234, 1235` (item 3). Another key is not reported.

Narrowed (only where the hazard is genuinely absent; tests in `TestImportingThePackageIsTheVersionCheck`):

4. A function that runs `<interp> -c "import claude_code_hooks_daemon..."` with no `sys.path` edit. After a minor change the venv cannot see its site-packages, so that import fails: it is a stronger test than a version compare. Removed `install.sh:430` (both copies), `init.sh:1702` (`validate_venv`) and `client_validator.py:609` (search items 27 and 38, both "no"). `venv.sh verify_venv` is NOT narrowed: its import puts `src` on `sys.path` (search item 41, unsure); a test pins that case.

## Every finding (64)

R = real instance, FP = false positive (hazard absent), R? = real but exposure low or judgement open (for the owner).

| #     | Site                                                                                           | Class | Reason                                                                                                                                                     |
| ----- | ---------------------------------------------------------------------------------------------- | ----- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1-3   | `.claude/skills/hooks-daemon/scripts/{daemon-cli:190, health-check:202, init-handlers:187}.sh` | R     | Resolver result runs after `-f` only (search item 25 consumers)                                                                                            |
| 4     | `CLAUDE/UPGRADES/v2/v2.0-to-v2.1/verification.sh:79`                                           | R?    | Frozen historical script, retired `untracked/venv` layout, then starts the daemon from it                                                                  |
| 5     | `CLAUDE/UPGRADES/v2/v2.12-to-v2.13/verification.sh:26`                                         | R?    | As 4                                                                                                                                                       |
| 6     | `bin/hooks-daemon:278`                                                                         | R     | `-x` then `exec -m claude_code_hooks_daemon...` (item 33)                                                                                                  |
| 7     | `init.sh:2197`                                                                                 | R     | "Installed" = `-f` (item 28)                                                                                                                               |
| 8     | `scripts/debug_hooks.sh:70`                                                                    | R     | Resolver result, `-f`, then starts the daemon                                                                                                              |
| 9     | `scripts/install/rollback.sh:132`                                                              | FP    | Existence guard before recording `python_version` in a manifest (item 50): reporting only                                                                  |
| 10    | `rollback.sh:133`                                                                              | FP    | `--version` output is recorded, not used to judge usability                                                                                                |
| 11    | `rollback.sh:210`                                                                              | FP    | Best-effort `pip freeze` backup; the comment says failure is tolerated                                                                                     |
| 12-14 | `scripts/install/venv.sh:137, 143, 149` (`verify_venv`)                                        | R     | Exists, executable, `--version`; its import adds `src` to `sys.path` (item 41)                                                                             |
| 15    | `venv.sh:202` (`get_venv_python_version`)                                                      | FP    | The function reports the interpreter's version; the exec guard avoids running a non-executable                                                             |
| 16-17 | `venv.sh:366, 368` (`venv_lock_hash_matches` fallback)                                         | R     | Picks the interpreter on `-x` (item 40)                                                                                                                    |
| 18    | `venv.sh:1593` (`install_package_editable`)                                                    | R?    | Pre-install guard on a venv usually just built                                                                                                             |
| 19    | `venv.sh:1693` (`eager_cleanup_stale_venvs`)                                                   | R?    | Search item 43 (unsure): failure is a skipped cleanup                                                                                                      |
| 20    | `scripts/install_version.sh:805`                                                               | R?    | Runs a just-installed venv on `-x`; low exposure                                                                                                           |
| 21-22 | `scripts/lib/resolve_venv.sh:216, 221`                                                         | R     | `_rv_candidate_runs`, `-c 'import sys'` (item 17)                                                                                                          |
| 23    | `resolve_venv.sh:324`                                                                          | R     | `_rv_pick_ranked_scan` `-x` (item 18); added by widening 2                                                                                                 |
| 24-25 | `resolve_venv.sh:355, 359`                                                                     | R     | `HOOKS_DAEMON_VENV_PATH` branch, `-x` only (item 19)                                                                                                       |
| 26-27 | `resolve_venv.sh:579, 583`                                                                     | R     | `resolve_venv_python_in_venv` (item 22)                                                                                                                    |
| 28    | `scripts/qa/run_canonical_callers_check.sh:43`                                                 | R     | Resolver result, `-x`, then runs it                                                                                                                        |
| 29    | `scripts/qa/run_strategy_pattern_check.sh:44`                                                  | R     | As 28                                                                                                                                                      |
| 30    | `scripts/setup_worktree.sh:307`                                                                | R?    | Just-built venv; lines 344-364 later compare the `-py{MM}-` directory tag with the venv's `sys.version_info` (item 51). Owner: accept that as proof or not |
| 31    | `scripts/upgrade.sh:345`                                                                       | FP    | `--version` printed in a message for a system interpreter `find_latest_python` already version-checked                                                     |
| 32-40 | `scripts/upgrade.sh:923, 932, 967, 998, 1052, 1106, 1158, 1253, 1289`                          | R     | `venv-*py3*` glob picks the first executable; written to metadata the resolver later trusts                                                                |
| 41-45 | `scripts/upgrade_version.sh:804, 884, 1098, 1166, 1670`                                        | R     | Resolver result guarded by `-f` (item 49)                                                                                                                  |
| 46    | `scripts/validate_worktrees.sh:73`                                                             | R     | The verdict "venv present" is `-x`                                                                                                                         |
| 47    | `scripts/venv-include.bash:70`                                                                 | R     | `venv_exists` (item 36)                                                                                                                                    |
| 48    | `venv-include.bash:157`                                                                        | FP    | Checks that `python -m venv` just created the file; the interpreter was made by the one that built it                                                      |
| 49    | `venv-include.bash:307`                                                                        | R     | `venv_tool` (item 37); added by widening 2                                                                                                                 |
| 50-51 | `src/claude_code_hooks_daemon/daemon/cli.py:3319, 3321`                                        | FP    | Tells a venv directory from other `untracked/` entries to list it; nothing is run or selected, and `is_current` uses the fingerprint                       |
| 52    | `cli.py:3899` (`_write_venv_metadata`)                                                         | FP    | Existence guard before writing metadata; it is the producer of the `python_path` that paths.py:1234 trusts, and that consumer is the instance              |
| 53    | `daemon/paths.py:404` (`_probe_python_version`)                                                | FP    | Probes a PATH-discovered system interpreter and parses its major.minor; this is the version check, and it is not a venv                                    |
| 54    | `paths.py:960`                                                                                 | R     | `_venv_interpreter_runs` (item 1)                                                                                                                          |
| 55-57 | `paths.py:998, 1082, 1174`                                                                     | R     | Items 6, 7, 2 (items 4, 5, 8 reach `_pick_interpreter`)                                                                                                    |
| 58-59 | `paths.py:1234, 1235`                                                                          | R     | Metadata branch (item 3); added by widening 3                                                                                                              |
| 60    | `paths.py:2977`                                                                                | R?    | `live_venv_realpaths` (item 13, unsure)                                                                                                                    |
| 61    | `src/.../install/templates/hooks-daemon:278`                                                   | R     | Same as `bin/hooks-daemon`                                                                                                                                 |
| 62-64 | `src/.../skills/hooks-daemon/scripts/{daemon-cli:190, health-check:202, init-handlers:187}.sh` | R     | Same as 1-3                                                                                                                                                |

Counts: FP = rows 9, 10, 11, 15, 31, 48, 50, 51, 52, 53 (10). Everything else is real (54), of which R? = rows 4, 5, 18, 19, 20, 30, 60 (7).

False positives NOT narrowed, and why: each needs a rule about what the output of a `--version` run is used for, or what a "venv listing" is. Those are not cleanly lexical, I could not show a narrowing that stays hazard-free, and the brief says to list rather than guess. The owner decides: the options are a narrowing per row, a fix that makes the site compare anyway (cheapest for 9-11, 31), or a rule change. Until then the check is red on these ten as well. The doc lists them.

## The searcher's 29 "yes" items

| Item | Site                                             | Result                | Reason                                                                                                                      |
| ---- | ------------------------------------------------ | --------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| 1    | paths.py `_venv_interpreter_runs`                | caught (960)          | -                                                                                                                           |
| 2    | `_pick_interpreter`                              | caught (1174)         | -                                                                                                                           |
| 3    | step 2 metadata `python_path`                    | caught (1234, 1235)   | Missed by the first rules; widening 3                                                                                       |
| 4    | step 3 fingerprint-keyed venv                    | caught via helper     | The exec test is in `_pick_interpreter` (1174); the caller line has no test of its own                                      |
| 5    | step 4 scan fallback                             | caught via helper     | As 4, plus 998 for the hot-path scan                                                                                        |
| 6    | `_best_ranked_scan_candidate`                    | caught (998)          | -                                                                                                                           |
| 7    | `resolve_existing_venv_python`                   | caught (1082, 998)    | -                                                                                                                           |
| 8    | step 5 legacy venv                               | caught via helper     | `_pick_interpreter`                                                                                                         |
| 11   | `_cli_check_venv_fresh`                          | not caught            | Root cause (d): freshness by lock_hash; a missing term, no spelling to match                                                |
| 17   | `_rv_candidate_runs`                             | caught (216, 221)     | -                                                                                                                           |
| 18   | `_rv_pick_ranked_scan`                           | caught (324)          | Missed first (`bin/"$name"`); widening 2                                                                                    |
| 19   | `HOOKS_DAEMON_VENV_PATH`                         | caught (355, 359)     | -                                                                                                                           |
| 20   | hot-path cache `.python-cmd-cache`               | not caught            | Root cause (c): invalidated by a timestamp; an absent invalidator. `-x` on the cached path is not a distinct line to report |
| 21   | cache write                                      | not caught            | As 20                                                                                                                       |
| 22   | `resolve_venv_python_in_venv`                    | caught (579, 583)     | -                                                                                                                           |
| 24   | `venv_resolver.sh` shim                          | not caught            | Delegation: no test in the file                                                                                             |
| 25   | `_resolve-venv.sh` shim                          | not caught            | Delegation; its consumers are caught (rows 1-3, 62-64)                                                                      |
| 26   | init.sh `_resolve_python_cmd`                    | not caught            | Delegation: assigns the resolver output, tests nothing                                                                      |
| 28   | init.sh `_is_daemon_installed`                   | caught (2197)         | -                                                                                                                           |
| 29   | `_venv_self_heal` gating                         | not caught            | Root cause (e): the branch condition's meaning                                                                              |
| 31   | `_hooks_daemon_run_cli_helper`                   | not caught            | Delegation                                                                                                                  |
| 33   | `bin/hooks-daemon:278`                           | caught                | -                                                                                                                           |
| 34   | `_run_venv_free_verb` repair arm                 | not caught            | Root cause (e)                                                                                                              |
| 35   | `run-qa-runner.sh`                               | not caught            | Root cause (f): runs the resolver output with no test at all                                                                |
| 36   | `venv-include.bash` `venv_exists`, `ensure_venv` | caught (70)           | -                                                                                                                           |
| 37   | `venv_tool`                                      | caught (307)          | Missed first; widening 2                                                                                                    |
| 39   | `venv.sh` `_venv_is_fresh`, `ensure_venv`        | not caught            | Root cause (d)                                                                                                              |
| 44   | `_vb_build_under_lock`                           | not caught            | Root cause (f): success = the resolver returned something                                                                   |
| 47   | `_warn_if_venv_not_built_for_source`             | not caught            | Judges lock drift only; it tests no interpreter at all                                                                      |
| 49   | `upgrade_version.sh` `VENV_PYTHON`               | caught (804 and four) | -                                                                                                                           |

Tally: 17 caught (1-8, 17, 18, 19, 22, 28, 33, 36, 37, 49; items 4, 5 and 8 through the shared helper) and 13 not caught (11, 20, 21, 24, 25, 26, 29, 31, 34, 35, 39, 44, 47). That is 30 rows, not 29: the searcher's stated total of 29 disagrees with its own list of numbers (1-8, 11, 17-22, 24-26, 28, 29, 31, 33-37, 39, 44, 47, 49 is 30 items). I mapped every number in the list.

All 13 misses were examined for a lexical widening and none has one: 24, 25, 26, 31, 35 contain no test (delegation, root cause f); 29, 34, 47 are gating (e); 11, 39 are freshness (d); 20, 21 are the cache (c); 44 is (f).

## What each technique found that the other could not

The search found, and the Detector cannot: the freshness and cache holes (c, d), the repair gating (e), "success = resolver returned something" (f), and the shims. These have no spelling; they are properties of what a function fails to ask. It also found the positive controls (`setup_worktree.sh` tag compare, `create_venv_at_path`), which told me what proof looks like and that the one in `setup_worktree.sh` is proof of a different kind than pyvenv.cfg (open for the owner).

The Detector found, and the search did not: (1) the ten exec-bit and probe sites in scripts the search listed only as "matched the broad grep, not read": `debug_hooks.sh`, `validate_worktrees.sh`, `run_canonical_callers_check.sh`, `run_strategy_pattern_check.sh`, `install_version.sh`, the three skill scripts' `-f` guards (the search named them as consumers, never as sites), `rollback.sh`, `install.sh:430`, and the two frozen `CLAUDE/UPGRADES/v2` verification scripts; (2) all nine `upgrade.sh` exec tests (the search recorded only metadata reporting, item 50, and judged it "no"; the glob there picks a venv with no minor check and the result is written to metadata that paths.py trusts, so I classed it real); (3) `paths.py:2977` and `cli.py:3319-3321` and `3899`, which the search read as part of larger spans. The Detector also over-reports: ten false positives that a reader dismisses at a glance, which is the cost of lexical matching.

## Verification

- Detector tests: 117 pass. Touched test files pass (see below). Ruff, black, mypy clean on the two new files.
- llm_qa.py targeted to `venv_interpreter_trust`: FAILS on the tree with 64 findings. That red is correct; no instance was fixed, suppressed or baselined.
