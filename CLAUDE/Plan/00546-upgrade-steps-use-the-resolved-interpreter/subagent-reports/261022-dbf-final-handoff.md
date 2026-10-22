# DBF final pass handoff (Plan 00546 Task 3.1)

Stopped at the context budget. Task 3.1 is NOT ticked; the final report 261022-dbf-final.md is NOT written; the final QA run is NOT green yet.

## Done (committed on worktree-issue-130-p3-dbf)

- Bare-python checker: exactly B2's 11 hits remained; all 8 allowlist entries added to scripts/qa/bare-python-allowlist.json (covers 11 lines; checker green, no stale entry).
- scripts/qa/error_hiding_exclusions.json: removed the stale entries for get_python_major_minor, detect_install_mode, scripts/detect_location.sh (line 117) and prerequisites get_python_version; realigned run_shell_check.sh from line 21 to 30 (its code had moved; a realign, not a new exclusion). audit_error_hiding.py passes.
- detect_install_mode: kept failing loudly; its only caller (detect_and_validate_project, project_detection.sh) now stops with fail_fast on non-zero. test_install_helpers_capture_uncorrupted.py passes (13).
- v2.11-to-v2.12/verification.sh: every PASS_COUNT/FAIL_COUNT increment is now X=$((X + 1)) (FAIL_COUNT had the same set -e bug).
- Release note 017-install-and-upgrade-scripts-run-the-resolved-interpreter.md.
- Coordinator ruling applied: the three `shellcheck disable=SC1090` lines were replaced by `# shellcheck source=scripts/lib/resolve_venv.sh`. shellcheck -x shows no SC1090/SC1091 on those files (3 remaining findings are older, unrelated lines: SC2034, SC2162, SC2181); check_inline_suppressions.py is clean (0 violations). In all three scripts an empty PYTHON_BIN after the resolver fails loudly with a named message (the two migration scripts exit 1; verification.sh prints it to stderr and its checks FAIL).
- Black reformat of scripts/qa/check_bare_python_invocation.py committed.

## Left

1. Run targeted QA once through the entry point on a STILL tree and read the summary:
   `FULL_QA_LOCK_WAIT_SECONDS=3600 ./scripts/qa/llm_qa.py changed --allow-unmapped > untracked/scratch/qa-dbf-final3.txt 2>&1`
   First run (before the fixes above): 37/41 pass; failures were format (fixed, committed), inline_suppressions (fixed), and changed_tests: "pytest selected 165 test files but executed no tests", the pytest subprocess timed out after 1800 s. The 9 test files this branch changed all pass individually in 3-8 s each (per-file loop in untracked/scratch/per_file.sh), so the hang is in one of the other mapped files, or the run was waiting on a host lock. If it recurs, find the hanging file by running the mapped files one by one with `timeout 300`. Do not edit the tree while QA runs (it makes the result "not recorded for this tree").
2. If green: tick Task 3.1 and the "QA rule finds the class" success criterion in PLAN.md.
3. Write 261022-dbf-final.md from /root/.claude/plugins/cache/defence-before-fix/defence-before-fix/0.1.1/skills/dbf/references/REPORT-TEMPLATE.md, every heading filled. Facts: spec 1.1.0 (fetched); defence-red commit ab1793dce; widening ac99acf7b; sweep 41 at red, 34 after step A (QA/CI fixed; Plan dir excluded), 18 after B1+B3, 11 after B3 final, 0 after allowlist of 11; independent-search report 261022-dbf-independent-search.md (search found probe-result forms, default args, escaped heredoc line, python shebangs; the rule initially missed value defaults and `ensure_venv ... python3` argument and the invoke.sh heredoc, fixed by widening and by B1/B3). Next wider rule considered, not built: heredoc bodies that generate agent-run shell (invoke.sh line 72 was the only instance; fixed with jq; a general reader needs to tell shell-that-generates-prompts from data, high false-positive risk).
4. Owner items to list unchanged: probe-result forms (scripts/bootstrap-self-install.sh:55 `command -v python3`, bin/hooks-daemon:193 and its template, .claude/ccy/claude-supervise candidate loop); 54 Python files with `#!/usr/bin/env python3` shebangs (about 5 plausibly client-run: install.py, scripts/debug_info.py, scripts/handler_status.py, core/error_response.py, scripts/audit_handler_config_keys.py); .github/workflows/qa.yml `python`/`command -v python` lines; verification.sh hint text with `python3 -c` (not executed); upgrade_version.sh uses GATE_PYTHON_FLOOR as the build floor (split if they should differ); resolver multi-line trace prints before the HOOKS_DAEMON_PYTHON fallback in detect_install_mode; the setup_worktree.sh nesting guard prevents an end-to-end run (tested by function extraction).
5. Commit.
