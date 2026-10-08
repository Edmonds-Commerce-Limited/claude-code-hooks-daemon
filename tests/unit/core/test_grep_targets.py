"""The Grep tool names its target in ``path`` or ``file_path`` (Claude Code 2.1.292).

Every handler that reads a Grep call's target goes through these helpers, so a
payload carrying only ``file_path`` is judged like one carrying ``path``.
"""

from typing import Any

import pytest

from claude_code_hooks_daemon.core.utils import grep_input_for, grep_targets


@pytest.mark.parametrize(
    ("tool_input", "expected"),
    [
        ({"path": "/a"}, ["/a"]),
        ({"file_path": "/b"}, ["/b"]),
        ({"path": "/a", "file_path": "/b"}, ["/a", "/b"]),
        ({"path": "/a", "file_path": "/a"}, ["/a"]),
        ({"path": "", "file_path": "/b"}, ["/b"]),
        ({"path": None, "file_path": 3}, []),
        ({"pattern": "x"}, []),
        ({}, []),
        (None, []),
        ("not a dict", []),
    ],
)
def test_grep_targets(tool_input: Any, expected: list[str]) -> None:
    assert grep_targets(tool_input) == expected


def test_grep_input_for_names_one_target_in_path() -> None:
    hook_input = {
        "tool_name": "Grep",
        "tool_input": {"pattern": "x", "file_path": "/b", "path": "/a"},
        "cwd": "/w",
    }

    narrowed = grep_input_for(hook_input, "/b")

    assert narrowed["tool_input"] == {"pattern": "x", "path": "/b"}
    assert narrowed["cwd"] == "/w"
    assert hook_input["tool_input"]["path"] == "/a"  # the original is untouched
