"""Older holes in the secret guard's search-option reading (Plan 00618 Task 2.1).

``deep/`` holds an indexed protected file; ``sub/`` holds none; ``_ABSENT`` is a
name only a protected glob matches. Every shape here is judged by the guard
end to end, with the twins that must stay allowed beside the ones that must deny.
"""

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
from claude_code_hooks_daemon.utils import protected_file_index

# Assembled so this file never spells a protected name itself.
_SUFFIX = "sec" + "ret"
_PROTECTED = f"demo.{_SUFFIX}"
_ABSENT = f"absent.{_SUFFIX}"


@pytest.fixture()
def project(tmp_path: Path) -> Iterator[Path]:
    """A project whose root and ``deep`` hold a protected file; ``sub`` holds none."""
    root = tmp_path / "project"
    root.mkdir()
    (root / _PROTECTED).write_bytes(b"not-a-real-secret\n")
    (root / "sub").mkdir()
    (root / "sub" / "plain.txt").write_bytes(b"hello\n")
    (root / "deep").mkdir()
    (root / "deep" / f"key.{_SUFFIX}").write_bytes(b"not-a-real-secret\n")
    protected_file_index.reset_index_cache()
    with patch.object(guard_module, "resolve_project_root", return_value=str(root)):
        index_project(root, SecretFileGuardHandler()._patterns())
        yield root
    protected_file_index.reset_index_cache()


def _verdict(root: Path, command: str, cwd: Path | None = None) -> Decision:
    hook_input: dict[str, Any] = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(cwd or root),
    }
    handler = SecretFileGuardHandler()
    if not handler.matches(hook_input):
        return Decision.ALLOW
    return handler.handle(hook_input).decision


class TestUnit1SearchOptionGrammar:
    """scan_options fails closed: a pattern option it cannot place never hides a directory."""

    @pytest.mark.parametrize(
        "command",
        [
            # RED: GNU long-option abbreviations of --regexp / --file.
            "grep -r --regex=. deep /dev/null",
            "command grep -r --regex=. deep /dev/null",
            "/usr/bin/grep -r --regex=. deep /dev/null",
            "egrep -r --rege=. deep /dev/null",
            "grep -r --fi=pats deep /dev/null",
            "grep -r --reg=zz deep sub",
            # RED: ugrep --and supplies the pattern.
            "grep -r --and=. deep sub",
            "grep -r --and=. deep /dev/null",
            # RED: -T / separate --color take no value in GNU grep and ugrep.
            "grep -rT x deep sub",
            "grep -r --color x deep sub",
            # REGRESSION (already denied): exact spellings.
            "grep -r --regexp=zz deep sub",
            "grep -r -e zz deep sub",
            "grep -r zz deep",
            "grep -r zz sub deep",
        ],
    )
    def test_directory_holding_a_protected_file_is_denied(
        self, project: Path, command: str
    ) -> None:
        assert _verdict(project, command) is Decision.DENY

    def test_valueless_misread_with_relative_root_from_a_subdirectory(self, project: Path) -> None:
        assert _verdict(project, "grep -rT x ../deep", cwd=project / "sub") is Decision.DENY

    @pytest.mark.parametrize(
        "command",
        [
            "grep -r zz sub",
            "grep -rn zz sub",
            "grep -r --line-number zz sub",
            "grep -r --line-n zz sub",
            "rg -n zz sub",
            "rg --color never zz sub",
            "grep -rT x sub",
            "grep -r --color x sub",
            "grep -r -e zz sub",
            "grep -r --regexp=zz sub",
            "grep -r --regex=zz sub",
            "grep -r --and=zz sub",
            f"grep -r {_ABSENT} sub",
        ],
    )
    def test_twin_over_a_clean_directory_stays_allowed(self, project: Path, command: str) -> None:
        assert _verdict(project, command) is Decision.ALLOW
