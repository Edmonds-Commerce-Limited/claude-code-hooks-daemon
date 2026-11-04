"""Plan allocation also considers plan folders other clones pushed (GitHub #154).

The counter and the disk are both local, so two clones could allocate the same
plan number. Before allocating, ``mkplan.bash`` and ``plan_numbering.py`` fetch
the default remote and read the plan folder names on its branches, read-only,
and take the highest of counter, disk and remote.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
from tests.support.git_fixtures import git_setup_timeout

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.handlers.utils.plan_numbering import (
    next_plan_number_for_target,
    remote_highest_plan_number,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_TEMPLATE = (
    _REPO_ROOT / "src" / "claude_code_hooks_daemon" / "install" / "templates" / "mkplan.bash"
)
_PLAN_ASSETS = _REPO_ROOT / "CLAUDE" / "Plan"
_PLAN_SUBDIR = "CLAUDE/Plan"
_NOTICE = "remote could not be checked"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
        timeout=git_setup_timeout(),
    )
    return result.stdout.strip()


def _identity(clone: Path) -> None:
    _git(clone, "config", "user.email", "mkplan-tester@test.invalid")
    _git(clone, "config", "user.name", "Mkplan Tester")


def _scaffold(clone: Path, name: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(clone / _PLAN_SUBDIR / "mkplan.bash"), name],
        capture_output=True,
        text=True,
        check=False,
        cwd=clone,
        timeout=git_setup_timeout(),
    )


def _commit_and_push(clone: Path) -> None:
    _git(clone, "add", "-A")
    _git(clone, "commit", "--quiet", "-m", "plans")
    _git(clone, "push", "--quiet", "origin", "main")


@pytest.fixture
def remote_and_clones(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A bare remote carrying the scaffolder, and two clones of it."""
    bare = tmp_path / "remote.git"
    _git(tmp_path, "init", "--quiet", "--bare", "-b", "main", str(bare))
    seed = tmp_path / "seed"
    _git(tmp_path, "init", "--quiet", "-b", "main", str(seed))
    _identity(seed)
    plan_dir = seed / _PLAN_SUBDIR
    plan_dir.mkdir(parents=True)
    script = plan_dir / "mkplan.bash"
    script.write_bytes(_TEMPLATE.read_bytes())
    script.chmod(0o755)
    for asset in _PLAN_ASSETS.glob("_*"):
        if asset.is_file():
            (plan_dir / asset.name).write_bytes(asset.read_bytes())
    _git(seed, "remote", "add", "origin", str(bare))
    _commit_and_push(seed)
    clones = []
    for label in ("a", "b"):
        clone = tmp_path / f"clone-{label}"
        _git(tmp_path, "clone", "--quiet", str(bare), str(clone))
        _identity(clone)
        clones.append(clone)
    return bare, clones[0], clones[1]


class TestSecondCloneSeesPushedPlans:
    """Clone A pushes plan N; clone B, behind on counter and disk, gets N+1."""

    def test_mkplan_allocates_above_a_number_pushed_by_another_clone(
        self, remote_and_clones: tuple[Path, Path, Path]
    ) -> None:
        _, clone_a, clone_b = remote_and_clones
        assert _scaffold(clone_a, "from-a").returncode == 0
        _commit_and_push(clone_a)

        result = _scaffold(clone_b, "from-b")

        assert result.returncode == 0, result.stderr
        assert (clone_b / _PLAN_SUBDIR / "00002-from-b").is_dir()
        assert not (clone_b / _PLAN_SUBDIR / "00001-from-b").exists()
        assert _git(clone_b, "config", "--local", "hooksdaemon.latestPlanNumber") == "2"

    def test_daemon_allocates_above_a_number_pushed_by_another_clone(
        self, remote_and_clones: tuple[Path, Path, Path]
    ) -> None:
        _, clone_a, clone_b = remote_and_clones
        assert _scaffold(clone_a, "from-a").returncode == 0
        _commit_and_push(clone_a)

        number = next_plan_number_for_target(
            clone_b / _PLAN_SUBDIR / "x", _PLAN_SUBDIR, fallback_root=clone_b
        )

        assert number == "00002"

    def test_archived_plan_on_the_remote_counts(
        self, remote_and_clones: tuple[Path, Path, Path]
    ) -> None:
        _, clone_a, clone_b = remote_and_clones
        (clone_a / _PLAN_SUBDIR / "Completed" / "00040-old").mkdir(parents=True)
        (clone_a / _PLAN_SUBDIR / "Completed" / "00040-old" / "PLAN.md").write_text("x")
        _commit_and_push(clone_a)

        assert remote_highest_plan_number(clone_b, _PLAN_SUBDIR) == 40
        assert _scaffold(clone_b, "after-archive").returncode == 0
        assert (clone_b / _PLAN_SUBDIR / "00041-after-archive").is_dir()

    def test_a_plan_only_on_a_feature_branch_counts(
        self, remote_and_clones: tuple[Path, Path, Path]
    ) -> None:
        _, clone_a, clone_b = remote_and_clones
        _git(clone_a, "checkout", "--quiet", "-b", "feature")
        (clone_a / _PLAN_SUBDIR / "00007-on-branch").mkdir()
        (clone_a / _PLAN_SUBDIR / "00007-on-branch" / "PLAN.md").write_text("x")
        _git(clone_a, "add", "-A")
        _git(clone_a, "commit", "--quiet", "-m", "branch plan")
        _git(clone_a, "push", "--quiet", "origin", "feature")

        assert remote_highest_plan_number(clone_b, _PLAN_SUBDIR) == 7

    def test_the_scan_never_pushes(self, remote_and_clones: tuple[Path, Path, Path]) -> None:
        bare, clone_a, clone_b = remote_and_clones
        assert _scaffold(clone_a, "from-a").returncode == 0
        _commit_and_push(clone_a)
        before = _git(bare, "for-each-ref")

        assert _scaffold(clone_b, "from-b").returncode == 0

        assert _git(bare, "for-each-ref") == before


class TestOfflineFallback:
    """No remote, or an unreachable one: today's local answer plus one stderr line."""

    def test_mkplan_without_a_remote_uses_local_numbers(
        self, remote_and_clones: tuple[Path, Path, Path]
    ) -> None:
        _, _, clone_b = remote_and_clones
        _git(clone_b, "remote", "remove", "origin")

        result = _scaffold(clone_b, "local-only")

        assert result.returncode == 0, result.stderr
        assert (clone_b / _PLAN_SUBDIR / "00001-local-only").is_dir()
        assert result.stderr.count(_NOTICE) == 1

    def test_mkplan_with_an_unreachable_remote_uses_local_numbers(
        self, remote_and_clones: tuple[Path, Path, Path], tmp_path: Path
    ) -> None:
        _, _, clone_b = remote_and_clones
        _git(clone_b, "remote", "set-url", "origin", str(tmp_path / "does-not-exist.git"))

        result = _scaffold(clone_b, "unreachable")

        assert result.returncode == 0, result.stderr
        assert (clone_b / _PLAN_SUBDIR / "00001-unreachable").is_dir()
        assert result.stderr.count(_NOTICE) == 1

    def test_reachable_remote_prints_no_notice(
        self, remote_and_clones: tuple[Path, Path, Path]
    ) -> None:
        _, _, clone_b = remote_and_clones

        result = _scaffold(clone_b, "reachable")

        assert _NOTICE not in result.stderr

    def test_daemon_without_a_remote_returns_none_and_the_local_answer(
        self, remote_and_clones: tuple[Path, Path, Path], capsys: pytest.CaptureFixture[str]
    ) -> None:
        _, _, clone_b = remote_and_clones
        _git(clone_b, "remote", "remove", "origin")

        assert remote_highest_plan_number(clone_b, _PLAN_SUBDIR) is None
        number = next_plan_number_for_target(
            clone_b / _PLAN_SUBDIR / "x", _PLAN_SUBDIR, fallback_root=clone_b
        )

        assert number == "00001"
        assert capsys.readouterr().err.count(_NOTICE) == 1

    def test_daemon_with_an_unreachable_remote_falls_back(
        self,
        remote_and_clones: tuple[Path, Path, Path],
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _, _, clone_b = remote_and_clones
        _git(clone_b, "remote", "set-url", "origin", str(tmp_path / "does-not-exist.git"))

        number = next_plan_number_for_target(
            clone_b / _PLAN_SUBDIR / "x", _PLAN_SUBDIR, fallback_root=clone_b
        )

        assert number == "00001"
        assert capsys.readouterr().err.count(_NOTICE) == 1

    def test_outside_a_git_repo_there_is_nothing_to_check(self, tmp_path: Path) -> None:
        (tmp_path / _PLAN_SUBDIR).mkdir(parents=True)

        assert remote_highest_plan_number(tmp_path, _PLAN_SUBDIR) is None


class TestFetchBudgetParity:
    """The bash fetch budget is the daemon's, not a second number."""

    def test_script_fetch_timeout_matches_the_daemon_constant(self) -> None:
        match = re.search(
            r"^readonly REMOTE_FETCH_TIMEOUT_SECONDS=(\d+)$", _TEMPLATE.read_text(), re.MULTILINE
        )

        assert match is not None
        assert int(match.group(1)) == Timeout.GIT_FETCH_SESSION
