#!/usr/bin/env python3
"""Plan-tree and doc-corpus drift as a QA gate (Plan 00373 Phase 2).

Both sweeps already shipped as CLI verbs that exit non-zero on findings.
Neither was in ``llm_qa.py``'s ``TOOL_REGISTRY``, so neither could fail QA —
and therefore neither could fail CI or the release gate. That is not a
hypothetical: a merge resurrected an archived plan folder, and the four
plan-QA findings that resulted survived a ``27/27 PASSED`` QA run, a green CI
run and a ``release-slate-check`` whose only complaint was live worktrees.

This wrapper deliberately SHELLS OUT to the shipped CLI rather than calling
the check runners itself. ``cmd_plan_qa``/``cmd_docs_qa`` load the project
config, honour ``plan_workflow.qa.enabled`` and ``daemon.exclude_paths``, and
resolve the corpus directory; a second implementation of that here would be
free to disagree with the one the handlers use, and a QA gate that disagrees
with the gate it is meant to back up is worse than no gate.

ANY finding fails, at either severity. The advise/block split governs whether
a COMMIT is denied — it is about who gets blamed for inherited state. QA asks
a different question: is the tree clean now. Everything the sweeps report is
fixable, and each check that can legitimately fire has its own configured
allowlist, so a finding left standing is a decision, not an accident.

The CLI is invoked through the interpreter running this script, not through
``bin/hooks-daemon``: that wrapper re-resolves its own venv, and a worktree or
CI runner resolves it differently from the main checkout.

Usage:
    python scripts/qa/run_corpus_qa.py --corpus plan|docs [--json] [--root DIR]

Exit codes:
    0 - corpus clean
    1 - findings reported
    2 - operational failure (the sweep produced no verdict)
"""

from __future__ import annotations

import argparse
import json
import subprocess  # nosec B404 — runs this interpreter against a fixed module, argv form
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final, NamedTuple

_PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_QA_OUTPUT_DIR_PARTS: Final[tuple[str, str]] = ("untracked", "qa")
_CLI_MODULE: Final[str] = "claude_code_hooks_daemon.daemon.cli"

EXIT_SUCCESS: Final[int] = 0
EXIT_ISSUES: Final[int] = 1
EXIT_OPERATIONAL: Final[int] = 2

# The CLI's own exit codes, which this wrapper mirrors rather than reinterprets.
_CLI_CLEAN: Final[int] = 0
_CLI_FINDINGS: Final[int] = 1

# Generous: both sweeps walk a whole corpus from cold. A hang past this is a
# broken toolchain, not a slow one.
_SWEEP_TIMEOUT_SECONDS: Final[int] = 300

_SEVERITY_BLOCK: Final[str] = "block"
_SEVERITY_ADVISE: Final[str] = "advise"


class Corpus(NamedTuple):
    """One sweepable corpus: its CLI verb and the QA tool name it reports as."""

    verb: str
    tool: str


CORPORA: Final[dict[str, Corpus]] = {
    "plan": Corpus(verb="plan-qa", tool="plan_qa"),
    "docs": Corpus(verb="docs-qa", tool="docs_qa"),
}

# (exit code, stdout, stderr) — injected in tests so the wrapper's own verdict
# logic is exercised without a subprocess per case.
SweepRunner = Callable[[str, Path], tuple[int, str, str]]


def run_sweep(corpus: str, root: Path) -> tuple[int, str, str]:
    """Run one corpus's sweep via the shipped CLI and return its raw result."""
    command = [
        sys.executable,
        "-m",
        _CLI_MODULE,
        "--project-root",
        str(root),
        CORPORA[corpus].verb,
        "--sweep",
        "--json",
    ]
    try:
        completed = subprocess.run(  # nosec B603 — argv form, this interpreter, no shell
            command,
            capture_output=True,
            text=True,
            cwd=str(root),
            timeout=_SWEEP_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return EXIT_OPERATIONAL, "", f"the {corpus} sweep did not run: {exc}"
    return completed.returncode, completed.stdout, completed.stderr


def build_report(corpus: str, findings: list[dict[str, Any]]) -> dict[str, Any]:
    """The QA artefact for one completed sweep.

    ``total_issues`` is one of the keys ``llm_qa.failure_count`` sums. A
    novel key would print in the summary line and still score as a pass.
    """
    severities = [str(finding.get("severity", "")) for finding in findings]
    return {
        "tool": CORPORA[corpus].tool,
        "summary": {
            "passed": not findings,
            "total_issues": len(findings),
            _SEVERITY_BLOCK: severities.count(_SEVERITY_BLOCK),
            _SEVERITY_ADVISE: severities.count(_SEVERITY_ADVISE),
        },
        "findings": findings,
    }


def failure_report(corpus: str, message: str) -> dict[str, Any]:
    """A report for a sweep that produced no verdict — never a pass.

    An empty findings list is what CLEAN looks like, so a wrapper that
    reported ``[]`` for a sweep that failed would reintroduce the exact
    invisibility this gate exists to remove, one layer further down.
    """
    return {
        "tool": CORPORA[corpus].tool,
        "summary": {
            "passed": False,
            "total_issues": 0,
            _SEVERITY_BLOCK: 0,
            _SEVERITY_ADVISE: 0,
            "error": message,
        },
        "findings": [],
    }


def parse_findings(stdout: str) -> list[dict[str, Any]] | None:
    """The findings array from a sweep's ``--json`` output, or ``None``.

    ``None`` means the output was not the documented shape, which is an
    operational failure rather than an empty result.
    """
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, list):
        return None
    return [entry for entry in parsed if isinstance(entry, dict)]


def _write_report(root: Path, corpus: str, report: dict[str, Any]) -> Path:
    output_dir = root.joinpath(*_QA_OUTPUT_DIR_PARTS)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{CORPORA[corpus].tool}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fail QA on plan-tree or doc-corpus drift.")
    parser.add_argument(
        "--corpus",
        required=True,
        choices=sorted(CORPORA),
        help="which corpus to sweep",
    )
    parser.add_argument("--root", default=str(_PROJECT_ROOT), help="project root to sweep")
    parser.add_argument("--json", action="store_true", help="write the JSON artefact")
    return parser.parse_args(argv)


def _verdict(
    corpus: str, exit_code: int, stdout: str, stderr: str
) -> tuple[dict[str, Any], int]:
    """Turn one raw CLI result into a report and this wrapper's exit code.

    A CLI exit outside its documented clean/findings pair means no verdict
    exists — ``cmd_plan_qa`` returns 2 for a missing plan directory, and
    reading that as a clean ``[]`` would report green for a tree the sweep
    never examined.
    """
    if exit_code not in (_CLI_CLEAN, _CLI_FINDINGS):
        detail = stderr.strip() or stdout.strip() or "no output"
        return (
            failure_report(corpus, f"the {corpus} sweep exited {exit_code}: {detail}"),
            EXIT_OPERATIONAL,
        )
    findings = parse_findings(stdout)
    if findings is None:
        detail = stderr.strip() or "stdout was not a JSON array of findings"
        return failure_report(corpus, f"the {corpus} sweep produced no verdict: {detail}"), (
            EXIT_OPERATIONAL
        )
    report = build_report(corpus, findings)
    return report, EXIT_ISSUES if findings else EXIT_SUCCESS


def main(argv: list[str] | None = None, *, run_sweep: SweepRunner = run_sweep) -> int:
    args = _parse_args(argv)
    root = Path(args.root).resolve()
    corpus = str(args.corpus)

    exit_code, stdout, stderr = run_sweep(corpus, root)
    report, verdict = _verdict(corpus, exit_code, stdout, stderr)

    if args.json:
        _write_report(root, corpus, report)

    summary = report["summary"]
    recorded_error = summary.get("error")
    if recorded_error:
        print(f"{CORPORA[corpus].tool}: FAILED — {recorded_error}", file=sys.stderr)
    else:
        print(
            f"{CORPORA[corpus].tool}: {summary['total_issues']} findings "
            f"({summary[_SEVERITY_BLOCK]} block, {summary[_SEVERITY_ADVISE]} advise)"
        )
    return verdict


if __name__ == "__main__":
    sys.exit(main())
