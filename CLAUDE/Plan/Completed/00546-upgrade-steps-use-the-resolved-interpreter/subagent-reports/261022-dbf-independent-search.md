# Independent search: bare python3 / python in first-party shell (Plan 00546 Phase 3)

The dispatch contained a class description only, no rule or pattern. I did not open the excluded paths. `git diff --name-only 62733426f -- scripts/qa` returned nothing, so there were no post-commit scripts/qa files to skip. I did not run the detector.

Universe: 6019 tracked files minus untracked/, .venv, tests/fixtures and the check_bare_python files. 325 of them are non-.py/.md/.json files (the shell universe). .py files were checked for shebangs and embedded shell.

Notes: `.claude/init.sh` is a symlink to `init.sh`, and `.claude/provision.sh` to `provision.sh`. `bin/hooks-daemon` is byte-identical to `src/claude_code_hooks_daemon/install/templates/hooks-daemon` (cmp verified), so each hit there counts twice. Confidence: C = confident, U = unsure. Technique: T = text search, R = reading.

## A. Executed bare python3 / python in client-host paths (install, upgrade, hook dispatch)

| # | file:line | text | form | conf | tech |
|---|---|---|---|---|---|
| A1 | init.sh:325 | `python3 -c "$recovery_py"'` | command position, hook dispatch (recovery check) | C | T |
| A2 | init.sh:344 | `python3 -c "$recovery_py"'` | `_hooks_daemon_recovery_command` | C | T |
| A3 | init.sh:360 | `python3 -c "$recovery_py"'` | `_hooks_daemon_recovery_advice` | C | T |
| A4 | init.sh:390 | `python3 -c '` | `_hooks_daemon_stdin_is_provision_command` | C | T |
| A5 | init.sh:581 | `if python3 -c '` | conditional command position | C | T |
| A6 | init.sh:1128 | `python3 -c '` | JSON answer builder, no-jq branch | C | T |
| A7 | init.sh:1728 | `python3 -c "$recovery_py"'` | `_hooks_daemon_root_is_this_install` | C | T |
| A8 | init.sh:3041 | `_hd_answer="$(python3 -c "` | `$(python3 ...)` transport rung | C | T |
| A9 | init.sh:3727 | `python3 -c "` | command position | C | T |
| A10 | scripts/install/prerequisites.sh:222 | `python3 -c 'import sys; print(".".join(map(str, sys.version_info[:3])))'` | version getter after `command -v python3` (218) | U (see C3) | T |
| A11 | scripts/install/prerequisites.sh:237 | `python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))'` | same, after 233 | U (see C3) | T |
| A12 | scripts/install/project_detection.sh:178 | `self_install=$(python3 -c "` | `$(python3 ...)` at install; `command -v python3` guard at 172 | C | T |
| A13 | scripts/health_check.sh:81 | `if python3 -c "import yaml; yaml.safe_load(open('$CONFIG_FILE'))"` | command position | C | T |
| A14 | scripts/health_check.sh:124 | `SELF_INSTALL=$(python3 -c "` | `$(python3 ...)` | C | T |
| A15 | scripts/health_check.sh:158 | `SELF_INSTALL=$(python3 -c "` | `$(python3 ...)` | C | T |
| A16 | scripts/detect_location.sh:117-118 | `if command -v python3 ...; then local_self_install=$(python3 -c "` | probe then executed | C | T |
| A17 | install.sh:123 | `python3 "$DAEMON_DIR/install.py" --force` | legacy installer path | C | T |
| A18 | scripts/venv-include.bash:137 | `python3 -m venv "${VENV_DIR}"` | creates the venv with PATH python3 | C | T |
| A19 | scripts/venv-include.bash:57 | `VENV_PYTHON="${VENV_DIR}/bin/python3"` | venv path, not a bare name; listed for pairing with 137 | U, likely not the class | T |
| A20 | scripts/upgrade_version.sh:920 | `ensure_venv "$DAEMON_DIR" "$INSTALL_STAMP" "${HOOKS_DAEMON_PYTHON:-python3}"` | bare-name default handed to ensure_venv, which executes it | C | T (second pass) |
| A21 | scripts/upgrade_version.sh:1289 | same expression | same | C | T (second pass) |
| A22 | scripts/install_version.sh:375 | `ensure_venv "$DAEMON_DIR" "$INSTALLED_VERSION" "${HOOKS_DAEMON_PYTHON:-python3}"` | same | C | T (second pass) |
| A23 | scripts/install/venv.sh:1137 | `local python_bin="${3:-python3}"` (ensure_venv) | default argument executed later | C | T (second pass) |
| A24 | scripts/install/venv.sh:1176 | `local python_bin="${3:-python3}"` | same shape | C | T (second pass) |
| A25 | scripts/install/python_fingerprint.sh:43 | `local python_bin="${1:-python3}"`, run as `"$python_bin" -c` | default for an executed interpreter | C | T (second pass) |
| A26 | scripts/setup_worktree.sh:287 | `ensure_venv "${WORKTREE_DIR}" "v${DAEMON_VERSION}" python3` | literal bare name passed as the interpreter | C | T |
| A27 | scripts/setup_worktree.sh:49 | `python3 - "$version_file" <<'PY'` | `_read_daemon_version`, command position | C | T |
| A28 | scripts/setup_worktree.sh:208, 215 | `command -v python3` guard, then `report="$(python3 - ... <<'PY'` | probe then `$(python3 ...)`; comment at 190 says the system python3 is deliberate | U (candidate bootstrap/measurement) | T |
| A29 | scripts/bootstrap-self-install.sh:55 | `PYTHON_CMD="$(command -v python3)"`, used at 62 (HOOKS_DAEMON_PYTHON) and 65 (`uv sync --python`) | probe result executed / used to build the venv, before any venv exists | U (candidate bootstrap probe) | T |
| A30 | bin/hooks-daemon:193 | `if ! system_python="$(command -v python3)"; then` (executed about line 212 as `"$system_python" "$floor_script"`) | probe result executed in the signal channel | U (candidate bootstrap probe, it runs the floor check on it) | T |
| A31 | src/claude_code_hooks_daemon/install/templates/hooks-daemon:193 | identical to A30 | template copy | U (as A30) | T |
| A32 | .claude/skills/acceptance-test/invoke.sh:72 | `TOTAL_TESTS=\$(python3 -c "import json; ...` | inside a heredoc writing a markdown prompt, escaped, not executed here; it instructs the agent to run bare python3 | U, text only | T |

### Candidate bootstrap probes (job is to find or validate an interpreter before a venv exists)

| # | file:line | text | reasoning |
|---|---|---|---|
| C1 | init.sh:1379, 1394 | `[[ -z "$(command -v python3)" ]]` then `found="$(python3 -c 'import sys; v = sys.version_info; ...')"` | `_detect_unsupported_python` reads PATH python3's version to refuse an unsupported one. A probe by purpose, but the same file runs A1-A9 on that python3 |
| C2 | .claude/ccy/claude-supervise:64-65, 95 | `command -v python3`, `version_of python3`, loop `python3.14 ... python3.11 python3` | The loop validates each candidate with `is_supported` before use, so it is a true bootstrap picker. Line 64 is the diagnostic. Dev-container supervisor, not a client path |
| C3 | scripts/install/prerequisites.sh:218-237 | A10 and A11 | System dependency check of python3 (3.11+). A probe by purpose, but it uses the bare name rather than the discovery helper |
| C4 | A28, A29, A30/A31 | see above | Each validates or measures the system python3 before a venv exists |

## B. Dev, QA and CI scripts (not client hosts, same bare-name shape)

| file:line | text | conf |
|---|---|---|
| scripts/qa/run_all.sh:446 | `python3 << 'EOF'` | C (dev only) |
| scripts/qa/run_lint.sh:114 | `python3 << 'EOF' > "${OUTPUT_FILE}"` | C (dev only) |
| scripts/qa/run_type_check.sh:61 | `python3 << 'EOF' > "${OUTPUT_FILE}"` | C (dev only) |
| scripts/qa/run_type_check.sh:147 | `python3 -c "` | C (dev only) |
| scripts/qa/run_tests.sh:324 | `python3 -c "` | C (dev only) |
| scripts/qa/run_capture_corruption_check.sh:35 | `if python3 scripts/qa/audit_capture_corruption.py ...` | C (dev only) |
| scripts/qa/run_capture_corruption_check.sh:42 | `python3 - "${OUTPUT_FILE}" <<'PYEOF'` | C (dev only) |
| scripts/qa/run_shell_check.sh:64, 85, 157 | `python3 - << 'PYEOF' > ...`, `python3 - << PYEOF > ...`, `python3 - << PYEOF` | C (dev only) |
| scripts/ci/emit_tier.bash:22 | `base="$(python3 "${here}/last_verdict_sha.py" ...)"` | C (CI only) |
| scripts/ci/emit_tier.bash:31 | `python3 "${here}/classify_changes.py" ...` | C (CI only) |
| scripts/ci/full_suite_if_unmapped.bash:11 | `python scripts/qa/run_changed_tests.py ...` (bare `python`) | C (CI only) |
| .github/workflows/qa.yml:116, 239, 549, 611 | `python -m pip install ...` | U (CI YAML, not a shell script) |
| .github/workflows/qa.yml:120, 123, 283, 287, 553, 556, 613 | `"$(command -v python)"` | U (CI YAML, a probe whose result becomes HOOKS_DAEMON_PYTHON) |
| .github/workflows/qa.yml:161, 328 | `python scripts/qa/run_pyright_check.py --json` | U (CI YAML) |
| .github/workflows/qa.yml:624 | `python - <<'PY'` | U (CI YAML) |

## C. Historical upgrade and migration scripts (CLAUDE/UPGRADES, run during upgrades)

| file:line | text | conf |
|---|---|---|
| CLAUDE/UPGRADES/v2/v2.10-to-v2.11/migration-script.sh:85 | `python3 << 'PYTHON_SCRIPT'` | C |
| CLAUDE/UPGRADES/v2/v2.10-to-v2.11/migration-script.sh:160 | `python3 << 'PYTHON_SCRIPT'` | C |
| CLAUDE/UPGRADES/v2/v2.11-to-v2.12/migration-script.sh:61 | `python3 << 'PYTHON_SCRIPT'` | C |
| CLAUDE/UPGRADES/v2/v2.11-to-v2.12/migration-script.sh:96 | `if python3 -c "import yaml; ..."` | C |
| CLAUDE/UPGRADES/v2/v2.11-to-v2.12/verification.sh:59 | `if python3 -c "import yaml; ..."` | C |
| CLAUDE/UPGRADES/v2/v2.11-to-v2.12/verification.sh:107 | `if command -v python3 &> /dev/null; then` | C (probe, then used) |
| CLAUDE/UPGRADES/v2/v2.11-to-v2.12/verification.sh:115, 125 | `PYTHON_BIN="python3"` (fallback when the venv python is missing; executed afterwards) | C |
| CLAUDE/UPGRADES/v2/v2.11-to-v2.12/verification.sh:177 | `echo "  2. Validate config: python3 -c ..."` | text only, advice, not executed |

## D. Shebangs `#!/usr/bin/env python3` (Python files, not shell)

54 tracked Python files carry a python shebang. Plausibly run on client hosts: install.py:1, scripts/debug_info.py:1 (it also calls `which python3` at 376 and `python3 --version` at 378 via subprocess), scripts/handler_status.py:1, src/claude_code_hooks_daemon/core/error_response.py:1, scripts/audit_handler_config_keys.py:1. Confidence U: whether the shebang is ever the execution route is unconfirmed.

Dev, QA, release or CI only: .claude/ccy/claude-supervise.py, 33 scripts/qa/*.py, scripts/ci/classify_changes.py, scripts/ci/last_verdict_sha.py, scripts/release/build_github_release_body.py, scripts/release/check_startup_budget.py, src/claude_code_hooks_daemon/qa/strategy_pattern_checker.py. Docs, historical or relay: CLAUDE/AcceptanceTests/validation/validate-logs.py, two CLAUDE/Plan/Completed/00154-* bench scripts, relay/test_relay.py.

## E. Checked and found NOT to carry the class

- scripts/lib/resolve_venv.sh, scripts/install/venv_resolver.sh, scripts/upgrade.sh and the rest of scripts/install/venv.sh: comments or `bin/python` and `bin/python3` venv paths only.
- scripts/lib/python_discovery.sh, scripts/install/daemon_control.sh, validation.sh, rollback.sh, transport_env.sh, hooks_deploy.sh, env_sanitise.sh, parse_min_python.sh: comments or message text only.
- .claude/hooks/* (28 forwarders): comment hits only ("the python3 transport it already spawns"). They source init.sh.
- .claude/skills/hooks-daemon/scripts/install.sh and the src/ copy: comments only (they use `find_latest_python`).
- scripts/dummy-client-repo.sh: "python" is a subcommand name.
- relay/hooks_relay.rs, tests/integration/fixtures/*.Dockerfile, scripts/qa/semgrep/*.yaml, scripts/qa/dangerous-invocation-corpus.yaml:206 (`| env python3` as a corpus string): not shell scripts the project runs.
- Python source with shell text embedded: none found containing python3 in a shell string.

## Searches run

1. Word-boundary regex for `python` or `python3` (not preceded by alphanumeric, `_`, `.`, `-`) over the 325 shell-universe files: 431 hits.
2. Second pass for forms the first excluded: `:-python3`, `:=python`, `=python3`, `python3.N`, `/usr/bin/(env )?python`, `env python`, `uv run`, `uvx`, `pipx`, `xargs python`, `exec python`, `| python`, `py -3`, quoted `"python"` and `'python'`. This added A20-A25; the first regex missed them because `-` was in its exclusion class.
3. Shebang scan of line 1 of every tracked file for `python`: 54 Python files.
4. Search of src/, scripts/ and install.py Python sources for shell-embedded `exec python`, `command -v python`, `$(python`, `| python`, `env python`, quoted `"python3"`.
5. cmp of init.sh against .claude/init.sh and of bin/hooks-daemon against its template.

## What each technique found that the other could not

Text search only: the volume (9 hits in init.sh, the scripts/qa runners, the CLAUDE/UPGRADES scripts); the default-argument forms A20-A25, but only after the second regex pass; the 54-file shebang census.

Reading only (text search could not decide these): that A10 and A11 are guarded by `command -v python3` and are version probes (candidate bootstrap); that A29 and A30/A31 resolve with `command -v python3` and then execute the result; that A32 is escaped in a heredoc that writes a prompt and is not executed; that CLAUDE/UPGRADES verification.sh:115 and :125 `PYTHON_BIN="python3"` are executed later; that .claude/hooks/*, the resolver files and the skill install.sh hits are comment or venv-path only (a negative result); that bin/hooks-daemon and its template are identical and .claude/init.sh is a symlink, so the true count is lower than the raw matches; that venv-include.bash:57 is a venv path, not a bare name.

## Counts

- Section A: 32 rows (A1-A32). 9 in init.sh, 2 identical copies at bin/hooks-daemon:193 and its template, 1 text-only (A32), 1 likely-not-class (A19). 5 candidate bootstrap probe groups (C1-C4 plus claude-supervise in C2).
- Section B (dev, QA, CI): 14 shell lines in scripts, plus CI YAML lines.
- Section C (historical upgrade scripts): 7 executed lines, plus 1 advice text line.
- Section D: 54 shebang files, about 5 plausibly on client hosts.
