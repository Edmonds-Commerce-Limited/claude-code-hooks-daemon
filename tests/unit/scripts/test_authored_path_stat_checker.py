"""The `authored-path-stat` Detector — Plan 00412 (Defence Before Fix, RED first).

The class: **an author-written relative path resolved by stat-ing the join.**

``Path.exists()`` stats the path exactly as written, so a ``..`` segment is
walked through the filesystem and every directory along the way has to exist.
``CLAUDE/Security/../Routine/x.md`` therefore answers False while
``CLAUDE/Security/`` does not yet exist — which is the state of the FIRST
document written into a new directory. The hazard: a link to a file that is
really there is reported as dead, and in the edit-time docs gate a new dead
link is BLOCK severity, so the write is denied and cannot be retried into
success.

The distinguishing property is the SOURCE of the relative path. A join with a
literal filename (``root / "README.md"``) can never carry ``..``; a join with a
value lifted out of a document can. So the rule fires only on the second shape,
which is what keeps it from crying wolf over the many benign joins nearby — and
a Detector that cries wolf is a Detector that gets suppressed.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

_CHECKER = Path(__file__).resolve().parents[3] / "scripts" / "qa" / "check_authored_path_stat.py"


@pytest.fixture(scope="module")
def checker() -> ModuleType:
    """The Detector, imported from its script path."""
    spec = importlib.util.spec_from_file_location("check_authored_path_stat", _CHECKER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _scan(checker: ModuleType, tmp_path: Path, source: str, *, tree: str = "docs_qa") -> list[str]:
    """Scan ``source`` as a module inside ``tree``; return the reported rules."""
    module_dir = tmp_path / "src" / "claude_code_hooks_daemon" / tree / "checks"
    module_dir.mkdir(parents=True)
    module = module_dir / "sample.py"
    module.write_text(source, encoding="utf-8")
    return [v.rule for v in checker.scan_tree(tmp_path / "src" / "claude_code_hooks_daemon")]


class TestTheRuleFires:
    """On the shape that carries the hazard."""

    def test_a_join_with_a_variable_operand_is_reported(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        """The originating shape: the target came from a document."""
        source = "def f(base, target):\n    return (base / target).exists()\n"

        assert _scan(checker, tmp_path, source) == ["authored-path-stat"]

    @pytest.mark.parametrize("predicate", ["exists", "is_file", "is_dir"])
    def test_every_stat_predicate_counts(
        self, checker: ModuleType, tmp_path: Path, predicate: str
    ) -> None:
        """All three walk ``..`` through the filesystem identically."""
        source = f"def f(base, target):\n    return (base / target).{predicate}()\n"

        assert _scan(checker, tmp_path, source) == ["authored-path-stat"]

    def test_an_attribute_operand_counts(self, checker: ModuleType, tmp_path: Path) -> None:
        """``context.span`` is as document-sourced as a bare name."""
        source = "def f(ctx, base):\n    return (base / ctx.span).exists()\n"

        assert _scan(checker, tmp_path, source) == ["authored-path-stat"]

    def test_it_reports_the_line(self, checker: ModuleType, tmp_path: Path) -> None:
        """A finding nobody can locate is a finding nobody acts on."""
        module_dir = tmp_path / "src" / "claude_code_hooks_daemon" / "docs_qa"
        module_dir.mkdir(parents=True)
        (module_dir / "sample.py").write_text(
            "def f(base, target):\n    return (base / target).exists()\n", encoding="utf-8"
        )

        violations = checker.scan_tree(tmp_path / "src" / "claude_code_hooks_daemon")

        assert violations[0].line == 2


class TestTheRuleStaysQuiet:
    """The false positives that would get it suppressed."""

    def test_a_literal_operand_is_not_reported(self, checker: ModuleType, tmp_path: Path) -> None:
        """``root / "README.md"`` cannot carry a ``..`` segment, ever."""
        source = 'def f(root):\n    return (root / "README.md").is_file()\n'

        assert _scan(checker, tmp_path, source) == []

    def test_a_bare_predicate_is_not_reported(self, checker: ModuleType, tmp_path: Path) -> None:
        """No join, no ``..`` introduced by this expression."""
        source = "def f(path):\n    return path.exists()\n"

        assert _scan(checker, tmp_path, source) == []

    def test_a_tree_outside_the_scope_is_not_reported(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        """Scoped to the trees that resolve document-authored paths.

        Elsewhere the same shape is overwhelmingly a daemon-chosen path where
        ``..`` cannot arise: scanning all of ``src/`` finds 17 sites, against
        7 in the two trees that resolve what an author wrote.
        """
        source = "def f(base, target):\n    return (base / target).exists()\n"

        assert _scan(checker, tmp_path, source, tree="handlers") == []


class TestTheReport:
    """What a violation says for itself."""

    def test_the_rule_id_is_stable(self, checker: ModuleType, tmp_path: Path) -> None:
        """A finding is looked up by this string; it must not drift."""
        source = "def f(base, target):\n    return (base / target).exists()\n"
        module_dir = tmp_path / "src" / "claude_code_hooks_daemon" / "docs_qa"
        module_dir.mkdir(parents=True)
        (module_dir / "sample.py").write_text(source, encoding="utf-8")

        violation = checker.scan_tree(tmp_path / "src" / "claude_code_hooks_daemon")[0]

        assert violation.to_dict()["rule"] == "authored-path-stat"

    def test_the_message_names_the_hazard(self, checker: ModuleType, tmp_path: Path) -> None:
        """Not just "wrong": why the answer is wrong."""
        source = "def f(base, target):\n    return (base / target).exists()\n"
        module_dir = tmp_path / "src" / "claude_code_hooks_daemon" / "docs_qa"
        module_dir.mkdir(parents=True)
        (module_dir / "sample.py").write_text(source, encoding="utf-8")

        message = str(
            checker.scan_tree(tmp_path / "src" / "claude_code_hooks_daemon")[0].to_dict()["message"]
        )

        assert ".." in message
