"""Every QA check reports what it CHECKED, not just what it found (Plan 00412).

Class 5, `absence-indistinguishable-from-clean`: a scanner reports a clean
result without reporting its denominator, so "nothing matched" and "nothing was
checked" render identically. A reader cannot tell them apart, and the second one
is a broken check reporting success.

This is not hypothetical here. `bin/hooks-daemon secret-meta` reports the
configured word list absent in this checkout, so the secret-term half of
`sensitive_content` loads ZERO terms — and the checker, both batch sweeps and
every `gh`-body scan all report clean. Nothing asserts a non-zero term count.
The reviewers' own contract (`.claude/agents/security-reviewer.md`) requires a
HUMAN to tell absence from cleanliness; the obligation was never pushed onto the
tooling that human reads.

**This guard proposes a convention rather than pinning one**, and that is a
weaker claim worth stating out loud. When it was written, 2 of 15 checkers
reported a denominator. Compare `test_subprocess_spawns_are_bounded`, where 14
of 16 sites already complied and the guard merely stopped the drift. Here the
sweep IS the work, so the vocabulary below is explicit: a rule this broad must
not also be guessing which keys count.

An input-count key is one naming what went IN. `total_violations` is an output
and does not qualify — a check that found nothing in nothing would satisfy a
rule that accepted it, which is the exact defect.

The most uncomfortable instance is in this plan's own work:
`check_declared_invariant_pairs.py` prints "Every declared invariant pair
holds", and would print precisely that if the registry file failed to load and
it checked zero rows.

**What this guard does NOT catch, including its own headline case.** It asks
for ONE input count, not one per configured source. `check_sensitive_content.py`
satisfies it today with `files_scanned` while the defect that motivated the
whole class — a secret word list resolving to zero terms — stays invisible,
because the file count is healthy and the term count is absent. A check with two
independent corpora can therefore go half-inert and still pass here.

That is a real limit, not a rounding error, and the honest response is both
halves: the guard raises the floor across every check, and the
`sensitive_content` instance is fixed specifically rather than left to be
implied. A rule strong enough to demand a denominator PER SOURCE would need to
know what each check's sources are, which is a declaration this codebase does
not have yet.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final, NamedTuple

_QA_ROOT: Final[Path] = Path(__file__).resolve().parents[2] / "scripts" / "qa"

#: Suffixes naming an INPUT count — what the check consumed. Explicit rather
#: than a regex over "looks numeric", because the distinction this guard exists
#: to make is precisely between inputs and findings.
_INPUT_COUNT_SUFFIXES: Final[tuple[str, ...]] = (
    "_scanned",
    "_loaded",
    "_compiled",
    "_analysed",
    "_analyzed",
    "_swept",
    "_checked",
    "_considered",
    "_read",
)

#: Checks whose summary reports its denominator under a name this vocabulary
#: does not cover, each with the key that serves the purpose. An entry is a
#: judgement that the check DOES answer "how much did you look at" — not a
#: waiver of the obligation.
_ALTERNATE_DENOMINATOR: Final[dict[str, str]] = {
    # `total` here is the number of project-handler tests RUN, which is an input
    # count in every sense that matters: zero tests discovered would otherwise
    # render as a clean pass.
    "check_project_handler_tests.py": "total",
}


class _MissingDenominator(NamedTuple):
    """A check whose clean result cannot be told from an empty one."""

    checker: str
    summary_keys: tuple[str, ...]

    def __str__(self) -> str:
        return f"{self.checker} — summary is {list(self.summary_keys)}, no input count"


def _summary_keys(tree: ast.Module) -> tuple[str, ...] | None:
    """The string keys of the first ``"summary": {...}`` literal in the module.

    Only a dict LITERAL is read. A summary assembled in a variable is left
    alone — resolving it would mean following control flow, which is the
    guessing that makes a checker untrustworthy.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        keys = [
            k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)
        ]
        if "summary" not in keys:
            continue
        summary = node.values[keys.index("summary")]
        if not isinstance(summary, ast.Dict):
            continue
        return tuple(
            k.value
            for k in summary.keys
            if isinstance(k, ast.Constant) and isinstance(k.value, str)
        )
    return None


def _has_input_count(checker: str, keys: tuple[str, ...]) -> bool:
    """Whether these summary keys include something naming what went IN."""
    alternate = _ALTERNATE_DENOMINATOR.get(checker)
    if alternate is not None and alternate in keys:
        return True
    return any(key.endswith(_INPUT_COUNT_SUFFIXES) for key in keys)


def _checks_without_denominator(qa_root: Path) -> list[_MissingDenominator]:
    """Every `check_*.py` whose summary reports findings but not inputs."""
    found: list[_MissingDenominator] = []
    for module in sorted(qa_root.glob("check_*.py")):
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        keys = _summary_keys(tree)
        if keys is None:
            continue
        if not _has_input_count(module.name, keys):
            found.append(_MissingDenominator(module.name, keys))
    return found


class TestEveryCheckReportsItsDenominator:
    """The guard. A check that goes inert must not be able to report clean."""

    def test_no_check_reports_findings_without_inputs(self) -> None:
        violations = _checks_without_denominator(_QA_ROOT)

        assert violations == [], (
            "These checks report what they FOUND but not what they CHECKED, so "
            "a broken check that scanned nothing is indistinguishable from a "
            "clean run:\n\n  "
            + "\n  ".join(str(violation) for violation in violations)
            + "\n\nFix: add an input count to the `summary` dict — a key ending "
            + "in one of "
            + ", ".join(_INPUT_COUNT_SUFFIXES)
            + " — and surface it in that check's `llm_qa.py` summariser, the "
            "way `check_git_history.py` reports commits and refs swept."
        )


class TestTheScannerIsNotVacuous:
    """An empty-list assertion is what a BROKEN scanner also produces."""

    def _scan(self, tmp_path: Path, source: str) -> list[str]:
        (tmp_path / "check_offender.py").write_text(source, encoding="utf-8")
        return [missing.checker for missing in _checks_without_denominator(tmp_path)]

    def test_a_findings_only_summary_is_caught(self, tmp_path: Path) -> None:
        source = 'out = {"tool": "x", "summary": {"passed": True, "total_violations": 0}}\n'

        assert self._scan(tmp_path, source) == ["check_offender.py"]

    def test_an_input_count_satisfies_it(self, tmp_path: Path) -> None:
        source = 'out = {"summary": {"passed": True, "total_violations": 0, "files_scanned": 9}}\n'

        assert self._scan(tmp_path, source) == []

    def test_a_findings_total_alone_does_not_satisfy_it(self, tmp_path: Path) -> None:
        """The whole point: an output count is not a denominator.

        `total_violations: 0` over zero files is the defect, so a rule that
        accepted any numeric key would pass exactly the case it exists to catch.
        """
        source = 'out = {"summary": {"total_violations": 0, "by_rule": {}}}\n'

        assert self._scan(tmp_path, source) == ["check_offender.py"]

    def test_a_module_with_no_summary_is_not_flagged(self, tmp_path: Path) -> None:
        """Not every script in the directory publishes a report."""
        source = "VALUE = 1\n"

        assert self._scan(tmp_path, source) == []

    def test_terms_loaded_counts_as_an_input(self, tmp_path: Path) -> None:
        """The shape that matters most: a corpus that resolved to nothing."""
        source = 'out = {"summary": {"total_violations": 0, "secret_terms_loaded": 0}}\n'

        assert self._scan(tmp_path, source) == []
