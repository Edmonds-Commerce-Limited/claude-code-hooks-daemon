"""`remote-docs add` swaps unlisted fakes for listed ones and records it (Plan 00492)."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon.cli import cmd_remote_docs
from claude_code_hooks_daemon.remote_docs.provenance import Fidelity, parse_provenance
from claude_code_hooks_daemon.utils.fake_values import REGISTRY_RELATIVE_PATH

_LISTED_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_LISTED_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
# Built at runtime so this file never carries a real-looking UUID literal.
_UPSTREAM = "-".join(("8e11bfb5", "7dc2", "432b", "9206", "928fa5c35731"))
_UUID_PATTERN = (
    r"\b(?!([0-9a-fA-F])\1{7}-\1{4}-\1{4}-\1{4}-\1{12}\b)"
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
_NOW = datetime(2026, 10, 6, 10, 0, tzinfo=UTC)
_URL = "https://example.com/docs/statusline"


def _configure(root: Path, *, registry: bool = True) -> None:
    (root / ".claude").mkdir(parents=True, exist_ok=True)
    (root / ".claude" / "hooks-daemon.yaml").write_text(
        'version: "1.0"\n'
        "handlers:\n"
        "  pre_tool_use:\n"
        "    sensitive_content:\n"
        "      enabled: true\n"
        "      options:\n"
        "        public_patterns:\n"
        "          - name: session-uuid\n"
        f"            pattern: '{_UUID_PATTERN}'\n",
        encoding="utf-8",
    )
    if registry:
        (root / REGISTRY_RELATIVE_PATH).write_text(
            f"kinds:\n  session-uuid:\n    values:\n      - '{_LISTED_A}'\n      - '{_LISTED_B}'\n",
            encoding="utf-8",
        )


def _args(root: Path, action: str, body: bytes, **overrides: object) -> argparse.Namespace:
    base: dict[str, object] = {
        "project_root": root,
        "remote_docs_action": action,
        "url": _URL,
        "path": None,
        "all_docs": False,
        "licence": None,
        "stale_after_days": None,
        "json_output": False,
        "fetch_fn": lambda _url: body,
        "now": _NOW,
        "force": False,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


def _page(root: Path) -> Path:
    return root / "remote-docs" / "example.com" / "docs" / "statusline.md"


class TestAddSwapsUnlistedFakes:
    def test_the_page_is_vendored_with_a_listed_fake_and_the_swap_recorded(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tmp_path / ".claude").mkdir()
        _configure(tmp_path)
        body = f'{{"session_id": "{_UPSTREAM}"}}\n'.encode()

        code = cmd_remote_docs(_args(tmp_path, "add", body))

        assert code == 0
        text = _page(tmp_path).read_text(encoding="utf-8")
        assert _UPSTREAM not in text
        parsed = parse_provenance(text)
        assert parsed.provenance is not None
        assert parsed.provenance.fidelity is Fidelity.CONVERTED
        assert [(s.kind, s.replacement) for s in parsed.provenance.value_swaps] == [
            ("session-uuid", _LISTED_A)
        ]
        assert "swapped 1 unlisted" in capsys.readouterr().out

    def test_without_a_registry_the_same_page_is_still_refused(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _configure(tmp_path, registry=False)
        body = f'{{"session_id": "{_UPSTREAM}"}}\n'.encode()

        code = cmd_remote_docs(_args(tmp_path, "add", body))

        assert code == 1
        assert "session-uuid" in capsys.readouterr().err
        assert not _page(tmp_path).exists()

    def test_a_malformed_registry_refuses_the_capture(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _configure(tmp_path)
        (tmp_path / REGISTRY_RELATIVE_PATH).write_text("kinds: [oops", encoding="utf-8")

        code = cmd_remote_docs(_args(tmp_path, "add", b"# page\n"))

        assert code == 1
        assert "nothing was written" in capsys.readouterr().err
        assert not _page(tmp_path).exists()

    def test_a_page_with_only_listed_fakes_stays_verbatim(self, tmp_path: Path) -> None:
        _configure(tmp_path)
        body = f"id {_LISTED_A}\n".encode()

        code = cmd_remote_docs(_args(tmp_path, "add", body))

        assert code == 0
        parsed = parse_provenance(_page(tmp_path).read_text(encoding="utf-8"))
        assert parsed.provenance is not None
        assert parsed.provenance.fidelity is Fidelity.VERBATIM
        assert parsed.provenance.value_swaps == ()

    def test_refresh_swaps_the_same_way(self, tmp_path: Path) -> None:
        _configure(tmp_path)
        assert cmd_remote_docs(_args(tmp_path, "add", b"# first\n")) == 0
        body = f"# second {_UPSTREAM}\n".encode()

        code = cmd_remote_docs(_args(tmp_path, "refresh", body, path=_page(tmp_path)))

        assert code == 0
        text = _page(tmp_path).read_text(encoding="utf-8")
        assert _UPSTREAM not in text
        parsed = parse_provenance(text)
        assert parsed.provenance is not None
        assert len(parsed.provenance.value_swaps) == 1
