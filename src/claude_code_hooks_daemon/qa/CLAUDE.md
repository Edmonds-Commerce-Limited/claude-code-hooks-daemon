# QA Runner Module

Automated QA execution for Python projects: `runner.py` runs the configured
tools (ruff, mypy, black, pytest, optionally bandit) via subprocess, parses
their output into structured, JSON-serialisable results, and prints a
summary. `strategy_pattern_checker.py` AST-checks strategy modules;
`pytest_text_report.py` renders pytest output for LLM consumption.

**The code is the API reference.** Class and method behaviour
(`QARunner`, `QAResult`, `ToolResult`, `QAExecutionError`, the per-tool
parsers) is documented by the module's own docstrings — read `runner.py`
rather than a hand-maintained mirror here.

## Entry points

- Python: `from claude_code_hooks_daemon.qa import QARunner` →
  `QARunner(project_root=...).run_all()`; `save_results()` writes JSON.
- Shell: `./scripts/run-qa-runner.sh /path/to/project "ruff,mypy,black,pytest" true`
- Exit codes: `0` all passed, `1` some checks failed, `2` execution error
  (CI-suitable).

## Local invariants

- One tool failing never stops the others — execution is resilient; a tool
  that crashes is recorded in its result rather than aborting the run.
- This module is NOT the project's own QA gate: contributors run
  `./scripts/qa/llm_qa.py all` (see [CLAUDE/QA.md](/CLAUDE/QA.md), the
  canonical QA policy).

Tests: `tests/unit/test_qa_runner.py`.
