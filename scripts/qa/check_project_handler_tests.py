#!/usr/bin/env python3
"""QA gate: run the project handlers' own tests.

DBF (``CLAUDE.md`` Core Standard 15). ``scripts/qa/gate-scope.bash`` excludes
``.claude/project-handlers/`` from the mypy gate — mypy refuses a directory
whose name contains a hyphen — and justifies the exclusion in writing:

    Those handlers are covered by their own tests and by
    "hooks-daemon validate-project-handlers".

Half of that was not true. The tests existed, but ``pyproject.toml`` sets
``testpaths = ["tests"]`` and ``run_tests.sh`` runs ``pytest tests/``, so no
gate ever executed them; ``validate-project-handlers`` proves only that the
modules IMPORT. The exclusion was therefore resting on an assurance nothing
enforced. This gate makes it real.

The handlers in question are not decorative. Both are ``terminal=True`` and
both DENY — ``release_blocker`` denies the Stop event, ``enforce_llm_qa`` denies
a Bash command — so a regression in either changes what a session is permitted
to do, and could reach a release with every gate green.

It runs the PRODUCTION runner (``bin/hooks-daemon test-project-handlers``)
rather than re-deriving pytest's flags here. That keeps one caller for the
invocation and exercises the path the documentation tells developers to use.

Usage:
    python scripts/qa/check_project_handler_tests.py [--json] [--root DIR]
                                                     [--report-stdout]
"""

from __future__ import annotations

import argparse
import json
import subprocess  # nosec B404 — runs the project's own daemon CLI, fixed argv
import sys
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.qa.pytest_text_report import parse_pytest_text_output

_PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]

#: The directory whose tests this gate runs. Named so the guard test can assert
#: the gate still points at the tree ``gate-scope.bash`` excuses.
PROJECT_HANDLERS_DIR_PARTS: Final[tuple[str, str]] = (".claude", "project-handlers")

#: The production runner, invoked through the deployed wrapper exactly as
#: ``CLAUDE/PROJECT_HANDLERS.md`` instructs. Never a hand-rolled pytest command:
#: the flags belong to the CLI, and duplicating them here would let the gate and
#: the documented command drift apart.
_CLI_PARTS: Final[tuple[str, str]] = ("bin", "hooks-daemon")
_CLI_SUBCOMMAND: Final[str] = "test-project-handlers"

#: The suite runs in seconds; this bound exists so a hung runner fails the gate
#: rather than hanging the QA run.
_RUNNER_TIMEOUT_SECONDS: Final[int] = 300

_TOOL_NAME: Final[str] = "project_handlers"
_OUTCOME_FAILED: Final[str] = "failed"

_QA_OUTPUT_DIR_PARTS: Final[tuple[str, str]] = ("untracked", "qa")
_OUTPUT_FILENAME: Final[str] = "project_handlers.json"

#: Exit code used when the gate could not run the suite at all, as distinct from
#: the suite running and failing.
_EXIT_COULD_NOT_RUN: Final[int] = 2


def build_report(exit_code: int, output: str) -> dict[str, Any]:
    """Turn a runner invocation into the standard QA report shape.

    The verdict is conjoined with a POSITIVE test count, not derived from the
    failure count alone. A runner that collected nothing — absent pytest, a
    renamed directory, a collection error — prints no failures, and
    ``failed == 0`` would otherwise read as success. This is the same trap
    ``tests/integration/test_qa_gate_scope.py`` pins for the type gate: a check
    that analysed nothing has not passed, it has not run.

    The runner's own exit code is part of the verdict too, because pytest can
    print a green summary for the tests that ran and still exit non-zero.

    Args:
        exit_code: Exit status of the runner invocation.
        output: Combined stdout/stderr, ANSI colouring included.

    The verdict is published as ``summary.passed_all``, which is the key BOTH
    consumers read: ``llm_qa.py`` and the summary block in ``run_all.sh`` each
    take ``summary["passed_all"]`` when present and fall back to
    ``summary["passed"]`` otherwise. For a test runner that fallback is a trap —
    ``summary.passed`` is a COUNT here, so "60 passed, 1 failed" would be read
    as the truthy ``60`` and printed as PASSED. ``run_tests.sh`` publishes
    ``passed_all`` for exactly this reason; this report follows it rather than
    inventing a top-level key neither consumer looks at.

    Returns:
        A report whose ``summary.passed_all`` carries the verdict, alongside the
        counts and a ``tests`` array naming every failure — the array the
        operator's jq hint points at.
    """
    parsed = parse_pytest_text_output(output)

    total = parsed["total"]
    passed = exit_code == 0 and parsed["failed"] == 0 and total > 0

    return {
        "tool": _TOOL_NAME,
        "exit_code": exit_code,
        "summary": {
            "passed_all": passed,
            "total": total,
            "passed": parsed["passed"],
            "failed": parsed["failed"],
            "skipped": parsed["skipped"],
        },
        "tests": [
            {"name": node_id, "outcome": _OUTCOME_FAILED} for node_id in parsed["failed_tests"]
        ],
    }


def run_project_handler_tests(root: Path) -> tuple[int, str]:
    """Invoke the production project-handler test runner.

    SECURITY: fixed argv, no shell. The only interpolated value is the
    repository root, and the executable is this project's own deployed wrapper.

    Returns:
        ``(exit_code, combined_output)``. A missing wrapper, a timeout or an OS
        error all surface as a non-zero code with the reason in the output, so
        the gate fails loudly instead of reporting a suite it never ran.
    """
    cli = root.joinpath(*_CLI_PARTS)
    if not cli.is_file():
        return _EXIT_COULD_NOT_RUN, f"ERROR: daemon CLI wrapper not found at {cli}\n"

    try:
        result = subprocess.run(  # nosec B603 — fixed argv, no shell, trusted input
            [str(cli), _CLI_SUBCOMMAND],
            capture_output=True,
            text=True,
            timeout=_RUNNER_TIMEOUT_SECONDS,
            check=False,
            cwd=str(root),
        )
    except subprocess.TimeoutExpired:
        return (
            _EXIT_COULD_NOT_RUN,
            f"ERROR: {_CLI_SUBCOMMAND} exceeded {_RUNNER_TIMEOUT_SECONDS}s\n",
        )
    except OSError as exc:
        return _EXIT_COULD_NOT_RUN, f"ERROR: could not run {_CLI_SUBCOMMAND}: {exc}\n"

    return result.returncode, result.stdout + result.stderr


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(_PROJECT_ROOT), help="repository root to scan")
    parser.add_argument("--json", action="store_true", help="write the JSON artifact")
    parser.add_argument(
        "--report-stdout", action="store_true", help="print the JSON report to stdout"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    root = Path(args.root)

    exit_code, output = run_project_handler_tests(root)
    report = build_report(exit_code, output)
    summary = report["summary"]

    if args.json:
        output_dir = root.joinpath(*_QA_OUTPUT_DIR_PARTS)
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / _OUTPUT_FILENAME).write_text(json.dumps(report, indent=2))

    if args.report_stdout:
        print(json.dumps(report, indent=2))
    elif summary["passed_all"]:
        print(f"Project handler tests passed: {summary['passed']} test(s)")
    else:
        if summary["total"] == 0:
            print(
                "Project handler tests did NOT RUN — zero tests collected. "
                "This is a gate failure, not a clean result. Runner output:"
            )
            print(output.rstrip())
        else:
            print(f"Project handler tests FAILED: {summary['failed']} of {summary['total']}")
            for entry in report["tests"]:
                print(f"  {entry['name']}")

    return 0 if summary["passed_all"] else 1


if __name__ == "__main__":
    sys.exit(main())
