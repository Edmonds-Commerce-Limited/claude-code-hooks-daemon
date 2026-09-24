"""Every test that reads this repository's markdown by glob is declared to the mapper.

Plan 00463 review 4 N1. ``run_changed_tests`` finds the tests that NAME a
file. A test that walks ``docs/**/*.md`` names no file, so a new or edited
page mapped to no test: ``llm_qa.py main-moved`` called it ``docs-only``, the
doc tools passed, and a head that failed
``test_documented_commands_are_not_self_denied.py`` would have landed. The
remedy is a ``path_glob`` rule in ``changed_tests_map.yaml`` naming each such
test, and this guard, so the next glob reader cannot reopen the hole silently.

A glob reader is a ``.glob``/``.rglob`` call with a markdown pattern, or an
``os.walk``, whose receiver is derived from the repository root (a name bound
to an expression over ``__file__``, directly or through other such names), in
any scope. A glob over ``tmp_path`` or a fixture is not one.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
_TESTS = PROJECT_ROOT / "tests"
#: Inputs for tests (handlers that are broken on purpose), never tests themselves.
_FIXTURES = _TESTS / "fixtures"
_GLOB_METHODS = frozenset({"glob", "rglob"})
_MARKDOWN = ".md"
_WILDCARD = "*"


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


changed_tests = _load("run_changed_tests.py", "run_changed_tests_for_glob_guard")


def _names(node: ast.AST) -> set[str]:
    return {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}


def _mentions_file(node: ast.AST) -> bool:
    return "__file__" in _names(node)


def _targets(node: ast.AST) -> set[str]:
    if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        return set().union(*(_names(target) for target in targets))
    if isinstance(node, (ast.For, ast.comprehension)):
        return _names(node.target)
    return set()


def _source_of(node: ast.AST) -> ast.AST | None:
    if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
        return node.value
    if isinstance(node, (ast.For, ast.comprehension)):
        return node.iter
    return None


def _repo_names(tree: ast.Module) -> set[str]:
    """Every name, in any scope, bound from ``__file__`` or from another such name."""
    repo: set[str] = set()
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            source = _source_of(node)
            if source is None:
                continue
            if _mentions_file(source) or _names(source) & repo:
                new = _targets(node) - repo
                if new:
                    repo |= new
                    changed = True
    return repo


def _markdown_constants(tree: ast.Module) -> bool:
    return any(
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.endswith(_MARKDOWN)
        and _WILDCARD in node.value
        for node in ast.walk(tree)
    )


def _is_markdown_pattern(argument: ast.expr, module_has_md_globs: bool) -> bool:
    if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
        return _MARKDOWN in argument.value
    if isinstance(argument, ast.JoinedStr):
        return _MARKDOWN in ast.unparse(argument)
    return module_has_md_globs


def glob_readers(source: str) -> list[int]:
    """Lines where ``source`` reads repository markdown by glob or walk."""
    tree = ast.parse(source)
    repo = _repo_names(tree)
    has_md_globs = _markdown_constants(tree)
    lines = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        method, receiver = node.func.attr, node.func.value
        if method in _GLOB_METHODS and node.args:
            if _names(receiver) & repo and _is_markdown_pattern(node.args[0], has_md_globs):
                lines.append(node.lineno)
        elif method == "walk" and ast.unparse(receiver) == "os" and node.args:
            if _names(node.args[0]) & repo or _mentions_file(node.args[0]):
                lines.append(node.lineno)
    return lines


def _glob_reader_files() -> dict[str, list[int]]:
    found = {}
    for path in sorted(_TESTS.rglob("*.py")):
        if _FIXTURES in path.parents:
            continue
        lines = glob_readers(path.read_text(encoding="utf-8"))
        if lines:
            found[path.relative_to(PROJECT_ROOT).as_posix()] = lines
    return found


def _declared_tests() -> set[str]:
    rules, problems = changed_tests.load_declared_rules(changed_tests.DEFAULT_RULES_PATH)
    assert problems == []
    return {test for rule in rules for test in rule.tests}


class TestTheScanner:
    def test_a_glob_over_the_repository_root_is_a_reader(self) -> None:
        source = (
            "from pathlib import Path\n"
            "ROOT = Path(__file__).resolve().parents[3]\n"
            "DOCS = ROOT / 'docs'\n"
            "def test_x():\n"
            "    for page in DOCS.rglob('*.md'):\n"
            "        page.read_text()\n"
        )
        assert glob_readers(source) == [5]

    def test_a_pattern_held_in_a_variable_counts_when_the_module_names_md_globs(self) -> None:
        source = (
            "from pathlib import Path\n"
            "ROOT = Path(__file__).parents[2]\n"
            "GLOBS = ('docs/**/*.md',)\n"
            "def pages():\n"
            "    return [p for g in GLOBS for p in ROOT.glob(g)]\n"
        )
        assert glob_readers(source) == [5]

    def test_a_loop_variable_over_a_repository_directory_is_a_repository_path(self) -> None:
        source = (
            "from pathlib import Path\n"
            "ROOTS = (Path(__file__).parents[3] / 'skills',)\n"
            "def test_x():\n"
            "    for skill in [s for r in ROOTS for s in r.iterdir()]:\n"
            "        list(skill.rglob('*.md'))\n"
        )
        assert glob_readers(source) == [5]

    @pytest.mark.parametrize(
        "body",
        [
            "def test_x(tmp_path):\n    list(tmp_path.glob('*.md'))\n",
            "def test_x(tmp_path):\n    d = tmp_path / 'r'\n    list(d.rglob('*.md'))\n",
            "ROOT = Path(__file__).parents[2]\ndef test_x():\n    list(ROOT.rglob('*.py'))\n",
        ],
        ids=["tmp-path", "derived-from-a-fixture", "not-markdown"],
    )
    def test_anything_else_is_not(self, body: str) -> None:
        assert glob_readers("from pathlib import Path\n" + body) == []


class TestEveryGlobReaderIsDeclared:
    def test_the_scan_finds_the_readers_review_4_named(self) -> None:
        """Not vacuous: a scanner that finds nothing would pass the next test."""
        found = _glob_reader_files()
        assert "tests/integration/test_documented_commands_are_not_self_denied.py" in found
        assert "tests/unit/scripts/test_branch_install_gate_is_unadvertised.py" in found

    def test_each_is_named_by_a_declared_rule(self) -> None:
        undeclared = sorted(set(_glob_reader_files()) - _declared_tests())
        assert undeclared == [], (
            "these tests read repository markdown by glob, which the mapper cannot see: "
            "add a `path_glob` rule to scripts/qa/changed_tests_map.yaml naming each, "
            f"covering the paths it reads: {undeclared}"
        )


def _selected_for(path: str) -> list[str]:
    tree, error = changed_tests.tree_files(PROJECT_ROOT)
    assert tree is not None, error
    corpus = changed_tests.build_corpus(PROJECT_ROOT, tree)
    rules, _ = changed_tests.load_declared_rules(changed_tests.DEFAULT_RULES_PATH)
    selection = changed_tests.select_tests([path], corpus, PROJECT_ROOT, rules)
    return [test for entry in selection.mapping for test in entry["tests"]]


class TestTheReviewReproduction:
    """Review 4 N1: each of these read ``docs-only`` or missed the failing test."""

    @pytest.mark.parametrize(
        "path",
        [
            "docs/guides/TROUBLESHOOTING.md",
            "docs/guides/PROBE_NEW_GUIDE.md",
            "CLAUDE/Worktree.md",
        ],
    )
    def test_a_page_the_command_checker_reads_selects_it(self, path: str) -> None:
        assert (
            "tests/integration/test_documented_commands_are_not_self_denied.py"
            in _selected_for(path)
        )

    def test_a_plan_document_is_not_swept_in(self) -> None:
        """``CLAUDE/*.md`` is one directory deep, not every plan document.

        The path is made up: naming a real ledger here would make this file
        a test that reads it.
        """
        assert (
            "tests/integration/test_documented_commands_are_not_self_denied.py"
            not in _selected_for("CLAUDE/Plan/99999-an-example-plan/NOTES.md")
        )
