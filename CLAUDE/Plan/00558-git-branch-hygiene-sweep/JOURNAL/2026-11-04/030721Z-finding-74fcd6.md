## 03:07 · finding · —

Main went red after the Plan 00558 merges, and was fixed forward in 42502078a (merge of fix-main-red-558) and 523df2d35.

CI run 41739164451 (71fe4edc6, Python 3.11) failed repo-wide invariant tests that per-branch targeted QA never selects: the example and reference config completeness checks, handler instantiation (BranchStopGuardBase discovered as a handler), the priority-band doc row, evasion classification of BranchCreationGuardHandler, session-mode reader declarations, the fixture git budget, bare-wrapper runtime strings, and protected-path filtering of git-enumerated content (branch_inventory). A local full run (scripts/qa/run_tests.sh, 1h48m) also found one more Plan 00558 defect, fixed in 523df2d35: the evacuation recorder's acceptance probe pointed at untracked/scratch.

Lesson: these invariants are cross-cutting, and targeted QA's scope selection does not reach them when a plan adds handlers. Before calling a handler-adding plan done, run the full suite once, or at least tests/integration plus the repo-wide invariant tests under tests/unit/test\_\*.py.

Local-only failures, not Plan 00558's and green in CI:

- tests/unit/qa/test_run_format_check.py::test_an_unparseable_file_fails_the_json_too: the local venv's black 26.10.1 prints "Error: cannot parse ...", which scripts/qa/run_format_check.sh does not parse into the file name. Latent: it will hit CI when CI's black moves. Follow-up needed.
- tests/integration/test_client_owned_asset_lint.py: the local ruff flags ISC004/SIM102/SIM103 in the tracked asset .claude/ccy/claude-supervise.py (last changed by Plan 00538). A newer-ruff drift, the same class as above.
- shellcheck timeout and test_doc_write_jail (live worktrees during the run), plus the install e2e CLAUDE.md rewrite: run-environment artefacts.

Guard gap seen: R-BRANCH-STOP-GUARD blocked a coordinator stop over a branch a running sub-agent was still committing to.
