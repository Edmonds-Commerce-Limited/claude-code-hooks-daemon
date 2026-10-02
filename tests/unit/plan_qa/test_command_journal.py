"""Tests for reading the journal entries a command writes before it commits (N317)."""

from pathlib import Path

import pytest

from claude_code_hooks_daemon.plan_qa.command_journal import command_journal_plans
from claude_code_hooks_daemon.utils.git_commit_parsing import read_commit_form

_PLAN_DIR_REL = "CLAUDE/Plan"
_JOURNAL = "JOURNAL"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    project = tmp_path / "repo"
    (project / "CLAUDE/Plan/00470-widget").mkdir(parents=True)
    (project / "CLAUDE/Plan/00471-gadget").mkdir(parents=True)
    (project / "CLAUDE/Plan/mkplan.bash").write_text("#!/bin/bash\n")
    return project


def _plans(command: str, root: Path, cwd: Path | None = None) -> frozenset[int]:
    return command_journal_plans(
        command, read_commit_form(command), cwd or root, root, _PLAN_DIR_REL, _JOURNAL
    )


_LIVE = (
    'CLAUDE/Plan/mkplan.bash --journal 470 finding body.md --title "x" '
    "&& git add CLAUDE/Plan/00470-widget && git commit -m 'Plan 00470: x'"
)


class TestTheLiveShape:
    def test_mkplan_then_add_of_the_plan_folder_then_commit(self, root: Path) -> None:
        assert _plans(_LIVE, root) == {470}

    def test_a_padded_plan_number(self, root: Path) -> None:
        command = _LIVE.replace("--journal 470", "--journal 00470")
        assert _plans(command, root) == {470}

    def test_an_add_of_the_journal_directory(self, root: Path) -> None:
        command = _LIVE.replace("00470-widget", "00470-widget/JOURNAL")
        assert _plans(command, root) == {470}

    def test_add_all_and_dot(self, root: Path) -> None:
        for spelling in ("-A", "--all", "."):
            assert _plans(_LIVE.replace("CLAUDE/Plan/00470-widget", spelling), root) == {470}

    def test_an_absolute_and_a_dotted_spelling_of_the_script(self, root: Path) -> None:
        for spelling in (
            str(root / "CLAUDE/Plan/mkplan.bash"),
            "./CLAUDE/../CLAUDE/Plan/mkplan.bash",
        ):
            command = _LIVE.replace("CLAUDE/Plan/mkplan.bash", spelling)
            assert _plans(command, root) == {470}

    def test_a_relative_script_run_from_the_plan_directory(self, root: Path) -> None:
        command = (
            "./mkplan.bash --journal 470 finding b.md && git add 00470-widget && git commit -m x"
        )
        assert _plans(command, root, root / "CLAUDE/Plan") == {470}


class TestWhatDoesNotCount:
    def test_a_different_plan_is_not_covered(self, root: Path) -> None:
        assert _plans(_LIVE.replace("00470-widget", "00471-gadget"), root) == frozenset()

    def test_mkplan_for_another_plan_than_the_add(self, root: Path) -> None:
        assert _plans(_LIVE.replace("--journal 470", "--journal 471"), root) == frozenset()

    def test_no_covering_add(self, root: Path) -> None:
        command = "CLAUDE/Plan/mkplan.bash --journal 470 finding b.md && git commit -m x"
        assert _plans(command, root) == frozenset()

    def test_an_add_of_something_else(self, root: Path) -> None:
        assert _plans(_LIVE.replace("CLAUDE/Plan/00470-widget", "src"), root) == frozenset()

    def test_a_shell_resolved_pathspec(self, root: Path) -> None:
        command = _LIVE.replace("CLAUDE/Plan/00470-widget", '"$D"')
        assert _plans(command, root) == frozenset()

    def test_mkplan_after_the_commit(self, root: Path) -> None:
        command = (
            "git add CLAUDE/Plan/00470-widget && git commit -m x && "
            "CLAUDE/Plan/mkplan.bash --journal 470 finding b.md"
        )
        assert _plans(command, root) == frozenset()

    def test_mkplan_after_the_add(self, root: Path) -> None:
        command = (
            "git add CLAUDE/Plan/00470-widget && "
            "CLAUDE/Plan/mkplan.bash --journal 470 finding b.md && git commit -m x"
        )
        assert _plans(command, root) == frozenset()

    def test_another_script_with_the_same_name(self, root: Path) -> None:
        command = _LIVE.replace("CLAUDE/Plan/mkplan.bash", "/tmp/elsewhere/mkplan.bash")
        assert _plans(command, root) == frozenset()

    def test_mkplan_creating_a_plan_is_not_a_journal_entry(self, root: Path) -> None:
        command = "CLAUDE/Plan/mkplan.bash widget && git add . && git commit -m x"
        assert _plans(command, root) == frozenset()

    def test_a_non_numeric_plan_argument(self, root: Path) -> None:
        assert _plans(_LIVE.replace("--journal 470", "--journal abc"), root) == frozenset()

    def test_no_commit_at_all(self, root: Path) -> None:
        command = "CLAUDE/Plan/mkplan.bash --journal 470 finding b.md && git add -A"
        assert _plans(command, root) == frozenset()

    def test_a_plan_with_no_folder(self, root: Path) -> None:
        assert _plans(_LIVE.replace("470", "999"), root) == frozenset()

    def test_an_add_that_moves_git_elsewhere(self, root: Path) -> None:
        command = _LIVE.replace("git add", "git -C /other add")
        assert _plans(command, root) == frozenset()

    def test_update_only_add_does_not_stage_a_new_day_file(self, root: Path) -> None:
        assert _plans(_LIVE.replace("CLAUDE/Plan/00470-widget", "-u"), root) == frozenset()

    def test_a_script_naming_the_plan_dir_text_in_a_message_only(self, root: Path) -> None:
        command = "git commit -m 'mkplan.bash --journal 470 x'"
        assert _plans(command, root) == frozenset()


class TestDirectoryTracking:
    def test_a_cd_before_the_add_moves_it_away_from_the_journal(self, root: Path) -> None:
        (root / "src").mkdir()
        command = _LIVE.replace("&& git add CLAUDE/Plan/00470-widget", "&& cd src && git add .")
        assert _plans(command, root) == frozenset()

    def test_a_cd_into_the_plan_directory_before_the_script(self, root: Path) -> None:
        command = (
            "cd CLAUDE/Plan && ./mkplan.bash --journal 470 finding b.md "
            "&& git add 00470-widget && git commit -m x"
        )
        assert _plans(command, root) == {470}

    def test_a_cd_that_lands_the_add_on_the_journal(self, root: Path) -> None:
        command = (
            "CLAUDE/Plan/mkplan.bash --journal 470 finding b.md "
            "&& cd CLAUDE/Plan && git add 00470-widget && git commit -m x"
        )
        assert _plans(command, root) == {470}

    def test_git_dash_c_moves_the_add(self, root: Path) -> None:
        command = _LIVE.replace("git add", "git -C src add")
        assert _plans(command, root) == frozenset()

    def test_a_cd_that_may_not_take_effect_is_not_trusted(self, root: Path) -> None:
        command = _LIVE.replace("&& git add CLAUDE/Plan/00470-widget", "; cd src; git add .")
        assert _plans(command, root) == frozenset()


class TestTheCommitOwnForm:
    def test_a_commit_pathspec_that_leaves_the_journal_out(self, root: Path) -> None:
        command = _LIVE.replace("git commit", "git commit CLAUDE/Plan/00470-widget/PLAN.md")
        assert _plans(command, root) == frozenset()

    def test_a_commit_pathspec_that_covers_the_journal(self, root: Path) -> None:
        command = _LIVE.replace("git commit", "git commit CLAUDE/Plan/00470-widget")
        assert _plans(command, root) == {470}

    def test_an_include_commit_keeps_the_index(self, root: Path) -> None:
        command = _LIVE.replace("git commit", "git commit -i CLAUDE/Plan/00470-widget/PLAN.md")
        assert _plans(command, root) == {470}


class TestStagingFlagsAndSequencing:
    @pytest.mark.parametrize("flag", ["-n", "--dry-run", "-p", "--patch", "-i", "--interactive"])
    def test_an_add_that_stages_nothing(self, root: Path, flag: str) -> None:
        assert _plans(_LIVE.replace("git add", f"git add {flag}"), root) == frozenset()

    def test_semicolon_after_the_script_does_not_count(self, root: Path) -> None:
        assert _plans(_LIVE.replace(" && git add", "; git add", 1), root) == frozenset()

    def test_semicolon_between_the_add_and_the_commit_does_not_count(self, root: Path) -> None:
        assert _plans(_LIVE.replace(" && git commit", "; git commit"), root) == frozenset()

    def test_a_dotted_spelling_of_the_add_path(self, root: Path) -> None:
        command = _LIVE.replace(
            "git add CLAUDE/Plan/00470-widget", "git add ./CLAUDE/x/../Plan/00470-widget"
        )
        assert _plans(command, root) == {470}
