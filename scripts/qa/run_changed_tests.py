#!/usr/bin/env python3
"""QA tool: pytest on the tests mapped from what changed since the merge base.

The test half of ``llm_qa.py changed`` (Plan 00463). Sub-agents run targeted QA,
and the coordinator runs the full suite once per delivery. The targeted path
has to be ONE command, or each agent invents its own subset and some invent
none.

**The mapping is by module NAME, not by import graph.** A changed
``shell_segmentation.py`` selects every ``test_shell_segmentation.py`` and
``test_shell_segmentation_*.py`` under ``tests/``. A changed test file selects
itself. That is a heuristic, and deliberately so: the coordinator's full gate
is the backstop for every consumer a name cannot see, so this tool is judged
on being fast and honest rather than complete.

**Honest means two things.** A run that selected nothing says so rather than
reporting ``0 failed``. A changed source file that maps to no test is listed
under ``unmapped`` rather than dropped. Files under
``.claude/project-handlers/`` are left to the ``project_handlers`` tool, which
``changed`` also runs.

"Changed" is everything that differs from the merge base with ``--base``:
committed work on the branch, uncommitted edits, and new untracked files.
Deleted files and non-Python files are not candidates.

Usage:
    python scripts/qa/run_changed_tests.py [--json] [--root DIR] [--base REF]

Exit codes:
    0 - the selected tests passed, or nothing was selected
    1 - a selected test failed, or the selection collected nothing
    2 - operational failure (no merge base, git unavailable)
"""

from __future__ import annotations

import argparse
import json
import subprocess  # nosec B404 — runs git and this interpreter, argv form, no shell
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.qa.pytest_text_report import parse_pytest_text_output

_PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_QA_OUTPUT_DIR_PARTS: Final[tuple[str, str]] = ("untracked", "qa")
_OUTPUT_FILENAME: Final[str] = "changed_tests.json"
_TOOL_NAME: Final[str] = "changed_tests"

EXIT_SUCCESS: Final[int] = 0
EXIT_ISSUES: Final[int] = 1
EXIT_OPERATIONAL: Final[int] = 2

DEFAULT_BASE: Final[str] = "main"

_TEST_ROOT: Final[str] = "tests"
_TEST_GLOB: Final[str] = "test_*.py"
_TEST_PREFIX: Final[str] = "test_"
_PYTHON_SUFFIX: Final[str] = ".py"
_PACKAGE_INIT_STEM: Final[str] = "__init__"

#: Trees whose tests another ``changed`` tool already runs.
_COVERED_ELSEWHERE: Final[tuple[str, ...]] = (".claude/project-handlers/",)

_OUTCOME_FAILED: Final[str] = "failed"

#: A git plumbing call is instant; this bound only stops a hung git from
#: hanging the QA run.
_GIT_TIMEOUT_SECONDS: Final[int] = 60

#: A targeted run is minutes at most. Past this the selection was not targeted.
_PYTEST_TIMEOUT_SECONDS: Final[int] = 1800

#: (exit code, stdout, stderr) and (exit code, combined output): injected in
#: tests so the selection and verdict logic run without a repository or pytest.
GitRunner = Callable[[list[str], Path], tuple[int, str, str]]
PytestRunner = Callable[[list[str], Path], tuple[int, str]]


def run_git(args: list[str], root: Path) -> tuple[int, str, str]:
    """Run one git command in ``root``; a failure to run is a non-zero result."""
    try:
        completed = subprocess.run(  # nosec B603 B607 — git by name, argv form, no shell
            ["git", *args],
            capture_output=True,
            text=True,
            cwd=str(root),
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return EXIT_OPERATIONAL, "", f"git {' '.join(args)} did not run: {exc}"
    return completed.returncode, completed.stdout, completed.stderr


def run_pytest(paths: list[str], root: Path) -> tuple[int, str]:
    """Run pytest on explicit paths under this interpreter."""
    try:
        completed = subprocess.run(  # nosec B603 — this interpreter, argv form, no shell
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *paths],
            capture_output=True,
            text=True,
            cwd=str(root),
            timeout=_PYTEST_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return EXIT_OPERATIONAL, f"ERROR: pytest did not run: {exc}\n"
    return completed.returncode, completed.stdout + completed.stderr


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def changed_files(
    root: Path, base: str, *, git: GitRunner = run_git
) -> tuple[list[str] | None, str | None]:
    """``(files, None)``, or ``(None, reason)`` when the change set is unknowable.

    No merge base is an ERROR, not an empty change set: an empty list would
    read as "nothing changed", select nothing, and pass.
    """
    code, stdout, stderr = git(["merge-base", "HEAD", base], root)
    merge_base = stdout.strip()
    if code != 0 or not merge_base:
        detail = stderr.strip() or "no output"
        return None, f"no merge base between HEAD and `{base}`: {detail}"

    code, diffed, stderr = git(["diff", "--name-only", merge_base], root)
    if code != 0:
        return None, f"git diff against {merge_base} failed: {stderr.strip() or 'no output'}"

    code, untracked, stderr = git(["ls-files", "--others", "--exclude-standard"], root)
    if code != 0:
        return None, f"git ls-files failed: {stderr.strip() or 'no output'}"

    return sorted(set(_lines(diffed)) | set(_lines(untracked))), None


def build_test_index(root: Path) -> dict[str, list[str]]:
    """Every test file under ``tests/``, keyed by filename."""
    index: dict[str, list[str]] = {}
    test_root = root / _TEST_ROOT
    if not test_root.is_dir():
        return index
    for path in sorted(test_root.rglob(_TEST_GLOB)):
        index.setdefault(path.name, []).append(path.relative_to(root).as_posix())
    return index


def select_tests(
    changed: list[str], index: dict[str, list[str]], root: Path
) -> tuple[list[str], list[str]]:
    """``(selected test files, changed source files with no mapped test)``."""
    selected: set[str] = set()
    unmapped: list[str] = []
    for relative in changed:
        path = Path(relative)
        if path.suffix != _PYTHON_SUFFIX or not (root / path).is_file():
            continue
        if relative.startswith(_COVERED_ELSEWHERE):
            continue
        in_tests = path.parts[0] == _TEST_ROOT
        if in_tests and path.name.startswith(_TEST_PREFIX):
            selected.add(path.as_posix())
            continue
        if in_tests or path.stem == _PACKAGE_INIT_STEM:
            unmapped.append(relative)
            continue
        named = f"{_TEST_PREFIX}{path.stem}{_PYTHON_SUFFIX}"
        variant_prefix = f"{_TEST_PREFIX}{path.stem}_"
        matches = [
            test_path
            for filename, test_paths in index.items()
            if filename == named or filename.startswith(variant_prefix)
            for test_path in test_paths
        ]
        if matches:
            selected.update(matches)
        else:
            unmapped.append(relative)
    return sorted(selected), sorted(unmapped)


def build_report(
    *,
    base: str,
    changed: list[str],
    selected: list[str],
    unmapped: list[str],
    exit_code: int | None,
    output: str,
) -> dict[str, Any]:
    """The QA artefact for one targeted run.

    A non-empty selection that collected nothing has NOT passed: ``0 failed``
    from a run that ran no tests is the reading this report exists to
    prevent. An empty selection passes, and says so through
    ``test_files_selected``.
    """
    parsed = parse_pytest_text_output(output)
    if selected:
        passed_all = (
            exit_code == EXIT_SUCCESS
            and parsed["failed"] == 0
            and parsed["errors"] == 0
            and parsed["total"] > 0
        )
    else:
        passed_all = True
    return {
        "tool": _TOOL_NAME,
        "base": base,
        "summary": {
            "passed_all": passed_all,
            "total": parsed["total"],
            "passed": parsed["passed"],
            "failed": parsed["failed"],
            "skipped": parsed["skipped"],
            "errors": parsed["errors"],
            "files_considered": len(changed),
            "test_files_selected": len(selected),
        },
        "selected": selected,
        "unmapped": unmapped,
        "tests": [
            {"name": node_id, "outcome": _OUTCOME_FAILED} for node_id in parsed["failed_tests"]
        ],
    }


def failure_report(message: str) -> dict[str, Any]:
    """A report for a run that produced no verdict. Never a pass."""
    return {
        "tool": _TOOL_NAME,
        "summary": {
            "passed_all": False,
            "total": 0,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "errors": 0,
            "error": message,
        },
        "selected": [],
        "unmapped": [],
        "tests": [],
    }


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the tests mapped from changed files.")
    parser.add_argument("--root", default=str(_PROJECT_ROOT), help="repository root")
    parser.add_argument("--base", default=DEFAULT_BASE, help="ref to diff against (merge base)")
    parser.add_argument("--json", action="store_true", help="write the JSON artefact")
    return parser.parse_args(argv)


def _write_report(root: Path, report: dict[str, Any]) -> None:
    output_dir = root.joinpath(*_QA_OUTPUT_DIR_PARTS)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / _OUTPUT_FILENAME).write_text(json.dumps(report, indent=2), encoding="utf-8")


def main(
    argv: list[str] | None = None,
    *,
    run_git: GitRunner = run_git,
    run_pytest: PytestRunner = run_pytest,
) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    root = Path(args.root).resolve()
    base = str(args.base)

    changed, error = changed_files(root, base, git=run_git)
    if changed is None:
        report = failure_report(error or "the change set could not be read")
        verdict = EXIT_OPERATIONAL
    else:
        selected, unmapped = select_tests(changed, build_test_index(root), root)
        exit_code, output = run_pytest(selected, root) if selected else (None, "")
        report = build_report(
            base=base,
            changed=changed,
            selected=selected,
            unmapped=unmapped,
            exit_code=exit_code,
            output=output,
        )
        verdict = EXIT_SUCCESS if report["summary"]["passed_all"] else EXIT_ISSUES

    if args.json:
        _write_report(root, report)

    summary = report["summary"]
    if summary.get("error"):
        print(f"{_TOOL_NAME}: FAILED — {summary['error']}", file=sys.stderr)
    else:
        print(
            f"{_TOOL_NAME}: {summary['passed']} passed, {summary['failed']} failed "
            f"from {summary['test_files_selected']} test files "
            f"({len(report['unmapped'])} unmapped)"
        )
    return verdict


if __name__ == "__main__":
    sys.exit(main())
