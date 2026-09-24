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
_SEPARATOR = "/"
_ANY_DEPTH = "**"
_SAMPLE_NAME = "sample"
#: The other ways a test enumerates files (review 5 m4).
_ITERDIR = "iterdir"
_GLOB_MODULE = "glob"
_PATH_LISTERS = frozenset(
    {("listdir", "os"), ("scandir", "os"), ("glob", _GLOB_MODULE), ("iglob", _GLOB_MODULE)}
)
_GIT_LISTING = frozenset({"git", "ls-files"})


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


def _reads_markdown(tree: ast.Module) -> bool:
    """Whether the module filters by the markdown suffix or names a markdown glob."""
    return _markdown_constants(tree) or any(
        isinstance(node, ast.Constant) and node.value == _MARKDOWN for node in ast.walk(tree)
    )


def _is_repo_path(node: ast.expr, repo: set[str]) -> bool:
    return bool(_names(node) & repo) or _mentions_file(node)


def _is_git_listing(node: ast.Call, repo: set[str]) -> bool:
    """A process call running ``git ls-files`` in, or on, the repository."""
    listing = any(
        isinstance(argument, (ast.List, ast.Tuple))
        and _GIT_LISTING
        <= {
            element.value
            for element in argument.elts
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        }
        for argument in node.args
    )
    return listing and (
        any(_is_repo_path(argument, repo) for argument in node.args)
        or any(_is_repo_path(keyword.value, repo) for keyword in node.keywords)
    )


def glob_readers(source: str) -> list[int]:
    """Lines where ``source`` enumerates repository markdown.

    ``.glob``/``.rglob`` with a markdown pattern, ``os.walk``, and (in a module
    that reads markdown) ``.iterdir()``, ``os.listdir``, ``glob.glob`` and
    ``git ls-files`` (review 5 m4), each over a path from the repository root.
    """
    tree = ast.parse(source)
    repo = _repo_names(tree)
    has_md_globs = _markdown_constants(tree)
    reads_markdown = _reads_markdown(tree)
    lines = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if reads_markdown and _is_git_listing(node, repo):
            lines.append(node.lineno)
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        method, receiver = node.func.attr, node.func.value
        module = ast.unparse(receiver)
        first = node.args[0] if node.args else None
        if method in _GLOB_METHODS and first is not None and module != _GLOB_MODULE:
            if _names(receiver) & repo and _is_markdown_pattern(first, has_md_globs):
                lines.append(node.lineno)
        elif method == "walk" and module == "os" and first is not None:
            if _is_repo_path(first, repo):
                lines.append(node.lineno)
        elif not reads_markdown:
            continue
        elif method == _ITERDIR and _names(receiver) & repo:
            lines.append(node.lineno)
        elif (method, module) in _PATH_LISTERS and first is not None:
            if _is_repo_path(first, repo):
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


def _declared_rules() -> list[Any]:
    rules, problems = changed_tests.load_declared_rules(changed_tests.DEFAULT_RULES_PATH)
    assert problems == []
    return list(rules)


def _declared_tests() -> set[str]:
    return {test for rule in _declared_rules() for test in rule.tests}


def _root_patterns(tree: ast.Module) -> list[str]:
    """Literal markdown globs written from the repository root (``docs/**/*.md``)."""
    return sorted(
        {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value.endswith(_MARKDOWN)
            and _WILDCARD in node.value
            and _SEPARATOR in node.value
            # A leading `/` anchors a gitignore line or names an absolute path.
            and not node.value.startswith(_SEPARATOR)
        }
    )


def _samples(pattern: str) -> list[str]:
    """Paths a glob matches: ``**`` as zero and as one directory, each wildcard as a name."""
    shallow = pattern.replace(_ANY_DEPTH + _SEPARATOR, "").replace(_WILDCARD, _SAMPLE_NAME)
    deep = pattern.replace(_ANY_DEPTH, _SAMPLE_NAME).replace(_WILDCARD, _SAMPLE_NAME)
    return sorted({shallow, deep})


def undeclared_patterns(source: str, reader: str, rules: list[Any]) -> list[str]:
    """Each root-relative markdown glob in ``source`` no rule naming ``reader`` covers."""
    own = [rule for rule in rules if reader in rule.tests]
    return [
        pattern
        for pattern in _root_patterns(ast.parse(source))
        if not all(any(rule.matches(path) for rule in own) for path in _samples(pattern))
    ]


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
        # The directory listing is an enumeration of its own (review 5 m4).
        assert glob_readers(source) == [4, 5]

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

    @pytest.mark.parametrize(
        ("body", "line"),
        [
            (
                "def test_x():\n"
                "    for p in ROOT.iterdir():\n"
                "        if p.suffix == '.md':\n"
                "            p.read_text()\n",
                4,
            ),
            (
                "import os\n"
                "def test_x():\n"
                "    for name in os.listdir(ROOT / 'docs'):\n"
                "        assert name.endswith('.md')\n",
                5,
            ),
            (
                "import glob\n"
                "def test_x():\n"
                "    assert glob.glob(str(ROOT / 'docs/**/*.md'), recursive=True)\n",
                5,
            ),
            (
                "import subprocess\n"
                "def test_x():\n"
                "    out = subprocess.run(['git', 'ls-files', '*.md'], cwd=ROOT, check=True)\n",
                5,
            ),
        ],
        ids=["iterdir", "os-listdir", "glob-glob", "git-ls-files"],
    )
    def test_the_other_enumeration_idioms_are_readers(self, body: str, line: int) -> None:
        """Review 5 m4: only ``.glob``/``.rglob``/``os.walk`` were seen."""
        source = "from pathlib import Path\nROOT = Path(__file__).parents[2]\n" + body
        assert glob_readers(source) == [line]

    def test_an_enumeration_that_reads_no_markdown_is_not_a_reader(self) -> None:
        source = (
            "from pathlib import Path\nimport os\nROOT = Path(__file__).parents[2]\n"
            "def test_x():\n    assert os.listdir(ROOT / 'src')\n"
        )
        assert glob_readers(source) == []

    def test_a_git_listing_of_a_temporary_repository_is_not_a_reader(self) -> None:
        source = (
            "import subprocess\n"
            "def test_x(tmp_path):\n"
            "    subprocess.run(['git', 'ls-files', 'CLAUDE.md'], cwd=tmp_path, check=True)\n"
        )
        assert glob_readers(source) == []


#: The review 5 m4 reproduction: a NEW pattern in a reader the rules already name.
_READER_WITH_A_NEW_PATTERN = (
    "from pathlib import Path\n"
    "REPO_ROOT = Path(__file__).resolve().parents[2]\n"
    "DOCUMENT_GLOBS = ('CLAUDE/*.md', 'docs/**/*.md', 'CLAUDE/Architecture/*.md')\n"
    "def pages():\n"
    "    return [p for g in DOCUMENT_GLOBS for p in REPO_ROOT.glob(g)]\n"
)
_COMMAND_CHECKER = "tests/integration/test_documented_commands_are_not_self_denied.py"


class TestEveryPatternOfAReaderIsDeclared:
    """Review 5 m4: the guard checked reader FILES, so a new pattern in one passed.

    Each literal markdown glob a reader writes from the repository root must be
    covered by a rule naming that reader: a path it reads must select it.
    """

    def test_a_new_pattern_in_a_declared_reader_is_found(self) -> None:
        rules = _declared_rules()
        missing = undeclared_patterns(_READER_WITH_A_NEW_PATTERN, _COMMAND_CHECKER, rules)
        assert missing == ["CLAUDE/Architecture/*.md"]

    def test_every_pattern_of_every_reader_is_declared(self) -> None:
        rules = _declared_rules()
        missing = {
            reader: found
            for reader in _glob_reader_files()
            if (
                found := undeclared_patterns(
                    (PROJECT_ROOT / reader).read_text(encoding="utf-8"), reader, rules
                )
            )
        }
        assert missing == {}, (
            "these readers glob markdown no declared rule sends them: add or widen a "
            f"`path_glob` rule in scripts/qa/changed_tests_map.yaml: {missing}"
        )


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
        assert "tests/integration/test_documented_commands_are_not_self_denied.py" in _selected_for(
            path
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
