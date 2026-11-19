"""A git command that reads no tree is not a reader after a computed cd (Plan 00623).

After a move the guard cannot place (`cd -`), every directory link in the
project is read as a root by any command that could read a tree, and an
unfinished link scan denies such a command outright. `git` counted as such a
command whatever its subcommand, so `cd - && git commit -m x` was denied in any
project holding a directory link to a protected file (playbook probes
#350/#351). Only `git grep` recurses a tree; `git commit` and `git status`
read the index and lstat the work tree, never through a link.

A subcommand the guard cannot read literally (an expansion, a `-c` that may
define an alias or move the work tree) stays a possible reader.

Synthetic fixtures only: the protected file is a dummy outside the project,
its name assembled so this file never spells one.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from tests.indexed_project import index_project

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use import secret_file_guard as guard_module
from claude_code_hooks_daemon.handlers.pre_tool_use.secret_file_guard import (
    SecretFileGuardHandler,
)
from claude_code_hooks_daemon.utils import (
    link_index,
    path_exclusion,
    protected_file_index,
    recursive_search,
)
from claude_code_hooks_daemon.utils import secret_file_matching as sfm

_PROTECTED = "id_" + "rsa"

NOT_READERS = [
    "cd - && git commit -m acceptance -- no-such-acceptance-path",
    "git commit --dry-run && cd - && git commit --dry-run",
    "cd - && git status",
    "cd - && git commit -am 'a message'",
    "cd - && git --no-pager status --short",
]

READERS = [
    "cd - && git grep x",
    "cd - && git grep -r x sub",
    "cd - && git -C sub grep x",
    "cd - && grep -r x .",
    'cd - && git "$SUB" x',
    "cd - && git $(echo grep) x",
    "cd - && git -c alias.s=grep s x",
    "cd - && git --config-env=alias.s=V s x",
    "cd - && git commit -F sub/dl/" + _PROTECTED,
]


@dataclass(frozen=True)
class Project:
    root: Path


@pytest.fixture()
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Project]:
    base = tmp_path.resolve()
    outside = base / "outside"
    outside.mkdir()
    (outside / _PROTECTED).write_bytes(b"DUMMY\n")
    (base / "home").mkdir()
    root = base / "proj"
    (root / "sub").mkdir(parents=True)
    (root / "r.md").write_bytes(b"hello\n")
    # A directory link out of the project, to a directory holding the dummy.
    (root / "sub" / "dl").symlink_to(outside)
    monkeypatch.chdir("/")
    monkeypatch.setenv("HOME", str(base / "home"))
    protected_file_index.reset_index_cache()
    link_index.reset_link_indexes()
    with (
        patch.object(guard_module, "resolve_project_root", return_value=str(root)),
        patch.object(sfm, "resolve_project_root", return_value=str(root)),
        patch.object(path_exclusion, "resolve_project_root", return_value=str(root)),
    ):
        index_project(root, SecretFileGuardHandler()._patterns())
        yield Project(root=root)
    link_index.reset_link_indexes()
    protected_file_index.reset_index_cache()


def _built(project: Project) -> None:
    link_index.prewarm(str(project.root))
    link_index.wait_for_link_index(60.0)
    assert link_index.link_scan_for(str(project.root)) is not None


@pytest.fixture()
def unscanned(project: Project, monkeypatch: pytest.MonkeyPatch) -> Project:
    """No link index, and a fallback walk that stops before it finishes."""
    monkeypatch.setattr(sfm, "_scan_from_index", lambda _root: None)
    monkeypatch.setattr(sfm, "LINK_SCAN_DIRECTORY_CAP", 1)
    return project


def _decision(project: Project, command: str) -> Decision:
    handler = SecretFileGuardHandler()
    hook_input: dict[str, Any] = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(project.root),
    }
    if not handler.matches(hook_input):
        return Decision.ALLOW
    return handler.handle(hook_input).decision


@pytest.mark.parametrize("command", NOT_READERS)
def test_a_git_command_that_reads_no_tree_is_allowed_after_a_computed_cd(
    project: Project, command: str
) -> None:
    _built(project)
    assert _decision(project, command) is Decision.ALLOW


@pytest.mark.parametrize("command", NOT_READERS)
def test_a_git_command_that_reads_no_tree_is_no_search_while_the_scan_is_unfinished(
    unscanned: Project, command: str
) -> None:
    # The search walk does not fail closed on it. The guard as a whole still
    # denies here: the word scan judges each relative word through the links an
    # unfinished scan cannot list, which is a separate, deliberate fail-closed.
    assert recursive_search.search_reads(command, str(unscanned.root)) == []


@pytest.mark.parametrize("command", READERS)
def test_a_possible_reader_after_a_computed_cd_is_still_denied(
    project: Project, command: str
) -> None:
    _built(project)
    assert _decision(project, command) is Decision.DENY


@pytest.mark.parametrize("command", READERS)
def test_a_possible_reader_is_still_denied_while_the_scan_is_unfinished(
    unscanned: Project, command: str
) -> None:
    assert _decision(unscanned, command) is Decision.DENY
