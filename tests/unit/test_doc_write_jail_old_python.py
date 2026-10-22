"""The doc-write jail's child-side code runs under every interpreter a test spawns.

``sitecustomize.py`` arms the jail in EVERY child Python on the run's
``PYTHONPATH``, including the deliberately old ones from ``tests/old_python.py``
that the entry-point tests start to prove a one-line refusal. So the modules it
imports must work on the oldest of :data:`OLD_VERSIONS`, not on the project's
3.11 floor. CI once failed both old-interpreter tests because
``isinstance(target, str | bytes | os.PathLike)`` raised ``TypeError`` on 3.8
inside the audit hook, the first time the child wrote a bytecode cache file.

Two checks, because each misses what the other catches:

* static, on every host: the grammar parses at the oldest version, and no
  ``isinstance``/``issubclass`` is handed a ``X | Y`` union (valid syntax,
  a runtime error before 3.10);
* runtime, under each real old interpreter: the armed jail is driven through
  every audit path (``open`` for write, ``os.rename``, ``os.remove`` with a
  ``dir_fd``) with an EMPTY bytecode cache, so the child also writes ``.pyc``
  files the way a fresh CI interpreter does.
"""

from __future__ import annotations

import ast
import os
import subprocess
from pathlib import Path

import pytest

from tests.jail_site import doc_write_jail as jail
from tests.old_python import OLD_VERSIONS, old_python_or_skip

JAIL_SITE = Path(jail.__file__).resolve().parent
CHILD_SIDE_MODULES = sorted(JAIL_SITE.glob("*.py"))


def _major_minor(version: str) -> tuple[int, int]:
    major, minor = version.split(".")
    return int(major), int(minor)


OLDEST = min(_major_minor(version) for version in OLD_VERSIONS)
_TYPE_CHECKS = frozenset({"isinstance", "issubclass"})

#: Driven inside the old child: each audit path, protected and unprotected.
_CHILD_SCRIPT = """
import os, sys
import doc_write_jail
protected, scratch = sys.argv[1], sys.argv[2]
refused = 0
for attempt in (
    lambda: open(protected, "w"),
    lambda: os.rename(scratch, protected),
    lambda: os.remove(protected),
):
    try:
        attempt()
    except doc_write_jail.DocWriteRefused:
        refused += 1
directory = os.open(os.path.dirname(protected), os.O_RDONLY)
try:
    os.remove(os.path.basename(protected), dir_fd=directory)
except doc_write_jail.DocWriteRefused:
    refused += 1
finally:
    os.close(directory)
with open(scratch, "w") as handle:
    handle.write("unprotected writes still work")
import json, csv, decimal
print("refused", refused)
"""


def _type_check_unions(tree: ast.AST) -> list[int]:
    lines: list[int] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in _TYPE_CHECKS
            and len(node.args) == 2
        ):
            for inner in ast.walk(node.args[1]):
                if isinstance(inner, ast.BinOp) and isinstance(inner.op, ast.BitOr):
                    lines.append(node.lineno)
                    break
    return lines


def test_the_union_scan_catches_the_runtime_union() -> None:
    tree = ast.parse("isinstance(x, str | bytes)\nflags = a | b\n")
    assert _type_check_unions(tree) == [1]


def test_the_child_side_modules_were_found() -> None:
    names = {path.name for path in CHILD_SIDE_MODULES}
    assert {"sitecustomize.py", "doc_write_jail.py"} <= names


@pytest.mark.parametrize("module", CHILD_SIDE_MODULES, ids=lambda path: path.name)
class TestChildSideModuleAtTheOldestVersion:
    def test_parses_at_the_oldest_version(self, module: Path) -> None:
        ast.parse(module.read_text(encoding="utf-8"), feature_version=OLDEST)

    def test_no_type_check_is_handed_a_union(self, module: Path) -> None:
        tree = ast.parse(module.read_text(encoding="utf-8"))
        assert _type_check_unions(tree) == [], (
            f"{module.name}: isinstance/issubclass given an X | Y union, a TypeError "
            f"before Python 3.10; use a tuple"
        )


@pytest.mark.parametrize("version", OLD_VERSIONS)
def test_the_armed_jail_works_under_an_old_interpreter(version: str, tmp_path: Path) -> None:
    python = old_python_or_skip(version)
    docs = tmp_path / "checkout"
    docs.mkdir()
    protected = docs / "CLAUDE.md"
    protected.write_text("original\n", encoding="utf-8")
    scratch = tmp_path / "scratch.txt"
    scratch.write_text("scratch\n", encoding="utf-8")
    pycache = tmp_path / "pycache"
    pycache.mkdir()
    log = tmp_path / "refusals.log"
    env = dict(os.environ)
    env.update(jail.environment_for_children(frozenset({str(protected.resolve())}), log))
    env["PYTHONPYCACHEPREFIX"] = str(pycache)

    completed = subprocess.run(
        [python, "-c", _CHILD_SCRIPT, str(protected), str(scratch)],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        cwd=str(tmp_path),
    )

    assert "Traceback" not in completed.stderr, completed.stderr
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "refused 4"
    assert protected.read_text(encoding="utf-8") == "original\n"
    assert any(pycache.rglob("*.pyc")), "the child wrote no bytecode, so the open path was not hit"
