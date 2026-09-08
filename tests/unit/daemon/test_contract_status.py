"""Plan 00327 Task 3.2 — the ``contract-status`` CLI verb.

Steps 1-2 of ``docs/guides/HOOK-CONTRACT-REFRESH.md`` are pure mechanism:
raw-fetch the documented hooks page and compare its sha256 with
``META.json.docs_sha256``. The verb does exactly that and nothing more — the
extraction steps stay a verified human/agent judgement (Plan 00271 D3).

No test here touches the network: the fetcher is injected.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon.cli import cmd_contract_status
from claude_code_hooks_daemon.daemon.contract_status import (
    EXIT_CHANGED,
    EXIT_ERROR,
    EXIT_UNCHANGED,
    ContractStatus,
    ContractStatusError,
    compare_contract,
)

_URL = "https://code.claude.com/docs/en/hooks.md"
_BODY = b"# Hooks reference\n\nverbatim text\n"
_BODY_SHA = hashlib.sha256(_BODY).hexdigest()


def _write_meta(path: Path, sha256: str, docs_bytes: int = len(_BODY)) -> Path:
    path.write_text(
        json.dumps(
            {
                "docs_url": _URL,
                "fetch_date": "2026-09-08",
                "docs_bytes": docs_bytes,
                "docs_sha256": sha256,
                "last_audited_claude_code_version": "2.1.263",
                "refresh_procedure": "docs/guides/HOOK-CONTRACT-REFRESH.md",
                "event_count": 33,
            }
        )
    )
    return path


@pytest.fixture
def meta_unchanged(tmp_path: Path) -> Path:
    return _write_meta(tmp_path / "META.json", _BODY_SHA)


@pytest.fixture
def meta_changed(tmp_path: Path) -> Path:
    return _write_meta(tmp_path / "META.json", "0" * 64, docs_bytes=1)


class TestCompareContract:
    def test_unchanged_when_hashes_match(self, meta_unchanged: Path) -> None:
        fetched: list[str] = []

        def fetch(url: str) -> bytes:
            fetched.append(url)
            return _BODY

        status = compare_contract(meta_unchanged, fetch)
        assert isinstance(status, ContractStatus)
        assert status.changed is False
        assert status.url == _URL
        assert status.recorded_sha256 == _BODY_SHA
        assert status.fetched_sha256 == _BODY_SHA
        assert status.fetched_bytes == len(_BODY)
        assert fetched == [_URL], "the fetch must go to META.json's documented URL"

    def test_changed_when_hashes_differ(self, meta_changed: Path) -> None:
        status = compare_contract(meta_changed, lambda _url: _BODY)
        assert status.changed is True
        assert status.recorded_sha256 == "0" * 64
        assert status.fetched_sha256 == _BODY_SHA
        assert status.recorded_bytes == 1
        assert status.fetched_bytes == len(_BODY)

    def test_body_is_hashed_raw_not_decoded(self, tmp_path: Path) -> None:
        """The RAW-fetch rule: the bytes on the wire are what is hashed."""
        body = "café \r\n".encode()
        meta = _write_meta(tmp_path / "META.json", hashlib.sha256(body).hexdigest())
        assert compare_contract(meta, lambda _url: body).changed is False

    def test_missing_meta_is_an_error(self, tmp_path: Path) -> None:
        with pytest.raises(ContractStatusError, match="META.json"):
            compare_contract(tmp_path / "absent" / "META.json", lambda _url: _BODY)

    def test_malformed_meta_is_an_error(self, tmp_path: Path) -> None:
        meta = tmp_path / "META.json"
        meta.write_text("not json")
        with pytest.raises(ContractStatusError, match="META.json"):
            compare_contract(meta, lambda _url: _BODY)

    def test_meta_without_hash_is_an_error(self, tmp_path: Path) -> None:
        meta = tmp_path / "META.json"
        meta.write_text(json.dumps({"docs_url": _URL}))
        with pytest.raises(ContractStatusError, match="docs_sha256"):
            compare_contract(meta, lambda _url: _BODY)

    def test_meta_without_url_is_an_error(self, tmp_path: Path) -> None:
        """The URL is read from META.json, never hard-coded a second time."""
        meta = tmp_path / "META.json"
        meta.write_text(json.dumps({"docs_sha256": _BODY_SHA}))
        with pytest.raises(ContractStatusError, match="docs_url"):
            compare_contract(meta, lambda _url: _BODY)

    def test_fetch_failure_is_an_error(self, meta_unchanged: Path) -> None:
        def fetch(_url: str) -> bytes:
            raise OSError("connection refused")

        with pytest.raises(ContractStatusError, match="connection refused"):
            compare_contract(meta_unchanged, fetch)

    def test_save_writes_the_raw_body(self, meta_unchanged: Path, tmp_path: Path) -> None:
        target = tmp_path / "untracked" / "hooks-raw.md"
        status = compare_contract(meta_unchanged, lambda _url: _BODY, save_to=target)
        assert target.read_bytes() == _BODY
        assert status.saved_to == target


class TestCmdContractStatus:
    def _args(self, meta: Path, save: Path | None = None) -> argparse.Namespace:
        return argparse.Namespace(meta=meta, save=save)

    def test_unchanged_exits_zero_and_says_so(
        self, meta_unchanged: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = cmd_contract_status(self._args(meta_unchanged), fetch=lambda _url: _BODY)
        out = capsys.readouterr().out
        assert code == EXIT_UNCHANGED == 0
        assert "unchanged" in out
        assert _URL in out
        assert _BODY_SHA[:12] in out

    def test_changed_exits_one_and_points_at_the_procedure(
        self, meta_changed: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = cmd_contract_status(self._args(meta_changed), fetch=lambda _url: _BODY)
        out = capsys.readouterr().out
        assert code == EXIT_CHANGED == 1
        assert "CHANGED" in out
        assert "HOOK-CONTRACT-REFRESH.md" in out
        assert "0" * 12 in out
        assert _BODY_SHA[:12] in out

    def test_error_exits_two_on_stderr(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = cmd_contract_status(
            self._args(tmp_path / "absent" / "META.json"), fetch=lambda _url: _BODY
        )
        captured = capsys.readouterr()
        assert code == EXIT_ERROR == 2
        assert "contract-status:" in captured.err
        assert captured.out == ""

    def test_save_is_reported(
        self, meta_changed: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        target = tmp_path / "hooks-raw.md"
        cmd_contract_status(self._args(meta_changed, save=target), fetch=lambda _url: _BODY)
        assert str(target) in capsys.readouterr().out
        assert target.read_bytes() == _BODY

    def test_default_meta_is_the_vendored_contract(self) -> None:
        """No --meta ⇒ the repository's own contracts/claude-code-hooks/META.json."""
        from claude_code_hooks_daemon.daemon.contract_status import DEFAULT_META_PATH

        assert DEFAULT_META_PATH.name == "META.json"
        assert DEFAULT_META_PATH.parent.name == "claude-code-hooks"
        assert DEFAULT_META_PATH.is_file()

    def test_default_fetcher_is_the_https_only_raw_fetch(self) -> None:
        """Production uses the remote-docs raw https fetcher: no summarising layer."""
        from claude_code_hooks_daemon.daemon.contract_status import DEFAULT_FETCH
        from claude_code_hooks_daemon.remote_docs.fetchers import https_fetch

        assert DEFAULT_FETCH is https_fetch


class TestParserWiring:
    """The parser is built inside ``main()``; drive it through ``sys.argv``."""

    def _parse(self, monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> argparse.Namespace:
        from claude_code_hooks_daemon.daemon import cli

        seen: list[argparse.Namespace] = []

        def stub(args: argparse.Namespace) -> int:
            seen.append(args)
            return 0

        monkeypatch.setattr(cli, "cmd_contract_status", stub)
        monkeypatch.setattr("sys.argv", ["hooks-daemon", *argv])
        assert cli.main() == 0
        assert len(seen) == 1
        return seen[0]

    def test_contract_status_subcommand_is_registered(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        args = self._parse(monkeypatch, ["contract-status"])
        assert args.save is None
        assert args.meta is None

    def test_flags_parse(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        args = self._parse(
            monkeypatch,
            ["contract-status", "--meta", str(tmp_path / "m.json"), "--save", "raw.md"],
        )
        assert args.meta == tmp_path / "m.json"
        assert args.save == Path("raw.md")
