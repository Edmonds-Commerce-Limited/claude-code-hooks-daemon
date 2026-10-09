"""Every test that reads this repository's markdown by glob is declared to the mapper.

Plan 00463 review 4 N1. ``run_changed_tests`` finds the tests that NAME a
file. A test that walks ``docs/**/*.md`` names no file, so a new or edited
page mapped to no test: ``llm_qa.py main-moved`` called it ``docs-only``, the
doc tools passed, and a head that failed
``test_documented_commands_are_not_self_denied.py`` would have landed. The
remedy is a ``path_glob`` rule in ``changed_tests_map.yaml`` naming each such
test, and this guard, so the next glob reader cannot reopen the hole silently.

A glob reader is a ``.glob``/``.rglob`` call with a markdown pattern, or a
walk, whose receiver is derived from the repository root (an expression over
``__file__``, ``os.getcwd()`` or pytest's ``rootpath``, or a name bound to
one, directly or through other such names), in any scope. A glob over
``tmp_path`` or a fixture is not one. Strings are folded as Python would
build them (a concatenation, an f-string, a name bound to either), so a
pattern or a directory is compared as the path it reads (review 6 m5).
"""

from __future__ import annotations

import ast
import functools
import importlib.util
import posixpath
import shlex
import sys
from itertools import product
from pathlib import Path, PurePosixPath
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
#: Where else a test finds the repository root (review 6 m5): ``os.getcwd()``,
#: ``Path.cwd()`` and pytest's ``config.rootpath``.
_CWD_CALLS = frozenset({"getcwd", "cwd"})
_ROOT_ATTRIBUTES = frozenset({"rootpath", "rootdir"})
_FILE = "__file__"
#: ``Path.walk()`` (3.12) as well as ``os.walk``.
_WALK = "walk"
_SPLIT = "split"
_SHLEX = "shlex"
#: Calls that pass a path through unchanged, or join more parts onto it.
_PATH_BUILDERS = frozenset({"Path", "PurePath", "PurePosixPath", "str", "join", "joinpath"})
_PATH_PASS_THROUGH = frozenset({"resolve", "absolute", "expanduser"})
_PARENT = "parent"
_PARENTS = "parents"
#: How far a string is followed through names and joins; past it, it is unknown.
_MAX_FOLD_DEPTH = 8
_MAX_FOLDED_VALUES = 64


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


def _is_root_source(node: ast.AST) -> bool:
    """Whether an expression takes a path from ``__file__``, the cwd or pytest's rootpath."""
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and child.id == _FILE:
            return True
        if isinstance(child, ast.Attribute) and child.attr in _ROOT_ATTRIBUTES:
            return True
        if (
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Attribute)
            and child.func.attr in _CWD_CALLS
        ):
            return True
    return False


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
    """Every name, in any scope, bound from a root source or from another such name."""
    repo: set[str] = set()
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            source = _source_of(node)
            if source is None:
                continue
            if _is_root_source(source) or _names(source) & repo:
                new = _targets(node) - repo
                if new:
                    repo |= new
                    changed = True
    return repo


Bindings = dict[str, list[ast.expr]]


def _bindings(tree: ast.Module) -> Bindings:
    """Each simple name, in any scope, and every expression bound to it.

    A loop variable is bound to ``*iterable`` (an ``ast.Starred``): each
    element of what it loops over.
    """
    bound: Bindings = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    bound.setdefault(target.id, []).append(node.value)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.value is not None:
                bound.setdefault(node.target.id, []).append(node.value)
        elif isinstance(node, (ast.For, ast.comprehension)) and isinstance(node.target, ast.Name):
            bound.setdefault(node.target.id, []).append(ast.Starred(value=node.iter))
    return bound


def _elements(node: ast.expr, bound: Bindings, depth: int) -> list[ast.expr] | None:
    """The elements of a literal list or tuple, directly or through a name bound to one."""
    if isinstance(node, (ast.List, ast.Tuple)):
        return list(node.elts)
    if isinstance(node, ast.Name) and depth < _MAX_FOLD_DEPTH:
        exprs = bound.get(node.id, [])
        if len(exprs) == 1:
            return _elements(exprs[0], bound, depth + 1)
    return None


def _strings(node: ast.expr, bound: Bindings, depth: int = 0) -> list[str] | None:
    """Every string ``node`` can be, built as Python builds it; None when a part is unknown.

    A concatenation and an f-string are folded, and a name is each value
    bound to it. An f-string part that cannot be known is ``*``: it may be
    anything, which is what a glob wildcard says.
    """
    if depth > _MAX_FOLD_DEPTH:
        return None
    if isinstance(node, ast.Constant):
        return [node.value] if isinstance(node.value, str) else None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _strings(node.left, bound, depth + 1)
        right = _strings(node.right, bound, depth + 1)
        if left is None or right is None:
            return None
        return [a + b for a, b in product(left, right)][:_MAX_FOLDED_VALUES]
    if isinstance(node, ast.JoinedStr):
        parts = [
            (
                _strings(value.value, bound, depth + 1) or [_WILDCARD]
                if isinstance(value, ast.FormattedValue)
                else _strings(value, bound, depth + 1) or [""]
            )
            for value in node.values
        ]
        return ["".join(choice) for choice in product(*parts)][:_MAX_FOLDED_VALUES]
    if isinstance(node, ast.Starred):
        elements = _elements(node.value, bound, depth + 1)
        return None if elements is None else _all_strings(elements, bound, depth + 1)
    if isinstance(node, ast.Name):
        exprs = bound.get(node.id)
        return None if not exprs else _all_strings(exprs, bound, depth + 1)
    return None


def _all_strings(nodes: list[ast.expr], bound: Bindings, depth: int) -> list[str] | None:
    values: list[str] = []
    for node in nodes:
        found = _strings(node, bound, depth)
        if found is None:
            return None
        values.extend(found)
    return values[:_MAX_FOLDED_VALUES]


def _string_list(node: ast.expr, bound: Bindings, depth: int = 0) -> list[str] | None:
    """The words of an argv: a literal list, a name bound to one, or a string split.

    ``'git ls-files *.md'.split()`` and ``shlex.split(...)`` are argvs too
    (review 6 m5).
    """
    elements = _elements(node, bound, depth)
    if elements is not None:
        return [(_strings(element, bound, depth + 1) or [""])[0] for element in elements]
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return None
    if node.func.attr != _SPLIT:
        return None
    if ast.unparse(node.func.value) == _SHLEX and node.args:
        text = _strings(node.args[0], bound, depth + 1)
        return shlex.split(text[0]) if text else None
    text = _strings(node.func.value, bound, depth + 1)
    return text[0].split() if text else None


def _folded_strings(tree: ast.Module, bound: Bindings) -> list[str]:
    """Every string the module writes, folded: constants, concatenations and f-strings."""
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Constant, ast.BinOp, ast.JoinedStr)):
            found.extend(_strings(node, bound) or [])
    return found


def _is_markdown_pattern(argument: ast.expr, bound: Bindings, module_has_md_globs: bool) -> bool:
    values = _strings(argument, bound)
    if values is None:
        return module_has_md_globs
    return any(_MARKDOWN in value for value in values)


def _is_repo_path(node: ast.expr, repo: set[str]) -> bool:
    return bool(_names(node) & repo) or _is_root_source(node)


def _is_git_listing(node: ast.Call, repo: set[str], bound: Bindings) -> bool:
    """A process call running ``git ls-files`` in, or on, the repository."""
    listing = any(
        _GIT_LISTING <= set(_string_list(argument, bound) or []) for argument in node.args
    )
    return listing and (
        any(_is_repo_path(argument, repo) for argument in node.args)
        or any(_is_repo_path(keyword.value, repo) for keyword in node.keywords)
    )


def _called_method(node: ast.Call, bound: Bindings) -> tuple[str, ast.expr] | None:
    """The method a call makes and its receiver, through a name bound to a bound method.

    ``g = ROOT.glob`` then ``g('*.md')`` is ``ROOT.glob('*.md')`` (review 6 m5).
    """
    function = node.func
    if isinstance(function, ast.Name):
        exprs = bound.get(function.id, [])
        if len(exprs) != 1 or not isinstance(exprs[0], ast.Attribute):
            return None
        function = exprs[0]
    if isinstance(function, ast.Attribute):
        return function.attr, function.value
    return None


def glob_readers(source: str) -> list[int]:
    """Lines where ``source`` enumerates repository markdown.

    ``.glob``/``.rglob`` with a markdown pattern, ``os.walk`` and ``Path.walk``,
    and (in a module that reads markdown) ``.iterdir()``, ``os.listdir``,
    ``glob.glob`` and ``git ls-files`` (review 5 m4), each over a path from the
    repository root.
    """
    tree = ast.parse(source)
    repo = _repo_names(tree)
    bound = _bindings(tree)
    strings = _folded_strings(tree, bound)
    has_md_globs = any(value.endswith(_MARKDOWN) and _WILDCARD in value for value in strings)
    reads_markdown = has_md_globs or _MARKDOWN in strings
    lines = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if reads_markdown and _is_git_listing(node, repo, bound):
            lines.append(node.lineno)
            continue
        called = _called_method(node, bound)
        if called is None:
            continue
        method, receiver = called
        module = ast.unparse(receiver)
        first = node.args[0] if node.args else None
        if method in _GLOB_METHODS and first is not None and module != _GLOB_MODULE:
            if _is_repo_path(receiver, repo) and _is_markdown_pattern(first, bound, has_md_globs):
                lines.append(node.lineno)
        elif method == _WALK:
            walked = first if module == "os" else receiver
            if walked is not None and _is_repo_path(walked, repo):
                lines.append(node.lineno)
        elif not reads_markdown:
            continue
        elif method == _ITERDIR and _is_repo_path(receiver, repo):
            lines.append(node.lineno)
        elif (method, module) in _PATH_LISTERS and first is not None:
            if _is_repo_path(first, repo):
                lines.append(node.lineno)
    return lines


@functools.cache
def _glob_reader_files() -> dict[str, list[int]]:
    """The scan of every test file, made once: the tree does not change during a run."""
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


def _single_string(node: ast.expr, bound: Bindings, depth: int) -> str | None:
    values = _strings(node, bound, depth)
    return values[0] if values is not None and len(values) == 1 else None


def _joined(base: PurePosixPath | None, parts: list[str | None]) -> PurePosixPath | None:
    """``base`` with ``parts`` joined on, normalised; None when a part is unknown or above the root."""
    if base is None or any(part is None for part in parts):
        return None
    joined = posixpath.normpath(base.joinpath(*(part for part in parts if part)).as_posix())
    return None if joined.startswith("..") else PurePosixPath(joined)


def _directory(
    node: ast.expr, bound: Bindings, reader: PurePosixPath, depth: int = 0
) -> PurePosixPath | None:
    """The repository-relative path an expression names, or None when it cannot be known.

    ``__file__`` is ``reader`` itself; ``.parents[N]``, ``.parent``, ``/``,
    ``joinpath``, ``Path(...)`` and ``os.path.join`` move from it; the cwd and
    pytest's rootpath are the root (review 6 m5).
    """
    if depth > _MAX_FOLD_DEPTH:
        return None
    if isinstance(node, ast.Name):
        if node.id == _FILE:
            return reader
        exprs = bound.get(node.id, [])
        return _directory(exprs[0], bound, reader, depth + 1) if len(exprs) == 1 else None
    if isinstance(node, ast.Attribute):
        if node.attr in _ROOT_ATTRIBUTES:
            return PurePosixPath()
        inner = _directory(node.value, bound, reader, depth + 1)
        if node.attr == _PARENT and inner is not None and inner != PurePosixPath():
            return inner.parent
        return None
    if isinstance(node, ast.Subscript):
        holder, index = node.value, node.slice
        if not (isinstance(holder, ast.Attribute) and holder.attr == _PARENTS):
            return None
        inner = _directory(holder.value, bound, reader, depth + 1)
        if inner is None or not isinstance(index, ast.Constant) or not isinstance(index.value, int):
            return None
        return inner.parents[index.value] if index.value < len(inner.parents) else None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        base = _directory(node.left, bound, reader, depth + 1)
        return _joined(base, [_single_string(node.right, bound, depth + 1)])
    if isinstance(node, ast.Call):
        return _called_directory(node, bound, reader, depth)
    return None


def _called_directory(
    node: ast.Call, bound: Bindings, reader: PurePosixPath, depth: int
) -> PurePosixPath | None:
    """The path a call returns: the cwd, a path passed through, or a path with parts joined."""
    function = node.func
    name = function.attr if isinstance(function, ast.Attribute) else ast.unparse(function)
    if name in _CWD_CALLS:
        return PurePosixPath()
    if isinstance(function, ast.Attribute) and name in _PATH_PASS_THROUGH:
        return _directory(function.value, bound, reader, depth + 1)
    if name not in _PATH_BUILDERS:
        return None
    if isinstance(function, ast.Attribute) and name == "joinpath":
        base, parts = _directory(function.value, bound, reader, depth + 1), node.args
    elif node.args:
        base, parts = _directory(node.args[0], bound, reader, depth + 1), node.args[1:]
    else:
        return None
    return _joined(base, [_single_string(part, bound, depth + 1) for part in parts])


def _call_patterns(tree: ast.Module, reader: str) -> list[str]:
    """Each markdown glob a ``.glob``/``.rglob`` call reads, as ``directory/pattern`` from the root.

    Review 6 m5: a directory joined onto the root, or held in a constant, and
    a pattern built by an f-string or a concatenation read the same pages as
    the literal ``CLAUDE/Architecture/*.md``, and were not compared.
    """
    bound = _bindings(tree)
    reader_path = PurePosixPath(reader)
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        called = _called_method(node, bound)
        if called is None or called[0] not in _GLOB_METHODS:
            continue
        method, receiver = called
        if ast.unparse(receiver) == _GLOB_MODULE:
            continue
        directory = _directory(receiver, bound, reader_path)
        patterns = _strings(node.args[0], bound)
        if directory is None or patterns is None:
            continue
        for pattern in patterns:
            if _MARKDOWN not in pattern or _WILDCARD not in pattern:
                continue
            reach = f"{_ANY_DEPTH}{_SEPARATOR}{pattern}" if method == "rglob" else pattern
            found.append(
                reach if directory == PurePosixPath() else f"{directory.as_posix()}/{reach}"
            )
    return found


def undeclared_patterns(source: str, reader: str, rules: list[Any]) -> list[str]:
    """Each root-relative markdown glob in ``source`` no rule naming ``reader`` covers.

    The literal globs the module writes, and each glob call's
    ``directory/pattern`` as it resolves from the root.
    """
    own = [rule for rule in rules if reader in rule.tests]
    tree = ast.parse(source)
    patterns = sorted(set(_root_patterns(tree)) | set(_call_patterns(tree, reader)))
    return [
        pattern
        for pattern in patterns
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

    @pytest.mark.parametrize(
        "body",
        [
            "CMD = ['git', 'ls-files', '*.md']\n"
            "def test_x():\n    subprocess.run(CMD, cwd=ROOT, check=True)\n",
            "def test_x():\n    subprocess.run('git ls-files *.md'.split(), cwd=ROOT, check=True)\n",
            "SUFFIX = '.m' + 'd'\ndef test_x():\n    return list(ROOT.glob('CLAUDE/*' + SUFFIX))\n",
            "def test_x():\n    g = ROOT.glob\n    return list(g('CLAUDE/*.md'))\n",
            "def test_x():\n"
            "    return [f for d, _, fs in (ROOT / 'CLAUDE').walk() for f in fs"
            " if f.endswith('.md')]\n",
            "def test_x():\n    return list(Path(os.getcwd(), 'CLAUDE').glob('*.md'))\n",
            "def test_x(pytestconfig):\n    return list(pytestconfig.rootpath.glob('CLAUDE/*.md'))\n",
            "def test_x():\n    return sorted(Path(__file__).parents[2].rglob('*.md'))\n",
        ],
        ids=[
            "git-argv-in-a-variable",
            "git-argv-split-from-a-string",
            "suffix-by-concatenation",
            "glob-method-alias",
            "path-walk",
            "root-from-getcwd",
            "root-from-rootpath",
            "inline-parents-receiver",
        ],
    )
    def test_the_spellings_review_6_found_missed_are_readers(self, body: str) -> None:
        """Review 6 m5: each of these read repository markdown and was not seen."""
        header = (
            "import os\nimport subprocess\nfrom pathlib import Path\n"
            "ROOT = Path(__file__).resolve().parents[2]\n"
        )
        assert glob_readers(header + body), body

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

    @pytest.mark.parametrize(
        "body",
        [
            "def test_probe():\n    list((REPO_ROOT / 'CLAUDE' / 'Architecture').glob('*.md'))\n",
            "PROBE_DIR = 'CLAUDE/Architecture'\n"
            "def test_probe():\n    list((REPO_ROOT / PROBE_DIR).glob('*.md'))\n",
            "def test_probe():\n    d = 'CLAUDE/Architecture'\n    list(REPO_ROOT.glob(f'{d}/*.md'))\n",
            "def test_probe():\n    list(REPO_ROOT.glob('CLAUDE/Architecture/' + '*.md'))\n",
            "def test_probe():\n    list(Path(__file__).parents[2].joinpath('CLAUDE', 'Architecture')"
            ".glob('*.md'))\n",
        ],
        ids=["joined", "directory-constant", "f-string", "concatenated", "joinpath"],
    )
    def test_the_same_new_directory_spelled_otherwise_is_found(self, body: str) -> None:
        """Review 6 m5: the receiver's directory joined with the pattern is what is read."""
        source = "from pathlib import Path\nREPO_ROOT = Path(__file__).resolve().parents[2]\n"
        missing = undeclared_patterns(source + body, _COMMAND_CHECKER, _declared_rules())
        assert missing == ["CLAUDE/Architecture/*.md"], body

    def test_a_declared_directory_spelled_as_a_join_is_not_reported(self) -> None:
        source = (
            "from pathlib import Path\nREPO_ROOT = Path(__file__).resolve().parents[2]\n"
            "def pages():\n    return list((REPO_ROOT / 'docs').rglob('*.md'))\n"
        )
        assert undeclared_patterns(source, _COMMAND_CHECKER, _declared_rules()) == []

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


@functools.cache
def _repository_corpus() -> object:
    """The mapper's corpus for this repository (immutable), built once."""
    tree, error = changed_tests.tree_files(PROJECT_ROOT)
    assert tree is not None, error
    return changed_tests.build_corpus(PROJECT_ROOT, tree)


def _selected_for(path: str) -> list[str]:
    corpus = _repository_corpus()
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
