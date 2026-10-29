# Independent search: venv / interpreter trusted without a major.minor match

Searcher: independent (Defence Before Fix). Checkout: /workspace (main). The dispatch did not contain the rule or its pattern; searched from the class description alone. Not opened: scripts/qa/semgrep/, any scripts/qa/check_*.py, the secret word list, .claude/worktrees/. Nothing modified. Some scripts/qa/check_*.py filenames appeared in grep file lists; their contents were not opened.

Forms written down before searching:
1. Liveness probes that prove only existence, exec bit, `import sys` or `--version`.
2. Caches of a resolved interpreter keyed on mtime, path or a fingerprint name.
3. Fallback scans over `venv-*` that accept any directory regardless of its py tag.
4. Freshness decided by a hash or stamp (lock_hash, .daemon-version) with no interpreter-version component.
5. Hard-coded `python3.NN`, `lib/python3.N/site-packages`, `pyNN` tags.
6. Trusting the version tag in a venv dir name or pyvenv.cfg without comparing it.
7. Success judged by "the resolver returns something".
8. Pointers/symlinks to a venv (lsp-venv).

## Instances (file:line, what, hazard, technique)

T = found by text search, R = found by reading. Hazard: yes / no / unsure.

### A. Python resolver (src/claude_code_hooks_daemon/daemon/paths.py)

1. paths.py:943-968 `_venv_interpreter_runs`: probe is `python -c "import sys"`, pass on returncode 0. A venv bin/python symlinked to a base interpreter of another minor passes. yes. T+R. Originating instance.
2. paths.py:1157-1180 `_pick_interpreter` (inside `resolve_existing_venv_python_with_diagnostics`): first exec-bit file that passes item 1. yes. R.
3. paths.py:1228-1248 step 2 metadata branch: `python_path` from `.daemon-metadata.json`; usable if is_file + X_OK + item 1. Selection is by lock_hash only. yes. R.
4. paths.py:1301-1314 step 3 fingerprint-keyed venv: the directory name carries py{MM} but nothing compares it to the interpreter; relies on item 1. yes (reduced: the key includes the running sys.version so a mismatching dir normally misses, but in-place drift of the base symlink under the same name is undetected). R.
5. paths.py:1327-1347 step 4 scan fallback over `sorted(untracked.glob("venv-*"))`: any slug-eligible venv accepted via item 2, no py{MM} comparison. yes. This is the incident mechanism: the resolver runs under the venv's own now-3.13 python, its fingerprint (py313-...) misses the py311 dir, the scan takes the py311 dir. R.
6. paths.py:976-1013 `_best_ranked_scan_candidate` (hot-path variant): only is_file + X_OK, no probe at all; ranks by lock_hash/slug/legacy. yes. R.
7. paths.py:1016-1094 `resolve_existing_venv_python` (docstring 1053-1063 says it deliberately does not run-probe): keyed path and scan accept exec bit only. yes. R.
8. paths.py:1369-1391 step 5 legacy `untracked/venv`: same acceptance as item 2. yes. R.
9. paths.py:191-224 `python_venv_fingerprint`: hashes sys.version, base_prefix, machine; embeds py{MM}. no on its own (a correct key), but items 4/5 trust the name. T.
10. paths.py:227-246 `_parse_venv_dir_slug` and `_VENV_NAME_SLUG_PATTERN` (about line 147): parse the py tag only to extract the slug; the tag is never compared to the running version. unsure. T+R.
11. paths.py:2883-2932 `_cli_check_venv_fresh`, with bash caller venv.sh:330-396: freshness = metadata lock_hash equals sha256(pyproject.toml + uv.lock); the interpreter version is not in the hash. A 3.11-built venv at the keyed path with a matching hash is "fresh". yes. R.
12. paths.py:2982-3014 `classify_venv`: lock_hash match => keep; "live" = resolver pick or sys.prefix. A wrong-minor venv is classed keep/live. unsure (affects pruning and reporting, not selection). R.
13. paths.py:2945 `current_venv_dir`, 2959 `live_venv_realpaths`: derive "the venv the daemon runs from" from item 7. unsure. R.
14. paths.py:2820-2873 `_cli_resolve_venv --fallback-target`: on a miss prints the keyed creation target. no. R.
15. paths.py:659-679 `_probe_python_major_minor`, 388-430 `_probe_python_version`, 494-552 `find_latest_python_or_explain`: version probes used for floor checks only. no. T.
16. paths.py:349 `_MIN_COMPATIBLE_PYTHON = (3, 11)`: a hard-coded floor, not a pin. no. T.

### B. Bash resolver and hot path (scripts/lib/resolve_venv.sh, scripts/install/venv_resolver.sh)

17. scripts/lib/resolve_venv.sh:212-258 `_rv_candidate_runs`: runs `"$candidate" -c 'import sys'`, pass on rc 0. yes. T+R.
18. scripts/lib/resolve_venv.sh:319-336 `_rv_pick_ranked_scan`: any `untracked/venv-*/bin/{python,python3}` that is -x and passes item 17, ranked by lock_hash/slug/legacy; no version comparison. yes. R.
19. scripts/lib/resolve_venv.sh:354-362 `HOOKS_DAEMON_VENV_PATH` branch: `-x` only, not even the probe. yes (explicit override, lower likelihood). R.
20. scripts/lib/resolve_venv.sh:411-425 and 450-487 hot-path cache `untracked/.python-cmd-cache` ("<untracked mtime> <path>"): invalidated only by the untracked/ directory mtime; served if the path is own-venv shaped and `-x`. Neither mtime nor `-x` changes when the system Python changes, so a cached py311 venv path keeps being served. yes. (No cache file present in this checkout at search time.) T+R.
21. scripts/lib/resolve_venv.sh:518-526 cache write after resolution: records whatever paths.py returned. yes (same root as 20). R.
22. scripts/lib/resolve_venv.sh:574-588 `resolve_venv_python_in_venv`: exec-bit check only; used by `venv_lock_hash_matches`. yes. R.
23. scripts/lib/resolve_venv.sh:386-400 `--fallback-target` uses `find_latest_python "3.11"`: newest on PATH, which can differ from the minor of an existing venv. unsure. R.
24. scripts/install/venv_resolver.sh:60-74: thin shim over the canonical library. yes by delegation. R.
25. src/claude_code_hooks_daemon/skills/hooks-daemon/scripts/_resolve-venv.sh:31-42: thin shim; exports PYTHON from `resolve_venv_python`. yes by delegation. R. Consumers named in its header: daemon-cli.sh, health-check.sh, init-handlers.sh (bodies not read).

### C. Hook library and entry points

26. init.sh:1424-1446 `_resolve_python_cmd`: PYTHON_CMD = `resolve_venv_python` output; inherits items 17-21. yes. R.
27. init.sh:1675-1714 `validate_venv`: checks -f, -x, then `"$PYTHON_CMD" -c "import claude_code_hooks_daemon"`; its message names "Python version mismatch". This verifies importability. no for selection; but it runs only at daemon start (init.sh:1998) and only reports, it does not trigger a rebuild (see 29). R.
28. init.sh:2196-2198 `_is_daemon_installed`: `[[ -f "$PYTHON_CMD" ]]`. yes (existence as installed). R.
29. init.sh:2329-2331, 2363-2389 `_venv_self_heal` / `_venv_driver_verb`, called only from ensure_daemon's VENV_MISSING diagnosis: self-heal runs only when the resolver finds NO venv. A resolvable wrong-minor venv never triggers it. yes. This is the "self-heal never triggers" half of the hazard. R.
30. init.sh:1385-1414 `_detect_unsupported_python`: compares system python3 to the pyproject floor; does not compare it to the venv's minor. unsure. T+R.
31. init.sh:1760-1781 `_hooks_daemon_run_cli_helper`: runs a snippet with `$PYTHON_CMD`. yes by delegation. R.
32. init.sh:2250-2264 `_daemon_orphan_venv_present`: any `untracked/venv-*` dir counts as present; documented as presence-only. no. R.
33. bin/hooks-daemon:270-282 (and src/claude_code_hooks_daemon/install/templates/hooks-daemon, same shape at about :270): `PYTHON=resolve_venv_python`, then only `[ -x "$PYTHON" ]` before `exec "$PYTHON" -m claude_code_hooks_daemon.daemon.cli`. A wrong-minor venv gives ModuleNotFoundError at start. yes. R.
34. bin/hooks-daemon:145-172 `_run_venv_free_verb` repair arm: the venv build is offered only when no venv resolves; with a resolvable wrong-minor venv the normal path runs. yes (same gating as 29). R. The `signal` arm uses system python3 checked against the floor by python_floor.py: no.
35. scripts/run-qa-runner.sh:48-60: `PYTHON_BIN=resolve_venv_python`, then `-m claude_code_hooks_daemon.qa.runner`. yes by delegation. R.
36. scripts/venv-include.bash:53-71, 97-106: `VENV_DIR` from `resolve_venv_dir --fallback-target`; `venv_exists` is dir + `-f bin/python3`; `ensure_venv` returns early ("Venv exists"). yes. Sourced by scripts/qa/run_lint.sh:23, scripts/qa/run_tests.sh:79, scripts/test.bash:19, which all call `ensure_venv`, so QA can run against the wrong environment silently. R.
37. scripts/venv-include.bash:299-314 `venv_tool`: only `-f tool_path` (shebang points into the venv). yes. `venv_run` (283-294) checks `import pytest` first: partial protection, no. R.

### D. Install / upgrade / repair

38. src/claude_code_hooks_daemon/install/client_validator.py:604-640: resolves via `resolve_existing_venv_python`, then runs `import claude_code_hooks_daemon`. no (verifies importability). R. Counter-example.
39. scripts/install/venv.sh:1078-1103 `_venv_is_fresh` and 1146-1175 `ensure_venv`: path keyed by fingerprint from the build interpreter (good), but reuse decided by lock_hash (item 11) or the `.daemon-version` stamp (`venv_version_matches`, 266-300) with no interpreter-minor check. yes. R.
40. scripts/install/venv.sh:330-373 `venv_lock_hash_matches`: runs paths.py under the venv's own bin/python (a symlink to the current system python, possibly another minor than the site-packages). unsure. R.
41. scripts/install/venv.sh:127-187 `verify_venv`: -f, -x, `--version`, then imports the package with `<daemon_dir>/src` prepended to sys.path, so the package can import from source even if the venv's site-packages are unreachable. unsure. R.
42. scripts/install/venv.sh:1349-1380 and 1544-1550 `create_venv_at_path`: compares the built version with the requested one via `_VENV_VERSION_PROBE`. no. Counter-example: the check the class lacks elsewhere.
43. scripts/install/venv.sh:1656-1731 `eager_cleanup_stale_venvs`: runs paths.py under `$current_abs/bin/python` if -x. unsure (exec bit only; failure mode is a skipped cleanup with a WARNING). R.
44. scripts/venv_bootstrap.sh:260-290 `_vb_build_under_lock`: success = `resolve_venv_python` returns anything. A leftover wrong-minor venv can make a build read as success; and the hook path only runs when nothing resolves (29). yes. R.
45. scripts/venv_bootstrap.sh:137-174 `_vb_gate`: newest interpreter via `find_latest_python`; fingerprint from it. no (self-consistent). R.
46. src/claude_code_hooks_daemon/daemon/cli.py:2825-2945 `cmd_repair` / `_repair_venv_locked`: target keyed on `python_venv_fingerprint` of the running CLI interpreter, `uv sync` with UV_PROJECT_ENVIRONMENT, then verifies `import claude_code_hooks_daemon`. Does not compare the minor the venv ends up with against the fingerprint's py tag. unsure. R.
47. src/claude_code_hooks_daemon/daemon/cli.py:2810-2822 `_warn_if_venv_not_built_for_source`: judges lock drift only, not interpreter drift. yes (same blind spot, in the advisory). R.
48. src/claude_code_hooks_daemon/handlers/session_start/unproven_venv_advisor.py:45-100: advises on lock drift of sys.prefix and on unproven venvs; no interpreter-minor drift. unsure. R.
49. scripts/upgrade_version.sh:~679-700: `VENV_PYTHON="$(resolve_existing_venv_python "$DAEMON_DIR")"` used for existing-venv reads and gates; inherits 17-21. yes by delegation (rest of the script not read line by line). T+R partial.
50. scripts/upgrade.sh:929-934 and scripts/install/rollback.sh:121-150: record `python_version` of the existing venv for metadata. no (reporting only). T.

### E. Positive controls and non-hazards

51. scripts/setup_worktree.sh:344-364: compares the `-py{MM}-` tag in the venv dir name to `sys.version_info` of the venv python and refuses a mismatch. no. The existing correct name-versus-actual pattern in the tree; it runs once, on the venv just built.
52. src/claude_code_hooks_daemon/python_floor.py; install/upgrade_gate_standalone.py:42-45: floor checks on the running interpreter. no.
53. pyproject.toml:166, 186, 234: `target-version py311/py312/py313`, mypy `python_version = "3.11"`. Hard-coded versions, but tool targets, not interpreter selection. no.
54. scripts/qa/run_pyright_check.py:105-115 `default_interpreter` returns `sys.executable`. no. T.
55. src/claude_code_hooks_daemon/core/project_context.py:75-137 `_ensure_self_install_lsp_venv_symlink`, and pyrightconfig.json `"venv": "lsp-venv"`: `untracked/lsp-venv` is pointed at `venv-<fingerprint>` from sys.prefix at daemon start, repointed only when a daemon starts from a venv directly under untracked/. If the daemon cannot start (the lockout), the link keeps pointing at the old-minor venv and pyright resolves against it. unsure. In this checkout the link resolves to venv-workspace-py313-0d6d49c6 (pyvenv.cfg version_info 3.13.5), matching the host. R.
56. scripts/lib/python_discovery.sh:159-180 (globs `python3.[0-9]`, `python3.[1-9][0-9]`) and paths.py:363: version-agnostic discovery. no.
57. templates/hooks-daemon:14, bin/hooks-daemon:14, utils/cli_command.py:12: comments noting `include-system-site-packages=false` (why a wrong venv cannot see packages). no.

### F. Not examined in depth (coverage gaps)

- scripts/bootstrap-self-install.sh:55-62 passes `command -v python3` as HOOKS_DAEMON_PYTHON to `resolve_venv.sh dir --fallback-target`; not read beyond those lines. unsure.
- .github/workflows/qa.yml:131-134, 330-334, 600-603 resolve the venv via resolve_venv.sh and assert equality with `$VENV_DIR/bin/python`; fresh runners, low exposure. unsure.
- daemon.sh, provision.sh, .claude/provision.sh, install.sh, install.py, scripts/install/{prerequisites,project_detection,detect_location,hooks_deploy,branch_install,upgrade_transition,validation,daemon_control}.sh, scripts/debug_hooks.sh, scripts/health_check.sh, scripts/validate_worktrees.sh, skills/hooks-daemon/scripts/{daemon-cli,health-check,init-handlers,install,optimise-invoke}.sh: matched the broad venv/python grep but were not read in detail. They source the resolver (inherit 17-24) or discover Python; individual instances are not itemised.
- .claude/hooks/* wrappers: a spot check of pre-tool-use shows only the python3 socket transport (no venv selection); the others share that shape and were not read individually.
- relay/hooks_relay.rs: only a comment mentions the "python3 transport"; it locates no interpreter. no.
- No hard-coded `lib/python3.X/site-packages` path was found in src/ or scripts/ outside comments.

## Technique attribution

Found by text search (and read only to confirm):
- Version-bearing spellings: paths.py:147, 214-221, 235, 349, 363, 624; python_fingerprint.sh:23, 81; setup_worktree.sh:344-364; pyproject.toml:166, 186, 234; init.sh:1056, 1403; venv.sh:206, 1331.
- The `import sys` probes (paths.py:961, resolve_venv.sh:216/221) and the cache filename `.python-cmd-cache` (resolve_venv.sh:456-467).
- The file inventory of everything that sources or calls the resolver (venv-include.bash, run-qa-runner.sh, bin/hooks-daemon, the template, _resolve-venv.sh).
- The positive controls (setup_worktree.sh name-vs-actual check, create_venv_at_path version check).

Found only by reading; no text search could have found or judged them:
- That the `import sys` probe is the only liveness test and so passes for a symlink to a different-minor system python (items 1, 17).
- That the scan fallback (5, 6, 18) is what picks the old venv once the fingerprint misses, because the resolver runs under the venv's own interpreter.
- That the hot-path cache's two invalidators (untracked mtime, `-x`) are both blind to a system Python change (20).
- That self-heal and repair are gated on "nothing resolves" (29, 34, 44), so a resolvable wrong-minor venv leaves them dormant.
- That freshness is lock_hash/stamp only, with no interpreter component (11, 39), and that cmd_repair and the advisories share the blind spot (46-48).
- That validate_venv and client_validator import the package and so are not instances (27, 38); that venv_run partly protects and venv_tool does not (37).
- That `_best_ranked_scan_candidate` does not probe at all while its diagnostics sibling does (6).
- The lsp-venv symlink's stale-on-failure behaviour (55).

## Searches run

- grep -rnIE "python3\.[0-9]+|py3[0-9]+|lib/python|site-packages|version_info|python_version" over src scripts bin .claude/hooks .claude/hooks-daemon .github init.sh Makefile pyproject.toml (excluding cyber-flag, .git, worktrees, node_modules, semgrep, CLAUDE, .venv, untracked, tests): 124 lines, all read.
- grep -rIlE "venv|bin/python|python3" over src scripts bin .claude/hooks .claude/hooks-daemon .github init.sh install.sh install.py daemon.sh provision.sh .claude/init.sh .claude/provision.sh pyproject.toml contracts examples relay screen, minus .md and .lock: about 250 files, triaged by name then by targeted grep. A first attempt rooted at `.` was refused by the guard because it would have read a protected file; it was narrowed to named roots, and nothing protected was read.
- Targeted greps: venv/bin/python/python3 in init.sh, scripts/venv_bootstrap.sh, scripts/install/venv.sh; PYTHON_CMD and python-cmd-cache in init.sh; venv, python_path, sys.executable, version_info, resolve_existing in client_validator.py, repair_install.py, venv_lock.py, unproven_venv_advisor.py, install_stamp.py, metadata.py; venv/python in the QA shell scripts, daemon.sh, .claude/hooks/pre-tool-use, the template, relay, bootstrap-self-install.sh, qa.yml; lsp-venv over src, scripts, bin, hooks, rules, pyrightconfig.json, pyproject.toml.
- Read in full or in the relevant ranges: paths.py 190-370, 560-690, 905-1394, 2795-3025; resolve_venv.sh (all); venv_resolver.sh (all); venv-include.bash (all); bin/hooks-daemon (all); _resolve-venv.sh; venv.sh 120-209, 300-450, 1070-1315, 1575-1731; venv_bootstrap.sh 115-315, 655-733; init.sh 1380-1500, 1670-1785, 1985-2015, 2180-2210, 2240-2390; cli.py 2780-2970; project_context.py 70-140; setup_worktree.sh 340-375; run-qa-runner.sh 30-110; upgrade_version.sh 670-700; run_pyright_check.py 100-135.
- Live state: untracked/ holds one venv, venv-workspace-py313-0d6d49c6, and no .python-cmd-cache; system python3 is 3.13.5; the lsp-venv target reports 3.13.5.

## Totals

57 numbered candidates. yes: 29 (1-8, 11, 17-22, 24-26, 28, 29, 31, 33-37 venv_tool only, 39, 44, 47, 49). unsure: 11 (10, 12, 13, 23, 30, 40, 41, 43, 46, 48, 55), plus the section F items. no: the rest (counter-examples, floors, reporting).

Distinct root causes behind the yes items: (a) liveness = exec bit or `import sys`; (b) version-blind scan fallback over `venv-*`; (c) hot-path cache invalidated only by untracked/ mtime; (d) freshness by lock_hash or stamp with no interpreter component; (e) self-heal, repair and advisories gated on "nothing resolves" or on lock drift only; (f) success judged by "the resolver returns something".
