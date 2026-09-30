"""``mkplan.bash`` serialises plan-number allocation across linked worktrees.

GitHub issue #59. The plan counter (``git config --local
hooksdaemon.latestPlanNumber``) lives in the repository's COMMON git dir and is
shared by every linked worktree, so the lock guarding it has to live there too.
A lock inside each checkout's own plan dir gives every worktree a private lock
over a shared counter, and two runners allocate the same number.

Driven as a real ``bash`` subprocess against a real temporary repository with a
real linked worktree: the property is about where a directory appears on disk.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout

#: The held-lock test waits out the script's own lock timeout (about ten seconds).
_SHELL_TIMEOUT = Timeout.QA_TEST_TIMEOUT

_REPO_ROOT = Path(__file__).resolve().parents[3]
_TEMPLATE = (
    _REPO_ROOT / "src" / "claude_code_hooks_daemon" / "install" / "templates" / "mkplan.bash"
)
_PLAN_ASSETS = _REPO_ROOT / "CLAUDE" / "Plan"

_COUNTER_KEY = "hooksdaemon.latestPlanNumber"
_COMMON_DIR_LOCK = "hooksdaemon-mkplan.lock"
_PLAN_DIR_LOCK = ".mkplan.lock"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
        timeout=_SHELL_TIMEOUT,
    )
    return result.stdout.strip()


@pytest.fixture
def primary(tmp_path: Path) -> Path:
    """A committed repo carrying the scaffolder, with the counter at 208."""
    repo = tmp_path / "primary"
    plan_dir = repo / "CLAUDE" / "Plan"
    plan_dir.mkdir(parents=True)
    script = plan_dir / "mkplan.bash"
    script.write_bytes(_TEMPLATE.read_bytes())
    script.chmod(0o755)
    for asset in _PLAN_ASSETS.glob("_*"):
        if asset.is_file():
            (plan_dir / asset.name).write_bytes(asset.read_bytes())

    _git(repo, "init", "--quiet")
    _git(repo, "config", "user.email", "mkplan-tester@test.invalid")
    _git(repo, "config", "user.name", "Mkplan Tester")
    _git(repo, "add", "-A")
    _git(repo, "commit", "--quiet", "-m", "seed")
    _git(repo, "config", "--local", _COUNTER_KEY, "208")
    return repo


@pytest.fixture
def linked(primary: Path, tmp_path: Path) -> Path:
    """A linked worktree of ``primary`` (own checkout, shared counter)."""
    worktree = tmp_path / "linked"
    _git(primary, "worktree", "add", "--quiet", str(worktree), "-b", "side")
    return worktree


def _common_dir(repo: Path) -> Path:
    return Path(_git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir"))


def _run(
    checkout: Path, *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(checkout / "CLAUDE" / "Plan" / "mkplan.bash"), *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=checkout,
        env=env,
        timeout=_SHELL_TIMEOUT,
    )


class TestWorktreeLock:
    """The scaffold lock is shared by every checkout of one repository."""

    def test_lock_held_in_common_git_dir_blocks_linked_worktree(
        self, primary: Path, linked: Path
    ) -> None:
        """A runner holding the common-dir lock stops a runner in another worktree."""
        lock = _common_dir(primary) / _COMMON_DIR_LOCK
        lock.mkdir()

        result = _run(linked, "held-elsewhere")

        assert result.returncode != 0
        assert _COMMON_DIR_LOCK in result.stderr
        assert _git(primary, "config", "--local", _COUNTER_KEY) == "208"
        assert not list((linked / "CLAUDE" / "Plan").glob("00209-*"))
        assert lock.is_dir(), "a lock this runner never took must not be removed"

    def test_linked_worktree_scaffolds_and_leaves_no_lock(
        self, primary: Path, linked: Path
    ) -> None:
        """With no lock held the scaffold succeeds and cleans up both lock locations."""
        result = _run(linked, "from-linked")

        assert result.returncode == 0, result.stderr
        assert list((linked / "CLAUDE" / "Plan").glob("00209-from-linked"))
        assert _git(primary, "config", "--local", _COUNTER_KEY) == "209"
        assert not (_common_dir(primary) / _COMMON_DIR_LOCK).exists()
        assert not (linked / "CLAUDE" / "Plan" / _PLAN_DIR_LOCK).exists()

    def test_primary_checkout_uses_the_same_common_dir_lock(self, primary: Path) -> None:
        """The primary checkout is blocked by the very same lock as a linked one."""
        (_common_dir(primary) / _COMMON_DIR_LOCK).mkdir()

        result = _run(primary, "held-elsewhere")

        assert result.returncode != 0
        assert _COMMON_DIR_LOCK in result.stderr

    def test_journal_mode_ignores_the_scaffold_lock(self, primary: Path, linked: Path) -> None:
        """--journal never takes (or waits on) the scaffold lock."""
        (_common_dir(primary) / _COMMON_DIR_LOCK).mkdir()
        plan = linked / "CLAUDE" / "Plan" / "00001-existing"
        plan.mkdir()
        (plan / "PLAN.md").write_text("# Plan 00001: existing\n")
        body = linked / "body.txt"
        body.write_text("an entry\n")

        result = _run(linked, "--journal", "1", "action", str(body))

        assert _COMMON_DIR_LOCK not in result.stderr


@pytest.fixture
def old_git_env(tmp_path: Path) -> dict[str, str]:
    """An environment whose ``git`` echoes ``--path-format=...`` back, like git < 2.31."""
    real_git = subprocess.run(
        ["bash", "-c", "command -v git"],
        capture_output=True,
        text=True,
        check=True,
        timeout=_SHELL_TIMEOUT,
    ).stdout.strip()
    fake_bin = tmp_path / "fakebin"
    fake_bin.mkdir()
    fake = fake_bin / "git"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        'for arg in "$@"; do\n'
        '    if [[ "$arg" == --path-format=* ]]; then echo "$arg"; exit 0; fi\n'
        "done\n"
        f'exec "{real_git}" "$@"\n'
    )
    fake.chmod(0o755)
    return {**os.environ, "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"}


class TestUntrustworthyCommonDir:
    """An answer that is not one absolute existing directory falls back to the plan dir."""

    def test_old_git_echoing_the_option_falls_back_to_plan_dir_lock(
        self, linked: Path, old_git_env: dict[str, str]
    ) -> None:
        """git < 2.31 echoes the option back with exit 0; the scaffold still succeeds."""
        result = _run(linked, "old-git", env=old_git_env)

        assert result.returncode == 0, result.stderr
        assert list((linked / "CLAUDE" / "Plan").glob("00209-old-git"))
        assert not (linked / "CLAUDE" / "Plan" / _PLAN_DIR_LOCK).exists()

    def test_fallback_lock_is_the_plan_dir_lock(
        self, linked: Path, old_git_env: dict[str, str]
    ) -> None:
        """When the fallback is in force, a held plan-dir lock is what blocks."""
        (linked / "CLAUDE" / "Plan" / _PLAN_DIR_LOCK).mkdir()

        result = _run(linked, "blocked-by-plan-dir", env=old_git_env)

        assert result.returncode != 0
        assert _PLAN_DIR_LOCK in result.stderr
