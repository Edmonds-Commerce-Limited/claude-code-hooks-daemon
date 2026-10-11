"""``mkplan.bash`` and the daemon agree on the highest plan number on disk (N371).

Both answer "which plan numbers are taken?" and a disagreement means one of them
hands out a number the other considers free. The single rule they share: a
numbered plan folder (``NNNNN-name``) holds its number and is not searched; every
other folder is an organisational subfolder and is searched at any depth.

Each case builds one fixture tree and runs both implementations against it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.handlers.utils.plan_numbering import highest_plan_number

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
    """A repo carrying the scaffolder with its counter at 0, so the disk decides."""
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
    _git(root, "config", "--local", _COUNTER_KEY, "0")
    return root


def _script_allocation(repo: Path) -> int:
    """The number ``mkplan.bash`` allocates against the fixture tree."""
    result = subprocess.run(
        [str(repo / "CLAUDE" / "Plan" / "mkplan.bash"), "probe"],
        capture_output=True,
        text=True,
        check=False,
        cwd=repo,
        timeout=_SHELL_TIMEOUT,
    )
    assert result.returncode == 0, result.stderr
    return int(_git(repo, "config", "--local", _COUNTER_KEY))


@pytest.mark.parametrize(
    ("folders", "expected_highest"),
    [
        pytest.param(["Completed/2025/00300-deep"], 300, id="year-folder-under-completed"),
        pytest.param(["Completed/2025/q1/00310-deeper"], 310, id="three-levels-down"),
        pytest.param(["Completed/00250-shallow", "00100-active"], 250, id="one-level-down"),
        pytest.param([".hidden/00320-dot-folder"], 320, id="dot-prefixed-subfolder"),
        pytest.param(["00050-plan/00999-inside-a-plan"], 50, id="numbered-folder-is-not-searched"),
        pytest.param(["2026-06-19/00400-x", "2026-06-19-notes"], 400, id="date-folder-is-searched"),
        pytest.param([], 0, id="empty-tree"),
    ],
)
def test_script_and_daemon_find_the_same_highest(
    repo: Path, folders: list[str], expected_highest: int
) -> None:
    plan_dir = repo / "CLAUDE" / "Plan"
    for folder in folders:
        (plan_dir / folder).mkdir(parents=True)

    daemon_highest = highest_plan_number(plan_dir)
    script_allocated = _script_allocation(repo)

    assert daemon_highest == expected_highest
    assert script_allocated == daemon_highest + 1
