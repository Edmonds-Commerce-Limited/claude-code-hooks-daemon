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


def _make_plan_folder(repo: Path, name: str, parent: str = "") -> Path:
    folder = repo / "CLAUDE" / "Plan" / parent / name
    folder.mkdir(parents=True)
    (folder / "PLAN.md").write_text(f"# Plan {name}\n")
    return folder


def _entries_in(folder: Path) -> list[Path]:
    journal = folder / "JOURNAL"
    return sorted(journal.rglob("*.md")) if journal.exists() else []


class TestJournalFolderNameSlugs:
    """The slug accepts real folder names; the existing directory is the gate."""

    @pytest.mark.parametrize(
        "name",
        ["00103-v3.9.1-venv-resolution-failfast", "00104-3d-render", "00105-a_b+c"],
    )
    def test_dotted_and_digit_led_slugs_are_accepted(self, plan_repo: Path, name: str) -> None:
        folder = _make_plan_folder(plan_repo, name)

        result = _run(plan_repo, "--journal", name, "finding", "body.txt")

        assert result.returncode == 0, result.stderr
        assert len(_entries_in(folder)) == 1

    def test_prefix_slug_is_refused_when_only_longer_name_exists(self, plan_repo: Path) -> None:
        folder = _make_plan_folder(plan_repo, "00050-ab")

        result = _run(plan_repo, "--journal", "00050-a", "finding", "body.txt")

        assert result.returncode != 0
        assert _entries_in(folder) == []

    def test_slug_picks_the_right_folder_among_duplicate_numbers(self, plan_repo: Path) -> None:
        first = _make_plan_folder(plan_repo, "00060-first")
        second = _make_plan_folder(plan_repo, "00060-second", "Completed")

        result = _run(plan_repo, "--journal", "00060-second", "finding", "body.txt")

        assert result.returncode == 0, result.stderr
        assert len(_entries_in(second)) == 1
        assert _entries_in(first) == []

    def test_bare_number_with_duplicate_numbers_is_still_ambiguous(self, plan_repo: Path) -> None:
        first = _make_plan_folder(plan_repo, "00060-first")
        second = _make_plan_folder(plan_repo, "00060-second", "Completed")

        result = _run(plan_repo, "--journal", "60", "finding", "body.txt")

        assert result.returncode != 0
        assert _entries_in(first) == [] and _entries_in(second) == []

    @pytest.mark.parametrize(
        "argument",
        [
            "00042-",
            "00042-../sample-plan",
            "00042-sample-plan/../x",
            "00042-sample*",
            "00042-sampl?-plan",
            "00042-[s]ample-plan",
            "00042-.hidden",
            "00042--flag",
            "00042-a..b",
            "00042-sample plan",
            "/abs/00042-sample-plan",
            "00042-sample-plan//",
            "00042//sample-plan",
        ],
    )
    def test_unsafe_arguments_are_refused_and_write_nothing(
        self, plan_repo: Path, argument: str
    ) -> None:
        result = _run(plan_repo, "--journal", argument, "finding", "body.txt")

        assert result.returncode != 0
        assert _entries(plan_repo) == []


class TestHelpDerivedFromDefinitions:
    """The help text and the validators come from one definition each."""

    @staticmethod
    def _script_categories() -> list[str]:
        text = _SCRIPT.read_text()
        marker = "readonly JOURNAL_CATEGORIES=("
        start = text.index(marker) + len(marker)
        return text[start : text.index(")", start)].split()

    def test_help_category_list_equals_the_array(self, plan_repo: Path) -> None:
        categories = self._script_categories()
        flat = " ".join(_run(plan_repo, "--journal").stderr.split())

        assert f"One of: {', '.join(categories)}." in flat
        assert "<" + "|".join(categories) + ">" in flat

    def test_help_ref_forms_are_accepted_by_the_ref_pattern(self, plan_repo: Path) -> None:
        flat = " ".join(_run(plan_repo, "--journal").stderr.split())
        assert "HH:MM" in flat and "YY-MM-DD/HH:MM" in flat

        for form in ("HH:MM", "YY-MM-DD/HH:MM"):
            ref = form
            for token in ("HH", "MM", "YY", "DD"):
                ref = ref.replace(token, "11")
            result = _run(plan_repo, "--journal", "42", "correction", "body.txt", "--ref", ref)

            assert "needs --ref" not in result.stderr, (form, result.stderr)
            assert "names no entry" in result.stderr, (form, result.stderr)

    @pytest.mark.parametrize("ref", ["1:1", "11-11/11:11", "11:11:11", "aa:bb"])
    def test_malformed_refs_are_refused_by_the_pattern(self, plan_repo: Path, ref: str) -> None:
        result = _run(plan_repo, "--journal", "42", "correction", "body.txt", "--ref", ref)

        assert "needs --ref" in result.stderr


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
