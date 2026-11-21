"""Plan 00594 Task 5.1: the client fixture's offline, bare-remote mode.

The default fixture makes ``.claude/hooks-daemon`` a ``git worktree`` of this
repository, so it shares this repository's ``.git/config`` and ``origin``. An
``upgrade.sh`` run there fetches the tracked ref from the REAL origin. The
branch-channel proof therefore needs a fixture whose daemon dir is a plain
clone of a LOCAL bare remote seeded from HEAD, with a release tag, so that no
fetch or push can reach the real origin or the network.

These tests run the fixture's helpers (extracted from the script, as the
teardown tests do) against throwaway repositories under ``tmp_path``.
"""

import subprocess
from pathlib import Path
from typing import Final

import pytest

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
_FIXTURE_SCRIPT: Final[Path] = _REPO_ROOT / "scripts" / "dummy-client-repo.sh"

#: The origin URL of the stand-in source repository: it must never reach the
#: bare remote or the clone.
_REAL_ORIGIN: Final[str] = "https://example.invalid/real-origin.git"

_VERSION: Final[str] = "9.8.7"

#: Sources the named helpers out of the script, with stub info/fail.
_HARNESS: Final[str] = r"""
set -euo pipefail
info() { printf '%s\n' "$*" >&2; }
fail() { printf 'FAIL %s\n' "$*" >&2; exit 1; }
for fn in release_tag_of seed_bare_remote clone_daemon_from_bare remove_daemon_dir; do
    source <(awk "/^${fn}\\(\\) \\{/,/^\\}\$/" "$SCRIPT")
done
"""


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _run(body: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", _HARNESS + body],
        capture_output=True,
        text=True,
        env={"SCRIPT": str(_FIXTURE_SCRIPT), "PATH": "/usr/bin:/bin:/usr/local/bin"},
    )


@pytest.fixture
def source(tmp_path: Path) -> Path:
    """A stand-in for this repository: one commit, a version, a real-looking origin."""
    repo = tmp_path / "source"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    _git(repo, "remote", "add", "origin", _REAL_ORIGIN)
    (repo / "pyproject.toml").write_text(f'[project]\nname = "x"\nversion = "{_VERSION}"\n')
    _git(repo, "add", "pyproject.toml")
    _git(repo, "commit", "-q", "-m", "seed")
    return repo


def _state(repo: Path) -> tuple[str, str, str, str]:
    return (
        _git(repo, "config", "--local", "--list"),
        _git(repo, "remote", "-v"),
        _git(repo, "worktree", "list", "--porcelain"),
        _git(repo, "for-each-ref"),
    )


class TestReleaseTag:
    def test_the_release_tag_is_the_version_head_carries(self, source: Path) -> None:
        result = _run(f'release_tag_of "{source}"')
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == f"v{_VERSION}"


class TestSeedBareRemote:
    def test_the_bare_remote_holds_head_on_main_and_the_release_tag(
        self, source: Path, tmp_path: Path
    ) -> None:
        bare = tmp_path / "remote.git"
        result = _run(f'seed_bare_remote "{source}" "{bare}"')
        assert result.returncode == 0, result.stderr

        head = _git(source, "rev-parse", "HEAD")
        assert _git(bare, "rev-parse", "--is-bare-repository") == "true"
        assert _git(bare, "rev-parse", "refs/heads/main") == head
        assert _git(bare, "rev-parse", f"refs/tags/v{_VERSION}^{{commit}}") == head

    def test_seeding_leaves_the_source_repository_untouched(
        self, source: Path, tmp_path: Path
    ) -> None:
        before = _state(source)
        result = _run(f'seed_bare_remote "{source}" "{tmp_path / "remote.git"}"')
        assert result.returncode == 0, result.stderr
        assert _state(source) == before

    def test_the_bare_remote_never_names_the_real_origin(
        self, source: Path, tmp_path: Path
    ) -> None:
        bare = tmp_path / "remote.git"
        result = _run(f'seed_bare_remote "{source}" "{bare}"')
        assert result.returncode == 0, result.stderr
        assert _REAL_ORIGIN not in (bare / "config").read_text()
        assert _git(bare, "remote") == ""

    def test_an_existing_remote_directory_is_refused(self, source: Path, tmp_path: Path) -> None:
        bare = tmp_path / "remote.git"
        bare.mkdir()
        result = _run(f'seed_bare_remote "{source}" "{bare}"')
        assert result.returncode != 0


class TestCloneDaemonFromBare:
    @pytest.fixture
    def bare(self, source: Path, tmp_path: Path) -> Path:
        bare = tmp_path / "remote.git"
        result = _run(f'seed_bare_remote "{source}" "{bare}"')
        assert result.returncode == 0, result.stderr
        return bare

    def test_the_daemon_dir_is_a_clone_of_the_bare_remote_on_the_tag(
        self, source: Path, bare: Path, tmp_path: Path
    ) -> None:
        daemon = tmp_path / "client" / ".claude" / "hooks-daemon"
        result = _run(f'clone_daemon_from_bare "{bare}" "{daemon}" "v{_VERSION}"')
        assert result.returncode == 0, result.stderr

        assert (daemon / ".git").is_dir(), "a worktree stores .git as a file"
        assert _git(daemon, "config", "--get-all", "remote.origin.url") == str(bare)
        assert _git(daemon, "rev-parse", "HEAD") == _git(source, "rev-parse", "HEAD")
        assert _git(daemon, "tag", "--list") == f"v{_VERSION}"
        assert _REAL_ORIGIN not in (daemon / ".git" / "config").read_text()
        assert not (daemon / ".git" / "objects" / "info" / "alternates").exists()

    def test_cloning_leaves_the_source_repository_untouched(
        self, source: Path, bare: Path, tmp_path: Path
    ) -> None:
        before = _state(source)
        result = _run(f'clone_daemon_from_bare "{bare}" "{tmp_path / "d"}" "v{_VERSION}"')
        assert result.returncode == 0, result.stderr
        assert _state(source) == before

    @pytest.mark.parametrize(
        "remote",
        [
            "https://example.invalid/x.git",
            "git@example.invalid:x.git",
            "file:///somewhere/x.git",
            "relative/x.git",
        ],
    )
    def test_a_remote_that_is_not_an_absolute_local_path_is_refused(
        self, remote: str, tmp_path: Path
    ) -> None:
        daemon = tmp_path / "d"
        result = _run(f'clone_daemon_from_bare "{remote}" "{daemon}" "v{_VERSION}"')
        assert result.returncode != 0
        assert not daemon.exists()

    def test_a_path_that_is_not_a_bare_repository_is_refused(
        self, source: Path, tmp_path: Path
    ) -> None:
        daemon = tmp_path / "d"
        result = _run(f'clone_daemon_from_bare "{source}" "{daemon}" "v{_VERSION}"')
        assert result.returncode != 0
        assert not daemon.exists()


class TestRemoveDaemonDir:
    def test_a_clone_is_deleted_without_touching_the_source(
        self, source: Path, tmp_path: Path
    ) -> None:
        bare = tmp_path / "remote.git"
        daemon = tmp_path / "d"
        setup = _run(
            f'seed_bare_remote "{source}" "{bare}"\n'
            f'clone_daemon_from_bare "{bare}" "{daemon}" "v{_VERSION}"'
        )
        assert setup.returncode == 0, setup.stderr
        before = _state(source)

        result = _run(f'remove_daemon_dir "{source}" "{daemon}"')
        assert result.returncode == 0, result.stderr
        assert not daemon.exists()
        assert _state(source) == before

    def test_a_worktree_is_removed_through_git(self, source: Path, tmp_path: Path) -> None:
        daemon = tmp_path / "wt"
        _git(source, "worktree", "add", "-q", "--detach", str(daemon), "HEAD")

        result = _run(f'remove_daemon_dir "{source}" "{daemon}"')
        assert result.returncode == 0, result.stderr
        assert not daemon.exists()
        assert str(daemon) not in _git(source, "worktree", "list", "--porcelain")

    def test_an_absent_daemon_dir_is_nothing_to_do(self, source: Path, tmp_path: Path) -> None:
        result = _run(f'remove_daemon_dir "{source}" "{tmp_path / "absent"}"')
        assert result.returncode == 0, result.stderr


class TestCreateHasTheBareRemoteMode:
    def test_create_accepts_the_bare_remote_flag(self) -> None:
        content = _FIXTURE_SCRIPT.read_text()
        assert "--bare-remote" in content
        assert 'clone_daemon_from_bare "$DUMMY_REMOTE_DIR"' in content
