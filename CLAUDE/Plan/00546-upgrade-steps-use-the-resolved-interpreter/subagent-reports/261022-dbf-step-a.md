# DBF step A handoff: bare-python-invocation widened, QA/CI instances fixed (Plan 00546 Task 3.1)

Branch worktree-issue-130-p3-dbf. Rule commit ac99acf7b; the QA/CI fixes and this report are in the commit after it (see `git log`).

## Rule changes (scripts/qa/check_bare_python_invocation.py)

Per the coordinator rulings, the rule now also reports a bare `python` / `python3` stored as a VALUE:

- defaults `${VAR:-python3}`, `${VAR:=python3}`, `${VAR-python3}`, `${1:-python3}`, also nested inside another default and with quoted values;
- assignments `VAR=python3`, `VAR="python3"`, `VAR='python3'`, also after `local`, `export`, `declare`, `readonly`, `typeset` (added to the prefix words).

Kept narrow: not reported in `echo` / `printf` arguments (tracked by the current command name, saved and restored across substitutions), not `${VAR:+python3}`, not `python3.12`, not `command -v python3`, not prose, comments or heredoc bodies. The tokenizer was NOT extended into heredoc bodies.

`CLAUDE/Plan/` is excluded (`_PLAN_PARTS`): plan prototypes and benchmarks never run on client hosts or by install, upgrade or dispatch. The reasoning is in the module docstring and the constant comment, and a test covers it (including `Completed/`, and that `CLAUDE/UPGRADES/` is still scanned).

No allowlist entries added.

## Tests (tests/unit/qa/test_check_bare_python_invocation.py)

Written first (RED), then GREEN: 15 positive value cases, 16 clean cases, a line-number case, the plan-exclusion scan test and a value-default scan test. File total 102 passed. Wider run (run_lint, run_shell_check, capture_corruption audit, perf_sweep_marker, llm_qa wiring, ci job timeouts and relay, lint gate integrity, gate scope, tests/unit/scripts): 703 passed after the one fix below.

tests/integration/test_qa_lint_gate_integrity.py extracts the run_lint.sh parser by regex; the regex now matches `"${VENV_PYTHON}" << 'EOF'`.

## The QA/CI fixes (13 instances found by the detector in these 8 files; the brief said 14)

| File                                       | Change                                                                                                                                                |
| ------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| scripts/qa/run_all.sh                      | summary heredoc runs on `"${VENV_PYTHON}"` (already resolved at the top via `resolve_existing_venv_python`)                                           |
| scripts/qa/run_lint.sh                     | parser heredoc on `"${VENV_PYTHON}"` (already sourced venv-include.bash)                                                                              |
| scripts/qa/run_type_check.sh               | parser heredoc and summary `-c` on `"${VENV_PYTHON}"`                                                                                                 |
| scripts/qa/run_tests.sh                    | summary `-c` on `"${VENV_PYTHON}"`                                                                                                                    |
| scripts/qa/run_shell_check.sh              | now sources venv-include.bash, exits 1 with a message if `VENV_PYTHON` is not executable; three heredocs on `"${VENV_PYTHON}"`                        |
| scripts/qa/run_capture_corruption_check.sh | same sourcing and guard; audit and summary on `"${VENV_PYTHON}"` (the old "pure stdlib, no venv" comment is gone)                                     |
| scripts/ci/emit_tier.bash                  | requires `HOOKS_DAEMON_PYTHON` (`:?` plus an executable check), runs both scripts on it                                                               |
| scripts/ci/full_suite_if_unmapped.bash     | interpreter is `bash scripts/lib/resolve_venv.sh python "$PWD"` (the exact call the Install step asserts), executable check, fails loudly             |
| .github/workflows/qa.yml (classify job)    | new `actions/setup-python@v5` 3.11 step; Classify step passes `HOOKS_DAEMON_PYTHON="$(command -v python)"` to emit_tier.bash with `set -euo pipefail` |

No fallback to a PATH python3 anywhere. These ran under the existing unit tests; the CI path itself is untested here (no runner).

## Not fixed, by ruling

`.claude/skills/acceptance-test/invoke.sh:72`: `python3 -c` inside a heredoc that writes an agent prompt. No resolved interpreter exists in that script (the agent calls `./bin/hooks-daemon`), so it is left. The detector cannot see it (heredoc body). For step B to decide.

## Detector blind spots noted (not widened, per "no wider than that")

- A literal bare name passed as an argument: `scripts/setup_worktree.sh:287` `ensure_venv "${WORKTREE_DIR}" "v${DAEMON_VERSION}" python3`.
- Result-of-probe forms: `PYTHON_CMD="$(command -v python3)"` (scripts/bootstrap-self-install.sh:55), `system_python="$(command -v python3)"` (bin/hooks-daemon:193 and its template), the candidate loop in .claude/ccy/claude-supervise.
- `.github/workflows/qa.yml` and Python shebangs are not shell files for this rule.

## REMAINING instances for step B (34 violations, file:line:text)

```
CLAUDE/UPGRADES/v2/v2.10-to-v2.11/migration-script.sh:85:python3 << 'PYTHON_SCRIPT'
CLAUDE/UPGRADES/v2/v2.10-to-v2.11/migration-script.sh:160:python3 << 'PYTHON_SCRIPT'
CLAUDE/UPGRADES/v2/v2.11-to-v2.12/migration-script.sh:61:python3 << 'PYTHON_SCRIPT'
CLAUDE/UPGRADES/v2/v2.11-to-v2.12/migration-script.sh:96:if python3 -c "import yaml; yaml.safe_load(open('$CONFIG_FILE'))" 2>/dev/null; then
CLAUDE/UPGRADES/v2/v2.11-to-v2.12/verification.sh:59:if python3 -c "import yaml; yaml.safe_load(open('$CONFIG_FILE'))" 2>/dev/null; then
CLAUDE/UPGRADES/v2/v2.11-to-v2.12/verification.sh:115:PYTHON_BIN="python3"
CLAUDE/UPGRADES/v2/v2.11-to-v2.12/verification.sh:125:PYTHON_BIN="python3"
init.sh:325:python3 -c "$recovery_py"'
init.sh:344:python3 -c "$recovery_py"'
init.sh:360:python3 -c "$recovery_py"'
init.sh:390:python3 -c '
init.sh:581:if python3 -c '
init.sh:1128:python3 -c '
init.sh:1394:found="$(python3 -c 'import sys; v = sys.version_info; print("%d.%d.%d" % (v[0], v[1], v[2]))')" || found=""
init.sh:1728:python3 -c "$recovery_py"'
init.sh:3041:_hd_answer="$(python3 -c "
init.sh:3727:python3 -c "
install.sh:123:python3 "$DAEMON_DIR/install.py" --force
scripts/detect_location.sh:118:local_self_install=$(python3 -c "
scripts/health_check.sh:81:if python3 -c "import yaml; yaml.safe_load(open('$CONFIG_FILE'))" 2>/dev/null; then
scripts/health_check.sh:124:SELF_INSTALL=$(python3 -c "
scripts/health_check.sh:158:SELF_INSTALL=$(python3 -c "
scripts/install/prerequisites.sh:222:python3 -c 'import sys; print(".".join(map(str, sys.version_info[:3])))' 2>/dev/null
scripts/install/prerequisites.sh:237:python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))' 2>/dev/null
scripts/install/project_detection.sh:178:self_install=$(python3 -c "
scripts/install/python_fingerprint.sh:43:local python_bin="${1:-python3}"
scripts/install/venv.sh:1137:local python_bin="${3:-python3}"
scripts/install/venv.sh:1176:local python_bin="${3:-python3}"
scripts/install_version.sh:375:VENV_PATH=$(ensure_venv "$DAEMON_DIR" "$INSTALLED_VERSION" "${HOOKS_DAEMON_PYTHON:-python3}")
scripts/setup_worktree.sh:49:python3 - "$version_file" <<'PY'
scripts/setup_worktree.sh:215:if ! report="$(python3 - "${paths_module}" "${worktree_dir}" "${self_install}" <<'PY'
scripts/upgrade_version.sh:920:VENV_PATH=$(ensure_venv "$DAEMON_DIR" "$INSTALL_STAMP" "${HOOKS_DAEMON_PYTHON:-python3}")
scripts/upgrade_version.sh:1289:VENV_PATH=$(ensure_venv "$DAEMON_DIR" "$INSTALL_STAMP" "${HOOKS_DAEMON_PYTHON:-python3}")
scripts/venv-include.bash:137:python3 -m venv "${VENV_DIR}"
```

Not detected, listed for completeness: `.claude/skills/acceptance-test/invoke.sh:72`, `scripts/setup_worktree.sh:287` (argument), and the probe-result forms above.

llm_qa was not run (step B owns it).
