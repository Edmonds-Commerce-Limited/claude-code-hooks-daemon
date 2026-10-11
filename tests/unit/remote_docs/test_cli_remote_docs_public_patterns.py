"""The capture swapper reads public patterns the way the sensitive-content guard does (N374).

``_capture_value_swapper`` used to compile each configured pattern itself, so a
broken regex crashed the CLI with a traceback while the guard, which owns the
same config, drops it with a warning. It now reuses the handler's own compiled
pattern accessor, and a malformed entry is a refused capture with a message.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon.cli import cmd_remote_docs
from claude_code_hooks_daemon.handlers.pre_tool_use import sensitive_content
from claude_code_hooks_daemon.utils.fake_values import REGISTRY_RELATIVE_PATH

_LISTED = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
# Built at runtime so this file never carries a real-looking UUID literal.
_UPSTREAM = "-".join(("8e11bfb5", "7dc2", "432b", "9206", "928fa5c35731"))
_UUID_PATTERN = (
    r"\b(?!([0-9a-fA-F])\1{7}-\1{4}-\1{4}-\1{4}-\1{12}\b)"
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
_NOW = datetime(2026, 10, 6, 10, 0, tzinfo=UTC)
_URL = "https://example.com/docs/statusline"


def _configure(root: Path, patterns_yaml: str) -> None:
    (root / ".claude").mkdir(parents=True, exist_ok=True)
    (root / ".claude" / "hooks-daemon.yaml").write_text(
        'version: "1.0"\n'
        "handlers:\n"
        "  pre_tool_use:\n"
        "    sensitive_content:\n"
        "      enabled: true\n"
        "      options:\n"
        "        public_patterns:\n" + patterns_yaml,
        encoding="utf-8",
    )
    (root / REGISTRY_RELATIVE_PATH).write_text(
        f"kinds:\n  session-uuid:\n    values:\n      - '{_LISTED}'\n",
        encoding="utf-8",
    )


def _add(root: Path, body: bytes) -> int:
    return cmd_remote_docs(
        argparse.Namespace(
            project_root=root,
            remote_docs_action="add",
            url=_URL,
            path=None,
            all_docs=False,
            licence=None,
            stale_after_days=None,
            json_output=False,
            fetch_fn=lambda _url: body,
            now=_NOW,
            force=False,
        )
    )


_GOOD = f"          - name: session-uuid\n            pattern: '{_UUID_PATTERN}'\n"


def test_a_pattern_that_does_not_compile_is_dropped_and_the_rest_still_swap(
    tmp_path: Path,
) -> None:
    broken = "          - name: session-uuid\n            pattern: '(unclosed'\n"
    _configure(tmp_path, broken + _GOOD)

    code = _add(tmp_path, f'{{"session_id": "{_UPSTREAM}"}}\n'.encode())

    assert code == 0
    page = tmp_path / "remote-docs" / "example.com" / "docs" / "statusline.md"
    assert _UPSTREAM not in page.read_text(encoding="utf-8")


def test_a_public_pattern_entry_that_is_not_a_mapping_refuses_the_capture(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _configure(tmp_path, "          - just-a-string\n" + _GOOD)

    code = _add(tmp_path, b"# page\n")

    assert code == 1
    assert "nothing was written" in capsys.readouterr().err


def test_the_swapper_and_the_guard_share_one_pattern_compiler() -> None:
    assert callable(sensitive_content.compiled_public_pattern)
    assert sensitive_content.compiled_public_pattern("(unclosed") is None
    assert sensitive_content.compiled_public_pattern("ab+c") is not None
