#!/usr/bin/env python3
"""QA tool: pytest on the tests mapped from what changed since the merge base.

The test half of ``llm_qa.py changed`` (Plan 00463). Sub-agents run targeted QA,
and the coordinator runs the full suite once per batch. The targeted path
has to be ONE command, or each agent invents its own subset and some invent
none.

**Every changed file is accounted for, or the run fails.** A test file
selects itself. Any other file's coverage is the UNION of:

1. its DECLARED rule in ``changed_tests_map.yaml``: named tests, or the
   ``llm_qa.py`` tools that check it. A ``tools`` rule certifies only what
   those tools check (markdown lint, shellcheck), never behaviour.
2. its MIRRORED tests: ``src/<pkg>/a/b.py`` and ``scripts/a/b.py`` map to
   ``tests/unit/a/test_b.py`` and ``test_b_*.py``.
3. the tests that REFER to it: by its path, by a path suffix, by its
   basename when no other file shares it, or by importing it.
4. one hop of DEPENDENTS: each source that refers to it the same way adds
   its own unit tests (its mirror, else the tests that refer to it). A
   conftest's tests are its whole subtree. Reach beyond one hop is the
   coordinator's full gate.

References are read from the syntax tree, so a comment or docstring that
mentions a file is not a dependency.

A reach wider than ``MAX_IMPORT_SELECTION`` test files is the full suite by
another name, and so is the root ``tests/conftest.py``: those are unmapped as
``too-broad``. A selected directory counts as every test file under it, so a
nested conftest's subtree is weighed by its size, not as one entry. A DELETED file maps to the tests that still refer to it, which
are exactly the ones that now break. One that a source still refers to is
unmapped, and one nothing refers to is verified rather than skipped. An
unmapped file fails the run unless ``--allow-unmapped`` says the
coordinator's full gate will cover it, and the report records why each one is
unmapped. A run that tested nothing never reads as a pass.

"Changed" is everything that differs from the merge base with ``--base``:
committed work on the branch, uncommitted edits, and new untracked files. On
the base branch itself the merge base is HEAD and committed work vanishes, so
that is refused. ``--range A..B`` instead takes exactly what ``git diff A B``
changed, judged in this tree: the batched gate's recheck of what a move of
``main`` brought in (``llm_qa.py main-moved``). ``--select-only`` prints that
selection as JSON and runs nothing; it is how ``main-moved`` asks this mapper,
and never another copy of it, which moved documents tests read.

Usage:
    python scripts/qa/run_changed_tests.py [--json] [--root DIR]
        [--base REF | --range A..B [--select-only]] [--rules FILE] [--allow-unmapped]

``--base`` defaults to the local branch ``origin/HEAD`` names, then to
``origin/<it>``, then to a local ``main``.

Exit codes:
    0 - every change is accounted for and the selected tests passed
    1 - a selected test failed, the selection collected nothing, a change is
        unmapped, or nothing changed at all
    2 - operational failure (no base, no merge base, on the base branch,
        a malformed rules file, git unavailable)
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import logging
import re
import subprocess  # nosec B404 — runs git and this interpreter, argv form, no shell
import sys
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Final

import yaml

from claude_code_hooks_daemon.qa.pytest_text_report import parse_pytest_text_output
from claude_code_hooks_daemon.utils.path_containment import path_relative_to

logger = logging.getLogger(__name__)

_PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_QA_OUTPUT_DIR_PARTS: Final[tuple[str, str]] = ("untracked", "qa")
_OUTPUT_FILENAME: Final[str] = "changed_tests.json"
_TOOL_NAME: Final[str] = "changed_tests"

#: This repository's declared rules for what a name cannot map.
DEFAULT_RULES_PATH: Final[Path] = Path(__file__).resolve().parent / "changed_tests_map.yaml"

EXIT_SUCCESS: Final[int] = 0
EXIT_ISSUES: Final[int] = 1
EXIT_OPERATIONAL: Final[int] = 2

#: The base when ``origin/HEAD`` names none.
FALLBACK_BASE: Final[str] = "main"
_RANGE_SEPARATOR: Final[str] = ".."
_REMOTE_PREFIX: Final[str] = "origin/"
_ORIGIN_HEAD_REF: Final[str] = "refs/remotes/origin/HEAD"
_LOCAL_BRANCH_PREFIX: Final[str] = "refs/heads/"

_TEST_ROOT: Final[str] = "tests"
_UNIT_DIR: Final[str] = "unit"
_SOURCE_ROOT: Final[str] = "src"
_SCRIPTS_ROOT: Final[str] = "scripts"
_TEST_GLOB: Final[str] = "test_*.py"
_TEST_PREFIX: Final[str] = "test_"
_PYTHON_SUFFIX: Final[str] = ".py"
_PACKAGE_INIT_STEM: Final[str] = "__init__"
_CONFTEST: Final[str] = "conftest.py"
#: Where the code a change can reach a test through lives.
_MODULE_ROOTS: Final[frozenset[str]] = frozenset({_SOURCE_ROOT, _SCRIPTS_ROOT, _TEST_ROOT})
#: How many of a deleted file's remaining referrers a reason names.
_NAMED_DEPENDENTS: Final[int] = 5

#: A reach wider than this many test files is the full suite by another name.
MAX_IMPORT_SELECTION: Final[int] = 40

# Mapping rules, as recorded in the report. A file's entry lists every rule
# that contributed tests, because its coverage is their union.
RULE_DECLARED: Final[str] = "declared"
RULE_SELF: Final[str] = "self"
RULE_REFERENCE: Final[str] = "reference"
RULE_SUBTREE: Final[str] = "conftest-subtree"
RULE_DEPENDENT: Final[str] = "dependent"
RULE_DELETED_TEST: Final[str] = "deleted-test"
RULE_DELETED_UNREFERENCED: Final[str] = "deleted-unreferenced"

# Why a file is unmapped, as recorded in the report.
REASON_TOO_BROAD: Final[str] = "too-broad"
REASON_UNCOVERED: Final[str] = "uncovered"
REASON_STILL_REFERENCED: Final[str] = "deleted-but-referenced"

# Declared-rule keys.
_KEY_RULES: Final[str] = "rules"
_KEY_GLOB: Final[str] = "glob"
_KEY_PATH_GLOB: Final[str] = "path_glob"
_KEY_PATH_EXCLUDE: Final[str] = "path_exclude"
_KEY_TESTS: Final[str] = "tests"
_KEY_TOOLS: Final[str] = "tools"
_KEY_WHY: Final[str] = "why"
_RULE_KEYS: Final[frozenset[str]] = frozenset(
    {_KEY_GLOB, _KEY_PATH_GLOB, _KEY_PATH_EXCLUDE, _KEY_TESTS, _KEY_TOOLS, _KEY_WHY}
)
#: A ``path_glob`` segment matching any number of directories, as in ``Path.glob``.
_ANY_DEPTH: Final[str] = "**"

_OUTCOME_FAILED: Final[str] = "failed"

#: A git plumbing call is instant; this bound only stops a hung git from
#: hanging the QA run.
_GIT_TIMEOUT_SECONDS: Final[int] = 60

#: A targeted run is minutes at most. Past this the selection was not targeted.
_PYTEST_TIMEOUT_SECONDS: Final[int] = 1800

#: (exit code, stdout, stderr) and (exit code, combined output): injected in
#: tests so the selection and verdict logic run without a repository or pytest.
GitRunner = Callable[[list[str], Path], tuple[int, str, str]]
PytestRunner = Callable[[list[str], Path], tuple[int, str]]


@dataclass(frozen=True, slots=True)
class DeclaredRule:
    """One entry of the rules file: a glob and what covers the files it matches.

    ``glob`` is fnmatch (``*`` crosses ``/``); with ``path_style`` it is a
    ``Path.glob`` pattern instead, so a rule can name exactly the files a test
    reads by glob (``CLAUDE/*.md`` is one directory, ``docs/**/*.md`` any depth).

    ``excludes`` are ``Path.glob``-style patterns a matching path must not
    also match: a reader can glob a broad tree and then drop a subtree of its
    own (``_EXCLUDED_PREFIXES``), and the declared rule has to mirror that
    drop or a file the reader never touches is wrongly covered. A second rule
    re-includes a path the first excludes, the same way the reader's own
    re-inclusion list does (rules OR together).
    """

    glob: str
    tests: tuple[str, ...]
    tools: tuple[str, ...]
    why: str
    path_style: bool = False
    excludes: tuple[str, ...] = ()

    def matches(self, relative: str) -> bool:
        """Whether this rule covers ``relative``."""
        if any(path_glob_matches(relative, pattern) for pattern in self.excludes):
            return False
        if self.path_style:
            return path_glob_matches(relative, self.glob)
        return fnmatch.fnmatch(relative, self.glob)


def path_glob_matches(relative: str, pattern: str) -> bool:
    """Whether ``Path(root).glob(pattern)`` would yield ``relative``.

    Each segment is matched on its own, so ``*`` never crosses ``/``, and a
    ``**`` segment matches zero or more whole directories.
    """
    return _segments_match(relative.split("/"), pattern.split("/"))


def _segments_match(parts: Sequence[str], patterns: Sequence[str]) -> bool:
    if not patterns:
        return not parts
    head, rest = patterns[0], patterns[1:]
    if head == _ANY_DEPTH:
        return any(_segments_match(parts[skip:], rest) for skip in range(len(parts) + 1))
    return bool(parts) and fnmatch.fnmatchcase(parts[0], head) and _segments_match(parts[1:], rest)


@dataclass(slots=True)
class Selection:
    """What a change set maps to, and what it does not."""

    selected: list[str] = field(default_factory=list)
    mapping: list[dict[str, Any]] = field(default_factory=list)
    unmapped: list[str] = field(default_factory=list)
    reasons: dict[str, dict[str, Any]] = field(default_factory=dict)
    deleted: list[str] = field(default_factory=list)
    non_python: list[str] = field(default_factory=list)


def run_git(args: list[str], root: Path) -> tuple[int, str, str]:
    """Run one git command in ``root``; a failure to run is a non-zero result."""
    try:
        completed = subprocess.run(  # nosec B603 B607 — git by name, argv form, no shell
            ["git", *args],
            capture_output=True,
            text=True,
            cwd=str(root),
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return EXIT_OPERATIONAL, "", f"git {' '.join(args)} did not run: {exc}"
    return completed.returncode, completed.stdout, completed.stderr


def run_pytest(paths: list[str], root: Path) -> tuple[int, str]:
    """Run pytest on explicit paths under this interpreter."""
    try:
        completed = subprocess.run(  # nosec B603 — this interpreter, argv form, no shell
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *paths],
            capture_output=True,
            text=True,
            cwd=str(root),
            timeout=_PYTEST_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return EXIT_OPERATIONAL, f"ERROR: pytest did not run: {exc}\n"
    return completed.returncode, completed.stdout + completed.stderr


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _local_branch_exists(root: Path, name: str, git: GitRunner) -> bool:
    code, _, _ = git(["rev-parse", "--verify", "--quiet", f"{_LOCAL_BRANCH_PREFIX}{name}"], root)
    return code == 0


def resolve_base(
    root: Path, requested: str | None, *, git: GitRunner = run_git
) -> tuple[str | None, str | None]:
    """``(base, None)``, or ``(None, reason)`` when there is nothing to diff against.

    An explicit ``--base`` wins. Otherwise the branch ``origin/HEAD`` names:
    its local copy when there is one, because a worktree branches from the
    local copy, and the remote one when there is not. With no ``origin/HEAD``
    a local ``main`` is used.
    """
    if requested:
        return requested, None
    code, stdout, _ = git(["symbolic-ref", "--quiet", "--short", _ORIGIN_HEAD_REF], root)
    remote_default = stdout.strip()
    if code == 0 and remote_default:
        local = remote_default.removeprefix(_REMOTE_PREFIX)
        return (local if _local_branch_exists(root, local, git) else remote_default), None
    if _local_branch_exists(root, FALLBACK_BASE, git):
        return FALLBACK_BASE, None
    return None, (
        f"no default base: `origin/HEAD` is unset and there is no local `{FALLBACK_BASE}`. "
        "Pass --base <ref>."
    )


def current_branch(root: Path, *, git: GitRunner = run_git) -> str | None:
    """The checked-out branch name, or None for a detached HEAD."""
    code, stdout, _ = git(["symbolic-ref", "--quiet", "--short", "HEAD"], root)
    name = stdout.strip()
    return name if code == 0 and name else None


def changed_files(
    root: Path, base: str, *, git: GitRunner = run_git
) -> tuple[list[str] | None, str | None]:
    """``(files, None)``, or ``(None, reason)`` when the change set is unknowable.

    No merge base is an ERROR, not an empty change set: an empty list would
    read as "nothing changed". Renames are listed as both paths, so a module
    renamed away still counts as deleted.
    """
    code, stdout, stderr = git(["merge-base", "HEAD", base], root)
    merge_base = stdout.strip()
    if code != 0 or not merge_base:
        detail = stderr.strip() or "no output"
        return None, f"no merge base between HEAD and `{base}`: {detail}"

    code, diffed, stderr = git(["diff", "--name-only", "--no-renames", merge_base], root)
    if code != 0:
        return None, f"git diff against {merge_base} failed: {stderr.strip() or 'no output'}"

    code, untracked, stderr = git(["ls-files", "--others", "--exclude-standard"], root)
    if code != 0:
        return None, f"git ls-files failed: {stderr.strip() or 'no output'}"

    return sorted(set(_lines(diffed)) | set(_lines(untracked))), None


def parse_range(spec: str) -> tuple[str, str] | None:
    """``A..B`` as ``(A, B)``, or None when it is not exactly two named ends."""
    start, separator, end = spec.partition(_RANGE_SEPARATOR)
    if not separator or not start or not end or _RANGE_SEPARATOR[0] in (start[-1], end[0]):
        return None
    if _RANGE_SEPARATOR in end:
        return None
    return start, end


def range_files(
    root: Path, spec: str, *, git: GitRunner = run_git
) -> tuple[list[str] | None, str | None]:
    """``(files, None)`` for what ``git diff A B`` changed, or ``(None, reason)``.

    Renames are listed as both paths, as for a ``--base`` run.
    """
    ends = parse_range(spec)
    if ends is None:
        return None, f"--range needs exactly two refs, `A..B`: got `{spec}`"
    code, stdout, stderr = git(["diff", "--name-only", "--no-renames", *ends], root)
    if code != 0:
        return None, f"git diff {spec} failed: {stderr.strip() or 'no output'}"
    return sorted(set(_lines(stdout))), None


def tree_files(root: Path, *, git: GitRunner = run_git) -> tuple[list[str] | None, str | None]:
    """Every tracked and untracked (not ignored) file: what a change can be searched in."""
    code, stdout, stderr = git(["ls-files", "--cached", "--others", "--exclude-standard"], root)
    if code != 0:
        return None, f"git ls-files failed: {stderr.strip() or 'no output'}"
    return _lines(stdout), None


def _text_list(value: object) -> tuple[str, ...] | None:
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        return None
    return tuple(v.strip() for v in value)


def parse_declared_rules(raw: object) -> tuple[list[DeclaredRule], list[str]]:
    """Validate the rules file's content; a malformed entry is reported, never guessed."""
    if not isinstance(raw, Mapping) or not isinstance(raw.get(_KEY_RULES), list):
        return [], [f"the rules file must be a mapping with a `{_KEY_RULES}` list"]
    rules: list[DeclaredRule] = []
    problems: list[str] = []
    for position, entry in enumerate(raw[_KEY_RULES], start=1):
        if not isinstance(entry, Mapping):
            problems.append(f"rule {position}: expected a mapping")
            continue
        unknown = sorted(str(key) for key in entry if key not in _RULE_KEYS)
        path_style = _KEY_PATH_GLOB in entry
        glob = entry.get(_KEY_PATH_GLOB if path_style else _KEY_GLOB)
        why = entry.get(_KEY_WHY)
        tests = _text_list(entry.get(_KEY_TESTS, []))
        tools = _text_list(entry.get(_KEY_TOOLS, []))
        excludes = _text_list(entry.get(_KEY_PATH_EXCLUDE, []))
        if unknown:
            problems.append(f"rule {position}: unknown key(s) {', '.join(unknown)}")
        elif path_style and _KEY_GLOB in entry:
            problems.append(
                f"rule {position}: give exactly one of `{_KEY_GLOB}` or `{_KEY_PATH_GLOB}`"
            )
        elif not isinstance(glob, str) or not glob.strip():
            problems.append(
                f"rule {position}: `{_KEY_GLOB}` or `{_KEY_PATH_GLOB}` must be a non-empty string"
            )
        elif not isinstance(why, str) or not why.strip():
            problems.append(f"rule {position}: `{_KEY_WHY}` must say what covers these files")
        elif tests is None or tools is None or excludes is None:
            problems.append(
                f"rule {position}: `{_KEY_TESTS}`/`{_KEY_TOOLS}`/`{_KEY_PATH_EXCLUDE}` "
                "must be string lists"
            )
        elif bool(tests) == bool(tools):
            problems.append(
                f"rule {position}: give exactly one of `{_KEY_TESTS}` or `{_KEY_TOOLS}`"
            )
        else:
            rules.append(
                DeclaredRule(
                    glob=glob.strip(),
                    tests=tests,
                    tools=tools,
                    why=why.strip(),
                    excludes=excludes,
                    path_style=path_style,
                )
            )
    return rules, problems


def load_declared_rules(path: Path) -> tuple[list[DeclaredRule], list[str]]:
    """Read and validate a rules file."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return [], [f"cannot read {path}: {exc}"]
    return parse_declared_rules(raw)


def build_test_index(root: Path) -> dict[str, list[str]]:
    """Every test file under ``tests/``, keyed by filename."""
    index: dict[str, list[str]] = {}
    test_root = root / _TEST_ROOT
    if not test_root.is_dir():
        return index
    for path in sorted(test_root.rglob(_TEST_GLOB)):
        index.setdefault(path.name, []).append(path_relative_to(path, root).as_posix())
    return index


def _named(stem: str, filename: str) -> bool:
    """``test_<stem>.py`` or a ``test_<stem>_*.py`` variant."""
    return filename == f"{_TEST_PREFIX}{stem}{_PYTHON_SUFFIX}" or filename.startswith(
        f"{_TEST_PREFIX}{stem}_"
    )


def _mirror_dir(path: PurePosixPath) -> str | None:
    """``tests/unit/<dirs>`` for a module under ``src/<pkg>/`` or ``scripts/``."""
    parts = path.parts
    if len(parts) > 2 and parts[0] == _SOURCE_ROOT:
        return PurePosixPath(_TEST_ROOT, _UNIT_DIR, *parts[2:-1]).as_posix()
    if len(parts) > 1 and parts[0] == _SCRIPTS_ROOT:
        return PurePosixPath(_TEST_ROOT, _UNIT_DIR, *parts[1:-1]).as_posix()
    return None


def _dotted_name(path: PurePosixPath) -> str | None:
    """The import name of a module under ``src/`` or ``tests/``, or None."""
    if path.suffix != _PYTHON_SUFFIX:
        return None
    parts = list(path.with_suffix("").parts)
    if parts[0] == _SOURCE_ROOT:
        parts = parts[1:]
    elif parts[0] != _TEST_ROOT:
        return None
    if parts and parts[-1] == _PACKAGE_INIT_STEM:
        parts = parts[:-1]
    return ".".join(parts) or None


def _is_test_file(path: PurePosixPath) -> bool:
    return path.parts[0] == _TEST_ROOT and fnmatch.fnmatch(path.name, _TEST_GLOB)


@dataclass(frozen=True, slots=True)
class SourceRefs:
    """What one Python source can refer to another file through.

    Read from the syntax tree, not the text, so a path or module named in a
    comment or docstring is not a dependency: prose that mentions a file does
    not break when it changes.

    Attributes:
        strings: Every string constant that is not a docstring, joined by
            newlines, for path search.
        constants: The same constants as a set, for exact matches.
        imports: Every module an ``import`` statement names, and each
            ``from``-imported name joined to its module, relative imports
            resolved.
    """

    strings: str
    constants: frozenset[str]
    imports: frozenset[str]


def _package_of(relative: str) -> list[str]:
    """The dotted package a source's relative imports resolve against, as parts."""
    path = PurePosixPath(relative)
    dotted = _dotted_name(path)
    if dotted is None:
        return []
    parts = dotted.split(".")
    return parts if path.stem == _PACKAGE_INIT_STEM else parts[:-1]


def source_refs(text: str, relative: str) -> SourceRefs:
    """The references in one source. Unparseable source raises: the tree is broken."""
    tree = ast.parse(text, filename=relative)
    docstrings = {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
    }
    constants = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]
    imports: set[str] = set()
    package = _package_of(relative)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            # Only the names: `from pkg import sub` uses `sub`, not what
            # `pkg/__init__.py` provides, though it runs it.
            base_parts = package[: len(package) - (node.level - 1)] if node.level else []
            module = ".".join([*base_parts, *([node.module] if node.module else [])])
            if module:
                imports.update(f"{module}.{alias.name}" for alias in node.names)
    return SourceRefs(
        strings="\n".join(constants), constants=frozenset(constants), imports=frozenset(imports)
    )


def _read_refs(root: Path, relative: str) -> SourceRefs:
    """A source's references; one that does not parse is searched as plain text.

    The tree carries deliberately broken fixtures (``tests/fixtures/``). Such
    a file imports nothing, but it can still name a path, so it is kept, and
    searched over its whole text, rather than dropped.
    """
    text = (root / relative).read_text(encoding="utf-8")
    try:
        return source_refs(text, relative)
    except SyntaxError as exc:
        logger.info("%s does not parse (%s); searched as plain text", relative, exc.msg)
        return SourceRefs(strings=text, constants=frozenset(), imports=frozenset())


@dataclass(frozen=True, slots=True)
class Corpus:
    """What a changed file is searched for in.

    Attributes:
        index: Every ``test_*.py`` under ``tests/``, keyed by filename.
        tests: The references of each of those test files.
        modules: The references of every other Python file under ``src/``,
            ``scripts/`` and ``tests/`` (conftests and helpers included): the
            code a change can reach a test THROUGH.
        basename_counts: How many files in the tree carry each basename. A
            basename alone identifies a file only when no other file shares it.
        module_names: The dotted name of every module and package in the tree,
            to tell ``from pkg import sub`` (a module) from ``from pkg import
            Name`` (something the package's ``__init__`` provides).
    """

    index: Mapping[str, list[str]]
    tests: Mapping[str, SourceRefs]
    modules: Mapping[str, SourceRefs]
    basename_counts: Mapping[str, int]
    module_names: frozenset[str]


def build_corpus(root: Path, tree: Sequence[str]) -> Corpus:
    """The corpus for ``root``, whose files (tracked and untracked) are ``tree``."""
    index = build_test_index(root)
    modules: dict[str, SourceRefs] = {}
    for relative in tree:
        path = PurePosixPath(relative)
        if (
            path.suffix == _PYTHON_SUFFIX
            and path.parts[0] in _MODULE_ROOTS
            and not _is_test_file(path)
            and (root / relative).is_file()
        ):
            modules[relative] = _read_refs(root, relative)
    return Corpus(
        index=index,
        tests={
            test_path: _read_refs(root, test_path)
            for paths in index.values()
            for test_path in paths
        },
        modules=modules,
        basename_counts=Counter(PurePosixPath(relative).name for relative in tree),
        module_names=frozenset(
            name for relative in tree if (name := _dotted_name(PurePosixPath(relative))) is not None
        ),
    )


@dataclass(frozen=True, slots=True)
class _Needles:
    """The spellings by which a source can refer to one file.

    ``package`` is set for a package ``__init__``: importing a submodule runs
    it too, but what the ``__init__`` itself provides is reached only by
    importing the package, or a name from it that is not a submodule.
    """

    paths: tuple[str, ...]
    last_two: tuple[str, str] | None
    dotted: str | None
    package: bool


def _needles(relative: str, basename_counts: Mapping[str, int]) -> _Needles:
    path = PurePosixPath(relative)
    paths = [relative]
    last_two: tuple[str, str] | None = None
    if len(path.parts) > 1:
        last_two = (path.parts[-2], path.parts[-1])
        paths.append("/".join(last_two))
    if basename_counts.get(path.name, 0) == 1:
        paths.append(path.name)
    return _Needles(
        paths=tuple(dict.fromkeys(paths)),
        last_two=last_two,
        dotted=_dotted_name(path),
        package=path.stem == _PACKAGE_INIT_STEM,
    )


def _path_pattern(literal: str) -> re.Pattern[str]:
    """``literal`` as a whole path or path suffix, not part of a longer name."""
    return re.compile(rf"(?<![\w.-]){re.escape(literal)}(?![\w-])")


def _refers(refs: SourceRefs, needles: _Needles, module_names: frozenset[str]) -> bool:
    """Whether a source names the file by path, builds its path from parts, or imports it."""
    for literal in needles.paths:
        if literal in refs.strings and _path_pattern(literal).search(refs.strings):
            return True
    if needles.last_two is not None and all(part in refs.constants for part in needles.last_two):
        return True
    dotted = needles.dotted
    if dotted is None:
        return False
    below = f"{dotted}."
    for name in (*refs.imports, *refs.constants):
        if name == dotted:
            return True
        if not name.startswith(below):
            continue
        child = f"{below}{name[len(below) :].split('.')[0]}"
        if not (needles.package and child in module_names):
            return True
    return False


@dataclass(slots=True)
class _Cover:
    """How one changed file is covered, or why it is not."""

    rules: list[str] = field(default_factory=list)
    tests: set[str] = field(default_factory=set)
    tools: tuple[str, ...] = ()
    reason: tuple[str, str] | None = None


class _Mapper:
    """Maps changed files onto tests, caching each file's search across the change set."""

    def __init__(self, corpus: Corpus) -> None:
        self._corpus = corpus
        self._test_refs: dict[str, frozenset[str]] = {}
        self._module_refs: dict[str, frozenset[str]] = {}

    def _needles(self, relative: str) -> _Needles:
        return _needles(relative, self._corpus.basename_counts)

    def referencing_tests(self, relative: str) -> frozenset[str]:
        """Test files that name or import ``relative``."""
        if relative not in self._test_refs:
            needles = self._needles(relative)
            self._test_refs[relative] = frozenset(
                test
                for test, refs in self._corpus.tests.items()
                if test != relative and _refers(refs, needles, self._corpus.module_names)
            )
        return self._test_refs[relative]

    def referencing_modules(self, relative: str) -> frozenset[str]:
        """Non-test sources that name or import ``relative``."""
        if relative not in self._module_refs:
            needles = self._needles(relative)
            self._module_refs[relative] = frozenset(
                module
                for module, refs in self._corpus.modules.items()
                if module != relative and _refers(refs, needles, self._corpus.module_names)
            )
        return self._module_refs[relative]

    def mirror_tests(self, relative: str) -> set[str]:
        path = PurePosixPath(relative)
        mirror = _mirror_dir(path)
        if mirror is None or path.stem == _PACKAGE_INIT_STEM:
            return set()
        return {
            test_path
            for filename, test_paths in self._corpus.index.items()
            if _named(path.stem, filename)
            for test_path in test_paths
            if PurePosixPath(test_path).parent.as_posix() == mirror
        }

    def own_tests(self, relative: str) -> tuple[set[str], str | None]:
        """A file's own tests: its conftest subtree, or its mirror plus its references.

        Returns the tests and, for the root conftest, why no subtree can cover it.
        """
        path = PurePosixPath(relative)
        if path.name == _CONFTEST and path.parts[0] == _TEST_ROOT:
            subtree = path.parent.as_posix()
            if subtree == _TEST_ROOT:
                return set(), f"`{relative}` is loaded by every test: its subtree is the suite"
            return {subtree}, None
        return self.mirror_tests(relative) | self.referencing_tests(relative), None

    def dependent_tests(self, relative: str) -> tuple[set[str], str | None]:
        """A dependent's own unit tests: its mirror, else the tests that refer to it.

        Not every test that touches a hub such as the CLI: a change reaches a
        dependent through what the dependent does, which its own tests cover.
        """
        path = PurePosixPath(relative)
        if path.name == _CONFTEST:
            return self.own_tests(relative)
        mirrored = self.mirror_tests(relative)
        return (mirrored or set(self.referencing_tests(relative))), None

    def cover(self, relative: str, exists: bool, rules: Sequence[DeclaredRule]) -> _Cover:
        """Every test a change to ``relative`` can break, or why that cannot be targeted.

        ``rules`` are every declared rule that matches; their tests and tools
        are all part of the cover. A file whose reach is too broad still runs
        its OWN tests when they fit the cap, so the agent gets that signal, but
        it stays unmapped: the rest of its reach is the coordinator's full gate.
        """
        cover = _Cover()
        path = PurePosixPath(relative)
        if rules:
            cover.rules.append(RULE_DECLARED)
            for rule in rules:
                cover.tests.update(rule.tests)
            cover.tools = tuple(dict.fromkeys(tool for rule in rules for tool in rule.tools))
        if _is_test_file(path):
            cover.rules.append(RULE_SELF if exists else RULE_DELETED_TEST)
            if exists:
                cover.tests.add(relative)
            return cover

        own, broad = self.own_tests(relative)
        if broad is not None:
            cover.reason = (REASON_TOO_BROAD, broad)
            return cover
        if own:
            cover.rules.append(RULE_SUBTREE if path.name == _CONFTEST else RULE_REFERENCE)
            cover.tests.update(own)
        own_weight = self.test_file_count(cover.tests)
        if own_weight > MAX_IMPORT_SELECTION:
            cover.reason = (REASON_TOO_BROAD, self._too_broad(own_weight, "its own tests"))
            cover.tests.clear()
            return cover

        dependents = self.referencing_modules(relative)
        if dependents and not exists:
            named = ", ".join(sorted(dependents)[:_NAMED_DEPENDENTS])
            cover.reason = (
                REASON_STILL_REFERENCED,
                f"deleted, but {len(dependents)} source file(s) still refer to it: {named}",
            )
            return cover
        reach, broad = self._reach(cover.tests, dependents)
        if broad is not None:
            cover.reason = (REASON_TOO_BROAD, broad)
            return cover
        if dependents:
            cover.rules.append(RULE_DEPENDENT)
        cover.tests = reach

        if not exists and not cover.tests:
            cover.rules.append(RULE_DELETED_UNREFERENCED)
        elif not cover.tests and not cover.tools:
            cover.reason = (REASON_UNCOVERED, "no test, declared rule or dependent covers it")
        return cover

    def _reach(self, own: set[str], dependents: frozenset[str]) -> tuple[set[str], str | None]:
        """``own`` plus each dependent's tests, or why that reach is too broad to target.

        One hop: a dependent's own tests are where a change to what it
        consumes shows first. Reach beyond that is the coordinator's full
        gate, since through a registry that imports every handler it is the
        whole suite.
        """
        reach = set(own)
        for module in sorted(dependents):
            tests, broad = self.dependent_tests(module)
            if broad is not None:
                return reach, f"reached through {module}: {broad}"
            reach.update(tests)
            weight = self.test_file_count(reach)
            if weight > MAX_IMPORT_SELECTION:
                return reach, self._too_broad(weight, f"its tests through {module}")
        return reach, None

    def test_file_count(self, entries: set[str]) -> int:
        """How many test files ``entries`` runs: a directory counts every test under it."""
        count = 0
        for entry in entries:
            if entry.endswith(_PYTHON_SUFFIX):
                count += 1
                continue
            prefix = f"{entry}/"
            count += sum(1 for test in self._corpus.tests if test.startswith(prefix))
        return count

    @staticmethod
    def _too_broad(count: int, via: str) -> str:
        return (
            f"{via} pass {MAX_IMPORT_SELECTION} test files ({count} and counting): the "
            "suite by another name, so the coordinator's full gate covers it"
        )


def _prune_covered(selected: set[str]) -> list[str]:
    """Drop test files a selected directory already runs, so nothing runs twice."""
    directories = [entry for entry in selected if not entry.endswith(_PYTHON_SUFFIX)]
    return sorted(
        entry
        for entry in selected
        if not any(entry != d and entry.startswith(f"{d}/") for d in directories)
    )


def select_tests(
    changed: list[str], corpus: Corpus, root: Path, rules: list[DeclaredRule]
) -> Selection:
    """Account for every changed file: every test it can break, or why it is unmapped.

    A file's coverage is the UNION of its declared rule, its mirrored tests,
    the tests that name or import it, and the tests of every source that
    reaches it. Stopping at the first hit reported "0 unmapped" for a module
    whose dependents' tests never ran (delta review N3).
    """
    selection = Selection()
    selected: set[str] = set()
    mapper = _Mapper(corpus)

    for relative in changed:
        path = PurePosixPath(relative)
        exists = (root / relative).is_file()
        if not exists:
            selection.deleted.append(relative)
        if path.suffix != _PYTHON_SUFFIX:
            selection.non_python.append(relative)

        cover = mapper.cover(relative, exists, [rule for rule in rules if rule.matches(relative)])
        selected.update(cover.tests)
        if cover.reason is not None:
            code, detail = cover.reason
            selection.unmapped.append(relative)
            selection.reasons[relative] = {
                "reason": code,
                "detail": detail,
                "tests_run": sorted(cover.tests),
            }
            continue

        entry: dict[str, Any] = {
            "file": relative,
            "rules": cover.rules,
            "tests": sorted(cover.tests),
        }
        if cover.tools:
            entry["tools"] = list(cover.tools)
        selection.mapping.append(entry)

    selection.selected = _prune_covered(selected)
    return selection


def build_report(
    *,
    base: str,
    changed: list[str],
    selection: Selection,
    exit_code: int | None,
    output: str,
    allow_unmapped: bool,
) -> dict[str, Any]:
    """The QA artefact for one targeted run.

    Passing needs every file accounted for (or the allowance given) AND, when
    tests were selected, a green run that collected some.
    """
    parsed = parse_pytest_text_output(output)
    tests_green = not selection.selected or (
        exit_code == EXIT_SUCCESS
        and parsed["failed"] == 0
        and parsed["errors"] == 0
        and parsed["total"] > 0
    )
    accounted = allow_unmapped or not selection.unmapped
    return {
        "tool": _TOOL_NAME,
        "base": base,
        "summary": {
            "passed_all": tests_green and accounted,
            "total": parsed["total"],
            "passed": parsed["passed"],
            "failed": parsed["failed"],
            "skipped": parsed["skipped"],
            "errors": parsed["errors"],
            "files_considered": len(changed),
            "test_files_selected": len(selection.selected),
            "unmapped": len(selection.unmapped),
        },
        "selected": selection.selected,
        "mapping": selection.mapping,
        "unmapped": selection.unmapped,
        "unmapped_reasons": selection.reasons,
        "unmapped_allowed": allow_unmapped,
        "deleted": selection.deleted,
        "non_python": selection.non_python,
        "tests": [
            {"name": node_id, "outcome": _OUTCOME_FAILED} for node_id in parsed["failed_tests"]
        ],
    }


def failure_report(message: str) -> dict[str, Any]:
    """A report for a run that produced no verdict. Never a pass."""
    return {
        "tool": _TOOL_NAME,
        "summary": {
            "passed_all": False,
            "total": 0,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "errors": 0,
            "error": message,
        },
        "selected": [],
        "unmapped": [],
        "tests": [],
    }


def selection_payload(spec: str, changed: list[str], selection: Selection) -> dict[str, Any]:
    """What ``--select-only`` prints: the selection for a range, with nothing run."""
    return {
        "range": spec,
        "changed": changed,
        "selected": selection.selected,
        "mapping": selection.mapping,
        "unmapped": selection.unmapped,
        "unmapped_reasons": selection.reasons,
    }


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the tests mapped from changed files.")
    parser.add_argument("--root", default=str(_PROJECT_ROOT), help="repository root")
    change_set = parser.add_mutually_exclusive_group()
    change_set.add_argument("--base", default=None, help="ref to diff against (merge base)")
    change_set.add_argument(
        "--range", default=None, help="`A..B`: exactly what git diff A B changed"
    )
    parser.add_argument(
        "--select-only",
        action="store_true",
        help="print the --range selection as JSON and run nothing",
    )
    parser.add_argument("--rules", default=str(DEFAULT_RULES_PATH), help="declared rules file")
    parser.add_argument(
        "--allow-unmapped",
        action="store_true",
        help="pass with unmapped files; the coordinator's full gate must cover them",
    )
    parser.add_argument("--json", action="store_true", help="write the JSON artefact")
    args = parser.parse_args(argv)
    if args.select_only and args.range is None:
        parser.error("--select-only needs --range")
    return args


def _write_report(root: Path, report: dict[str, Any]) -> None:
    output_dir = root.joinpath(*_QA_OUTPUT_DIR_PARTS)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / _OUTPUT_FILENAME).write_text(json.dumps(report, indent=2), encoding="utf-8")


def _change_set(
    args: argparse.Namespace, root: Path, run_git: GitRunner
) -> tuple[str, list[str] | None, str | None]:
    """``(label, files, error)``: the range as given, or the resolved ``--base``."""
    if args.range is not None:
        files, error = range_files(root, args.range, git=run_git)
        return args.range, files, error
    base, error = resolve_base(root, args.base, git=run_git)
    if base is None:
        return "", None, error or "no base to diff against"
    if current_branch(root, git=run_git) == base:
        return (
            base,
            None,
            f"HEAD is on `{base}`, the base itself: the merge base is HEAD, so "
            "committed work cannot be told apart. Run from the worktree branch, "
            "or pass --base <ref>.",
        )
    files, error = changed_files(root, base, git=run_git)
    return base, files, error


def _selection(
    args: argparse.Namespace, root: Path, run_git: GitRunner
) -> tuple[str, list[str], Selection | None, dict[str, Any] | None, int]:
    """The change set and its selection, or the failure report that replaces them."""
    label, changed, error = _change_set(args, root, run_git)
    if changed is None:
        return (
            label,
            [],
            None,
            failure_report(error or "the change set could not be read"),
            (EXIT_OPERATIONAL),
        )
    if not changed and not args.select_only:
        return (
            label,
            [],
            None,
            failure_report(f"nothing changed since `{label}`: nothing verified"),
            EXIT_ISSUES,
        )

    rules, problems = load_declared_rules(Path(args.rules))
    if problems:
        return label, changed, None, failure_report("; ".join(problems)), EXIT_OPERATIONAL

    tree, error = tree_files(root, git=run_git)
    if tree is None:
        return (
            label,
            changed,
            None,
            failure_report(error or "the tree could not be listed"),
            (EXIT_OPERATIONAL),
        )
    return label, changed, select_tests(changed, build_corpus(root, tree), root, rules), None, 0


def _verdict(
    args: argparse.Namespace, root: Path, run_git: GitRunner, run_pytest: PytestRunner
) -> tuple[dict[str, Any], int]:
    base, changed, selection, failure, code = _selection(args, root, run_git)
    if selection is None:
        return failure or failure_report("no selection"), code

    exit_code, output = run_pytest(selection.selected, root) if selection.selected else (None, "")
    report = build_report(
        base=base,
        changed=changed,
        selection=selection,
        exit_code=exit_code,
        output=output,
        allow_unmapped=bool(args.allow_unmapped),
    )
    if args.range is not None:
        report["range"] = args.range
    return report, EXIT_SUCCESS if report["summary"]["passed_all"] else EXIT_ISSUES


def _describe(report: dict[str, Any]) -> str:
    summary = report["summary"]
    unmapped = report["unmapped"]
    scope = (
        f"{summary['files_considered']} changed files: {len(unmapped)} unmapped, "
        f"{len(report['deleted'])} deleted, {len(report['non_python'])} non-Python"
    )
    if summary["test_files_selected"]:
        line = (
            f"{summary['passed']} passed, {summary['failed']} failed from "
            f"{summary['test_files_selected']} test files ({scope})"
        )
    else:
        line = f"no tests ran ({scope})"
    if unmapped:
        verdict = "ALLOWED" if report["unmapped_allowed"] else "FAILS the run"
        reasons = report.get("unmapped_reasons", {})
        line += f"\nunmapped ({verdict}):"
        for name in unmapped:
            why = reasons.get(name, {})
            line += f"\n  {name} [{why.get('reason', REASON_UNCOVERED)}] {why.get('detail', '')}"
    return line


def main(
    argv: list[str] | None = None,
    *,
    run_git: GitRunner = run_git,
    run_pytest: PytestRunner = run_pytest,
) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    root = Path(args.root).resolve()
    if args.select_only:
        spec, changed, selection, failure, code = _selection(args, root, run_git)
        if selection is None:
            error = (failure or {}).get("summary", {}).get("error", "no selection")
            print(f"{_TOOL_NAME}: FAILED — {error}", file=sys.stderr)
            return code
        print(json.dumps(selection_payload(spec, changed, selection), indent=2))
        return EXIT_SUCCESS
    report, verdict = _verdict(args, root, run_git, run_pytest)

    if args.json:
        _write_report(root, report)

    error = report["summary"].get("error")
    if error:
        print(f"{_TOOL_NAME}: FAILED — {error}", file=sys.stderr)
    else:
        print(f"{_TOOL_NAME}: {_describe(report)}")
    return verdict


if __name__ == "__main__":
    sys.exit(main())
