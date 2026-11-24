"""``mkplan.bash --journal`` ergonomics (Plan 00636 Tasks 3.1 and 3.2).

3.1: the plan may be named by its full folder name as well as its number.
3.2: the one-line synopsis names the valid categories and the ``--ref`` format,
so a wrong call is corrected from the usage line alone.

Exercised as a real ``bash`` subprocess against a temporary git repository.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO_ROOT / "CLAUDE" / "Plan" / "mkplan.bash"
_JOURNAL_TEMPLATE = _REPO_ROOT / "CLAUDE" / "Plan" / "_JOURNAL_TEMPLATE_.md"
_CATEGORIES = ("action", "finding", "decision", "thought", "blocker", "handoff", "correction")


@pytest.fixture
def plan_repo(tmp_path: Path) -> Path:
    """A temporary git repo with the real scaffolder and journal template."""
    plan_dir = tmp_path / "CLAUDE" / "Plan"
    plan_dir.mkdir(parents=True)
    target = plan_dir / _SCRIPT.name
    target.write_bytes(_SCRIPT.read_bytes())
    target.chmod(0o755)
    (plan_dir / _JOURNAL_TEMPLATE.name).write_bytes(_JOURNAL_TEMPLATE.read_bytes())
    for args in (
        ("init", "--quiet"),
        ("config", "user.email", "t@test.invalid"),
        ("config", "user.name", "Tester"),
    ):
        subprocess.run(
            ["git", "-C", str(tmp_path), *args],
            check=True,
            capture_output=True,
            timeout=Timeout.VALIDATION_CHECK,
        )
    folder = plan_dir / "00042-sample-plan"
    folder.mkdir()
    (folder / "PLAN.md").write_text("# Plan 00042: sample plan\n")
    (tmp_path / "body.txt").write_text("Something worth logging.\n")
    return tmp_path


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(repo / "CLAUDE" / "Plan" / "mkplan.bash"), *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=repo,
        env=dict(os.environ),
        timeout=Timeout.VALIDATION_CHECK,
    )


def _entries(repo: Path) -> list[Path]:
    journal = repo / "CLAUDE" / "Plan" / "00042-sample-plan" / "JOURNAL"
    return sorted(journal.rglob("*.md")) if journal.exists() else []


class TestJournalAcceptsFolderName:
    """Task 3.1."""

    def test_full_folder_name_is_accepted(self, plan_repo: Path) -> None:
        result = _run(plan_repo, "--journal", "00042-sample-plan", "finding", "body.txt")

        assert result.returncode == 0, result.stderr
        assert len(_entries(plan_repo)) == 1

    def test_unpadded_number_with_slug_is_accepted(self, plan_repo: Path) -> None:
        result = _run(plan_repo, "--journal", "42-sample-plan", "finding", "body.txt")

        assert result.returncode == 0, result.stderr
        assert len(_entries(plan_repo)) == 1

    def test_trailing_slash_from_tab_completion_is_accepted(self, plan_repo: Path) -> None:
        result = _run(plan_repo, "--journal", "00042-sample-plan/", "finding", "body.txt")

        assert result.returncode == 0, result.stderr

    def test_wrong_slug_is_refused_and_writes_nothing(self, plan_repo: Path) -> None:
        result = _run(plan_repo, "--journal", "00042-other-name", "finding", "body.txt")

        assert result.returncode != 0
        assert "00042-other-name" in result.stderr
        assert _entries(plan_repo) == []

    @pytest.mark.parametrize("number", ["42", "00042"])
    def test_bare_number_still_works(self, plan_repo: Path, number: str) -> None:
        result = _run(plan_repo, "--journal", number, "finding", "body.txt")

        assert result.returncode == 0, result.stderr
        assert len(_entries(plan_repo)) == 1

    def test_garbage_plan_argument_is_refused(self, plan_repo: Path) -> None:
        result = _run(plan_repo, "--journal", "../00042-sample-plan", "finding", "body.txt")

        assert result.returncode != 0
        assert _entries(plan_repo) == []


class TestSynopsisNamesCategoriesAndRef:
    """Task 3.2: the first Usage line carries the categories and the ref format."""

    @staticmethod
    def _synopsis_lines(stderr: str) -> str:
        lines = stderr.splitlines()
        start = next(i for i, line in enumerate(lines) if "--journal" in line)
        end = next((i for i in range(start + 1, len(lines)) if lines[i].strip() == ""), len(lines))
        return "\n".join(lines[start:end])

    def test_journal_usage_synopsis_lists_every_category(self, plan_repo: Path) -> None:
        result = _run(plan_repo, "--journal")

        assert result.returncode != 0
        synopsis = self._synopsis_lines(result.stderr)
        for category in _CATEGORIES:
            assert category in synopsis

    def test_journal_usage_synopsis_states_the_ref_format(self, plan_repo: Path) -> None:
        result = _run(plan_repo, "--journal")

        synopsis = self._synopsis_lines(result.stderr)
        assert "HH:MM" in synopsis
        assert "YY-MM-DD/HH:MM" in synopsis

    def test_top_level_help_synopsis_lists_categories(self, plan_repo: Path) -> None:
        result = _run(plan_repo, "--help")

        assert result.returncode == 0
        synopsis = self._synopsis_lines(result.stderr)
        assert "correction" in synopsis
        assert "YY-MM-DD/HH:MM" in synopsis
        assert "progress" not in synopsis


class TestExistingInvocationsUnchanged:
    """mkplan.bash is deployed to clients: every existing call shape still works."""

    def test_plan_creation_still_works(self, plan_repo: Path) -> None:
        result = _run(plan_repo, "my new plan")

        assert result.returncode == 0, result.stderr
        assert (plan_repo / "CLAUDE" / "Plan" / "00043-my-new-plan" / "PLAN.md").is_file()

    def test_correction_with_ref_still_works(self, plan_repo: Path) -> None:
        assert _run(plan_repo, "--journal", "42", "finding", "body.txt").returncode == 0
        entry = _entries(plan_repo)[0].read_text()
        stamp = entry.splitlines()[0].split()[1]

        result = _run(plan_repo, "--journal", "42", "correction", "body.txt", "--ref", stamp)

        assert result.returncode == 0, result.stderr

    def test_correction_without_ref_is_still_refused(self, plan_repo: Path) -> None:
        result = _run(plan_repo, "--journal", "42", "correction", "body.txt")

        assert result.returncode != 0
