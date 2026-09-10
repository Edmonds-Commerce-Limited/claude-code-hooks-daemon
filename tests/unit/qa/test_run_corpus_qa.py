"""The plan-tree and doc-corpus sweeps are QA tools (Plan 00373 Phase 2).

Both sweeps shipped as CLI verbs that exit non-zero on findings, and neither
was in ``scripts/qa/llm_qa.py``'s ``TOOL_REGISTRY``. So plan-tree and
doc-corpus drift could not fail QA, and therefore could not fail CI or the
release gate. It did not: an archived plan folder was resurrected by a merge
and four plan-QA findings survived a ``27/27 PASSED`` run, a green CI run and
a ``release-slate-check``.

The wrapper under test shells out to the SHIPPED CLI rather than
re-resolving config itself. ``cmd_plan_qa`` reads the project config, honours
``plan_workflow.qa.enabled`` and ``daemon.exclude_paths``, and picks the
plan directory; a second implementation of that in a QA script would be free
to disagree with the one the handlers use, which is the drift this plan
exists to close rather than widen.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _load(script: str, name: str) -> Any:
    """Import a file under ``scripts/qa/``, which is a script rather than a module."""
    module_path = PROJECT_ROOT / "scripts" / "qa" / script
    spec = importlib.util.spec_from_file_location(name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


corpus_qa = _load("run_corpus_qa.py", "run_corpus_qa_under_test")
llm_qa = _load("llm_qa.py", "llm_qa_for_corpus_test")


def _finding(check_id: str = "row-folder-bijection", severity: str = "advise") -> dict[str, Any]:
    return {
        "check_id": check_id,
        "severity": severity,
        "message": "a folder is indexed somewhere its location does not expect",
        "remediation": "move the row or move the folder",
        "path": "CLAUDE/Plan/00372-worktree-reap-two-defects",
    }


def _sweep_returning(
    exit_code: int, stdout: str, stderr: str = ""
) -> Callable[[str, Path], tuple[int, str, str]]:
    """A ``run_sweep`` stand-in with a fixed result.

    It asserts on what the wrapper hands it, so the injection also pins the
    call contract: a corpus the registry knows and an absolute root. A bare
    lambda would accept anything and prove only that the stub was called.
    """

    def run(corpus: str, root: Path) -> tuple[int, str, str]:
        assert corpus in corpus_qa.CORPORA
        assert root.is_absolute()
        return exit_code, stdout, stderr

    return run


class TestTheReportShape:
    """The artefact has to satisfy the same contract every other QA tool does."""

    def test_a_clean_corpus_passes_and_counts_nothing(self) -> None:
        report = corpus_qa.build_report("plan", [])

        assert report["summary"]["passed"] is True
        assert report["summary"]["total_issues"] == 0
        assert report["findings"] == []

    def test_findings_are_counted_and_carried_through_verbatim(self) -> None:
        findings = [_finding(), _finding("no-new-collisions", "block")]

        report = corpus_qa.build_report("plan", findings)

        assert report["summary"]["passed"] is False
        assert report["summary"]["total_issues"] == 2
        assert report["findings"] == findings

    def test_the_severity_split_is_reported(self) -> None:
        """`0 block, 4 advise` is the first thing a reader wants to know."""
        findings = [
            _finding(severity="block"),
            _finding(severity="advise"),
            _finding(severity="advise"),
        ]

        summary = corpus_qa.build_report("docs", findings)["summary"]

        assert summary["block"] == 1
        assert summary["advise"] == 2

    def test_the_plan_sweeps_level_key_counts_too(self) -> None:
        """The two sibling CLIs name the same concept differently.

        `docs-qa --json` emits `severity`; `plan-qa --json` emits `level`.
        Counting only `severity` made the summary line contradict itself —
        measured on a replay of the 00372 scenario, which printed
        `3 findings (0 block, 0 advise)`. A reader cannot act on a report
        that disagrees with its own total.
        """
        findings = [
            {"check_id": "no-new-collisions", "level": "block", "message": "m", "path": None},
            {"check_id": "row-folder-bijection", "level": "advise", "message": "m", "path": None},
        ]

        summary = corpus_qa.build_report("plan", findings)["summary"]

        assert (summary["block"], summary["advise"]) == (1, 1)

    def test_the_split_always_accounts_for_every_finding(self) -> None:
        """The class guard: no key naming can make the split disagree with the total.

        Stated as a property rather than as two more key names, because the
        failure was never about `level` specifically — it was a summary that
        could claim three findings and place none of them.
        """
        findings = [
            _finding(severity="block"),
            {"check_id": "x", "level": "advise", "message": "m", "path": None},
        ]

        summary = corpus_qa.build_report("plan", findings)["summary"]

        assert summary["block"] + summary["advise"] == summary["total_issues"]

    def test_an_operational_failure_is_never_a_pass(self) -> None:
        """A sweep that could not run must not look like a sweep that found nothing.

        This is the whole point of the plan: an empty findings list is what
        CLEAN looks like, so a wrapper that reports `[]` when the CLI failed
        would reintroduce exactly the invisibility being fixed — one layer
        further down, and harder to notice.
        """
        report = corpus_qa.failure_report("plan", "the CLI did not produce JSON")

        assert report["summary"]["passed"] is False
        assert report["summary"]["error"] == "the CLI did not produce JSON"
        assert report["findings"] == []


class TestTheCliVerdictIsHonoured:
    """The wrapper's exit code mirrors the CLI's, including its failure codes."""

    def test_clean_sweep_exits_zero(self, tmp_path: Path) -> None:
        exit_code = corpus_qa.main(
            ["--corpus", "plan", "--json", "--root", str(tmp_path)],
            run_sweep=_sweep_returning(0, "[]"),
        )

        assert exit_code == corpus_qa.EXIT_SUCCESS

    def test_findings_exit_one(self, tmp_path: Path) -> None:
        payload = json.dumps([_finding()])
        exit_code = corpus_qa.main(
            ["--corpus", "plan", "--json", "--root", str(tmp_path)],
            run_sweep=_sweep_returning(1, payload),
        )

        assert exit_code == corpus_qa.EXIT_ISSUES

    def test_a_cli_operational_exit_is_operational_here_too(self, tmp_path: Path) -> None:
        """CLI exit 2 means "no verdict exists", even when stdout parses.

        `cmd_plan_qa` returns 2 for a missing plan directory and prints
        nothing useful to stdout. Reading that as a clean `[]` would report
        green for a tree the sweep never examined.
        """
        exit_code = corpus_qa.main(
            ["--corpus", "plan", "--json", "--root", str(tmp_path)],
            run_sweep=_sweep_returning(2, "[]", "ERROR: no plan directory"),
        )

        assert exit_code == corpus_qa.EXIT_OPERATIONAL

    def test_unparseable_output_is_operational(self, tmp_path: Path) -> None:
        exit_code = corpus_qa.main(
            ["--corpus", "plan", "--json", "--root", str(tmp_path)],
            run_sweep=_sweep_returning(0, "Traceback (most recent call last)"),
        )

        assert exit_code == corpus_qa.EXIT_OPERATIONAL

    def test_the_artefact_is_written_where_the_registry_looks(self, tmp_path: Path) -> None:
        payload = json.dumps([_finding()])
        corpus_qa.main(
            ["--corpus", "docs", "--json", "--root", str(tmp_path)],
            run_sweep=_sweep_returning(1, payload),
        )

        written = tmp_path / "untracked" / "qa" / "docs_qa.json"
        assert written.is_file(), "the registry reads untracked/qa/<tool>.json"
        assert json.loads(written.read_text(encoding="utf-8"))["findings"] == [_finding()]


class TestBothCorporaAreRegisteredQaTools:
    """Registration is the fix; the wrapper is only how it is delivered."""

    @pytest.mark.parametrize("tool_name", ["plan_qa", "docs_qa"])
    def test_the_tool_is_in_the_registry(self, tool_name: str) -> None:
        assert tool_name in llm_qa.TOOL_REGISTRY, (
            f"{tool_name} is not a QA tool, so drift in that corpus cannot fail "
            "QA, CI or the release gate — the defect Plan 00373 was filed for"
        )

    @pytest.mark.parametrize("tool_name", ["plan_qa", "docs_qa"])
    def test_the_hint_points_at_the_array_the_report_writes(self, tool_name: str) -> None:
        """The printed hint is a promise about where the detail lives."""
        hint = llm_qa.TOOL_REGISTRY[tool_name].jq_hint

        assert llm_qa.detail_array_key(hint) == "findings"

    @pytest.mark.parametrize("tool_name", ["plan_qa", "docs_qa"])
    def test_the_tool_has_a_summarizer(self, tool_name: str) -> None:
        assert tool_name in llm_qa.SUMMARIZERS

    @pytest.mark.parametrize("tool_name", ["plan_qa", "docs_qa"])
    def test_the_count_key_is_one_llm_qa_actually_reads(self, tool_name: str) -> None:
        """`failure_count` sums a fixed set of keys; a novel one reads as zero.

        A report using `total_findings` would print its count in the summary
        line and still be scored as a pass by `failure_count`, which is the
        producer/consumer split Plan 00229 generalised a guard against.
        """
        summary = corpus_qa.build_report(tool_name.removesuffix("_qa"), [_finding()])["summary"]

        assert llm_qa.failure_count(summary) == 1
