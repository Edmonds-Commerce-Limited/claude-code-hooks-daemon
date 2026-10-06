"""Tests for the plan fact-check state and diff (Plan 00480 Tasks 4.1/4.2 partial).

The debounced fire records NOTHING about delivery: it stores a "pending
fact-check" record. :func:`deliver_pending` (run on the next hook event) turns
each record into an instruction for the session, once.
"""

import logging
from pathlib import Path

import pytest

from claude_code_hooks_daemon.utils.plan_fact_check import (
    PlanFactCheckState,
    PlanFactCheckStateError,
    deliver_pending,
    plan_folder_match,
    process_quiet_plan,
    snapshot_hash,
    snapshot_plan,
)

FOLDER = "00480-demo"


def _plan(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "CLAUDE" / "Plan" / FOLDER
    for rel, text in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


class TestPlanFolderMatch:
    def test_matches_a_plan_document(self) -> None:
        match = plan_folder_match("/p/CLAUDE/Plan/00480-demo/PLAN.md", "CLAUDE/Plan")
        assert match is not None
        assert match.folder == "00480-demo"
        assert match.plan_root == Path("/p/CLAUDE/Plan/00480-demo")

    def test_matches_a_supporting_document(self) -> None:
        assert plan_folder_match("/p/CLAUDE/Plan/00480-demo/DESIGN.md", "CLAUDE/Plan")

    @pytest.mark.parametrize(
        "path",
        [
            "/p/src/module.py",
            "/p/CLAUDE/Plan/README.md",
            "/p/CLAUDE/Plan/Completed/00001-old/PLAN.md",
            "/p/CLAUDE/Plan/00480-demo/subagent-reports/r.md",
            "/p/CLAUDE/Plan/00480-demo/JOURNAL/26-10-02.md",
            "/p/CLAUDE/Plan/00480-demo/data.json",
        ],
    )
    def test_ignores_everything_else(self, path: str) -> None:
        assert plan_folder_match(path, "CLAUDE/Plan") is None

    def test_honours_a_configured_plan_dir(self) -> None:
        assert plan_folder_match("/p/plans/00001-x/PLAN.md", "plans") is not None
        assert plan_folder_match("/p/CLAUDE/Plan/00001-x/PLAN.md", "plans") is None


class TestSnapshot:
    def test_collects_markdown_and_skips_excluded(self, tmp_path: Path) -> None:
        root = _plan(
            tmp_path,
            {
                "PLAN.md": "a",
                "DESIGN.md": "b",
                "notes.txt": "c",
                "JOURNAL/d.md": "d",
                "subagent-reports/r.md": "e",
            },
        )
        assert snapshot_plan(root) == {"PLAN.md": "a", "DESIGN.md": "b"}

    def test_hash_depends_on_content_and_names(self) -> None:
        assert snapshot_hash({"A.md": "x"}) == snapshot_hash({"A.md": "x"})
        assert snapshot_hash({"A.md": "x"}) != snapshot_hash({"A.md": "y"})
        assert snapshot_hash({"A.md": "x"}) != snapshot_hash({"B.md": "x"})


class TestState:
    def test_nothing_recorded_initially(self, tmp_path: Path) -> None:
        state = PlanFactCheckState(tmp_path / "state")
        assert state.read_checked(FOLDER) is None
        assert state.read_pending(FOLDER) is None

    def test_checked_round_trips(self, tmp_path: Path) -> None:
        state = PlanFactCheckState(tmp_path / "state")
        files = {"PLAN.md": "hello"}
        state.record_checked(FOLDER, files)
        checked = state.read_checked(FOLDER)
        assert checked is not None
        assert checked.content_hash == snapshot_hash(files)
        assert checked.files == files


class TestProcessQuietPlan:
    def test_first_fire_diffs_against_nothing_and_stores_pending(self, tmp_path: Path) -> None:
        root = _plan(tmp_path, {"PLAN.md": "line one\n"})
        state = PlanFactCheckState(tmp_path / "state")
        pending = process_quiet_plan(root, FOLDER, state, trigger_count=3, now=100.0)
        assert pending is not None
        assert "+line one" in pending.diff
        assert pending.trigger_count == 3
        assert pending.content_hash == snapshot_hash({"PLAN.md": "line one\n"})
        assert state.read_pending(FOLDER) == pending

    def test_diff_is_since_the_last_checked_content(self, tmp_path: Path) -> None:
        root = _plan(tmp_path, {"PLAN.md": "old\n"})
        state = PlanFactCheckState(tmp_path / "state")
        state.record_checked(FOLDER, snapshot_plan(root))
        (root / "PLAN.md").write_text("old\nnew claim\n", encoding="utf-8")
        pending = process_quiet_plan(root, FOLDER, state, trigger_count=1, now=1.0)
        assert pending is not None
        assert "+new claim" in pending.diff
        assert "+old" not in pending.diff

    def test_unchanged_since_checked_stores_nothing(self, tmp_path: Path) -> None:
        root = _plan(tmp_path, {"PLAN.md": "same\n"})
        state = PlanFactCheckState(tmp_path / "state")
        state.record_checked(FOLDER, snapshot_plan(root))
        assert process_quiet_plan(root, FOLDER, state, trigger_count=2, now=1.0) is None
        assert state.read_pending(FOLDER) is None

    def test_fire_does_not_advance_the_checked_hash(self, tmp_path: Path) -> None:
        """Only delivery (a later task) marks content as checked."""
        root = _plan(tmp_path, {"PLAN.md": "v1\n"})
        state = PlanFactCheckState(tmp_path / "state")
        process_quiet_plan(root, FOLDER, state, trigger_count=1, now=1.0)
        assert state.read_checked(FOLDER) is None

    def test_a_vanished_plan_stores_nothing(self, tmp_path: Path) -> None:
        state = PlanFactCheckState(tmp_path / "state")
        missing = tmp_path / "CLAUDE" / "Plan" / FOLDER
        assert process_quiet_plan(missing, FOLDER, state, trigger_count=1, now=1.0) is None
        assert state.read_pending(FOLDER) is None


class TestDelivery:
    def _pending(self, tmp_path: Path, text: str = "claim\n") -> tuple[Path, PlanFactCheckState]:
        root = _plan(tmp_path, {"PLAN.md": text})
        state = PlanFactCheckState(tmp_path / "state")
        process_quiet_plan(root, FOLDER, state, trigger_count=1, now=1.0)
        return root, state

    def test_pending_folders_lists_owed_checks(self, tmp_path: Path) -> None:
        _, state = self._pending(tmp_path)
        assert state.pending_folders() == [FOLDER]

    def test_pending_folders_empty_without_state_dir(self, tmp_path: Path) -> None:
        assert PlanFactCheckState(tmp_path / "nope").pending_folders() == []

    def test_delivery_returns_instruction_naming_agent_plan_and_diff_file(
        self, tmp_path: Path
    ) -> None:
        root, state = self._pending(tmp_path)
        messages = deliver_pending(state)
        assert len(messages) == 1
        text = messages[0]
        assert "plan-fact-checker" in text
        assert str(root / "PLAN.md") in text
        assert "REFUTED" in text
        diff_file = tmp_path / "state" / f"{FOLDER}.diff"
        assert str(diff_file) in text
        assert "+claim" in diff_file.read_text(encoding="utf-8")

    def test_delivery_records_checked_and_clears_pending(self, tmp_path: Path) -> None:
        root, state = self._pending(tmp_path)
        deliver_pending(state)
        checked = state.read_checked(FOLDER)
        assert checked is not None
        assert checked.files == snapshot_plan(root)
        assert state.read_pending(FOLDER) is None

    def test_each_pending_record_is_delivered_once(self, tmp_path: Path) -> None:
        _, state = self._pending(tmp_path)
        assert len(deliver_pending(state)) == 1
        assert deliver_pending(state) == []

    def test_next_diff_is_since_the_delivered_content(self, tmp_path: Path) -> None:
        root, state = self._pending(tmp_path, "old\n")
        deliver_pending(state)
        (root / "PLAN.md").write_text("old\nnew claim\n", encoding="utf-8")
        process_quiet_plan(root, FOLDER, state, trigger_count=1, now=2.0)
        deliver_pending(state)
        diff = (tmp_path / "state" / f"{FOLDER}.diff").read_text(encoding="utf-8")
        assert "+new claim" in diff
        assert "+old" not in diff

    def test_unreadable_pending_is_set_aside_not_raised(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        state = PlanFactCheckState(tmp_path)
        bad = tmp_path / f"{FOLDER}.pending.json"
        bad.write_text("{nope", encoding="utf-8")
        with caplog.at_level(logging.INFO, logger="claude_code_hooks_daemon.utils.plan_fact_check"):
            assert deliver_pending(state) == []
        assert not bad.exists()
        assert (tmp_path / f"{FOLDER}.pending.json.unreadable").is_file()
        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert len(warnings) == 1
        assert warnings[0].levelno == logging.WARNING
        assert warnings[0].exc_info is None
        assert f"{FOLDER}.pending.json" in warnings[0].getMessage()

    def test_old_format_record_is_never_re_read(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        state = PlanFactCheckState(tmp_path)
        (tmp_path / f"{FOLDER}.pending.json").write_text('{"folder": "x"}', encoding="utf-8")
        deliver_pending(state)
        caplog.clear()
        with caplog.at_level(logging.INFO, logger="claude_code_hooks_daemon.utils.plan_fact_check"):
            assert deliver_pending(state) == []
        assert state.pending_folders() == []
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]

    def test_valid_record_after_a_malformed_one_is_delivered(self, tmp_path: Path) -> None:
        state = PlanFactCheckState(tmp_path / "state")
        (tmp_path / "state").mkdir()
        (tmp_path / "state" / "00001-aaa.pending.json").write_text('{"folder": "x"}', "utf-8")
        root = _plan(tmp_path, {"PLAN.md": "claim\n"})
        process_quiet_plan(root, FOLDER, state, trigger_count=1, now=1.0)
        assert state.pending_folders() == ["00001-aaa", FOLDER]
        messages = deliver_pending(state)
        assert len(messages) == 1
        assert FOLDER in messages[0]
        assert state.pending_folders() == []


class TestCorruptState:
    def test_corrupt_checked_state_fails_loudly(self, tmp_path: Path) -> None:
        state = PlanFactCheckState(tmp_path)
        (tmp_path / f"{FOLDER}.checked.json").write_text("{not json", encoding="utf-8")
        with pytest.raises(PlanFactCheckStateError):
            state.read_checked(FOLDER)

    def test_malformed_pending_state_fails_loudly(self, tmp_path: Path) -> None:
        state = PlanFactCheckState(tmp_path)
        (tmp_path / f"{FOLDER}.pending.json").write_text('{"folder": "x"}', encoding="utf-8")
        with pytest.raises(PlanFactCheckStateError):
            state.read_pending(FOLDER)

    def test_unsafe_folder_name_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            PlanFactCheckState(tmp_path).read_checked("../escape")
