"""A bracket glob that spells a link to a protected file (Plan 00623 final review).

``cat a/[l]ink`` is glob-shaped, so the link check skipped it, but its bracket
expressions are finite: bash expands it to exactly ``a/link`` and reads through
the link. Each finite expansion must face the same link check as the literal.
Synthetic fixtures only: the protected file is a dummy, its name assembled so
this file never spells one.
"""

from __future__ import annotations

from collections.abc import Iterator
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
from claude_code_hooks_daemon.utils import link_index, path_exclusion, protected_file_index
from claude_code_hooks_daemon.utils import secret_file_matching as sfm

_PROTECTED = "id_" + "rsa"


@pytest.fixture()
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    base = tmp_path.resolve()
    outside = base / "outside"
    outside.mkdir()
    (outside / _PROTECTED).write_bytes(b"DUMMY\n")
    root = base / "proj"
    deep = root / "w" / "zz"
    deep.mkdir(parents=True)
    (deep / "late").symlink_to(outside / _PROTECTED)
    (deep / "dl").symlink_to(outside)
    (root / "r.md").write_bytes(b"hello\n")
    monkeypatch.chdir("/")
    protected_file_index.reset_index_cache()
    link_index.reset_link_indexes()
    with (
        patch.object(guard_module, "resolve_project_root", return_value=str(root)),
        patch.object(sfm, "resolve_project_root", return_value=str(root)),
        patch.object(path_exclusion, "resolve_project_root", return_value=str(root)),
    ):
        index_project(root, SecretFileGuardHandler()._patterns())
        yield root
    link_index.reset_link_indexes()
    protected_file_index.reset_index_cache()


def _decision(root: Path, command: str) -> Decision:
    handler = SecretFileGuardHandler()
    hook_input: dict[str, Any] = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(root),
    }
    if not handler.matches(hook_input):
        return Decision.ALLOW
    return handler.handle(hook_input).decision


@pytest.mark.parametrize(
    "command",
    [
        "cat w/zz/[l]ate",
        "cat w/zz/la[t]e",
        "cat w/z[z]/late",
        "cat [w]/zz/late",
        "cd w && cat zz/[l]ate",
        "cd w/zz && cat [l]ate",
        "cat w/z[z]/dl/" + _PROTECTED,
    ],
)
def test_a_bracket_glob_spelling_a_link_to_a_protected_file_is_denied(
    project: Path, command: str
) -> None:
    assert _decision(project, command) is Decision.DENY


@pytest.mark.parametrize("command", ["cat [r].md", "cat w/zz/[x]ate", "ls w/[z]z"])
def test_a_bracket_glob_spelling_no_link_to_a_protected_file_is_allowed(
    project: Path, command: str
) -> None:
    assert _decision(project, command) is Decision.ALLOW
