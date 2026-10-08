"""N374 item 13: a Grep call may name its target in ``file_path`` (Claude Code 2.1.292).

The file type a search names decides whether an enabled language server covers
it; a ``.ts`` target in ``file_path`` must count like one in ``path``.
"""

import pytest

from claude_code_hooks_daemon.handlers.pre_tool_use.lsp_enforcement import _grep_tool_suffixes


@pytest.mark.parametrize("field", ["path", "file_path"])
def test_the_target_suffix_is_read_from_either_field(field: str) -> None:
    assert _grep_tool_suffixes({"pattern": "x", field: "src/app.ts"}) == frozenset({".ts"})


def test_both_fields_contribute() -> None:
    found = _grep_tool_suffixes({"pattern": "x", "path": "a.ts", "file_path": "b.py"})

    assert found == frozenset({".ts", ".py"})
