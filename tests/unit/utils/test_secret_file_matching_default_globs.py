"""A bare ``**`` is judged by bash's default expansion when every shell snapshot agrees (#142).

Every snapshot directory here is a tmp one reached through ``CLAUDE_CONFIG_DIR``;
the real Claude config directory is never consulted.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_code_hooks_daemon.utils import secret_file_matching as sfm
from claude_code_hooks_daemon.utils.protected_file_index import (
    IndexedFile,
    ProtectedFileIndex,
    reset_index_cache,
)
from claude_code_hooks_daemon.utils.shell_snapshot import reset_snapshot_cache

KEY = "id_" + "rsa"
PATTERNS = (KEY,)

SNAPSHOT_OFF = "shopt -u dotglob\nshopt -u globstar\n"


def _write_snapshot(config: Path, name: str, body: str) -> None:
    directory = config / "shell-snapshots"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(body)


@pytest.fixture(autouse=True)
def _clean() -> None:
    reset_index_cache()
    reset_snapshot_cache()


@pytest.fixture()
def config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "claude-config"
    directory.mkdir()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(directory))
    return directory


def _index(root: Path, *relpaths: str) -> ProtectedFileIndex:
    return ProtectedFileIndex(
        project_root=str(root),
        patterns=PATTERNS,
        files=tuple(
            IndexedFile(relpath=rel, pattern=KEY, tracked=True, ignored=False) for rel in relpaths
        ),
    )


def _verdict(command: str, root: Path, index: ProtectedFileIndex) -> object:
    return sfm.find_protected_mention_detail(command, PATTERNS, cwd=str(root), index=index)


def _strict(command: str, root: Path, index: ProtectedFileIndex) -> object:
    return sfm.find_protected_mention_strict(command, PATTERNS, cwd=str(root), index=index)


class TestDefaultExpansionAllowed:
    def test_a_bare_double_star_with_a_file_only_in_a_hidden_directory_is_allowed(
        self, tmp_path: Path, config: Path
    ) -> None:
        _write_snapshot(config, "snapshot-bash-1-a.sh", SNAPSHOT_OFF)
        index = _index(tmp_path, f".hidden/{KEY}")

        assert _verdict("ls **", tmp_path, index) is None
        assert _strict("ls **", tmp_path, index) is None

    def test_a_bare_double_star_with_a_file_only_two_levels_down_is_allowed(
        self, tmp_path: Path, config: Path
    ) -> None:
        _write_snapshot(config, "snapshot-bash-1-a.sh", SNAPSHOT_OFF)
        index = _index(tmp_path, f"a/b/{KEY}")

        assert _verdict("ls **", tmp_path, index) is None

    def test_a_double_star_pattern_reaching_one_level_down_is_still_denied(
        self, tmp_path: Path, config: Path
    ) -> None:
        _write_snapshot(config, "snapshot-bash-1-a.sh", SNAPSHOT_OFF)
        index = _index(tmp_path, f"keys/{KEY}")

        assert _verdict(f"cat **/{KEY}", tmp_path, index) is not None

    def test_a_double_star_glob_naming_a_protected_file_stays_denied_by_its_spelling(
        self, tmp_path: Path, config: Path
    ) -> None:
        _write_snapshot(config, "snapshot-bash-1-a.sh", SNAPSHOT_OFF)
        index = _index(tmp_path, f"a/b/{KEY}")

        assert _verdict(f"cat **/{KEY}", tmp_path, index) is not None


class TestConservativeReadingKept:
    @pytest.fixture()
    def index(self, tmp_path: Path) -> ProtectedFileIndex:
        return _index(tmp_path, f".hidden/{KEY}")

    def test_a_snapshot_with_globstar_on_keeps_the_denial(
        self, tmp_path: Path, config: Path, index: ProtectedFileIndex
    ) -> None:
        _write_snapshot(config, "snapshot-bash-1-a.sh", SNAPSHOT_OFF)
        _write_snapshot(config, "snapshot-bash-2-b.sh", "shopt -u dotglob\nshopt -s globstar\n")

        assert _verdict("ls **", tmp_path, index) is not None

    def test_a_snapshot_with_dotglob_on_keeps_the_denial(
        self, tmp_path: Path, config: Path, index: ProtectedFileIndex
    ) -> None:
        _write_snapshot(config, "snapshot-bash-1-a.sh", "shopt -s dotglob\nshopt -u globstar\n")

        assert _verdict("ls **", tmp_path, index) is not None

    def test_no_snapshots_keeps_the_denial(
        self, tmp_path: Path, config: Path, index: ProtectedFileIndex
    ) -> None:
        assert _verdict("ls **", tmp_path, index) is not None

    def test_an_unreadable_snapshot_keeps_the_denial(
        self, tmp_path: Path, config: Path, index: ProtectedFileIndex
    ) -> None:
        _write_snapshot(config, "snapshot-bash-1-a.sh", SNAPSHOT_OFF)
        directory = config / "shell-snapshots"
        (directory / "snapshot-bash-2-b.sh").write_bytes(b"\xff\xfe\x00 not text \xff")

        assert _verdict("ls **", tmp_path, index) is not None

    @pytest.mark.parametrize(
        "command",
        ["shopt -s globstar; ls **", "set -O globstar && ls **", "shopt -s dotglob\nls **"],
    )
    def test_a_command_that_switches_the_options_keeps_the_denial(
        self, tmp_path: Path, config: Path, index: ProtectedFileIndex, command: str
    ) -> None:
        _write_snapshot(config, "snapshot-bash-1-a.sh", SNAPSHOT_OFF)

        assert _verdict(command, tmp_path, index) is not None

    def test_a_literal_protected_path_is_denied_whatever_the_snapshots_say(
        self, tmp_path: Path, config: Path, index: ProtectedFileIndex
    ) -> None:
        _write_snapshot(config, "snapshot-bash-1-a.sh", SNAPSHOT_OFF)

        assert _verdict(f"cat .hidden/{KEY}", tmp_path, index) is not None

    def test_a_double_star_pattern_reaching_a_protected_file_is_denied_with_globstar_on(
        self, tmp_path: Path, config: Path
    ) -> None:
        _write_snapshot(config, "snapshot-bash-1-a.sh", "shopt -u dotglob\nshopt -s globstar\n")
        index = _index(tmp_path, f"a/b/{KEY}")

        assert _verdict(f"cat **/{KEY}", tmp_path, index) is not None


class TestIndexDefaultExpansion:
    def test_double_star_reads_like_a_single_star_under_default_expansion(
        self, tmp_path: Path
    ) -> None:
        index = _index(tmp_path, f"a/{KEY}", f"a/b/{KEY}")
        base = (str(tmp_path),)

        assert index.glob_matches(f"**/{KEY}", base) is not None
        assert index.glob_matches(f"**/{KEY}", base, default_expansion=True) is not None
        deep = _index(tmp_path, f"a/b/{KEY}")
        assert deep.glob_matches(f"**/{KEY}", base) is not None
        assert deep.glob_matches(f"**/{KEY}", base, default_expansion=True) is None

    def test_double_star_skips_dot_names_under_default_expansion(self, tmp_path: Path) -> None:
        hidden = _index(tmp_path, f".h/{KEY}")

        assert hidden.glob_matches("**", (str(tmp_path),)) is not None
        assert hidden.glob_matches("**", (str(tmp_path),), default_expansion=True) is None
