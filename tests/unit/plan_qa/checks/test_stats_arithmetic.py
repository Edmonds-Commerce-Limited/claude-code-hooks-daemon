"""Tests for ``plan-stats-arithmetic`` (Plan 00466 N13).

The plan index's reconciliation bullet states several figures and closes with a
self-check carrying a tick. The check lived only in ``check_repo_hygiene.py``,
which runs in full QA alone, so an index whose closing line disagreed with the
bullet above it was committed and pushed with every fast gate green. It now
lives here, once, and repo hygiene calls it.

**EDIT advises, never blocks.** Updating the bullet takes more than one edit,
and the index is inconsistent between them; a block there would deny the first
half of a correct update. The commit is where the figures must agree.
"""

from pathlib import Path

import pytest

from claude_code_hooks_daemon.plan_qa.checks.stats_arithmetic import (
    CHECK_ID,
    CHECKS,
    stats_arithmetic_disagreements,
)
from claude_code_hooks_daemon.plan_qa.readme_index import ReadmeIndex
from claude_code_hooks_daemon.plan_qa.types import CheckContext, CheckSpec, Level, Stage

_ROOT = Path("/repo")
_PLAN_DIR_REL = "CLAUDE/Plan"


def _index(
    *,
    folders: str = "16 + 340 + 13 = **369 folders**",
    distinct: int = 366,
    folderless: int = 13,
    allocated: int = 379,
    closing: str = "366 + 13 = 379. ✅",
    listed: int = 13,
) -> str:
    """A plan index carrying the reconciliation bullet; the closing sum is line 9."""
    numbers = ", ".join(f"{900 + i:05d}" for i in range(listed))
    return (
        "# Plans Index\n\n## Plan Statistics\n\n"
        f"- **Folder-to-number reconciliation**: {folders}, spanning\n"
        f"  **{distinct} distinct plan numbers** — three numbers carry two folders\n"
        f"  each. That leaves **{folderless}** of the {allocated} allocated numbers\n"
        f"  with no folder: {numbers} — abandoned drafts.\n"
        f"  {closing}\n"
    )


_FOLDER_SUM_LINE = 5
_FOLDERLESS_LINE = 7
_CLOSING_LINE = 9

#: The N13 incident: bullets updated to 455/468, closing line left at 454 + 13 = 467.
_INCIDENT = _index(distinct=455, allocated=468, closing="454 + 13 = 467. ✅")


class TestDisagreements:
    def test_a_consistent_bullet_has_none(self) -> None:
        assert stats_arithmetic_disagreements(_index()) == ()

    def test_an_index_without_the_bullet_has_none(self) -> None:
        assert stats_arithmetic_disagreements("# Plans Index\n\n- **Active**: 4\n") == ()

    def test_the_incident_names_the_closing_line(self) -> None:
        found = stats_arithmetic_disagreements(_INCIDENT)
        assert found, "a closing sum contradicting its bullet must be reported"
        assert {item.line for item in found} == {_CLOSING_LINE}
        assert all(f"line {_CLOSING_LINE}" in item.message for item in found)
        joined = " ".join(item.message for item in found)
        assert "455" in joined and "468" in joined

    def test_true_arithmetic_with_contradicted_operands_is_still_reported(self) -> None:
        """364 + 13 really is 377; what is wrong is that it disagrees with 365 and 378."""
        text = _index(distinct=365, allocated=378, closing="364 + 13 = 377. ✅")
        assert stats_arithmetic_disagreements(text)

    def test_a_closing_sum_that_does_not_add_up(self) -> None:
        found = stats_arithmetic_disagreements(_index(closing="366 + 13 = 380. ✅"))
        assert any("does not add up" in item.message for item in found)

    def test_a_folder_sum_that_does_not_add_up_names_its_line(self) -> None:
        found = stats_arithmetic_disagreements(_index(folders="16 + 340 + 13 = **400 folders**"))
        assert [item.line for item in found] == [_FOLDER_SUM_LINE]

    def test_a_folderless_count_disagreeing_with_its_list(self) -> None:
        found = stats_arithmetic_disagreements(_index(folderless=13, listed=11))
        assert any(item.line == _FOLDERLESS_LINE for item in found)
        assert any("lists 11" in item.message for item in found)

    def test_thousands_separators_are_read(self) -> None:
        text = _index(
            folders="16 + 1,340 + 13 = **1,369 folders**",
            distinct=1366,
            allocated=1379,
            closing="1366 + 13 = 1379. ✅",
        )
        assert stats_arithmetic_disagreements(text) == ()


_REPO_ROOT = Path(__file__).resolve().parents[4]
#: A fragment of the folderless-clause pattern that only an implementation carries.
_IMPLEMENTATION_MARKER = r"allocated\s+numbers\s+with\s+no\s+folder"


def test_there_is_exactly_one_implementation() -> None:
    """Repo hygiene calls this module; neither may grow a second copy."""
    carriers = sorted(
        str(path.relative_to(_REPO_ROOT))
        for root in ("src", "scripts")
        for path in (_REPO_ROOT / root).rglob("*.py")
        if _IMPLEMENTATION_MARKER in path.read_text(encoding="utf-8")
    )
    assert carriers == ["src/claude_code_hooks_daemon/plan_qa/checks/stats_arithmetic.py"]


def _spec(stage: Stage) -> CheckSpec:
    return next(spec for spec in CHECKS if spec.stage is stage)


def _tree_context(text: str | None) -> CheckContext:
    return CheckContext(
        project_root=_ROOT,
        plan_dir_rel=_PLAN_DIR_REL,
        readme=None if text is None else ReadmeIndex.parse(text),
    )


class TestRegistration:
    def test_registered_on_edit_commit_and_sweep(self) -> None:
        assert {spec.stage for spec in CHECKS} == {Stage.EDIT, Stage.COMMIT, Stage.SWEEP}
        assert all(spec.check_id == CHECK_ID == "plan-stats-arithmetic" for spec in CHECKS)

    def test_the_catalogue_carries_every_registration(self) -> None:
        from claude_code_hooks_daemon.plan_qa.checks import all_checks

        registered = {spec.stage for spec in all_checks() if spec.check_id == CHECK_ID}
        assert registered == {Stage.EDIT, Stage.COMMIT, Stage.SWEEP}


class TestSweep:
    def test_reports_a_disagreement_as_blocking(self) -> None:
        findings = _spec(Stage.SWEEP).run(_tree_context(_INCIDENT))
        assert findings
        assert all(finding.level is Level.BLOCK for finding in findings)
        assert all(finding.path == f"{_PLAN_DIR_REL}/README.md" for finding in findings)
        assert all(f"line {_CLOSING_LINE}" in finding.message for finding in findings)

    def test_silent_on_a_consistent_index(self) -> None:
        assert _spec(Stage.SWEEP).run(_tree_context(_index())) == []

    def test_silent_without_a_readme(self) -> None:
        assert _spec(Stage.SWEEP).run(_tree_context(None)) == []


class TestEdit:
    @staticmethod
    def _edit_context(file_path: Path) -> CheckContext:
        return CheckContext(
            project_root=_ROOT,
            plan_dir_rel=_PLAN_DIR_REL,
            file_path=file_path,
            file_content=_INCIDENT,
        )

    def test_advises_on_the_plan_index(self) -> None:
        context = self._edit_context(_ROOT / _PLAN_DIR_REL / "README.md")
        findings = _spec(Stage.EDIT).run(context)
        assert findings
        assert all(finding.level is Level.ADVISE for finding in findings)

    @pytest.mark.parametrize("rel", ["00001-x/PLAN.md", "00001-x/NOTES.md"])
    def test_ignores_a_file_that_is_not_an_index(self, rel: str) -> None:
        context = self._edit_context(_ROOT / _PLAN_DIR_REL / rel)
        assert _spec(Stage.EDIT).run(context) == []
