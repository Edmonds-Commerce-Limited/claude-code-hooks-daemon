"""``utils`` and ``docs_qa`` must not import from ``plan_qa``.

Plan 00439, from ledger 00422 N5 row (h). ``utils/markdown_links.py`` states
the intended direction in its own docstring — "both QA packages import it, and
it imports neither of them" — and then imported ``plan_qa.model`` six lines
below the sentence. A claim nothing checks drifts silently; this checks it.

The direction is not a style preference. ``utils`` is what both QA subsystems
share, so an edge from ``utils`` into either one makes the other depend on a
package it has no business loading, and makes the shared layer impossible to
reason about from the outside.

Writing this test found six such edges where the ledger entry described one.
Clearing all six is a larger design question than the entry covers — two of
them are deliberate reuse with a documented rationale — so the five that remain
are named in :data:`_KNOWN_EDGES` with the reason each is still there. That
makes this a ratchet rather than a wish: an edge that is removed must be struck
from the list, and an edge nobody declared fails the test.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_PACKAGE: Final[Path] = _REPO_ROOT / "src" / "claude_code_hooks_daemon"

#: The package no module in :data:`_DEPENDENT_TREES` may import from.
_FORBIDDEN: Final[str] = "claude_code_hooks_daemon.plan_qa"

#: Trees that sit at or below the shared layer and must stay free of the edge.
_DEPENDENT_TREES: Final[tuple[str, ...]] = ("utils", "docs_qa")

#: Edges that exist today, each with the reason it has not been cleared.
#: Shrink this list when one goes; never grow it to make a new edge pass.
_KNOWN_EDGES: Final[dict[str, str]] = {
    "utils/goal_ledger.py -> claude_code_hooks_daemon.plan_qa.model": (
        "The ledger reads plan status through PlanDoc. Whether a plan-shaped "
        "utility belongs in utils at all is the open question, not the import."
    ),
    "docs_qa/checks/module_doc_budget.py -> claude_code_hooks_daemon.plan_qa.types": (
        "Deliberate reuse of plan_qa's own tier line-count constants, so the "
        "two budgets cannot drift apart. Moving them needs a shared home first."
    ),
}


def _imported_modules(source: str) -> list[str]:
    """Every dotted module name ``source`` imports, by either import form."""
    names: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            names.append(node.module)
    return names


def _forbidden_imports(source: str) -> list[str]:
    """The imports in ``source`` that reach into the forbidden package."""
    return [
        name
        for name in _imported_modules(source)
        if name == _FORBIDDEN or name.startswith(f"{_FORBIDDEN}.")
    ]


def _modules_in(tree: str) -> list[Path]:
    """Every ``.py`` file under one dependent tree."""
    return sorted(path for path in (_PACKAGE / tree).rglob("*.py"))


def _live_edges() -> set[str]:
    """Every ``<module> -> <plan_qa module>`` edge present in the tree."""
    edges: set[str] = set()
    for tree in _DEPENDENT_TREES:
        for path in _modules_in(tree):
            relative = path.relative_to(_PACKAGE).as_posix()
            for name in _forbidden_imports(path.read_text(encoding="utf-8")):
                edges.add(f"{relative} -> {name}")
    return edges


class TestNothingBelowTheQaPackagesImportsPlanQa:
    def test_no_undeclared_module_imports_plan_qa(self) -> None:
        undeclared = sorted(_live_edges() - set(_KNOWN_EDGES))
        assert undeclared == [], (
            "These imports invert the dependency direction utils/markdown_links.py "
            "documents, and are not in the declared allowlist: " + "; ".join(undeclared)
        )

    def test_every_declared_edge_still_exists(self) -> None:
        """A cleared edge must leave the list, or the list stops meaning anything."""
        stale = sorted(set(_KNOWN_EDGES) - _live_edges())
        assert stale == [], (
            "These edges are gone from the code but still declared — delete them "
            "from _KNOWN_EDGES: " + "; ".join(stale)
        )


class TestTheCheckWouldSeeTheEdgeIfItReturned:
    """A guard nobody has watched fail is a guard nobody has tested."""

    def test_a_from_import_of_plan_qa_is_detected(self) -> None:
        source = "from claude_code_hooks_daemon.plan_qa.model import lines_outside_fences\n"
        assert _forbidden_imports(source) == ["claude_code_hooks_daemon.plan_qa.model"]

    def test_a_plain_import_of_plan_qa_is_detected(self) -> None:
        source = "import claude_code_hooks_daemon.plan_qa\n"
        assert _forbidden_imports(source) == ["claude_code_hooks_daemon.plan_qa"]

    def test_a_package_whose_name_merely_starts_the_same_is_not_detected(self) -> None:
        source = "import claude_code_hooks_daemon.plan_qa_helpers\n"
        assert _forbidden_imports(source) == []

    def test_an_unrelated_import_is_not_detected(self) -> None:
        source = "from claude_code_hooks_daemon.utils.naming import slugify\n"
        assert _forbidden_imports(source) == []


class TestTheScanReachesRealFiles:
    """An empty scan passes the main test while checking nothing at all."""

    def test_every_dependent_tree_yields_modules(self) -> None:
        found = {tree: len(_modules_in(tree)) > 0 for tree in _DEPENDENT_TREES}
        assert found == dict.fromkeys(_DEPENDENT_TREES, True)

    def test_the_scan_sees_imports_in_those_modules(self) -> None:
        markdown_links = _PACKAGE / "utils" / "markdown_links.py"
        assert _imported_modules(markdown_links.read_text(encoding="utf-8")) != []
