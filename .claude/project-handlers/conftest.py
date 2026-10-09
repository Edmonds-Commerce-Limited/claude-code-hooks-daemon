"""Shared test fixtures for project handlers."""

import sys
from pathlib import Path
from typing import Any

import pytest

# Add each event-type subdirectory to sys.path so co-located tests
# can import handler modules with --import-mode=importlib
_handlers_root = Path(__file__).resolve().parent
for _subdir in _handlers_root.iterdir():
    if _subdir.is_dir() and not _subdir.name.startswith("_"):
        sys.path.insert(0, str(_subdir))

# The repository root, so a test can share the main suite's helpers
# (`tests.scaling`). CI runs the bare `pytest` entry point, which does not put
# the working directory on sys.path the way `python -m pytest` does.
_repository_root = _handlers_root.parent.parent
if str(_repository_root) not in sys.path:
    sys.path.insert(0, str(_repository_root))


def pytest_configure(config: pytest.Config) -> None:
    """Judge every deny a project handler returns, as the main suite does.

    Registered rather than named in ``pytest_plugins``: this conftest is not the
    top-level one when the main suite and the project handlers run together.
    """
    from tests.plugins.deny_carries_rule_id import register

    register(config)


@pytest.fixture
def bash_hook_input():
    """Factory fixture for creating Bash tool hook inputs."""

    def _make(command: str) -> dict[str, Any]:
        return {
            "tool_name": "Bash",
            "tool_input": {"command": command},
        }

    return _make


@pytest.fixture
def write_hook_input():
    """Factory fixture for creating Write tool hook inputs."""

    def _make(file_path: str, content: str = "") -> dict[str, Any]:
        return {
            "tool_name": "Write",
            "tool_input": {"file_path": file_path, "content": content},
        }

    return _make


@pytest.fixture
def edit_hook_input():
    """Factory fixture for creating Edit tool hook inputs."""

    def _make(file_path: str, old_string: str = "", new_string: str = "") -> dict[str, Any]:
        return {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": file_path,
                "old_string": old_string,
                "new_string": new_string,
            },
        }

    return _make
