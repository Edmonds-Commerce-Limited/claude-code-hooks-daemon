# Plan 00546 Task 3.1: bare-python-invocation defence (PARTIAL: detector done, fixes not started)

Stopped at the context budget after the defence-RED commit. Detector, tests, registration and sweep are done; no instance has been fixed yet; Task 3.1 is NOT ticked.

- Defence-red commit: `ab1793dce` (branch worktree-issue-130-p3-dbf). Tree is red by design: 41 instances.
- Final commit: this report's commit (see `git log -1`).
- Rule ID: `bare-python-invocation` (plus meta rules `bare-python-allowlist-stale`, `bare-python-unreadable`), documented in `scripts/qa/qa-rules.json`.
- Files: `scripts/qa/check_bare_python_invocation.py`, `scripts/qa/bare-python-allowlist.json` (empty), `tests/unit/qa/test_check_bare_python_invocation.py` (68 tests, all green except the one that needed qa-rules registration, now added), registration in `scripts/qa/llm_qa.py` (tool `bare_python_invocation`, in the changed/full step list and summariser map) and `scripts/qa/run_all.sh` (step 25c).
- Run it: `untracked/venv-*/bin/python scripts/qa/check_bare_python_invocation.py --json` (output `untracked/qa/bare_python_invocation.json`).
- QA verdict: NOT RUN through `llm_qa.py changed` (would be red on the 41 instances). The unit test file passed 67/68 before registration; the 68th (registration) should now pass.

## What the rule is

A shell file (suffix .sh/.bash, or extensionless with a sh/bash shebang; git-visible; not under tests/fixtures or untracked/worktrees) where the word `python` or `python3` is the COMMAND of a simple command. A small quote/heredoc/comment-aware tokenizer finds command position (after `;` `&&` `||` `|` `(` `{` `$(` backtick, `then`/`do`/`else`/`!`, and after `VAR=x`, `exec`, `env`, `sudo`, `nohup`, `timeout N`, `xargs`). Not reported: `command -v python3`, `which`, arguments, prose, heredoc bodies, comments, `python3.12`, resolved paths and `"$interpreter"`. Allowlist entries are `{file, match, reason}`; an entry matching nothing fails.

## Sweep: 41 instances

- Plan assets (2): `CLAUDE/Plan/00266-.../prototype/dynamic-prompt-probe.sh:18`, `CLAUDE/Plan/Completed/00154-.../assets/bench_forwarder.sh:70`. Never run by install/upgrade/dispatch. I judged these hazard-free and intended to exclude `CLAUDE/Plan/` from the scan (plan folders "record what was run", per `changed_tests_map.yaml`); NOT yet done, and it is a narrowing the owner may wish to confirm.
- Released upgrade guides (5), left for the owner, neither fixed nor excluded: `CLAUDE/UPGRADES/v2/v2.10-to-v2.11/migration-script.sh:85,160`, `v2.11-to-v2.12/migration-script.sh:61,96`, `v2.11-to-v2.12/verification.sh:59`. Frozen history, but an old client upgrading through them would run them. Owner decision: fix in place, or exclude released guides as `check_install_mode_marker.py` does.
- Hook dispatch / installer entry (11): `init.sh:325,344,360,390,581,1128,1394,1728,3041,3727`, `install.sh:123`. Most are stdlib-only JSON snippets run before any venv exists; `init.sh:1394` is the interpreter-version probe (a genuine bootstrap probe, the one clear allowlist candidate); `install.sh:123` runs `install.py`, which now carries the python_floor guard (Phase 2). Each needs reading before deciding fix versus allowlist.
- Install/support scripts (9): `scripts/detect_location.sh:118`, `scripts/health_check.sh:81,124,158`, `scripts/install/prerequisites.sh:222,237` (version probes, likely allowlist), `scripts/install/project_detection.sh:178`, `scripts/setup_worktree.sh:49,215`, `scripts/venv-include.bash:137` (`python3 -m venv`, creates the venv: bootstrap).
- QA/CI scripts (14), all fixable with the already-resolved `${VENV_PYTHON}` (sourced via `scripts/venv-include.bash`, or `resolve_existing_venv_python` in run_all.sh): `scripts/qa/run_all.sh:456`, `run_capture_corruption_check.sh:35,42` (does not source venv-include yet), `run_lint.sh:114`, `run_shell_check.sh:64,85,157`, `run_tests.sh:324`, `run_type_check.sh:61,147`, `scripts/ci/emit_tier.bash:22,31`, `scripts/ci/full_suite_if_unmapped.bash:11`.

## Missed by the rule, found by hand (search wins; not yet reflected in the rule)

- `.claude/skills/acceptance-test/invoke.sh:72`: `TOTAL_TESTS=\$(python3 -c ...)` is shell text inside a heredoc that GENERATES a skill document, so the tokenizer correctly skipped it as data. It is text an agent will run. Decide whether the rule should read that heredoc (it is a template of shell the project ships).

## Next wider rule considered (not built; owner decision per SPEC 4)

A bare name used as a VALUE that is later executed: `${VAR:-python3}` defaults and `VAR=python3`. Current instances: `scripts/install/venv.sh:1137,1176` (`ensure_venv`, `ensure_venv_locked`), `scripts/install/python_fingerprint.sh:43`, `scripts/install_version.sh:375`, `scripts/upgrade_version.sh:920,1289` (`${HOOKS_DAEMON_PYTHON:-python3}`), and historic `v2.11-to-v2.12/verification.sh:115,125`. Not built because these are interpreter-SELECTION defaults whose result `create_venv_at_path` version-checks, so I could not confirm they carry the hazard, which makes excluding them an owner question; `init.sh:1363` records a Plan 00103 rule against `${VAR:-python3}` that suggests the owner has already leaned that way.

## Open items for whoever continues

1. Decide the Plan-asset exclusion and the released-guide question above.
2. Triage and fix or allowlist the init.sh / install.sh / scripts/\* groups (read each; allowlist only interpreter-finding probes, with reasons).
3. Fix the 14 QA/CI scripts to use `${VENV_PYTHON}`.
4. Tick Task 3.1 only once every instance is fixed or reasonably allowlisted; add `CLAUDE/UPGRADES/UNRELEASED/release-notes/017-<slug>.md` only if a shipped script's behaviour changed (init.sh, install.sh, scripts/install/\*, health_check.sh do ship).
5. Run `FULL_QA_LOCK_WAIT_SECONDS=3600 ./scripts/qa/llm_qa.py changed --allow-unmapped > untracked/scratch/qa-dbf.txt 2>&1` and confirm green.
