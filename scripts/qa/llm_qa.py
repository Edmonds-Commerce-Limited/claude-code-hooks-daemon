#!/usr/bin/env python3
"""LLM-optimized QA runner - minimal stdout, structured JSON to file.

Runs the same QA tools as run_all.sh but produces 2 lines per tool
instead of 50+. Designed for AI coding assistants that prefer concise,
machine-parseable output with pointers to detailed JSON.

Usage:
    ./scripts/qa/llm_qa.py all              # Run all 7 QA checks
    ./scripts/qa/llm_qa.py tests lint       # Run specific tools
    ./scripts/qa/llm_qa.py --read-only all  # Summarize existing JSON only
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Callable, NamedTuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts" / "qa"
QA_OUTPUT_DIR = PROJECT_ROOT / "untracked" / "qa"
VENV_PYTHON = PROJECT_ROOT / "untracked" / "venv" / "bin" / "python"

# Exit codes
EXIT_SUCCESS = 0
EXIT_FAILURE = 1

# Type alias for summarizer functions
Summarizer = Callable[[dict], str]


class ToolConfig(NamedTuple):
    """Configuration for a single QA tool."""

    command: list[str]
    json_file: str
    jq_hint: str


def _python(script: str) -> list[str]:
    """Build command to run a Python script via the project venv."""
    return [str(VENV_PYTHON), str(SCRIPTS_DIR / script)]


def _bash(script: str) -> list[str]:
    """Build command to run a bash QA script."""
    return [str(SCRIPTS_DIR / script)]


# ── Tool registry ──────────────────────────────────────────────────
# Order matches run_all.sh for consistency.
TOOL_REGISTRY: dict[str, ToolConfig] = {
    "magic_values": ToolConfig(
        command=_python("check_magic_values.py") + ["--json"],
        json_file="magic_values.json",
        jq_hint="jq '.violations[] | {file, line, rule, message}'",
    ),
    "format": ToolConfig(
        command=_bash("run_format_check.sh"),
        json_file="format.json",
        jq_hint="jq '.violations[].file'",
    ),
    "lint": ToolConfig(
        command=_bash("run_lint.sh"),
        json_file="lint.json",
        jq_hint="jq '.violations[] | {file, rule, message}'",
    ),
    "type_check": ToolConfig(
        command=_bash("run_type_check.sh"),
        json_file="type_check.json",
        jq_hint="jq '.errors[] | {file, line, message}'",
    ),
    "tests": ToolConfig(
        command=_bash("run_tests.sh"),
        json_file="tests.json",
        jq_hint="jq '.summary'",
    ),
    "security": ToolConfig(
        command=_bash("run_security_check.sh"),
        json_file="security.json",
        jq_hint="jq '.issues[] | {file, test_id, severity, message}'",
    ),
    "dependencies": ToolConfig(
        command=_bash("run_dependency_check.sh"),
        json_file="dependencies.json",
        jq_hint="jq '.issues[]'",
    ),
}

ALL_TOOL_NAMES = list(TOOL_REGISTRY)


# ── Summarizers ────────────────────────────────────────────────────

def _summarize_magic_values(data: dict) -> str:
    total = data.get("summary", {}).get("total_violations", 0)
    return f"{total} violations"


def _summarize_format(data: dict) -> str:
    total = data.get("summary", {}).get("total_violations", 0)
    return f"{total} files need reformatting"


def _summarize_lint(data: dict) -> str:
    s = data.get("summary", {})
    total = s.get("total_violations", 0)
    if total == 0:
        return "0 violations"
    errors = s.get("errors", 0)
    warnings = s.get("warnings", 0)
    return f"{total} violations ({errors} errors, {warnings} warnings)"


def _summarize_type_check(data: dict) -> str:
    total = data.get("summary", {}).get("total_errors", 0)
    return f"{total} errors"


def _summarize_tests(data: dict) -> str:
    s = data.get("summary", {})
    passed = s.get("passed", 0)
    failed = s.get("failed", 0)
    skipped = s.get("skipped", 0)
    cov = data.get("coverage", {}).get("percent_covered", 0)
    return f"{passed} passed, {failed} failed, {skipped} skipped | coverage: {cov:.1f}%"


def _summarize_security(data: dict) -> str:
    total = data.get("summary", {}).get("total_issues", 0)
    return f"{total} issues"


def _summarize_dependencies(data: dict) -> str:
    total = data.get("summary", {}).get("total_issues", 0)
    return f"{total} issues"


SUMMARIZERS: dict[str, Summarizer] = {
    "magic_values": _summarize_magic_values,
    "format": _summarize_format,
    "lint": _summarize_lint,
    "type_check": _summarize_type_check,
    "tests": _summarize_tests,
    "security": _summarize_security,
    "dependencies": _summarize_dependencies,
}


# ── Core logic ─────────────────────────────────────────────────────

def _is_passed(data: dict) -> bool:
    """Determine pass/fail from JSON data (handles both schemas)."""
    summary = data.get("summary", {})
    # tests.json uses "passed_all", everything else uses "passed"
    if "passed_all" in summary:
        return bool(summary["passed_all"])
    return bool(summary.get("passed", False))


def run_tool(name: str) -> int:
    """Run a QA tool, suppressing its stdout/stderr. Returns exit code."""
    config = TOOL_REGISTRY[name]
    result = subprocess.run(
        config.command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=str(PROJECT_ROOT),
    )
    return result.returncode


def summarize_tool(name: str, exit_code: int | None = None) -> tuple[bool, str]:
    """Read JSON output and produce a 2-line summary.

    Args:
        name: Tool name from TOOL_REGISTRY.
        exit_code: Exit code from running the tool. If non-zero, overrides
            JSON pass/fail (catches cases where JSON lies about results).

    Returns (passed, formatted_summary_string).
    """
    config = TOOL_REGISTRY[name]
    json_path = QA_OUTPUT_DIR / config.json_file

    if not json_path.exists():
        return False, f"  {name}: NO OUTPUT (run tool first)\n"

    with open(json_path) as f:
        data = json.load(f)

    json_passed = _is_passed(data)
    # Tool exit code is authoritative - if non-zero, it's a failure
    # even if JSON claims success (e.g. mypy finds errors but JSON
    # parser misses them)
    if exit_code is not None and exit_code != 0:
        passed = False
    else:
        passed = json_passed

    icon = "\u2705" if passed else "\u274c"
    summarizer = SUMMARIZERS[name]
    metrics = summarizer(data)

    # Warn when exit code disagrees with JSON
    mismatch_note = ""
    if exit_code is not None and exit_code != 0 and json_passed:
        mismatch_note = " (exit code non-zero, JSON may be inaccurate)"

    line1 = f"{icon} {name}: {metrics}{mismatch_note}"
    line2 = f"   {config.json_file} | {config.jq_hint}"
    return passed, f"{line1}\n{line2}\n"


# ── CLI ────────────────────────────────────────────────────────────

def main() -> int:
    """Entry point."""
    args = sys.argv[1:]

    read_only = False
    if "--read-only" in args:
        read_only = True
        args.remove("--read-only")

    if not args or "--help" in args or "-h" in args:
        print("Usage: llm_qa.py [--read-only] <tool|all> [tool ...]")
        print(f"Tools: {', '.join(ALL_TOOL_NAMES)}")
        return EXIT_SUCCESS

    # Resolve tool list
    if "all" in args:
        tools = ALL_TOOL_NAMES
    else:
        tools = []
        for name in args:
            if name not in TOOL_REGISTRY:
                print(f"Unknown tool: {name}")
                print(f"Available: {', '.join(ALL_TOOL_NAMES)}")
                return EXIT_FAILURE
            tools.append(name)

    all_passed = True
    tool_results: dict[str, tuple[bool, str]] = {}

    for name in tools:
        # Run the tool (unless read-only)
        exit_code: int | None = None
        if not read_only:
            exit_code = run_tool(name)

        # Summarize from JSON, passing exit code for cross-check
        passed, summary = summarize_tool(name, exit_code=exit_code)
        tool_results[name] = (passed, summary)
        print(summary, end="")
        if not passed:
            all_passed = False

    # Overall summary
    total = len(tools)
    passed_count = sum(1 for passed, _ in tool_results.values() if passed)
    print()
    if all_passed:
        print(f"QA: {passed_count}/{total} PASSED")
    else:
        print(f"QA: {passed_count}/{total} PASSED, {total - passed_count}/{total} FAILED")

    return EXIT_SUCCESS if all_passed else EXIT_FAILURE


if __name__ == "__main__":
    sys.exit(main())
