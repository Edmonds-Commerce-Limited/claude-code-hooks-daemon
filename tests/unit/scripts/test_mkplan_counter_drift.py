"""``mkplan.bash`` advances a stale plan counter instead of refusing (N371).

The counter lives in each clone's local git config, so a clone whose counter was
never advanced (a second clone, a fresh pull of plans made elsewhere) reads a
number below the highest plan folder on disk. The disk is the truth about which
numbers are taken, so the scaffolder moves the counter up to it and allocates the
number after it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout

_REPO_ROOT = Path(__file__).resolve().parents[3]
_TEMPLATE = (
    _REPO_ROOT / "src" / "claude_code_hooks_daemon" / "install" / "templates" / "mkplan.bash"
)
_PLAN_ASSETS = _REPO_ROOT / "CLAUDE" / "Plan"
_COUNTER_KEY = "hooksdaemon.latestPlanNumber"
_SHELL_TIMEOUT = Timeout.QA_TEST_TIMEOUT


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
def repo(tmp_path: Path) -> Path:
    """A repo carrying the scaffolder, with the counter at 208."""
    root = tmp_path / "clone"
    plan_dir = root / "CLAUDE" / "Plan"
    plan_dir.mkdir(parents=True)
    script = plan_dir / "mkplan.bash"
    script.write_bytes(_TEMPLATE.read_bytes())
    script.chmod(0o755)
    for asset in _PLAN_ASSETS.glob("_*"):
        if asset.is_file():
            (plan_dir / asset.name).write_bytes(asset.read_bytes())
    _git(root, "init", "--quiet")
    _git(root, "config", "user.email", "mkplan-tester@test.invalid")
    _git(root, "config", "user.name", "Mkplan Tester")
    _git(root, "config", "--local", _COUNTER_KEY, "208")
    return root


def _run(repo: Path, name: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(repo / "CLAUDE" / "Plan" / "mkplan.bash"), name],
        capture_output=True,
        text=True,
        check=False,
        cwd=repo,
        timeout=_SHELL_TIMEOUT,
    )


class TestStaleCounterIsAdvanced:
    """A counter behind the disk is advanced, never reused and never fatal."""

    def test_active_folder_ahead_of_counter(self, repo: Path) -> None:
        (repo / "CLAUDE" / "Plan" / "00212-pulled-elsewhere").mkdir()

        result = _run(repo, "next-one")

        assert result.returncode == 0, result.stderr
        assert (repo / "CLAUDE" / "Plan" / "00213-next-one").is_dir()
        assert _git(repo, "config", "--local", _COUNTER_KEY) == "213"
        assert "208" in result.stderr and "212" in result.stderr

    def test_archived_folder_ahead_of_counter(self, repo: Path) -> None:
        (repo / "CLAUDE" / "Plan" / "Completed" / "00250-archived").mkdir(parents=True)

        result = _run(repo, "after-archive")

        assert result.returncode == 0, result.stderr
        assert (repo / "CLAUDE" / "Plan" / "00251-after-archive").is_dir()
        assert _git(repo, "config", "--local", _COUNTER_KEY) == "251"

    def test_a_fresh_clone_far_behind_the_disk_works_first_time(self, repo: Path) -> None:
        """GitHub #72: counter 414 against 487 plans on disk, no hand reconcile."""
        _git(repo, "config", "--local", _COUNTER_KEY, "414")
        (repo / "CLAUDE" / "Plan" / "Completed" / "00487-latest").mkdir(parents=True)

        first = _run(repo, "first-try")

        assert first.returncode == 0, first.stderr
        assert (repo / "CLAUDE" / "Plan" / "00488-first-try").is_dir()
        assert _git(repo, "config", "--local", _COUNTER_KEY) == "488"

    def test_the_counter_only_moves_forward(self, repo: Path) -> None:
        (repo / "CLAUDE" / "Plan" / "00212-pulled-elsewhere").mkdir()
        seen: list[int] = []
        for name in ("one", "two", "three"):
            assert _run(repo, name).returncode == 0
            seen.append(int(_git(repo, "config", "--local", _COUNTER_KEY)))

        assert seen == [213, 214, 215]

    def test_counter_ahead_of_disk_is_still_trusted(self, repo: Path) -> None:
        result = _run(repo, "counter-leads")

        assert result.returncode == 0, result.stderr
        assert (repo / "CLAUDE" / "Plan" / "00209-counter-leads").is_dir()
        assert "behind" not in result.stderr
