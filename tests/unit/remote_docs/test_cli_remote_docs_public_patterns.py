"""The capture swapper reads public patterns the way the sensitive-content guard does (N374).

``_capture_value_swapper`` used to compile each configured pattern itself, so a
broken regex crashed the CLI with a traceback. It now compiles through the
guard's own compiler, applies EVERY pattern configured for a kind, and refuses
the capture ("nothing was written") when a pattern for a registry kind does not
compile or an entry is malformed: a page cannot be judged against a pattern
that cannot be read.
"""

from __future__ import annotations

import argparse
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon.cli import cmd_remote_docs
from claude_code_hooks_daemon.handlers.pre_tool_use import sensitive_content
from claude_code_hooks_daemon.utils.fake_values import REGISTRY_RELATIVE_PATH

_LISTED_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_LISTED_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
# Built at runtime so this file never carries a real-looking UUID literal.
_UPSTREAM = "-".join(("8e11bfb5", "7dc2", "432b", "9206", "928fa5c35731"))
_UPSTREAM_TOKEN = "".join(("sess", "-", "0123456789ab"))
_UUID_PATTERN = (
    r"\b(?!([0-9a-fA-F])\1{7}-\1{4}-\1{4}-\1{4}-\1{12}\b)"
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
_TOKEN_PATTERN = r"sess-[0-9a-f]{12}"
_NOW = datetime(2026, 10, 6, 10, 0, tzinfo=UTC)
_URL = "https://example.com/docs/statusline"


def _entry(pattern: str) -> str:
    return f"          - name: session-uuid\n            pattern: '{pattern}'\n"


_UUID_ENTRY = _entry(_UUID_PATTERN)
_TOKEN_ENTRY = _entry(_TOKEN_PATTERN)
_BROKEN_ENTRY = _entry("(unclosed")


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
        f"kinds:\n  session-uuid:\n    values:\n      - '{_LISTED_A}'\n      - '{_LISTED_B}'\n",
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


def _page(root: Path) -> Path:
    return root / "remote-docs" / "example.com" / "docs" / "statusline.md"


@pytest.mark.parametrize(
    "patterns_yaml",
    [
        pytest.param(_BROKEN_ENTRY, id="only-pattern-is-broken"),
        pytest.param(_BROKEN_ENTRY + _UUID_ENTRY, id="broken-first"),
        pytest.param(_UUID_ENTRY + _BROKEN_ENTRY, id="broken-second"),
    ],
)
def test_a_pattern_for_a_registry_kind_that_does_not_compile_refuses_the_capture(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], patterns_yaml: str
) -> None:
    _configure(tmp_path, patterns_yaml)

    code = _add(tmp_path, f'{{"session_id": "{_UPSTREAM}"}}\n'.encode())

    captured = capsys.readouterr()
    assert code == 1
    assert "nothing was written" in captured.err
    assert "Traceback" not in captured.err
    assert not _page(tmp_path).exists()


def test_a_broken_pattern_for_a_kind_the_registry_does_not_list_is_ignored(
    tmp_path: Path,
) -> None:
    other = "          - name: unlisted-kind\n            pattern: '(unclosed'\n"
    _configure(tmp_path, other + _UUID_ENTRY)

    assert _add(tmp_path, f'{{"session_id": "{_UPSTREAM}"}}\n'.encode()) == 0
    assert _UPSTREAM not in _page(tmp_path).read_text(encoding="utf-8")


def test_a_public_pattern_entry_that_is_not_a_mapping_refuses_the_capture(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _configure(tmp_path, "          - just-a-string\n" + _UUID_ENTRY)

    code = _add(tmp_path, b"# page\n")

    assert code == 1
    assert "nothing was written" in capsys.readouterr().err
    assert not _page(tmp_path).exists()


@pytest.mark.parametrize(
    "patterns_yaml",
    [
        pytest.param(_UUID_ENTRY + _TOKEN_ENTRY, id="uuid-first"),
        pytest.param(_TOKEN_ENTRY + _UUID_ENTRY, id="token-first"),
    ],
)
def test_every_pattern_configured_for_a_kind_is_applied_not_just_the_last(
    tmp_path: Path, patterns_yaml: str
) -> None:
    _configure(tmp_path, patterns_yaml)
    body = f"id {_UPSTREAM} and {_UPSTREAM_TOKEN}\n".encode()

    code = _add(tmp_path, body)

    assert code == 0
    text = _page(tmp_path).read_text(encoding="utf-8")
    assert _UPSTREAM not in text
    assert _UPSTREAM_TOKEN not in text


def test_the_swapper_compiles_through_the_guards_shared_compiler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure(tmp_path, _UUID_ENTRY)
    seen: list[str] = []
    real = sensitive_content.compile_public_pattern

    def spy(pattern: str) -> re.Pattern[str]:
        seen.append(pattern)
        return real(pattern)

    monkeypatch.setattr(sensitive_content, "compile_public_pattern", spy)

    assert _add(tmp_path, f'{{"session_id": "{_UPSTREAM}"}}\n'.encode()) == 0
    assert _UUID_PATTERN in seen
