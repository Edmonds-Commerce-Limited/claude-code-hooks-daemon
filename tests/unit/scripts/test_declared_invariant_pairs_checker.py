"""The `declared-invariant-pairs` Detector — Plan 00412 (Defence Before Fix).

The class: **this repository already implements the correct behaviour at
another site, and this site re-derives it, derives it shorter, or omits it.**

It is the largest class in the run 2026-001 corpus — thirteen instances from
eight reports that never saw each other — and it has no syntactic signature.
No rule can find a member by reading one site, because nothing about the site
is wrong on its own; it is wrong only *relative to its sibling*. So the Defence
is a checked-in **registry**: a human who has read both sides declares the pair
and the relation between them, and the Detector asserts that relation
mechanically on every run.

That buys near-zero false positives by construction, and the price is the blind
spot, which is written into the category: **a registry only covers declared
pairs.** A fourteenth divergence with no row is invisible.

Two design points here were bought by checking rows against the code they name
rather than trusting the worklist, and both are tested below:

- an extractor must SKIP a non-literal entry (an f-string built from a shared
  grammar) rather than guess at it — an under-report, which is the safe
  direction for a rule that gets switched off if it cries wolf;
- a row must be able to fail because its own file or symbol has been renamed.
  A registry that silently stops covering a pair is worse than no registry,
  because it reads as a pair that passes.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CHECKER = _REPO_ROOT / "scripts" / "qa" / "check_declared_invariant_pairs.py"
_REGISTRY = _REPO_ROOT / "scripts" / "qa" / "declared-invariant-pairs.yaml"


@pytest.fixture(scope="module")
def checker() -> ModuleType:
    """The Detector, imported from its script path."""
    spec = importlib.util.spec_from_file_location("check_declared_invariant_pairs", _CHECKER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _registry(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "pairs.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def _module(tmp_path: Path, rel: str, source: str) -> None:
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


_ONE_ROW = """
- id: demo-row
  relation: disjoint
  reason: a whitelist and a wrapper table cannot both be right about a name.
  left:
    file: a.py
    symbol: WHITELIST
    extract: regex_head_names
  right:
    file: b.py
    symbol: WRAPPERS
    extract: dict_keys
"""


class TestTheRegistry:
    def test_a_row_parses_into_both_sides(self, checker: ModuleType, tmp_path: Path) -> None:
        rows = checker.load_registry(_registry(tmp_path, _ONE_ROW))
        assert len(rows) == 1
        row = rows[0]
        assert row.row_id == "demo-row"
        assert row.relation == "disjoint"
        assert row.left.symbol == "WHITELIST"
        assert row.right.extract == "dict_keys"

    def test_an_unknown_relation_is_rejected_at_load(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        """A typo in a relation must not read as a row that passes."""
        body = _ONE_ROW.replace("relation: disjoint", "relation: disjont")
        with pytest.raises(ValueError, match="disjont"):
            checker.load_registry(_registry(tmp_path, body))

    def test_an_unknown_extractor_is_rejected_at_load(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        body = _ONE_ROW.replace("extract: dict_keys", "extract: dict_keyz")
        with pytest.raises(ValueError, match="dict_keyz"):
            checker.load_registry(_registry(tmp_path, body))


class TestTheExtractors:
    def test_dict_keys_reads_string_keys_of_a_module_level_dict(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        _module(tmp_path, "b.py", 'WRAPPERS = {"env": 1, "sudo": 2, "timeout": 3}\n')
        side = checker.Side(file="b.py", symbol="WRAPPERS", extract="dict_keys")
        assert checker.extract_members(tmp_path, side) == frozenset({"env", "sudo", "timeout"})

    def test_dict_keys_reads_through_an_annotated_assignment(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        """The real `_WRAPPERS` is annotated `Final[dict[str, _Wrapper]]`."""
        _module(tmp_path, "b.py", 'WRAPPERS: Final[dict[str, int]] = {"env": 1}\n')
        side = checker.Side(file="b.py", symbol="WRAPPERS", extract="dict_keys")
        assert checker.extract_members(tmp_path, side) == frozenset({"env"})

    def test_regex_head_names_reads_the_anchored_command_name(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        _module(tmp_path, "a.py", 'WHITELIST = (r"^grep\\b", r"^env\\b", r"^ps\\b")\n')
        side = checker.Side(file="a.py", symbol="WHITELIST", extract="regex_head_names")
        assert checker.extract_members(tmp_path, side) == frozenset({"grep", "env", "ps"})

    def test_regex_head_names_skips_an_entry_it_cannot_read_literally(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        """An f-string entry is built from a shared grammar, not a bare name.

        The real whitelist holds `rf"^{GIT_INVOCATION}log\\b"` beside plain
        literals. Guessing at it would invent a member; skipping it under-reports,
        which is the direction that keeps the rule believed.
        """
        source = 'WHITELIST = (r"^env\\b", rf"^{GIT}log\\b")\n'
        _module(tmp_path, "a.py", source)
        side = checker.Side(file="a.py", symbol="WHITELIST", extract="regex_head_names")
        assert checker.extract_members(tmp_path, side) == frozenset({"env"})

    def test_a_missing_symbol_raises_rather_than_returning_empty(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        """A renamed symbol must break the row, not quietly satisfy it.

        An empty set is disjoint from everything, so returning one on a rename
        would turn a rotted row into a passing row — the exact failure a
        registry exists to prevent.
        """
        _module(tmp_path, "b.py", "SOMETHING_ELSE = {}\n")
        side = checker.Side(file="b.py", symbol="WRAPPERS", extract="dict_keys")
        with pytest.raises(checker.RegistryRotError, match="WRAPPERS"):
            checker.extract_members(tmp_path, side)

    def test_a_missing_file_raises_rather_than_returning_empty(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        side = checker.Side(file="gone.py", symbol="WRAPPERS", extract="dict_keys")
        with pytest.raises(checker.RegistryRotError, match="gone.py"):
            checker.extract_members(tmp_path, side)


class TestTheDisjointRelation:
    def _rows(self, checker: ModuleType, tmp_path: Path) -> list[object]:
        return checker.load_registry(_registry(tmp_path, _ONE_ROW))

    def test_an_overlapping_member_is_reported(self, checker: ModuleType, tmp_path: Path) -> None:
        _module(tmp_path, "a.py", 'WHITELIST = (r"^grep\\b", r"^env\\b")\n')
        _module(tmp_path, "b.py", 'WRAPPERS = {"env": 1, "sudo": 2}\n')
        violations = checker.check_row(tmp_path, self._rows(checker, tmp_path)[0])
        assert len(violations) == 1
        assert violations[0].row_id == "demo-row"
        assert violations[0].members == ("env",)

    def test_no_overlap_is_silent(self, checker: ModuleType, tmp_path: Path) -> None:
        _module(tmp_path, "a.py", 'WHITELIST = (r"^grep\\b",)\n')
        _module(tmp_path, "b.py", 'WRAPPERS = {"env": 1}\n')
        assert checker.check_row(tmp_path, self._rows(checker, tmp_path)[0]) == []

    def test_every_overlapping_member_is_named_and_ordered(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        _module(tmp_path, "a.py", 'WHITELIST = (r"^env\\b", r"^sudo\\b", r"^nice\\b")\n')
        _module(tmp_path, "b.py", 'WRAPPERS = {"sudo": 1, "env": 2, "nice": 3}\n')
        violations = checker.check_row(tmp_path, self._rows(checker, tmp_path)[0])
        assert violations[0].members == ("env", "nice", "sudo")

    def test_a_declared_exception_is_not_reported(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        """A row may carry reviewed exceptions, so a real one need not disable it."""
        body = _ONE_ROW + "  allow: [env]\n"
        _module(tmp_path, "a.py", 'WHITELIST = (r"^env\\b", r"^sudo\\b")\n')
        _module(tmp_path, "b.py", 'WRAPPERS = {"env": 1, "sudo": 2}\n')
        rows = checker.load_registry(_registry(tmp_path, body))
        violations = checker.check_row(tmp_path, rows[0])
        assert violations[0].members == ("sudo",)


class TestTheViolation:
    def test_it_carries_the_rows_reason_so_the_message_explains_itself(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        _module(tmp_path, "a.py", 'WHITELIST = (r"^env\\b",)\n')
        _module(tmp_path, "b.py", 'WRAPPERS = {"env": 1}\n')
        rows = checker.load_registry(_registry(tmp_path, _ONE_ROW))
        payload = checker.check_row(tmp_path, rows[0])[0].to_dict()
        assert payload["rule"] == "declared-invariant-pairs"
        assert "env" in payload["message"]
        assert "cannot both be right" in payload["message"]

    def test_it_names_both_sides_so_the_reader_can_open_them(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        _module(tmp_path, "a.py", 'WHITELIST = (r"^env\\b",)\n')
        _module(tmp_path, "b.py", 'WRAPPERS = {"env": 1}\n')
        rows = checker.load_registry(_registry(tmp_path, _ONE_ROW))
        payload = checker.check_row(tmp_path, rows[0])[0].to_dict()
        assert payload["left"] == "a.py::WHITELIST"
        assert payload["right"] == "b.py::WRAPPERS"


class TestTheLiveRegistry:
    """The shipped registry itself, which must not rot silently."""

    def test_it_parses(self) -> None:
        import importlib.util as _iu

        spec = _iu.spec_from_file_location("check_declared_invariant_pairs_live", _CHECKER)
        assert spec is not None and spec.loader is not None
        module = _iu.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        assert module.load_registry(_REGISTRY)

    def test_every_declared_side_still_resolves(self, checker: ModuleType) -> None:
        """Each row's file and symbol must exist in the repository today.

        This is the test that catches a rename. The relation assertion itself
        is the Detector's job at QA time, not a unit test's — a unit test that
        asserted the live relation would have to be edited in the same commit
        as the fix, which is precisely the coupling Defence Before Fix forbids.
        """
        for row in checker.load_registry(_REGISTRY):
            for side in (row.left, row.right):
                assert checker.extract_members(_REPO_ROOT, side)


class TestMain:
    def test_json_mode_writes_the_report(
        self, checker: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _module(tmp_path, "a.py", 'WHITELIST = (r"^env\\b",)\n')
        _module(tmp_path, "b.py", 'WRAPPERS = {"env": 1}\n')
        out = tmp_path / "out.json"
        monkeypatch.setattr(checker, "_OUTPUT_FILE", out)
        monkeypatch.setattr(checker, "_QA_OUTPUT_DIR", tmp_path)
        monkeypatch.setattr(sys, "argv", ["x", "--json"])
        monkeypatch.setattr(checker, "_REPO_ROOT", tmp_path)
        monkeypatch.setattr(checker, "_DEFAULT_REGISTRY", _registry(tmp_path, _ONE_ROW))

        assert checker.main() == 1
        payload = json.loads(out.read_text())
        assert payload["summary"]["passed"] is False
        assert payload["summary"]["total_violations"] == 1

    def test_a_clean_registry_exits_zero(
        self, checker: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _module(tmp_path, "a.py", 'WHITELIST = (r"^grep\\b",)\n')
        _module(tmp_path, "b.py", 'WRAPPERS = {"env": 1}\n')
        monkeypatch.setattr(sys, "argv", ["x"])
        monkeypatch.setattr(checker, "_REPO_ROOT", tmp_path)
        monkeypatch.setattr(checker, "_DEFAULT_REGISTRY", _registry(tmp_path, _ONE_ROW))

        assert checker.main() == 0
