"""``mkplan.bash`` states the plan-folder count for the dedupe dispatch.

Plan 00434, from ledger 00422 N13. The dedupe scout is asked to reconcile its
reported ``Checked N live plans.`` against its own enumerated list — which the
reader that miscounted cannot do. The count has to come from outside the agent,
and the scaffolder is where the caller is already told to dispatch it.

Driven as a real ``bash`` subprocess against a real temporary git repository:
the number has to be measured from the filesystem the script sees, and a
Python-level assertion could not observe that.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout

_SHELL_TIMEOUT = Timeout.VALIDATION_CHECK

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO_ROOT / "CLAUDE" / "Plan" / "mkplan.bash"
_JOURNAL_TEMPLATE = _REPO_ROOT / "CLAUDE" / "Plan" / "_JOURNAL_TEMPLATE_.md"

#: The claim under test is a NUMBER, so the assertion reads the number rather
#: than the sentence around it.
_STATED_COUNT = re.compile(r"there are (\d+) plan folders")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
        timeout=_SHELL_TIMEOUT,
    )


@pytest.fixture
def plan_repo(tmp_path: Path) -> Path:
    """A temporary git repo carrying the real scaffolder."""
    plan_dir = tmp_path / "CLAUDE" / "Plan"
    plan_dir.mkdir(parents=True)
    script_target = plan_dir / _SCRIPT.name
    script_target.write_bytes(_SCRIPT.read_bytes())
    script_target.chmod(0o755)
    (plan_dir / _JOURNAL_TEMPLATE.name).write_bytes(_JOURNAL_TEMPLATE.read_bytes())

    _git(tmp_path, "init", "--quiet")
    _git(tmp_path, "config", "user.email", "mkplan-tester@test.invalid")
    _git(tmp_path, "config", "user.name", "Mkplan Tester")
    return tmp_path


def _make_plan(repo: Path, number: str, slug: str) -> None:
    folder = repo / "CLAUDE" / "Plan" / f"{number}-{slug}"
    folder.mkdir(parents=True)
    (folder / "PLAN.md").write_text(f"# Plan {number}: {slug}\n")


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(repo / "CLAUDE" / "Plan" / "mkplan.bash"), *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=repo,
        timeout=_SHELL_TIMEOUT,
    )


def _stated_count(stderr: str) -> int:
    match = _STATED_COUNT.search(stderr)
    assert match is not None, f"the scout reminder states no folder count:\n{stderr}"
    return int(match.group(1))


class TestStatedFolderCount:
    def test_counts_the_existing_folders_plus_the_new_one(self, plan_repo: Path) -> None:
        for index, slug in enumerate(("alpha", "beta", "gamma"), start=1):
            _make_plan(plan_repo, f"0000{index}", slug)

        result = _run(plan_repo, "delta")

        assert result.returncode == 0, result.stderr
        # The scout enumerates the tree AFTER this folder exists, so the number
        # it can agree with includes it: three existing plus this one.
        assert _stated_count(result.stderr) == 4

    def test_the_count_tracks_the_tree_rather_than_a_constant(self, plan_repo: Path) -> None:
        """Control: a hard-coded number would satisfy the test above alone."""
        runs = [_run(plan_repo, slug) for slug in ("first", "second", "third")]

        for result in runs:
            assert result.returncode == 0, result.stderr
        assert [_stated_count(result.stderr) for result in runs] == [1, 2, 3]

    def test_ignores_the_archive_directories(self, plan_repo: Path) -> None:
        """Archived plans are not what the scout enumerates in step 2."""
        _make_plan(plan_repo, "00001", "live-one")
        archived = plan_repo / "CLAUDE" / "Plan" / "Completed" / "00002-archived"
        archived.mkdir(parents=True)
        (archived / "PLAN.md").write_text("# Plan 00002: archived\n")

        result = _run(plan_repo, "new-work")

        assert result.returncode == 0, result.stderr
        assert _stated_count(result.stderr) == 2

    def test_names_the_sentence_the_report_must_carry(self, plan_repo: Path) -> None:
        """The number is only useful beside what to compare it against."""
        result = _run(plan_repo, "solo")

        assert result.returncode == 0, result.stderr
        assert "Checked N live plans." in result.stderr
