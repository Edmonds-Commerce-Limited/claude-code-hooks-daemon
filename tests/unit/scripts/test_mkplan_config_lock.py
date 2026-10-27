"""``mkplan.bash`` tolerates brief contention on ``.git/config.lock``.

Git does not retry its config lock, so a concurrent git process makes a single
counter write fail. The script must wait it out, and report a lock that never
clears by name.
"""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout

_SHELL_TIMEOUT = Timeout.QA_TEST_TIMEOUT

_REPO_ROOT = Path(__file__).resolve().parents[3]
_TEMPLATE = (
    _REPO_ROOT / "src" / "claude_code_hooks_daemon" / "install" / "templates" / "mkplan.bash"
)
_PLAN_ASSETS = _REPO_ROOT / "CLAUDE" / "Plan"
_COUNTER_KEY = "hooksdaemon.latestPlanNumber"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
        timeout=_SHELL_TIMEOUT,
    )
    return result.stdout.strip()


def _run(repo: Path, name: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(repo / "CLAUDE" / "Plan" / "mkplan.bash"), name],
        capture_output=True,
        text=True,
        check=False,
        cwd=repo,
        timeout=_SHELL_TIMEOUT,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A committed repo carrying the scaffolder, with the counter at 208."""
    root = tmp_path / "repo"
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
    _git(root, "add", "-A")
    _git(root, "commit", "--quiet", "-m", "seed")
    _git(root, "config", "--local", _COUNTER_KEY, "208")
    return root


def test_brief_config_lock_is_waited_out(repo: Path) -> None:
    lock = repo / ".git" / "config.lock"
    lock.touch()
    timer = threading.Timer(0.3, lock.unlink)
    timer.start()
    try:
        result = _run(repo, "contended-plan")
    finally:
        timer.join()

    assert result.returncode == 0, result.stderr
    assert _git(repo, "config", "--local", "--get", _COUNTER_KEY) == "209"


def test_persistent_config_lock_fails_with_a_clear_message(repo: Path) -> None:
    (repo / ".git" / "config.lock").touch()

    result = _run(repo, "stuck-plan")

    assert result.returncode != 0
    assert "git config lock" in result.stderr
    assert _COUNTER_KEY in result.stderr
