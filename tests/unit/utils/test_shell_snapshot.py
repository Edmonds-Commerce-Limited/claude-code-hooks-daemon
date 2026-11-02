"""Reading the Claude Code shell snapshots for the glob options bash expands by (#142)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from claude_code_hooks_daemon.utils import shell_snapshot
from claude_code_hooks_daemon.utils.shell_snapshot import (
    MAX_SNAPSHOTS_READ,
    default_glob_semantics,
    reset_snapshot_cache,
)

OFF = "shopt -u dotglob\nshopt -u globstar\n"


@pytest.fixture(autouse=True)
def _clean() -> None:
    reset_snapshot_cache()


def _snap(config: Path, name: str, body: str, mtime: int | None = None) -> Path:
    directory = config / "shell-snapshots"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(body)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


class TestVerdict:
    def test_every_snapshot_off_means_default_semantics(self, tmp_path: Path) -> None:
        _snap(tmp_path, "a.sh", OFF)
        _snap(tmp_path, "b.sh", "shopt -s cmdhist\n" + OFF)

        assert default_glob_semantics("ls **", config_dir=tmp_path) is True

    def test_no_snapshot_directory_is_conservative(self, tmp_path: Path) -> None:
        assert default_glob_semantics("ls **", config_dir=tmp_path) is False

    def test_an_empty_snapshot_directory_is_conservative(self, tmp_path: Path) -> None:
        (tmp_path / "shell-snapshots").mkdir()

        assert default_glob_semantics("ls **", config_dir=tmp_path) is False

    @pytest.mark.parametrize(
        "body",
        [
            "shopt -s globstar\nshopt -u dotglob\n",
            "shopt -u globstar\nshopt -s dotglob\n",
            "shopt -u globstar\n",
            "shopt -u dotglob\n",
            "echo nothing\n",
            OFF + "shopt -s globstar\n",
        ],
    )
    def test_one_ambiguous_or_on_snapshot_is_conservative(self, tmp_path: Path, body: str) -> None:
        _snap(tmp_path, "a.sh", OFF)
        _snap(tmp_path, "b.sh", body)

        assert default_glob_semantics("ls **", config_dir=tmp_path) is False

    def test_an_unreadable_snapshot_is_conservative(self, tmp_path: Path) -> None:
        _snap(tmp_path, "a.sh", OFF)
        (tmp_path / "shell-snapshots" / "b.sh").write_bytes(b"\xff\xfe\x00\xff")

        assert default_glob_semantics("ls **", config_dir=tmp_path) is False

    @pytest.mark.parametrize(
        "command",
        ["shopt -s globstar; ls **", "shopt -s dotglob", "set -O globstar", "bash -O dotglob -c x"],
    )
    def test_a_command_that_could_switch_the_options_is_conservative(
        self, tmp_path: Path, command: str
    ) -> None:
        _snap(tmp_path, "a.sh", OFF)

        assert default_glob_semantics(command, config_dir=tmp_path) is False

    def test_a_command_merely_naming_a_similar_word_is_not_a_switch(self, tmp_path: Path) -> None:
        _snap(tmp_path, "a.sh", OFF)

        assert default_glob_semantics("ls -lO ** shoptions", config_dir=tmp_path) is True

    def test_the_default_config_directory_comes_from_the_environment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _snap(tmp_path, "a.sh", OFF)
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))

        assert default_glob_semantics("ls **") is True


class TestCache:
    def test_an_unchanged_directory_is_not_read_again(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _snap(tmp_path, "a.sh", OFF)
        assert default_glob_semantics("ls", config_dir=tmp_path) is True

        def _boom(*_args: object, **_kwargs: object) -> str:
            raise AssertionError("snapshot was read twice")

        monkeypatch.setattr(Path, "read_text", _boom)

        assert default_glob_semantics("ls", config_dir=tmp_path) is True

    def test_a_snapshot_that_changes_is_read_again(self, tmp_path: Path) -> None:
        path = _snap(tmp_path, "a.sh", OFF, mtime=1_000_000)
        assert default_glob_semantics("ls", config_dir=tmp_path) is True

        path.write_text("shopt -s globstar\nshopt -u dotglob\n")
        os.utime(path, (2_000_000, 2_000_000))

        assert default_glob_semantics("ls", config_dir=tmp_path) is False

    def test_a_new_snapshot_is_read(self, tmp_path: Path) -> None:
        _snap(tmp_path, "a.sh", OFF, mtime=1_000_000)
        assert default_glob_semantics("ls", config_dir=tmp_path) is True

        _snap(tmp_path, "b.sh", "shopt -s dotglob\nshopt -u globstar\n", mtime=2_000_000)

        assert default_glob_semantics("ls", config_dir=tmp_path) is False


class TestBound:
    def test_only_the_newest_snapshots_up_to_the_cap_are_read(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(shell_snapshot, "MAX_SNAPSHOTS_READ", 3)
        _snap(tmp_path, "old.sh", "shopt -s globstar\nshopt -s dotglob\n", mtime=1_000)
        for number in range(3):
            _snap(tmp_path, f"new{number}.sh", OFF, mtime=2_000 + number)

        assert default_glob_semantics("ls", config_dir=tmp_path) is True

    def test_the_cap_is_a_sensible_bound(self) -> None:
        assert 1 <= MAX_SNAPSHOTS_READ <= 1000
