# Task 4.1 report: branch-preflight, one report for the command and the creation deny

Branch: `plan-00594-task-4-1-branch-preflight` (from main at v3.74.0).

## What changed

- `core/branch_creation.py`: `creation_verdict` is now a thin wrapper over a new `creation_report(...)`, which judges every pool (open cap, dormancy block stage, parked, merged) and returns a `CreationReport` of `ReportSection`s (`rule_id`, `refuses`, `warns`, `lines`, `fixes`). `render_creation_report` is the one renderer; `CreationReport.verdict()` derives the allow/warn/deny decision and the first refusing rule id in the old priority order (cap, dormant, parked, merged). `creation_report_json` is the JSON form. `EXIT_CREATION_REFUSED = 4` is the named exit constant.
- `daemon/cli.py`: `hooks-daemon branch-preflight [name] [--json]`, read-only. Exit 0 when creation is allowed, 4 when refused, 1 when not a git repository. A warn-mode pool is listed but does not refuse.
- `handlers/pre_tool_use/branch_creation_guard.py`: the deny reason is the same rendered report, plus a closing pointer to `branch-preflight`; the CLAUDE.md guidance names the command.
- Fix commands: every blocker now carries its exact commands in `fixes`, and they appear in the rendered text. Two listings gained commands they lacked: cap entries without a snapshot action now name `branch-park <name> --reason ...`, and each dormant branch names its park and delete commands. Verdicts (what is allowed or denied) are unchanged; the 130 existing creation/pool tests pass untouched.
- Skill: `branch-preflight` added to both the package skill and the deployed copy (they must be byte-identical). Release note `046-branch-preflight.md`.
- Not touched: remote-delete proof, park code, PLAN.md checkbox.

## TDD

- `tests/unit/core/test_branch_preflight.py` written first; collection failed with `ImportError: cannot import name 'creation_report'` (seen red). It pins, for a real temporary repo in each blocked state (cap, dormant, parked, merged): the report's blockers equal the verdict's rule id and lines, every blocker has fix commands that appear in the text, all pools are listed together, warn-mode does not refuse, an existing name is a reset, and the guard handler's deny reason contains the preflight report.
- `tests/unit/daemon/test_cli_branch_preflight.py` written first; failed on `ImportError: EXIT_CREATION_REFUSED` (seen red). Covers exit 0, exit 4 with the fix printed, JSON, and a non-git directory.
- The deny-pointer assertion (`branch-preflight` in the deny reason) was added to the guard test and seen failing (4 failed) before the handler change turned it green.

## Verification

Separate pytest invocations: tests/unit/core (4190 passed), tests/unit/daemon (3336 passed; the 2 known test_paths_diagnose_venv_start failures, plus one skill-copy parity failure that I fixed by updating the package skill and which then passed), tests/unit/scripts + session_start + test_cli_config_validate (1612 passed), tests/unit/handlers/pre_tool_use (12132 passed, 1 known child-pytest artefact in test_project_containment), post_tool_use + the four named integration files (1396 passed). run_autofix.sh run; llm_qa format lint type_check error_hiding magic_values semgrep plan_qa docs_qa: 8/8 passed.
