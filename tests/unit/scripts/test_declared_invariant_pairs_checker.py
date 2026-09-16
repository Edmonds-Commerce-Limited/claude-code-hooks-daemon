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
from typing import Any

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


_SUPERSET_ROW = """
- id: demo-superset
  relation: superset
  reason: the guard must cover every verb the sibling already recognises.
  left:
    file: a.py
    symbol: VERBS
    extract: str_tuple
  right:
    file: b.py
    symbol: INDICATORS
    extract: regex_alternation
    only: [cp, mv, install, dd]
"""


class TestTheSupersetRelation:
    def _row(self, checker: ModuleType, tmp_path: Path, body: str = _SUPERSET_ROW) -> object:
        return checker.load_registry(_registry(tmp_path, body))[0]

    def test_a_member_missing_from_the_left_is_reported(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        _module(tmp_path, "a.py", 'VERBS = ("cp", "mv", "rsync")\n')
        _module(
            tmp_path, "b.py", 'INDICATORS = re.compile(r">|of=|\\b(?:tee|cp|mv|install|dd)\\b")\n'
        )
        violations = checker.check_row(tmp_path, self._row(checker, tmp_path))
        assert violations[0].members == ("dd", "install")

    def test_full_coverage_is_silent(self, checker: ModuleType, tmp_path: Path) -> None:
        _module(tmp_path, "a.py", 'VERBS = ("cp", "mv", "rsync", "install", "dd")\n')
        _module(
            tmp_path, "b.py", 'INDICATORS = re.compile(r">|of=|\\b(?:tee|cp|mv|install|dd)\\b")\n'
        )
        assert checker.check_row(tmp_path, self._row(checker, tmp_path)) == []

    def test_an_extra_member_on_the_left_is_not_a_violation(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        """`rsync` is on the left only, and superset is directional."""
        _module(tmp_path, "a.py", 'VERBS = ("cp", "mv", "rsync", "install", "dd")\n')
        _module(tmp_path, "b.py", 'INDICATORS = re.compile(r"\\b(?:cp|mv|install|dd)\\b")\n')
        assert checker.check_row(tmp_path, self._row(checker, tmp_path)) == []

    def test_only_excludes_a_member_that_does_not_participate(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        """`tee` writes new content rather than relocating, so it is excluded.

        Without `only` this row would demand the left side carry `tee`, which
        would be reporting a defect that is not one — the failure mode that
        gets a check switched off rather than satisfied.
        """
        _module(tmp_path, "a.py", 'VERBS = ("cp", "mv", "install", "dd")\n')
        _module(tmp_path, "b.py", 'INDICATORS = re.compile(r"\\b(?:tee|cp|mv|install|dd)\\b")\n')
        assert checker.check_row(tmp_path, self._row(checker, tmp_path)) == []

    def test_the_message_says_missing_rather_than_shared(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        _module(tmp_path, "a.py", 'VERBS = ("cp", "mv")\n')
        _module(tmp_path, "b.py", 'INDICATORS = re.compile(r"\\b(?:cp|mv|install)\\b")\n')
        payload = checker.check_row(tmp_path, self._row(checker, tmp_path))[0].to_dict()
        assert "missing from it" in payload["message"]
        assert "disjoint" not in payload["message"]


class TestTheNewExtractors:
    def test_str_tuple_reads_string_members(self, checker: ModuleType, tmp_path: Path) -> None:
        _module(tmp_path, "a.py", 'VERBS = ("cp", "mv", "rsync")\n')
        side = checker.Side(file="a.py", symbol="VERBS", extract="str_tuple")
        assert checker.extract_members(tmp_path, side) == frozenset({"cp", "mv", "rsync"})

    def test_regex_alternation_reads_through_re_compile(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        _module(tmp_path, "b.py", 'P = re.compile(r"\\b(?:tee|cp|mv)\\b")\n')
        side = checker.Side(file="b.py", symbol="P", extract="regex_alternation")
        assert checker.extract_members(tmp_path, side) == frozenset({"tee", "cp", "mv"})

    def test_regex_alternation_excludes_ungrouped_punctuation(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        """`>` and `of=` are operators, not named members.

        Folding them in would put punctuation into a set that gets compared
        against command names, and the resulting violation would name `>` as a
        missing verb.
        """
        _module(tmp_path, "b.py", 'P = re.compile(r">|of=|\\b(?:cp|mv)\\b")\n')
        side = checker.Side(file="b.py", symbol="P", extract="regex_alternation")
        assert checker.extract_members(tmp_path, side) == frozenset({"cp", "mv"})

    def test_regex_alternation_reads_a_bare_pattern_literal(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        _module(tmp_path, "b.py", 'P = r"(cp|mv)"\n')
        side = checker.Side(file="b.py", symbol="P", extract="regex_alternation")
        assert checker.extract_members(tmp_path, side) == frozenset({"cp", "mv"})


class TestTheEnumMembersExtractor:
    """Member sets spelled as enum references rather than as strings.

    The three extractors above all read STRING literals, so a set built from an
    enum — the shape this codebase reaches for whenever the members are a closed
    vocabulary — cannot be declared at all. A relation that cannot be expressed
    is a relation nobody writes down, and the class this registry defends against
    is precisely the one where two such sets drift apart.
    """

    def test_it_reads_the_members_of_a_frozenset_of_enum_references(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        _module(tmp_path, "a.py", "COVERS = frozenset({Event.CLEAN, Event.FINDINGS})\n")
        side = checker.Side(file="a.py", symbol="COVERS", extract="enum_members")
        assert checker.extract_members(tmp_path, side) == frozenset({"CLEAN", "FINDINGS"})

    def test_it_reads_a_bare_set_literal_too(self, checker: ModuleType, tmp_path: Path) -> None:
        """The wrapping call is presentation; the members are the declaration."""
        _module(tmp_path, "a.py", "COVERS = {Event.CLEAN, Event.FINDINGS}\n")
        side = checker.Side(file="a.py", symbol="COVERS", extract="enum_members")
        assert checker.extract_members(tmp_path, side) == frozenset({"CLEAN", "FINDINGS"})

    def test_it_reads_an_annotated_assignment(self, checker: ModuleType, tmp_path: Path) -> None:
        """Every such constant in this codebase carries a `Final` annotation."""
        _module(
            tmp_path,
            "a.py",
            "COVERS: Final[frozenset[Event]] = frozenset({Event.CLEAN})\n",
        )
        side = checker.Side(file="a.py", symbol="COVERS", extract="enum_members")
        assert checker.extract_members(tmp_path, side) == frozenset({"CLEAN"})

    def test_a_symbol_holding_no_enum_references_is_rot_not_an_empty_pass(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        """An empty set satisfies every relation, so it must never be returned."""
        _module(tmp_path, "a.py", 'COVERS = frozenset({"clean"})\n')
        side = checker.Side(file="a.py", symbol="COVERS", extract="enum_members")
        with pytest.raises(checker.RegistryRotError):
            checker.extract_members(tmp_path, side)


_CALL_PATH_ROW = """
- id: demo-call-path
  relation: reaches
  reason: the guard exists and both writers must go through it.
  helper: content_guard
  left:
    file: a.py
    function: write_capture
  right:
    file: a.py
    function: refresh_document
"""


class TestTheCallPathRelation:
    """The rule kind for "a helper exists and this site does not reach it".

    Several known instances of the class are this shape rather than two
    constants — an escaper applied at one interpolation and not its sibling, a
    content guard on one writer and not the other. The member sets are empty
    here; what is asserted is that a NAME is called.
    """

    def _row(self, checker: ModuleType, tmp_path: Path, body: str = _CALL_PATH_ROW) -> object:
        return checker.load_registry(_registry(tmp_path, body))[0]

    _BOTH_REACH = (
        "def write_capture(x):\n"
        "    content_guard(x)\n"
        "\n"
        "def refresh_document(x):\n"
        "    content_guard(x)\n"
    )
    _ONLY_LEFT_REACHES = (
        "def write_capture(x):\n"
        "    content_guard(x)\n"
        "\n"
        "def refresh_document(x):\n"
        "    return x\n"
    )

    def test_a_site_that_does_not_reach_the_helper_is_reported(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        _module(tmp_path, "a.py", self._ONLY_LEFT_REACHES)
        violations = checker.check_row(tmp_path, self._row(checker, tmp_path))
        assert len(violations) == 1
        assert violations[0].members == ("refresh_document",)

    def test_both_sites_reaching_it_is_silent(self, checker: ModuleType, tmp_path: Path) -> None:
        _module(tmp_path, "a.py", self._BOTH_REACH)
        assert checker.check_row(tmp_path, self._row(checker, tmp_path)) == []

    def test_a_helper_reached_via_attribute_access_counts(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        """`guards.content_guard(x)` reaches it as surely as a bare call."""
        source = (
            "def write_capture(x):\n"
            "    content_guard(x)\n"
            "\n"
            "def refresh_document(x):\n"
            "    guards.content_guard(x)\n"
        )
        _module(tmp_path, "a.py", source)
        assert checker.check_row(tmp_path, self._row(checker, tmp_path)) == []

    def test_a_helper_merely_passed_by_name_does_not_count_as_reaching_it(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        """Naming the helper is not calling it.

        A site that accepts `content_guard` as a parameter and never invokes it
        has exactly the defect this row exists to catch, so a NAME-mention test
        would report the bug as fixed.
        """
        source = (
            "def write_capture(x):\n"
            "    content_guard(x)\n"
            "\n"
            "def refresh_document(x, content_guard=None):\n"
            "    return x\n"
        )
        _module(tmp_path, "a.py", source)
        violations = checker.check_row(tmp_path, self._row(checker, tmp_path))
        assert violations[0].members == ("refresh_document",)

    def test_the_left_site_is_checked_too(self, checker: ModuleType, tmp_path: Path) -> None:
        """A row is a claim about BOTH sites, not a one-way comparison.

        If the reference site stops reaching the helper, the relation has
        stopped holding and saying so is the point.
        """
        source = "def write_capture(x):\n    return x\n\ndef refresh_document(x):\n    return x\n"
        _module(tmp_path, "a.py", source)
        violations = checker.check_row(tmp_path, self._row(checker, tmp_path))
        assert violations[0].members == ("refresh_document", "write_capture")

    def test_a_missing_function_is_registry_rot_not_a_pass(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        _module(tmp_path, "a.py", "def write_capture(x):\n    content_guard(x)\n")
        with pytest.raises(checker.RegistryRotError, match="refresh_document"):
            checker.check_row(tmp_path, self._row(checker, tmp_path))

    def test_a_row_across_two_files_resolves_each_side_separately(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        body = _CALL_PATH_ROW.replace(
            "    file: a.py\n    function: refresh_document",
            "    file: b.py\n    function: refresh_document",
        )
        _module(tmp_path, "a.py", "def write_capture(x):\n    content_guard(x)\n")
        _module(tmp_path, "b.py", "def refresh_document(x):\n    return x\n")
        violations = checker.check_row(tmp_path, self._row(checker, tmp_path, body))
        assert violations[0].members == ("refresh_document",)

    def test_a_call_path_row_requires_a_helper(self, checker: ModuleType, tmp_path: Path) -> None:
        body = _CALL_PATH_ROW.replace("  helper: content_guard\n", "")
        with pytest.raises(ValueError, match="helper"):
            checker.load_registry(_registry(tmp_path, body))

    def test_the_message_names_the_helper_and_the_site(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        _module(tmp_path, "a.py", self._ONLY_LEFT_REACHES)
        payload = checker.check_row(tmp_path, self._row(checker, tmp_path))[0].to_dict()
        assert "content_guard" in payload["message"]
        assert "refresh_document" in payload["message"]


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


_FRAGMENT_ROW = """
- id: demo-fragment-row
  relation: interpolates
  helper: OPTIONAL_PATH
  reason: >
    both anchor an executable NAME inside a command string, so an anchor that
    omits the shared path-qualifier fragment refuses to recognise the same
    binary invoked by path.
  left:
    file: a.py
    symbol: GH_PATTERN
  right:
    file: b.py
    symbol: SUDO_PATTERN
"""


class TestReachesFollowsOneHop:
    """A row names the function that OWNS the responsibility.

    Extracting the work into a small helper method is ordinary refactoring,
    and a rule that reads only the named body calls that a violation — which
    would push code to stay inline purely to satisfy a check. That is the rule
    dictating structure, and it is the wrong way round.

    The alternative was to repoint the row at the inner helper, and that is
    worse: the inner helper satisfies the row even if nobody calls it, so DEAD
    CODE would turn the row green.

    ONE hop, deliberately. Following arbitrarily far would make the row mean
    "this function eventually reaches anything", which is not an invariant.
    """

    _ROW = _CALL_PATH_ROW

    def _row(self, checker: ModuleType, tmp_path: Path) -> Any:
        return checker.load_registry(_registry(tmp_path, self._ROW))[0]

    def test_a_call_through_a_self_method_counts(self, checker: ModuleType, tmp_path: Path) -> None:
        source = (
            "class H:\n"
            "    def write_capture(self, x):\n"
            "        content_guard(x)\n"
            "\n"
            "    def refresh_document(self, x):\n"
            "        return self._scan(x)\n"
            "\n"
            "    def _scan(self, x):\n"
            "        return content_guard(x)\n"
        )
        _module(tmp_path, "a.py", source)
        assert checker.check_row(tmp_path, self._row(checker, tmp_path)) == []

    def test_a_call_through_a_module_level_function_counts(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        source = (
            "def _scan(x):\n"
            "    return content_guard(x)\n"
            "\n"
            "def write_capture(x):\n"
            "    content_guard(x)\n"
            "\n"
            "def refresh_document(x):\n"
            "    return _scan(x)\n"
        )
        _module(tmp_path, "a.py", source)
        assert checker.check_row(tmp_path, self._row(checker, tmp_path)) == []

    def test_two_hops_does_NOT_count_and_that_bound_is_the_point(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        """Stated as a limit rather than left to be discovered."""
        source = (
            "def _inner(x):\n"
            "    return content_guard(x)\n"
            "\n"
            "def _outer(x):\n"
            "    return _inner(x)\n"
            "\n"
            "def write_capture(x):\n"
            "    content_guard(x)\n"
            "\n"
            "def refresh_document(x):\n"
            "    return _outer(x)\n"
        )
        _module(tmp_path, "a.py", source)
        violations = checker.check_row(tmp_path, self._row(checker, tmp_path))
        assert violations[0].members == ("refresh_document",)

    def test_a_helper_nobody_reaches_is_still_a_violation(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        """The whole point: an unreferenced helper must not satisfy the row."""
        source = (
            "def _scan(x):\n"
            "    return content_guard(x)\n"
            "\n"
            "def write_capture(x):\n"
            "    content_guard(x)\n"
            "\n"
            "def refresh_document(x):\n"
            "    return x\n"
        )
        _module(tmp_path, "a.py", source)
        violations = checker.check_row(tmp_path, self._row(checker, tmp_path))
        assert violations[0].members == ("refresh_document",)

    def test_a_recursive_helper_terminates(self, checker: ModuleType, tmp_path: Path) -> None:
        """A cycle must not hang the Detector."""
        source = (
            "def _loop(x):\n"
            "    return _loop(x)\n"
            "\n"
            "def write_capture(x):\n"
            "    content_guard(x)\n"
            "\n"
            "def refresh_document(x):\n"
            "    return _loop(x)\n"
        )
        _module(tmp_path, "a.py", source)
        violations = checker.check_row(tmp_path, self._row(checker, tmp_path))
        assert violations[0].members == ("refresh_document",)


class TestTheFragmentRelation:
    """`interpolates` — Plan 00412 D-PUB-4.

    The third rule kind, and it exists because the first two could not express
    a real instance. `reaches` asserts a CALL; a shared regex fragment such as
    `OPTIONAL_PATH` is a module-level CONSTANT interpolated into a pattern, so
    a correct fix would have left a `reaches` row false.

    What earns this relation a row where the forwarder pair was refused one:
    **it cannot be satisfied by a partial fix.** The fragment is either in the
    pattern or it is not. A row that a half-fix turns green converts an open
    defect into a closed one on paper, which is worse than having no row.
    """

    _WITH = 'GH_PATTERN = re.compile(r"(?:^|\\s)" + OPTIONAL_PATH + r"gh\\s+issue\\b")\n'
    _SIBLING = 'SUDO_PATTERN = re.compile(SUDO_INVOCATION + OPTIONAL_PATH + r"pip\\b")\n'
    _WITHOUT = 'GH_PATTERN = re.compile(r"(?:^|\\s)gh\\s+issue\\b")\n'

    def _row(self, checker: ModuleType, tmp_path: Path, body: str = _FRAGMENT_ROW) -> Any:
        return checker.load_registry(_registry(tmp_path, body))[0]

    def test_a_fragment_row_names_a_symbol_and_needs_no_extractor(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        """The side carries a symbol, not a member set, so `extract` is absent."""
        row = self._row(checker, tmp_path)
        assert row.left.symbol == "GH_PATTERN"
        assert row.left.extract == ""
        assert row.helper == "OPTIONAL_PATH"

    def test_a_concatenated_fragment_satisfies_the_row(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        _module(tmp_path, "a.py", self._WITH)
        _module(tmp_path, "b.py", self._SIBLING)
        assert checker.check_row(tmp_path, self._row(checker, tmp_path)) == []

    def test_an_fstring_interpolated_fragment_satisfies_the_row(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        """`rf"^{OPTIONAL_PATH}gh\\b"` is how much of this repo spells it."""
        _module(tmp_path, "a.py", 'GH_PATTERN = re.compile(rf"^{OPTIONAL_PATH}gh\\b")\n')
        _module(tmp_path, "b.py", self._SIBLING)
        assert checker.check_row(tmp_path, self._row(checker, tmp_path)) == []

    def test_a_symbol_that_omits_the_fragment_is_the_violation(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        _module(tmp_path, "a.py", self._WITHOUT)
        _module(tmp_path, "b.py", self._SIBLING)
        violations = checker.check_row(tmp_path, self._row(checker, tmp_path))
        assert violations[0].members == ("GH_PATTERN",)

    def test_the_fragment_must_be_a_REFERENCE_not_the_name_as_text(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        """A pattern that merely mentions the name in a string is not using it.

        The same distinction `reaches` draws between calling a helper and
        naming it: a comment or a literal spelling `OPTIONAL_PATH` leaves the
        anchor exactly as strict as it was.
        """
        _module(tmp_path, "a.py", 'GH_PATTERN = re.compile(r"OPTIONAL_PATH gh\\s+issue\\b")\n')
        _module(tmp_path, "b.py", self._SIBLING)
        violations = checker.check_row(tmp_path, self._row(checker, tmp_path))
        assert violations[0].members == ("GH_PATTERN",)

    def test_the_reference_side_is_checked_too(self, checker: ModuleType, tmp_path: Path) -> None:
        """A row is a claim about the pair, so either side can break it."""
        _module(tmp_path, "a.py", self._WITHOUT)
        _module(tmp_path, "b.py", 'SUDO_PATTERN = re.compile(r"pip\\b")\n')
        violations = checker.check_row(tmp_path, self._row(checker, tmp_path))
        assert violations[0].members == ("GH_PATTERN", "SUDO_PATTERN")

    def test_a_fragment_row_requires_a_helper(self, checker: ModuleType, tmp_path: Path) -> None:
        body = _FRAGMENT_ROW.replace("  helper: OPTIONAL_PATH\n", "")
        with pytest.raises(ValueError, match="helper"):
            checker.load_registry(_registry(tmp_path, body))

    def test_a_missing_symbol_is_registry_rot_not_a_pass(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        """A rename must not read as a relation that holds."""
        _module(tmp_path, "a.py", "SOMETHING_ELSE = 1\n")
        _module(tmp_path, "b.py", self._SIBLING)
        with pytest.raises(checker.RegistryRotError, match="GH_PATTERN"):
            checker.check_row(tmp_path, self._row(checker, tmp_path))

    def test_the_message_names_the_fragment_and_the_site(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        _module(tmp_path, "a.py", self._WITHOUT)
        _module(tmp_path, "b.py", self._SIBLING)
        payload = checker.check_row(tmp_path, self._row(checker, tmp_path))[0].to_dict()
        assert "OPTIONAL_PATH" in payload["message"]
        assert "GH_PATTERN" in payload["message"]
        assert "invoked by path" in payload["message"]

    def test_every_relation_can_be_PRINTED_not_just_serialised(
        self, checker: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Adding a relation touches TWO renderers, and this is how I learned it.

        `to_dict` builds the JSON message; `main` keeps its own label map for
        the terminal. Adding `interpolates` to the first left the second
        raising `KeyError` on a real violation — a Detector that crashes
        instead of reporting is a Detector that gets read as a broken script.
        Asserting over the whole relation set means the next one cannot repeat
        it.
        """
        _module(tmp_path, "a.py", self._WITHOUT)
        _module(tmp_path, "b.py", self._SIBLING)
        for relation in sorted(checker._RELATIONS):
            violation = checker.Violation(
                row_id="r",
                relation=relation,
                reason="because",
                left="a.py::L",
                right="b.py::R",
                members=("L",),
                helper="OPTIONAL_PATH",
            )
            assert violation.to_dict()["message"]
            checker._print_violation(violation)
        assert capsys.readouterr().out


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
                if side.function:
                    # A call-path side names a FUNCTION; resolving it at all is
                    # the rot check, and `reaches_helper` raises if it is gone.
                    checker.reaches_helper(_REPO_ROOT, side, row.helper)
                elif not side.extract:
                    # A fragment side names a SYMBOL and no extractor; the
                    # resolution itself is the rot check, as above.
                    checker.interpolates_fragment(_REPO_ROOT, side, row.helper)
                else:
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
