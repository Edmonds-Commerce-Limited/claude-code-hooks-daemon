"""Plan 00291 — the install stamp a guarded branch install leaves behind.

A release install stamps the venv with ``vX.Y.Z``; a branch install stamps
``vX.Y.Z+<ref>.<shortsha>``. ``install_stamp`` is the one reader of that
stamp for ``status``, ``version_check`` and the UNRELEASED-manifest loaders,
so every consumer agrees on what a branch install is.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_code_hooks_daemon.install.install_stamp import (
    STAMP_FILENAME,
    InstallStamp,
    is_branch_install,
    parse_install_stamp,
    read_install_stamp,
)


class TestParseInstallStamp:
    def test_release_stamp_has_no_ref(self) -> None:
        stamp = parse_install_stamp("v3.63.0")
        assert stamp == InstallStamp(raw="v3.63.0", version="3.63.0", ref=None, sha=None)
        assert stamp.is_branch_install is False

    def test_branch_stamp_carries_ref_and_sha(self) -> None:
        stamp = parse_install_stamp("v3.63.0+main.8d011476")
        assert stamp.version == "3.63.0"
        assert stamp.ref == "main"
        assert stamp.sha == "8d011476"
        assert stamp.is_branch_install is True

    def test_ref_may_itself_contain_dots_and_dashes(self) -> None:
        stamp = parse_install_stamp("v3.63.0+release-3.63.abc1234")
        assert stamp.ref == "release-3.63"
        assert stamp.sha == "abc1234"

    def test_whitespace_is_stripped(self) -> None:
        assert parse_install_stamp("v3.63.0+main.8d011476\n").sha == "8d011476"

    @pytest.mark.parametrize(
        "raw", ["", "3.63.0", "main", "v3.63.0+", "v3.63.0+main", "v3.63.0+main.", "vX"]
    )
    def test_unparseable_stamp_is_rejected(self, raw: str) -> None:
        with pytest.raises(ValueError, match="install stamp"):
            parse_install_stamp(raw)


class TestReadInstallStamp:
    def test_reads_the_stamp_file_under_the_venv_root(self, tmp_path: Path) -> None:
        (tmp_path / STAMP_FILENAME).write_text("v3.63.0+main.8d011476\n")
        stamp = read_install_stamp(tmp_path)
        assert stamp is not None
        assert stamp.is_branch_install is True

    def test_missing_stamp_is_none(self, tmp_path: Path) -> None:
        assert read_install_stamp(tmp_path) is None

    def test_garbage_stamp_is_none_not_a_crash(self, tmp_path: Path) -> None:
        (tmp_path / STAMP_FILENAME).write_text("not a version\n")
        assert read_install_stamp(tmp_path) is None

    def test_defaults_to_the_running_interpreters_prefix(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / STAMP_FILENAME).write_text("v3.63.0\n")
        monkeypatch.setattr("claude_code_hooks_daemon.install.install_stamp.sys.prefix", tmp_path)
        stamp = read_install_stamp()
        assert stamp is not None
        assert stamp.raw == "v3.63.0"


class TestIsBranchInstall:
    def test_true_only_for_a_branch_stamp(self, tmp_path: Path) -> None:
        (tmp_path / STAMP_FILENAME).write_text("v3.63.0+main.8d011476\n")
        assert is_branch_install(tmp_path) is True

    def test_false_for_a_release_stamp_and_for_no_stamp(self, tmp_path: Path) -> None:
        assert is_branch_install(tmp_path) is False
        (tmp_path / STAMP_FILENAME).write_text("v3.63.0\n")
        assert is_branch_install(tmp_path) is False
