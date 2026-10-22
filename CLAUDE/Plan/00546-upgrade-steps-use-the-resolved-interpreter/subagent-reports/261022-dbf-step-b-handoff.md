# DBF step B handoff (Plan 00546 Task 3.1): analysis done for part of the list, NO code changed

The agent stopped at the context soft budget. That budget was mostly used by injected instructions. No source file has been edited. The next agent starts from the step A handoff (`261022-dbf-step-a.md`, 34 remaining instances), and from the findings below so it does not re-derive them.

## Mechanics confirmed

- Allowlist matching (`scripts/qa/check_bare_python_invocation.py:584-588`): an entry `{file, match, reason}` covers EVERY hit line in that file that contains `match` as a substring. An entry that matches nothing becomes a `bare-python-allowlist-stale` violation. One entry `python3 -c "$recovery_py"` would therefore cover init.sh:325, 344, 360 and 1728.
- The allowlist description (`scripts/qa/bare-python-allowlist.json`) and the module docstring (`check_bare_python_invocation.py:32-35`) currently say "bootstrap probes only". If the init.sh hot-path snippets are allowlisted (see below), widen BOTH texts to name that second category precisely: stdlib-only forwarder code that runs with no venv resolved, is written to the old-Python floor, and has a static fallback.

## Decided, ready to implement (FIX)

1. **`scripts/install/venv.sh:1137` (ensure_venv) and `:1176` (ensure_venv_locked), plus `scripts/install/python_fingerprint.sh:43`.** Every bash caller already passes the interpreter: `venv_bootstrap.sh:272` passes `"$python"` (from find_latest_python), `provision.sh:674/676` passes the venv python, and the tests pass `sys.executable`. The others are the instances in items 2-4, which are fixed separately. No caller relies on the default. Fix: make the argument required (`print_error` naming the function, then `return 1` when it is empty). Update the usage comments at `python_fingerprint.sh:21-34` and `venv.sh:1124`, which document the `python3` default. Add a test: `ensure_venv d v` with no third argument fails non-zero with a message, and `python_venv_fingerprint` with no argument fails. The bash tests are in `tests/integration/test_ensure_venv.py` and `test_install_helpers_capture_uncorrupted.py`.
2. **`scripts/install_version.sh:375`.** `check_all_prerequisites` (line 335) calls `check_python3` (`prerequisites.sh:72`), which exports `HOOKS_DAEMON_PYTHON` from `find_latest_python` or calls fail_fast. So the variable is always set by line 375. Fix: `fail_fast` if `${HOOKS_DAEMON_PYTHON:-}` is empty, then pass `"$HOOKS_DAEMON_PYTHON"`. Keep the `VENV_PATH=$(ensure_venv "$DAEMON_DIR"` prefix, because `tests/integration/test_install_records_gated_install.py:26` indexes on it.
3. **`scripts/upgrade_version.sh:920` and `:1289`.** The script sources `lib/python_discovery.sh` (line 87) and resets PATH to the trusted path (line 93). `HOOKS_DAEMON_PYTHON` is exported by `upgrade.sh:343` on the Layer 1 path, but may be unset when the script is run directly. Fix: add one helper that sets `BUILD_PYTHON` via `find_latest_python "$GATE_PYTHON_FLOOR" "$DAEMON_DIR/pyproject.toml"`. That call validates the override, or else globs PATH, the same way as `venv_bootstrap.sh:150`. The helper calls `fail_fast` with a named reason when nothing is found, and `print_info` names the interpreter it picked. Use it at both sites. Keep the `VENV_PATH=$(ensure_venv ` prefix (`tests/integration/test_upgrade_pre_deploy_phase_placement.py:42`).
4. **`scripts/setup_worktree.sh:287`** passes a literal `python3` to ensure_venv. The detector does not see it. Fix it the same way as item 3, using find_latest_python with the pyproject floor; check which libraries the script already sources.

## Decided pending one check (ALLOWLIST candidates)

- **`init.sh:1394` `_detect_unsupported_python`.** A genuine version probe: its whole job is to report that PATH python3 is below `requires-python` (it reads the floor from pyproject at 1383-1391) so that the advice can say "upgrade Python". Allowlist it with that reason.
- **init.sh hot-path snippets.** These are 325/344/360/1728 (`$recovery_py`), 390 (provision-command recogniser), 581 (needs-provision JSON when jq is absent), 1128, 3041 (transport rung) and 3727. They run in the hook forwarder, where no venv is resolved by design: init.sh:1343-1366 says "Venv Python only needed for daemon startup, NOT for hot path". Most of them are reached when the daemon or venv is absent. Each has a static, python-free fallback: `_hooks_daemon_static_deny` at :373, the printf answers at :609-613, and the advice at :1006-1016. Before allowlisting, the next agent must:
  - read 1128, 3041 and 3727 to confirm what reaches them (3041 is reached only after the nc rung fails, per :3014);
  - extract every snippet and check it parses under 3.8 grammar (`ast.parse(src, feature_version=(3, 8))`) and uses no 3.9+ API (`removeprefix`, `dict | dict`, runtime `list[str]`). The recovery snippet uses f-strings (3.6+).
  - If either check fails, the snippet carries the hazard. Fix it, or list it for the owner.

## Prerequisites probes (read, not decided)

- **`scripts/install/prerequisites.sh:222` `get_python_version` and `:237` `get_python_major_minor`.** Both use `command -v python3` and then run bare `python3`. Find their callers (`git grep -n get_python_version`). With no callers, delete them (YAGNI) rather than allowlist. If they are used, make them take the interpreter as an argument (the callers would have `HOOKS_DAEMON_PYTHON`).

## Not yet read

- `scripts/health_check.sh:81,124,158`, `scripts/detect_location.sh:118`, `scripts/install/project_detection.sh:178` (guarded by `command -v python3` at 172).
- `scripts/setup_worktree.sh:49,215`: a comment at :190 says the system python3 is deliberate there. Read it.
- `scripts/venv-include.bash:137` (`python3 -m venv`): check whether a version check guards it.
- `install.sh:123`: runs `install.py`, which carries the Phase 2 python_floor guard.
- `CLAUDE/UPGRADES/v2/v2.10-to-v2.11/migration-script.sh:85,160`, `v2.11-to-v2.12/migration-script.sh:61,96`, `verification.sh:59,115,125`.
- `.claude/skills/acceptance-test/invoke.sh:72` (heredoc text, not detected).

## Still owed after the fixes

`./scripts/qa/run_autofix.sh`, then a commit, then ONE targeted QA run (`FULL_QA_LOCK_WAIT_SECONDS=3600 ./scripts/qa/llm_qa.py changed --allow-unmapped > untracked/scratch/qa-dbf-b.txt 2>&1`). Then tick Task 3.1, add the release note `CLAUDE/UPGRADES/UNRELEASED/release-notes/017-<slug>.md` (same shape as 016), and write the final DBF report `261022-dbf-final.md` from the REPORT-TEMPLATE.
