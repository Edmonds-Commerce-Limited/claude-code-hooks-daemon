"""No QA scanner may report a finding inside a gitignored directory.

Hazard class: a QA scanner that walks the filesystem instead of the tracked
tree lets untracked or vendored content (a plugin marketplace installed under
an ignored directory) fail the gate for reasons no commit caused, and a failing
detector also marks every check that depends on it NOT MEANINGFUL.

The defence is one chokepoint, ``scan_scope.walk_files``, which every scanner
enumerates through. These tests pin the chokepoint, pin that git being unable
to answer is a failure rather than "nothing is ignored", and pin that no
scanner under ``scripts/qa`` enumerates the tree by any other route.
"""

from __future__ import annotations

import ast
import importlib.util
import subprocess  # nosec B404 - builds a throwaway repository with the trusted git binary
from pathlib import Path
from types import ModuleType

import pytest

from claude_code_hooks_daemon.utils import scan_scope
from claude_code_hooks_daemon.utils.scan_scope import WalkError, walk_files

_SCRIPTS_QA = Path(__file__).resolve().parents[3] / "scripts" / "qa"
_VIOLATION = "x = 1  # no" + "qa: E501\n"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS_QA / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(root: Path, *args: str) -> None:
    subprocess.run(  # nosec B603 B607 - fixed argv, trusted binary
        ["git", "-C", str(root), *args], check=True, capture_output=True
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A git repository whose ``plugins/`` directory is ignored and holds a violation."""
    _git(tmp_path, "init", "-q")
    (tmp_path / ".gitignore").write_text("plugins/\n")
    (tmp_path / "own.py").write_text("x = 1\n")
    ignored = tmp_path / "plugins" / "marketplace" / "vendored"
    ignored.mkdir(parents=True)
    (ignored / "third_party.py").write_text(_VIOLATION)
    (tmp_path / "untracked_new.py").write_text("y = 2\n")
    _git(tmp_path, "add", ".gitignore", "own.py")
    return tmp_path


def test_walk_files_leaves_out_a_gitignored_directory(repo: Path) -> None:
    names = [p.relative_to(repo).as_posix() for p in walk_files(repo, "*.py")]
    assert names == ["own.py", "untracked_new.py"]


def test_walk_files_still_walks_a_directory_that_is_not_a_repository(tmp_path: Path) -> None:
    (tmp_path / "plugins").mkdir()
    (tmp_path / "plugins" / "a.py").write_text("x = 1\n")
    assert [p.name for p in walk_files(tmp_path, "*.py")] == ["a.py"]


def test_an_inline_suppression_inside_an_ignored_directory_is_not_a_finding(repo: Path) -> None:
    checker = _load("check_inline_suppressions")
    assert checker.find_violations(repo) == []


def test_a_git_that_cannot_answer_fails_the_walk_instead_of_listing_everything(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The failure that scanned a plugin marketplace: git timed out, nothing was dropped."""

    def _timed_out(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise subprocess.TimeoutExpired(cmd="git", timeout=1)

    monkeypatch.setattr(scan_scope.subprocess, "run", _timed_out)
    with pytest.raises(WalkError):
        walk_files(repo, "*.py")


def _enumerations_bypassing_walk_files(source: str) -> list[int]:
    """Lines of ``source`` that recurse the filesystem other than through ``walk_files``."""
    lines: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        recursive_glob = (
            node.func.attr == "glob"
            and bool(node.args)
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
            and "**" in node.args[0].value
        )
        os_walk = (
            node.func.attr == "walk"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "os"
        )
        if node.func.attr == "rglob" or os_walk or recursive_glob:
            lines.append(node.lineno)
    return lines


@pytest.mark.parametrize("script", sorted(_SCRIPTS_QA.glob("*.py")), ids=lambda p: p.name)
def test_every_scanner_enumerates_through_walk_files(script: Path) -> None:
    found = _enumerations_bypassing_walk_files(script.read_text(encoding="utf-8"))
    assert found == [], (
        f"{script.name} recurses the filesystem at line(s) {found} instead of "
        "scan_scope.walk_files, so a gitignored tree would be scanned"
    )
