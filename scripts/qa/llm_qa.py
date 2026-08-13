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
from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple, TypeAlias

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts" / "qa"
QA_OUTPUT_DIR = PROJECT_ROOT / "untracked" / "qa"
VENV_PYTHON = PROJECT_ROOT / "untracked" / "venv" / "bin" / "python"

# Exit codes
EXIT_SUCCESS = 0
EXIT_FAILURE = 1

# A QA tool's parsed JSON report. Every tool writes its own schema, so the
# value type is genuinely open — but the mapping itself is not, and a bare
# ``dict`` disables checking on every summarizer that reads one.
QaReport: TypeAlias = dict[str, Any]

# Type alias for summarizer functions
Summarizer = Callable[[QaReport], str]


class ToolConfig(NamedTuple):
    """Configuration for a single QA tool."""

    command: list[str]
    json_file: str
    jq_hint: str


def _python(script: str, *args: str) -> list[str]:
    """Build command to run a Python script via the project venv.

    Extra ``args`` are appended to the invocation, so a caller writes
    ``_python("check_x.py", "--json")`` rather than concatenating a list onto
    the result.
    """
    return [str(VENV_PYTHON), str(SCRIPTS_DIR / script), *args]


def _bash(script: str) -> list[str]:
    """Build command to run a bash QA script."""
    return [str(SCRIPTS_DIR / script)]


# ── Tool registry ──────────────────────────────────────────────────
# Order matches run_all.sh for consistency.
TOOL_REGISTRY: dict[str, ToolConfig] = {
    "magic_values": ToolConfig(
        command=_python("check_magic_values.py", "--json"),
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
    # The hint MUST name the array holding the detail, not the summary. It
    # pointed at `.summary` until Plan 00229 — sending a reader who wanted to
    # know WHAT failed back to the count they had already been shown. That is
    # why Plan 00226's missing failure names had no surface on which they could
    # look wrong. Asserted by test_llm_qa_count_implies_detail.py.
    "tests": ToolConfig(
        command=_bash("run_tests.sh"),
        json_file="tests.json",
        jq_hint="jq '.tests[] | select(.outcome == \"failed\") | .name'",
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
    "error_hiding": ToolConfig(
        command=_python("audit_error_hiding.py", "--json"),
        json_file="error_hiding.json",
        jq_hint="jq '.violations[] | {file, line, rule, message}'",
    ),
    "shell_audit": ToolConfig(
        command=_python("audit_shell.py", "--json"),
        json_file="shell_audit.json",
        jq_hint="jq '.violations[] | {file, line, rule, message}'",
    ),
    "skill_refs": ToolConfig(
        command=_python("check_skill_references.py", "--json"),
        json_file="skill_references.json",
        jq_hint="jq '.violations[] | {file, line, rule, message}'",
    ),
    "canonical_callers": ToolConfig(
        command=_bash("run_canonical_callers_check.sh"),
        json_file="canonical_callers.json",
        jq_hint="jq '.violations[]'",
    ),
    "python_var_guidance": ToolConfig(
        command=_python("check_python_var_guidance.py", "--json"),
        json_file="python_var_guidance.json",
        jq_hint="jq '.violations[] | {file, line, rule, message}'",
    ),
    "capture_corruption": ToolConfig(
        command=_bash("run_capture_corruption_check.sh"),
        json_file="capture_corruption.json",
        jq_hint="jq '.violations[] | {file, line, function, rule, message}'",
    ),
    "repo_hygiene": ToolConfig(
        command=_python("check_repo_hygiene.py", "--json"),
        json_file="repo_hygiene.json",
        jq_hint="jq '.violations[] | {rule, path, message}'",
    ),
    "doc_truth": ToolConfig(
        command=_python("check_doc_truth.py", "--json"),
        json_file="doc_truth.json",
        jq_hint="jq '.violations[] | {rule, file, line, message}'",
    ),
    "sensitive_content": ToolConfig(
        command=_python("check_sensitive_content.py", "--json"),
        json_file="sensitive_content.json",
        jq_hint="jq '.violations[] | {file, line, rule, message}'",
    ),
    "git_history": ToolConfig(
        command=_python("check_git_history.py", "--json"),
        json_file="git_history.json",
        jq_hint="jq '.violations[] | {surface, locator, rule, message}'",
    ),
    "handler_reference": ToolConfig(
        command=_python("check_handler_reference.py", "--json"),
        json_file="handler_reference.json",
        jq_hint="jq '.violations[] | {rule, file, line, message}'",
    ),
    "british_english": ToolConfig(
        command=_python("check_british_english.py", "--json"),
        json_file="british_english.json",
        jq_hint="jq '.violations[] | {file, line, american, british}'",
    ),
    # smoke_test MUST stay last: it probes the live daemon, so it belongs
    # after every static check has had its say. Pinned by
    # test_smoke_test_is_last_in_registry -- three tools were appended below
    # it before that test caught the drift.
    "smoke_test": ToolConfig(
        command=_bash("run_smoke_test.sh"),
        json_file="smoke_test.json",
        jq_hint="jq '.probes[] | {name, passed, expected, actual_decision}'",
    ),
}

ALL_TOOL_NAMES = list(TOOL_REGISTRY)


# ── Summarizers ────────────────────────────────────────────────────


def _summarize_magic_values(data: QaReport) -> str:
    total = data.get("summary", {}).get("total_violations", 0)
    return f"{total} violations"


def _summarize_format(data: QaReport) -> str:
    total = data.get("summary", {}).get("total_violations", 0)
    return f"{total} files need reformatting"


def _summarize_lint(data: QaReport) -> str:
    s = data.get("summary", {})
    total = s.get("total_violations", 0)
    if total == 0:
        return "0 violations"
    errors = s.get("errors", 0)
    warnings = s.get("warnings", 0)
    return f"{total} violations ({errors} errors, {warnings} warnings)"


def _summarize_type_check(data: QaReport) -> str:
    total = data.get("summary", {}).get("total_errors", 0)
    return f"{total} errors"


# How many failing test names to print inline. This output is read by an LLM on
# every QA run, so a mass breakage must not flood it; the rest stay in
# tests.json, which is the complete record.
_MAX_NAMED_FAILURES = 15


def _summarize_tests(data: QaReport) -> str:
    s = data.get("summary", {})
    passed = s.get("passed", 0)
    failed = s.get("failed", 0)
    skipped = s.get("skipped", 0)
    cov = data.get("coverage", {}).get("percent_covered", 0)
    line = f"{passed} passed, {failed} failed, {skipped} skipped | coverage: {cov:.1f}%"

    # Name the failures (Plan 00226). A count alone forces a full re-run to
    # find out what broke, and a re-run may not reproduce an order-dependent
    # failure — during Plan 00224 one of two real failures was never
    # identified. Bounded so a mass breakage cannot flood the artifact.
    names = [t.get("name", "") for t in data.get("tests", []) if t.get("outcome") == "failed"]
    names = [name for name in names if name]
    if not names:
        return line

    shown = names[:_MAX_NAMED_FAILURES]
    line += "\n   failed: " + "\n           ".join(shown)
    if len(names) > len(shown):
        line += f"\n           ... and {len(names) - len(shown)} more (see tests.json)"
    return line


def _summarize_security(data: QaReport) -> str:
    total = data.get("summary", {}).get("total_issues", 0)
    return f"{total} issues"


def _summarize_dependencies(data: QaReport) -> str:
    total = data.get("summary", {}).get("total_issues", 0)
    return f"{total} issues"


def _summarize_error_hiding(data: QaReport) -> str:
    total = data.get("summary", {}).get("total_violations", 0)
    return f"{total} violations"


def _summarize_shell_audit(data: QaReport) -> str:
    total = data.get("summary", {}).get("total_violations", 0)
    return f"{total} violations"


def _summarize_skill_refs(data: QaReport) -> str:
    total = data.get("summary", {}).get("total_violations", 0)
    return f"{total} violations"


def _summarize_smoke_test(data: QaReport) -> str:
    s = data.get("summary", {})
    passed = s.get("passed_probes", 0)
    total = s.get("total_probes", 0)
    failed = s.get("failed_probes", 0)
    if failed == 0:
        return f"{passed}/{total} probes passed"
    return f"{passed}/{total} probes passed ({failed} failed)"


def _summarize_canonical_callers(data: QaReport) -> str:
    total = data.get("summary", {}).get("total_violations", 0)
    return f"{total} violations"


def _summarize_capture_corruption(data: QaReport) -> str:
    total = data.get("summary", {}).get("total_violations", 0)
    return f"{total} violations"


def _summarize_python_var_guidance(data: QaReport) -> str:
    total = data.get("summary", {}).get("total_violations", 0)
    return f"{total} violations"


def _summarize_repo_hygiene(data: QaReport) -> str:
    total = data.get("summary", {}).get("total_violations", 0)
    return f"{total} violations"


def _summarize_doc_truth(data: QaReport) -> str:
    total = data.get("summary", {}).get("total_violations", 0)
    return f"{total} violations"


def _summarize_sensitive_content(data: QaReport) -> str:
    total = data.get("summary", {}).get("total_violations", 0)
    return f"{total} violations"


def _summarize_git_history(data: QaReport) -> str:
    summary = data.get("summary", {})
    total = summary.get("total_violations", 0)
    commits = summary.get("commits_scanned", 0)
    refs = summary.get("refs_scanned", 0)
    return f"{total} violations ({commits} commits, {refs} refs swept)"


def _summarize_handler_reference(data: QaReport) -> str:
    total = data.get("summary", {}).get("total_violations", 0)
    return f"{total} violations"


def _summarize_british_english(data: QaReport) -> str:
    total = data.get("summary", {}).get("total_violations", 0)
    return f"{total} violations"


SUMMARIZERS: dict[str, Summarizer] = {
    "magic_values": _summarize_magic_values,
    "format": _summarize_format,
    "lint": _summarize_lint,
    "type_check": _summarize_type_check,
    "tests": _summarize_tests,
    "security": _summarize_security,
    "dependencies": _summarize_dependencies,
    "error_hiding": _summarize_error_hiding,
    "shell_audit": _summarize_shell_audit,
    "skill_refs": _summarize_skill_refs,
    "canonical_callers": _summarize_canonical_callers,
    "capture_corruption": _summarize_capture_corruption,
    "python_var_guidance": _summarize_python_var_guidance,
    "smoke_test": _summarize_smoke_test,
    "repo_hygiene": _summarize_repo_hygiene,
    "doc_truth": _summarize_doc_truth,
    "sensitive_content": _summarize_sensitive_content,
    "git_history": _summarize_git_history,
    "handler_reference": _summarize_handler_reference,
    "british_english": _summarize_british_english,
}


# ── Core logic ─────────────────────────────────────────────────────


def _is_passed(data: QaReport) -> bool:
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
    # Tool exit code is authoritative - if non-zero, it's a failure even if
    # JSON claims success (e.g. mypy finds errors but the JSON parser misses
    # them). Both conditions must hold for a PASS, so neither source can
    # unilaterally declare success.
    tool_reported_failure = exit_code is not None and exit_code != 0
    passed = json_passed and not tool_reported_failure

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
