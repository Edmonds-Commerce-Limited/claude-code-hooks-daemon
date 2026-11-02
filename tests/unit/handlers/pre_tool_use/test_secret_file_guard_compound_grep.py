"""Issue #144 at the handler: a compound command around a grep-pattern-only search.

The pattern-only search is let through as one statement of a compound command;
a statement that reads a protected file, existing and indexed, is still denied.
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

# Assembled so this file never spells the protected name itself.
K = "id_" + "rsa"


@pytest.fixture()
def project(tmp_path: Path) -> Iterator[Path]:
    """A project root holding a real protected file at its top level."""
    root = tmp_path / "project"
    root.mkdir()
    (root / K).write_bytes(b"not-a-real-key\n")
    (root / "docs").mkdir()
    protected_file_index.reset_index_cache()
    with patch.object(guard_module, "resolve_project_root", return_value=str(root)):
        index_project(root, SecretFileGuardHandler()._patterns())
        yield root
    protected_file_index.reset_index_cache()


def _bash(root: Path, command: str) -> Decision:
    hook_input: dict[str, Any] = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(root),
    }
    handler = SecretFileGuardHandler()
    if not handler.matches(hook_input):
        return Decision.ALLOW
    return handler.handle(hook_input).decision


class TestCompoundGrepPatternOnlyIsAllowed:
    @pytest.mark.parametrize(
        "command",
        [
            f"grep -rn '{K}' docs",
            f"grep -rn '{K}' docs; echo done",
            f"grep -rn '{K}' docs && echo ok",
            f"grep -rn '{K}' docs\necho done",
        ],
    )
    def test_allowed(self, project: Path, command: str) -> None:
        assert _bash(project, command) == Decision.ALLOW


class TestCompoundStatementThatReadsStaysDenied:
    @pytest.mark.parametrize(
        "command",
        [
            f"grep '{K}' docs; cat {K}",
            f"grep '{K}' docs | xargs cat",
            f"grep -f {K} docs",
            f"p={K}; cat $p",
            f"grep '{K}' docs > {K}",
            f"echo hi; cat ~/.ssh/{K}",
        ],
    )
    def test_denied(self, project: Path, command: str) -> None:
        assert _bash(project, command) == Decision.DENY
