"""Tests for the shared would-be-content helper (Plan 00367).

``plan_qa_edit`` and ``plan_close_approval`` both judge the content a file
WOULD have after a Write/Edit; one helper computes it so the two gates can
never disagree about what an Edit produces.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.handlers.utils.would_be_content import would_be_content


def _write(path: Path, content: str) -> dict[str, Any]:
    return {"tool_name": "Write", "tool_input": {"file_path": str(path), "content": content}}


def _edit(path: Path, old: str, new: str, replace_all: bool = False) -> dict[str, Any]:
    return {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(path),
            "old_string": old,
            "new_string": new,
            "replace_all": replace_all,
        },
    }


def test_write_is_the_payload_itself(tmp_path: Path) -> None:
    assert would_be_content(_write(tmp_path / "f.md", "new"), current="old") == "new"


def test_write_needs_no_current_content(tmp_path: Path) -> None:
    assert would_be_content(_write(tmp_path / "f.md", "new"), current=None) == "new"


def test_edit_applies_one_replacement(tmp_path: Path) -> None:
    payload = _edit(tmp_path / "f.md", "a", "b")
    assert would_be_content(payload, current="a a") == "b a"


def test_edit_replace_all(tmp_path: Path) -> None:
    payload = _edit(tmp_path / "f.md", "a", "b", replace_all=True)
    assert would_be_content(payload, current="a a") == "b b"


def test_edit_with_no_current_content_is_none(tmp_path: Path) -> None:
    assert would_be_content(_edit(tmp_path / "f.md", "a", "b"), current=None) is None


def test_edit_with_unmatched_old_string_is_none(tmp_path: Path) -> None:
    assert would_be_content(_edit(tmp_path / "f.md", "zzz", "b"), current="a a") is None


def test_edit_with_empty_old_string_is_none(tmp_path: Path) -> None:
    assert would_be_content(_edit(tmp_path / "f.md", "", "b"), current="a a") is None
