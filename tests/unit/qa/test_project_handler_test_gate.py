"""The project handlers' own tests must run in the QA gate.

DBF (``CLAUDE.md`` Core Standard 15). ``scripts/qa/gate-scope.bash`` excludes
``.claude/project-handlers/`` from the mypy gate and justifies it in writing:

    Those handlers are covered by their own tests and by
    "hooks-daemon validate-project-handlers".

Half of that was not true. The tests exist — 61 of them — but
``pyproject.toml`` sets ``testpaths = ["tests"]`` and ``run_tests.sh`` runs
``pytest tests/``, so nothing in ``run_all.sh``, ``llm_qa.py`` or
``.github/workflows/qa.yml`` ever executed them. ``validate-project-handlers``
only proves the modules IMPORT; it asserts nothing about behaviour.

This project's two project handlers are not decorative. Both are
``terminal=True`` and both DENY: ``release_blocker`` denies the Stop event and
``enforce_llm_qa`` denies a Bash command. A regression in either changes what
the session is allowed to do, and could reach a release with every gate green.

The exclusion itself is reasonable — mypy genuinely refuses a directory whose
name contains a hyphen. What was wrong was resting it on an assurance nothing
enforced. This gate makes the assurance real.

It also carries the lesson ``test_qa_gate_scope.py`` records for the type gate:
a check that analysed nothing has not passed, it has not run. A test runner that
collects zero tests reports "0 failed", which is indistinguishable from success
unless the count is conjoined.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
_QA_DIR = _REPO_ROOT / "scripts" / "qa"
_CHECKER = _QA_DIR / "check_project_handler_tests.py"

#: Registry key and summarizer key the check must be registered under.
_CHECK_NAME = "project_handlers"


def _load(module_path: Path, alias: str) -> Any:
    """Import a ``scripts/qa`` script, which is a script rather than a module."""
    spec = importlib.util.spec_from_file_location(alias, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _checker() -> Any:
    return _load(_CHECKER, "check_project_handler_tests_under_test")


def _llm_qa() -> Any:
    return _load(_QA_DIR / "llm_qa.py", "llm_qa_for_project_handler_gate")


#: A realistic green run of the project-handler suite, ANSI-coloured the way
#: pytest colours its summary even when stdout is redirected.
_GREEN_OUTPUT = (
    "collected 61 items\n"
    "\x1b[32m============================== \x1b[32m\x1b[1m61 passed\x1b[0m"
    "\x1b[32m in 4.79s\x1b[0m\x1b[32m ==============================\x1b[0m\n"
)

#: The short-summary banner is part of the shape, not decoration. Only the
#: text BELOW it is scraped for node ids, because the captured stream also
#: carries subprocess log output and a stray line beginning with "ERROR" was
#: otherwise read as a verdict. Faithful to the real runner: it resolves
#: `configfile: pyproject.toml`, whose addopts carry `-ra`, so a failing run
#: always prints this section.
_SUMMARY_BANNER = (
    "=========================== short test summary info ============================\n"
)

_RED_OUTPUT = (
    "collected 61 items\n" + _SUMMARY_BANNER + "FAILED "
    ".claude/project-handlers/stop/test_release_blocker.py::"
    "TestTheStateFileIsTheAuthority::test_a_dirty_tree_with_no_state_file_allows_the_stop\n"
    "======================== 1 failed, 60 passed in 3.99s =========================\n"
)

#: What the runner prints when pytest is absent: a dev-only extra, so its
#: absence is a real possibility rather than a hypothetical.
_NOTHING_RAN_OUTPUT = "ERROR: pytest is not installed in the daemon venv\n"


class TestTheGateIsActuallyWiredIn:
    """An unwired guard is the same defect it was written to fix."""

    def test_the_checker_script_exists(self) -> None:
        assert _CHECKER.is_file(), f"{_CHECKER} is missing"

    def test_llm_qa_registers_the_check(self) -> None:
        """Present in the registry, or agents running `llm_qa.py all` never see it."""
        registry = _llm_qa().TOOL_REGISTRY

        assert _CHECK_NAME in registry, (
            f"{_CHECK_NAME!r} is not in TOOL_REGISTRY, so `llm_qa.py all` — the "
            "suite AGENTS are required to use — does not run it. A check that "
            "exists but is not registered is exactly the blind spot this gate "
            "was added to close."
        )

    def test_the_check_has_a_summarizer(self) -> None:
        """Without one the result cannot be reported in the summary block."""
        assert _CHECK_NAME in _llm_qa().SUMMARIZERS, (
            f"{_CHECK_NAME!r} has no summarizer, so its line in the QA summary "
            "cannot state what happened."
        )

    def test_the_registered_hint_names_a_detail_array(self) -> None:
        """The jq hint is a promise about where the detail lives (Plan 00229)."""
        hint = _llm_qa().TOOL_REGISTRY[_CHECK_NAME].jq_hint

        assert ".tests[]" in hint, (
            f"the jq hint {hint!r} must send the reader to the array holding the "
            "failing test names, not to the summary count they were already shown."
        )

    def test_run_all_invokes_the_checker(self) -> None:
        """`run_all.sh` is the human-facing suite and must run it too.

        The two suites are not identical — `run_all.sh` deliberately omits the
        live-daemon `smoke_test` — so this asserts only that THIS check is in
        both. A static check present in one and absent from the other means a
        human at a terminal and an agent get different verdicts on one tree.
        """
        text = (_QA_DIR / "run_all.sh").read_text(encoding="utf-8")

        assert _CHECKER.name in text, (
            f"run_all.sh does not invoke {_CHECKER.name}, so a human running "
            "the suite directly would not exercise the project handlers."
        )

    def test_smoke_test_is_still_last_in_the_registry(self) -> None:
        """Inserting a check must not displace the live-daemon probe from last.

        `llm_qa.py` states this requirement in a comment beside `smoke_test`;
        three tools were appended below it before a test caught the drift.
        """
        names = list(_llm_qa().TOOL_REGISTRY)

        assert names[-1] == "smoke_test", (
            f"smoke_test is no longer last (registry ends {names[-3:]}). It "
            "probes the live daemon and belongs after every static check."
        )


class TestAGateThatRanNothingHasNotPassed:
    """`0 failed` is not evidence of success when nothing was collected."""

    def test_a_clean_run_passes(self) -> None:
        report = _checker().build_report(0, _GREEN_OUTPUT)

        assert report["summary"]["passed_all"] is True
        assert report["summary"]["passed"] == 61
        assert report["summary"]["failed"] == 0

    def test_zero_collected_tests_fails_even_with_a_zero_exit(self) -> None:
        """The failure mode the type gate already guards against.

        A runner that collected nothing parses as "0 failed". Conjoining the
        verdict with a positive total is what separates "clean" from "absent".
        """
        report = _checker().build_report(0, _NOTHING_RAN_OUTPUT)

        assert report["summary"]["total"] == 0
        assert report["summary"]["passed_all"] is False, (
            "a run that collected zero tests reported PASSED. That is how a "
            "missing pytest, a renamed directory or a collection error becomes "
            "a green gate."
        )

    def test_a_nonzero_exit_fails_even_with_a_green_summary(self) -> None:
        """The runner's own exit code is part of the verdict.

        A collection error or an internal pytest failure can print a green
        summary for the tests that did run while still exiting non-zero.
        """
        report = _checker().build_report(1, _GREEN_OUTPUT)

        assert report["summary"]["passed_all"] is False

    def test_failures_are_named_not_merely_counted(self) -> None:
        """A count alone forces a full re-run to discover what broke."""
        report = _checker().build_report(1, _RED_OUTPUT)

        assert report["summary"]["passed_all"] is False
        assert report["summary"]["failed"] == 1

        names = [entry["name"] for entry in report["tests"]]
        assert any("test_a_dirty_tree_with_no_state_file_allows_the_stop" in n for n in names), (
            f"the failing node id is absent from {names}. An agent reading this "
            "artifact cannot tell 'no detail exists' from 'the detail was dropped'."
        )

    def test_every_named_test_carries_an_outcome(self) -> None:
        """The detail array is a list of records, not bare strings."""
        report = _checker().build_report(1, _RED_OUTPUT)

        for entry in report["tests"]:
            assert entry["outcome"] == "failed"


class TestTheVerdictIsPublishedWhereTheSuitesReadIt:
    """A correct verdict under the wrong key is not a verdict.

    Both consumers resolve a report's status the same way — ``llm_qa.py`` at
    ``_report_passed`` and the summary heredoc at the end of ``run_all.sh``:

        if "passed_all" in summary: passed = summary["passed_all"]
        else:                       passed = summary.get("passed", False)

    That fallback is a trap for a TEST RUNNER, because ``summary.passed`` is a
    COUNT. This report first published its verdict as a top-level ``passed``,
    which neither consumer reads — so "60 passed, 1 failed" resolved via the
    fallback to the truthy ``60`` and both suites printed PASSED. The exit code
    was right; the line a human reads was wrong.
    """

    def test_the_verdict_lives_under_passed_all(self) -> None:
        summary = _checker().build_report(0, _GREEN_OUTPUT)["summary"]

        assert "passed_all" in summary, (
            "summary lacks 'passed_all', so both consumers fall back to "
            "summary['passed'] — a test COUNT — and report any non-zero number "
            "of passing tests as a clean check."
        )
        assert isinstance(summary["passed_all"], bool)

    def test_a_partial_failure_resolves_to_failed_through_the_consumer_logic(self) -> None:
        """Replays the consumers' own resolution, not just our own key."""
        summary = _checker().build_report(1, _RED_OUTPUT)["summary"]

        if "passed_all" in summary:
            resolved = summary["passed_all"]
        else:
            resolved = summary.get("passed", False)

        assert not resolved, (
            f"the consumers would resolve {summary!r} to a PASS. With 1 failed "
            "and 60 passed, that is the misleading-green failure this gate "
            "exists to prevent."
        )

    def test_a_run_that_collected_nothing_resolves_to_failed(self) -> None:
        """Same resolution, applied to the zero-collected case."""
        summary = _checker().build_report(0, _NOTHING_RAN_OUTPUT)["summary"]

        resolved = (
            summary["passed_all"] if "passed_all" in summary else summary.get("passed", False)
        )

        assert not resolved


class TestTheGateScopeClaimIsBacked:
    """The gate must point at the directory the exclusion note names."""

    def test_the_checker_targets_the_project_handlers_directory(self) -> None:
        """A gate scoped elsewhere would leave the claim as unenforced as before."""
        target = Path(*_checker().PROJECT_HANDLERS_DIR_PARTS)

        assert target == Path(".claude") / "project-handlers"

    def test_the_targeted_directory_holds_the_tests_it_claims_to_run(self) -> None:
        """Control: an empty target would make every assertion above vacuous."""
        target = _REPO_ROOT.joinpath(*_checker().PROJECT_HANDLERS_DIR_PARTS)

        assert list(target.rglob("test_*.py")), f"no test files found under {target}"
