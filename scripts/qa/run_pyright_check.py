#!/usr/bin/env python3
"""Pyright QA gate — the language server's view of the tree must be clean.

Plan 00368 Task 2.1. Claude Code injects ``pyright-langserver`` diagnostics
into the agent's context after every edit. When that stream carries errors
that are not real (other checkouts' half-built branches, archived probes,
Optional results the code never narrows) the agent learns to skim it, and a
skimmed stream reports nothing. This gate makes the property hold by
construction: the CLI runs over exactly what ``pyrightconfig.json`` scopes,
and ANY error-severity diagnostic fails QA, so every diagnostic the agent
sees is one worth reading.

Pyright is the same binary in both roles. The pinned PyPI ``pyright`` dev
extra (``pyproject.toml``) installs it into the QA venv, which is where this
gate looks first; a ``pyright`` on ``PATH`` is the fallback. A missing binary
is a tool FAILURE with a one-line install instruction, never a skip: a gate
that stands down when its tool is absent reports green for a tree it never
examined.

Warnings and information diagnostics are counted and reported, never failed
on — the rule set in ``pyrightconfig.json`` decides what is an error, and
that file is pinned by ``tests/unit/test_pyright_config.py``.

Imports resolve against the interpreter running this script, passed as
``--pythonpath``: ``pyrightconfig.json``'s ``untracked/venv`` is a symlink only
the main checkout has, and a worktree or CI runner without it would report
every third-party import missing.

Usage:
    python scripts/qa/run_pyright_check.py [--json] [--root DIR] [--pyright PATH]
                                           [--pythonpath INTERPRETER]

Exit codes:
    0 - No errors
    1 - Errors found
    2 - Operational failure (no binary, output not JSON, pyright did not run)
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess  # nosec B404 — runs only the resolved pyright binary, argv form
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

_PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_QA_OUTPUT_DIR_PARTS: Final[tuple[str, str]] = ("untracked", "qa")
OUTPUT_FILENAME: Final[str] = "pyright.json"
_TOOL_NAME: Final[str] = "pyright"
_BINARY_NAME: Final[str] = "pyright"

EXIT_SUCCESS: Final[int] = 0
EXIT_ERRORS: Final[int] = 1
EXIT_OPERATIONAL: Final[int] = 2

# Generous: the full tree with a cold cache is measured in tens of seconds,
# and a hang past this is a broken toolchain, not a slow one.
_PYRIGHT_TIMEOUT_SECONDS: Final[int] = 600

_SEVERITY_ERROR: Final[str] = "error"
_SEVERITY_WARNING: Final[str] = "warning"

INSTALL_INSTRUCTION: Final[str] = (
    "pyright is not installed: run `uv sync --frozen --all-extras` "
    "(installs the pinned PyPI `pyright` dev extra into the QA venv; needs `node` on PATH)."
)


def resolve_pyright_binary(
    explicit: Path | None = None,
    *,
    venv_bin: Path | None = None,
    path_lookup: Callable[[str], str | None] = shutil.which,
) -> Path | None:
    """Locate the pyright CLI: an explicit path, the QA venv, then ``PATH``.

    ``explicit`` is returned as given, existing or not, so a wrong ``--pyright``
    surfaces as the failure it is rather than being quietly replaced by a
    different binary than the one the operator named.
    """
    if explicit is not None:
        return explicit
    # NOT resolve(): a venv's python is a symlink to the base interpreter, and
    # following it would look beside /usr/bin/python3 instead of in the venv.
    bin_dir = Path(sys.executable).parent if venv_bin is None else venv_bin
    sibling = bin_dir / _BINARY_NAME
    if sibling.is_file():
        return sibling
    found = path_lookup(_BINARY_NAME)
    return Path(found) if found else None


def default_interpreter() -> Path:
    """The interpreter pyright resolves imports against: the one running QA.

    ``pyrightconfig.json`` names ``untracked/venv``, a symlink only the main
    checkout carries. A linked worktree and a CI runner have the
    fingerprint-keyed venv and no symlink, so left to the config pyright
    finds no site-packages there and reports every third-party import
    missing (597 of them, measured in a worktree). Passing the QA venv's own
    interpreter makes the verdict the same in every checkout.
    """
    return Path(sys.executable)


def _relative(file_path: str, root: Path) -> str:
    """Root-relative form when the file is under ``root``; verbatim otherwise."""
    try:
        return Path(file_path).relative_to(root).as_posix()
    except ValueError:
        return file_path


def build_report(raw: dict[str, Any], root: Path) -> dict[str, Any]:
    """The QA artefact for one ``--outputjson`` run.

    Line numbers are converted to the one-based form every other tool's
    report (and every editor) uses; pyright's ranges are zero-based.
    """
    diagnostics = raw.get("generalDiagnostics", [])
    errors: list[dict[str, Any]] = []
    warnings = 0
    for diagnostic in diagnostics:
        severity = diagnostic.get("severity")
        if severity == _SEVERITY_WARNING:
            warnings += 1
        if severity != _SEVERITY_ERROR:
            continue
        start = diagnostic.get("range", {}).get("start", {})
        errors.append(
            {
                "file": _relative(str(diagnostic.get("file", "")), root),
                "line": int(start.get("line", 0)) + 1,
                "rule": str(diagnostic.get("rule", "")),
                "message": str(diagnostic.get("message", "")),
            }
        )
    summary = raw.get("summary", {})
    return {
        "tool": _TOOL_NAME,
        "summary": {
            "passed": not errors,
            "total_errors": len(errors),
            "warnings": warnings,
            "files_analyzed": int(summary.get("filesAnalyzed", 0)),
            "pyright_version": str(raw.get("version", "")),
        },
        "errors": errors,
    }


def _failure_report(message: str) -> dict[str, Any]:
    """A report for a run that never produced a verdict — never a pass."""
    return {
        "tool": _TOOL_NAME,
        "summary": {
            "passed": False,
            "total_errors": 0,
            "warnings": 0,
            "files_analyzed": 0,
            "pyright_version": "",
            "error": message,
        },
        "errors": [],
    }


def run_pyright(
    binary: Path, root: Path, interpreter: Path
) -> tuple[dict[str, Any] | None, str | None]:
    """Run the CLI over ``root``'s project and parse its JSON.

    Returns ``(raw, None)`` on a parsed run — including one that found
    errors, which is a verdict, not a failure — and ``(None, reason)`` when
    no verdict exists.
    """
    if not binary.is_file():
        return None, f"{INSTALL_INSTRUCTION} (looked for {binary})"
    try:
        completed = subprocess.run(  # nosec B603 — argv form, resolved binary, no shell
            [
                str(binary),
                "--project",
                str(root),
                "--pythonpath",
                str(interpreter),
                "--outputjson",
            ],
            capture_output=True,
            text=True,
            cwd=str(root),
            timeout=_PYRIGHT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"pyright did not run: {exc}"
    try:
        raw = json.loads(completed.stdout)
    except json.JSONDecodeError:
        stderr = completed.stderr.strip()
        detail = f"; stderr: {stderr}" if stderr else ""
        return None, (
            f"pyright output was not JSON (exit {completed.returncode}){detail}. "
            "A pyright that cannot start usually means `node` is missing from PATH."
        )
    if not isinstance(raw, dict):
        return None, "pyright output was not JSON: expected an object at the top level."
    return raw, None


def _write_report(root: Path, report: dict[str, Any]) -> Path:
    output_dir = root.joinpath(*_QA_OUTPUT_DIR_PARTS)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / OUTPUT_FILENAME
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run pyright as a zero-errors QA gate.")
    parser.add_argument("--root", default=str(_PROJECT_ROOT), help="project root to analyse")
    parser.add_argument("--json", action="store_true", help="write the JSON artefact")
    parser.add_argument("--pyright", default=None, help="explicit path to the pyright CLI")
    parser.add_argument(
        "--pythonpath",
        default=None,
        help="interpreter to resolve imports against (default: the one running this script)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    root = Path(args.root).resolve()
    explicit = Path(args.pyright) if args.pyright else None
    interpreter = Path(args.pythonpath) if args.pythonpath else default_interpreter()
    binary = resolve_pyright_binary(explicit)

    if binary is None:
        report = _failure_report(INSTALL_INSTRUCTION)
        exit_code = EXIT_OPERATIONAL
    else:
        raw, reason = run_pyright(binary, root, interpreter)
        if raw is None:
            report = _failure_report(reason or "pyright produced no verdict")
            exit_code = EXIT_OPERATIONAL
        else:
            report = build_report(raw, root)
            exit_code = EXIT_SUCCESS if report["summary"]["passed"] else EXIT_ERRORS

    if args.json:
        _write_report(root, report)

    summary = report["summary"]
    recorded_error = summary.get("error")
    if recorded_error:
        print(f"pyright: FAILED — {recorded_error}", file=sys.stderr)
    else:
        print(
            f"pyright {summary['pyright_version']}: {summary['total_errors']} errors, "
            f"{summary['warnings']} warnings in {summary['files_analyzed']} files"
        )
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
