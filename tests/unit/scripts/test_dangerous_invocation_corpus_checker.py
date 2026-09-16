"""The `dangerous-invocation-corpus` Detector — Plan 00412 class 6.

The class: **a dangerous outcome is reachable by a command, flag or shell
construct that no guard's pattern names** — either because a guard enumerates a
tool whose subcommand set is open, or because no guard exists for the outcome
at all. The worklist merges F-BYPS's "sibling-spelling gaps" and F-GAP's "no
handler judges it" against both reports' framing, because one Detector finds
both: whether a row is uncovered because a pattern is short or because nothing
exists is a fact to report, not a reason for two Detectors.

**Both passes are required.** F-GAP measured that `verification_result_gate`
MATCHES almost every git command and then allows it, so a `matches()`-only
method scores 24 git candidates as covered while nothing denies them. The
corpus therefore asks the real chain for a DECISION.

**The verdict travels in both directions.** A `COVERED` row that stops being
denied is a guard regression. An `UNCOVERED` row that starts being denied is
also a failure — the good kind, but the corpus must not silently keep claiming
a gap that has since been closed, because the next reader uses this file to
decide what is worth building.

The blind spot belongs in the category and is the honest reason this Detector
is weaker than classes 1, 5 or 7: **the corpus only covers what someone thought
to add.** It converts an invisible gap into a visible list; it does not
generate the list.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CHECKER = _REPO_ROOT / "scripts" / "qa" / "check_dangerous_invocation_corpus.py"
_CORPUS = _REPO_ROOT / "scripts" / "qa" / "dangerous-invocation-corpus.yaml"


@pytest.fixture(scope="module")
def checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_dangerous_invocation_corpus", _CHECKER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _corpus(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "corpus.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def _row(command: str, verdict: str, *, row_id: str = "demo") -> str:
    return (
        f"rows:\n"
        f"  - id: {row_id}\n"
        f'    command: "{command}"\n'
        f"    axis: demo-axis\n"
        f"    verdict: {verdict}\n"
        f'    note: "a note that explains the verdict"\n'
    )


def _denies(*commands: str):
    """A stand-in chain that denies exactly the listed commands."""
    denied = set(commands)

    def verdict(command: str) -> tuple[bool, str]:
        return (command in denied, "stub-handler" if command in denied else "")

    return verdict


class TestVerdictsAreHeldInBothDirections:
    def test_a_covered_row_that_is_no_longer_denied_fails(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        """A guard regression: the row says covered, the chain allows it."""
        corpus = _corpus(tmp_path, _row("git reset --hard", "COVERED"))

        violations = checker.scan(corpus, _denies())

        assert len(violations) == 1
        assert "no longer" in violations[0].detail

    def test_a_covered_row_that_is_still_denied_is_clean(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        corpus = _corpus(tmp_path, _row("git reset --hard", "COVERED"))

        assert checker.scan(corpus, _denies("git reset --hard")) == []

    def test_an_uncovered_row_that_is_now_denied_fails(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        """The good direction, which must still fail.

        A corpus that silently kept claiming a gap after it was closed would
        mislead the next reader deciding what is worth building.
        """
        corpus = _corpus(tmp_path, _row("rm -rf ./src", "UNCOVERED-open"))

        violations = checker.scan(corpus, _denies("rm -rf ./src"))

        assert len(violations) == 1
        assert "now denies it" in violations[0].detail
        assert "record the good news" in violations[0].detail

    def test_an_uncovered_row_that_is_still_allowed_is_clean(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        corpus = _corpus(tmp_path, _row("rm -rf ./src", "UNCOVERED-open"))

        assert checker.scan(corpus, _denies()) == []

    def test_accepted_and_open_are_both_uncovered_for_pass_purposes(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        """The two uncovered verdicts differ in intent, not in what the chain does.

        `accepted` records a reviewed decision not to close the gap; `open`
        records one nobody has decided yet. Treating them the same here is what
        lets the distinction be about intent rather than about enforcement.
        """
        corpus = _corpus(tmp_path, _row("git rebase main", "UNCOVERED-accepted"))

        assert checker.scan(corpus, _denies()) == []


class TestRowQuality:
    def test_an_unknown_verdict_is_a_violation(self, checker: ModuleType, tmp_path: Path) -> None:
        corpus = _corpus(tmp_path, _row("git status", "PROBABLY-FINE"))

        violations = checker.scan(corpus, _denies())

        assert len(violations) == 1
        assert "verdict" in violations[0].detail

    def test_a_row_without_a_note_is_a_violation(self, checker: ModuleType, tmp_path: Path) -> None:
        """An unexplained row cannot be reviewed, and this corpus is all judgement."""
        corpus = _corpus(
            tmp_path,
            'rows:\n  - id: bare\n    command: "git status"\n    axis: x\n    verdict: COVERED\n',
        )

        violations = checker.scan(corpus, _denies("git status"))

        assert len(violations) == 1
        assert "note" in violations[0].detail

    def test_duplicate_ids_are_a_violation(self, checker: ModuleType, tmp_path: Path) -> None:
        """Two rows under one id makes the count a lie and hides one of them."""
        corpus = _corpus(tmp_path, _row("git status", "COVERED", row_id="same"))
        corpus.write_text(
            corpus.read_text(encoding="utf-8")
            + '  - id: same\n    command: "ls"\n    axis: x\n'
            + '    verdict: COVERED\n    note: "n"\n',
            encoding="utf-8",
        )

        violations = checker.scan(corpus, _denies("git status", "ls"))

        assert any("duplicate" in v.detail for v in violations)


class TestDenominator:
    def test_the_summary_reports_what_was_checked(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        """ "Nothing failed" and "nothing ran" must not render identically."""
        corpus = _corpus(tmp_path, _row("rm -rf ./src", "UNCOVERED-open"))

        counts = checker.count_rows(corpus)

        assert counts["total"] == 1
        assert counts["uncovered_open"] == 1
        assert counts["covered"] == 0


class TestRealTree:
    def test_the_real_corpus_matches_the_real_chain(self, checker: ModuleType) -> None:
        """Every recorded verdict still describes what the daemon actually does."""
        violations = checker.scan(_CORPUS, checker.real_chain_verdict())

        assert violations == [], "\n".join(f"{v.row_id}: {v.detail}" for v in violations)

    def test_the_real_chain_can_still_deny_something(self, checker: ModuleType) -> None:
        """Vacuity control, and the one that carries the evidence.

        If the in-process chain denied nothing at all, every UNCOVERED row
        would pass for the wrong reason and the corpus would read as a
        catalogue of gaps when it was really a broken harness.
        """
        verdict = checker.real_chain_verdict()

        denied, who = verdict("git reset --hard")

        assert denied, "the chain denied nothing -- the harness is not reading it"
        assert who
