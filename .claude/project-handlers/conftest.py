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

    def _make(
        file_path: str, old_string: str = "", new_string: str = ""
    ) -> dict[str, Any]:
        return {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": file_path,
                "old_string": old_string,
                "new_string": new_string,
            },
        }

    return _make
